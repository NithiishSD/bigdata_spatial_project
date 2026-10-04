# 08 — Working with MongoDB (practical handbook)

Everything needed to inspect, debug and demo the database by hand, independently of the
Python code. Written against the actual dev setup: **MongoDB 8.0.32, installed natively
from the `mongodb-org` apt packages, managed by systemd — not Docker.**

---

## 1. What is actually installed

| Thing | Value |
|---|---|
| Server version | 8.0.32 (`mongodb-org-server`) |
| Shell | `mongosh` 2.12.0 |
| Service name | `mongod.service` (systemd, enabled at boot) |
| Port | 27017 |
| Bind address | `127.0.0.1` — **localhost only**, not reachable from the network |
| Data directory | `/var/lib/mongodb` |
| Log file | `/var/log/mongodb/mongod.log` |
| Config file | `/etc/mongod.conf` |
| Authentication | **none configured** — which is why the URI needs no username or password |

**Native vs Docker.** Two normal ways to run MongoDB locally:

- **Native (this setup):** installed as a system package, runs as a background service,
  starts at boot. Data persists in `/var/lib/mongodb` whatever happens to your terminal.
- **Docker:** `docker run -d -p 27017:27017 -v mongodata:/data/db mongo:8` runs it inside
  a container. Easier to throw away and re-create, but you must remember a volume or the
  data disappears with the container.

Either way the connection URI is identical — `mongodb://localhost:27017` — because Docker
would publish the same port. Nothing in this project's code knows or cares which you use.

---

## 2. Controlling the service

```bash
systemctl status mongod          # is it running? (q to quit the pager)
sudo systemctl start mongod      # start it
sudo systemctl stop mongod       # stop it
sudo systemctl restart mongod    # after editing /etc/mongod.conf
sudo systemctl enable mongod     # start automatically at boot
systemctl is-active mongod       # prints just "active" / "inactive" — good for scripts
```

If a connection fails, this is the first thing to check. The second is the log:

```bash
sudo tail -n 40 /var/log/mongodb/mongod.log
```

---

## 3. Three ways to open the database

### a) `mongosh` — the shell (use this most)

```bash
mongosh                          # connects to mongodb://localhost:27017 by default
mongosh "mongodb://localhost:27017/forestgeo"   # straight into one database
```

It is a JavaScript REPL, so `.length`, `.map()` and template strings all work. Exit with
`exit` or Ctrl-D.

Run a single command without entering the shell — handy in scripts:

```bash
mongosh --quiet --eval 'db.getSiblingDB("forestgeo").villages.countDocuments()'
```

### b) MongoDB Compass — the GUI

A free desktop app that draws query results on a **map** when documents contain GeoJSON,
which makes it genuinely useful here for eyeballing whether geometry landed in the right
place. Download from mongodb.com/products/compass, then connect with
`mongodb://localhost:27017`.

### c) VS Code extension

Install "MongoDB for VS Code", connect to `mongodb://localhost:27017`, and you can browse
collections and run playground queries in an editor tab beside the code.

---

## 4. The mental model

```
client (one server)
└── database            "forestgeo"
    └── collection      "villages"      (like a table, but no fixed schema)
        └── document    { _id: ..., name: "Ooty", geometry: {...} }
            └── field   name, geometry, source, ingested_at
```

- A **document** is BSON — binary JSON with extra types JSON lacks: `Date`, `ObjectId`,
  `Double`, `Int32`. This matters here: fire-hotspot timestamps are stored as real BSON
  `Date` values, so MongoDB can compare and sort them as dates rather than strings.
- **`_id`** is the primary key. MongoDB adds one automatically (an `ObjectId`) if you do
  not supply it, and it is always indexed.
- **No schema is required.** Two documents in one collection may have different fields.
  That freedom is why validation happens in Python *before* insert — nothing else will
  stop bad data.
- **Databases and collections are created lazily**, on first write. You never "CREATE
  TABLE"; writing the first document is enough.

---

## 5. Everyday commands

```javascript
show dbs                       // all databases and their sizes
use forestgeo                  // switch database (creates it lazily on first write)
db                             // which database am I in?
show collections               // list collections

db.villages.countDocuments()                 // exact count
db.villages.estimatedDocumentCount()         // fast, from metadata
db.villages.findOne()                        // one document — check the shape
db.villages.find().limit(3)                  // first three
db.villages.find({ place: "town" })          // filter
db.villages.find({}, { name: 1, _id: 0 })    // projection: only the name field
db.villages.distinct("place")                // unique values of a field

db.villages.getIndexes()                     // every index on the collection
db.villages.drop()                           // delete the collection entirely
db.villages.deleteMany({})                   // empty it but keep indexes

db.stats()                                   // database size summary
db.villages.stats().size                     // collection size in bytes
```

Count how many documents of each geometry type a collection holds — this is how you prove
all three GeoJSON types are present:

```javascript
db.transport.aggregate([
  { $group: { _id: "$geometry.type", n: { $sum: 1 } } }
])
```

---

## 6. The spatial commands that matter for this project

### Create the index

```javascript
db.villages.createIndex({ geometry: "2dsphere" })
```

A `2dsphere` index treats coordinates as points on a sphere, so distances are real
great-circle distances. Without it, `$nearSphere` **refuses to run at all** — try it and
read the error; that refusal is a finding worth putting in the report.

### The four operations

```javascript
// $nearSphere — sorted by distance, nearest first. Needs an index. Point only.
db.villages.find({
  geometry: {
    $nearSphere: {
      $geometry: { type: "Point", coordinates: [76.70, 11.41] },  // [lon, lat]
      $maxDistance: 5000                                          // METRES
    }
  }
}).limit(5)

// $geoWithin — entirely inside a polygon. No index required, but much faster with one.
db.sightings.countDocuments({
  geometry: { $geoWithin: { $geometry: <a GeoJSON Polygon> } }
})

// $geoWithin + $centerSphere — a circle. Radius is in RADIANS: km / 6378.1
db.fire_hotspots.countDocuments({
  geometry: { $geoWithin: { $centerSphere: [[76.70, 11.41], 5 / 6378.1] } }
})

// $geoIntersects — touches, crosses or is inside. Use for lines crossing polygons.
db.transport.countDocuments({
  geometry: { $geoIntersects: { $geometry: <a GeoJSON Polygon> } }
})
```

### Measuring a query

```javascript
db.villages.find({ geometry: { $geoWithin: { $centerSphere: [[76.70, 11.41], 5/6378.1] } } })
  .explain("executionStats")
```

Read four numbers from the output:

| Field | Meaning |
|---|---|
| `executionStats.executionTimeMillis` | server-side time — use this, not wall clock |
| `executionStats.totalDocsExamined` | documents actually read |
| `executionStats.nReturned` | documents returned |
| `winningPlan.stage` | `IXSCAN` = index used · `COLLSCAN` = every document scanned |

Force a collection scan, to compare against the indexed run without dropping the index:

```javascript
db.villages.find({ ... }).hint({ $natural: 1 }).explain("executionStats")
```

---

## 7. Things that will bite you

| Symptom | Cause | Fix |
|---|---|---|
| `ServerSelectionTimeoutError` after ~10 s | server not running | `systemctl is-active mongod` |
| `$nearSphere` → "unable to find index for $geoNear query" | no `2dsphere` index | create the index first |
| `Can't extract geo keys … Edges cross` | invalid polygon (self-intersecting) | `make_valid` in Shapely before insert |
| Query returns 0 rows but data exists | coordinates stored as `[lat, lon]` | GeoJSON is **`[lon, lat]`**, always |
| A 5 km search behaves wildly wrong | `$centerSphere` given metres | `$centerSphere` wants **radians** = km / 6378.1 |
| `count_documents` fails with `$nearSphere` | not allowed in a count | use `$geoWithin` + `$centerSphere` |

---

## 8. Backup, restore and moving to Atlas

```bash
mongodump   --uri="mongodb://localhost:27017" --db=forestgeo --out=backup/
mongorestore --uri="mongodb://localhost:27017" backup/

# copy the whole local database into Atlas at the end of the project
mongodump   --uri="mongodb://localhost:27017" --db=forestgeo --out=backup/
mongorestore --uri="mongodb+srv://USER:PASS@cluster.mongodb.net" backup/
```

Useful if the Atlas re-run is only needed for final screenshots and numbers — though
re-running the pipeline against Atlas is the more honest demonstration, since it proves
the code is portable rather than just the data.
