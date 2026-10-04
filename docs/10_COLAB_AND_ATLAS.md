# 10 — Colab Demo & Atlas Setup

The demo runs in **Google Colab**, which lives in Google's cloud and therefore cannot
reach a `mongod` on your laptop. So the database moves to **MongoDB Atlas**, and the
notebook becomes a thin client over it.

```
your laptop  --(load once)-->  Atlas M0 (cloud)  <--(queries)--  Colab notebook
```

Your data is **15.8 MB on disk**, against the M0 free-tier limit of 512 MB — 496 MB of
headroom.

---

## 1. Create the Atlas cluster (15 minutes, once)

1. Sign up at <https://www.mongodb.com/cloud/atlas/register>
2. **Build a Database** → **M0 FREE** → region **Mumbai (ap-south-1)**, closest to you
3. **Database Access** → *Add New Database User*
   - username `forestgeo`
   - **Autogenerate a secure password and copy it somewhere safe**
   - role: **Read and write to any database**
     (read-only is not enough — the notebook creates a temporary collection to
     demonstrate that `$nearSphere` fails without an index)
   - avoid `@ : / ?` in the password, or URL-encode them, since it goes into a URI
4. **Network Access** → *Add IP Address* → **Allow access from anywhere (0.0.0.0/0)**
   - Colab's outbound IP changes between sessions, so an allowlist is not workable
   - **State this in the report's limitations**: it is acceptable for a read-mostly
     demo database with a strong generated password, and would not be acceptable for
     production
5. **Connect** → *Drivers* → *Python* → copy the `mongodb+srv://…` string

---

## 2. Load your data into Atlas (2 minutes, once)

Nothing in the code changes. The URI lives in `.env`, which is the only place that
knows which server is in use.

```bash
cd ~/Projects/bigdata_spatial_project

# keep the local setting so you can switch back
cp .env .env.local

# edit .env and replace MONGODB_URI with the Atlas string, password filled in
nano .env

.venv/bin/python scripts/check_connection.py     # must print ALL CHECKS PASSED
.venv/bin/python scripts/load_mongo.py           # ~2 min over the network
.venv/bin/python scripts/build_unions.py         # rebuild derived_zones in Atlas
.venv/bin/python scripts/create_indexes.py       # confirm every 2dsphere index exists
```

Expect `46,429 documents across 9 collections`, then 4 derived zones.

To switch back to local: `cp .env.local .env`.

**Then re-run the benchmark against Atlas** — the numbers will differ from your local
run, and that difference is itself worth reporting:

```bash
.venv/bin/python scripts/benchmark.py
```

M0 is a shared, throttled tier, so expect slower and noisier timings than local.
`totalDocsExamined` will be identical, because it measures work rather than speed —
which is exactly why the report should lead with that number.

---

## 3. Set up the notebook in Colab

1. Push the repo so Colab can fetch it:
   ```bash
   git add -A && git commit -m "Add Colab demo notebook" && git push
   ```
2. Open <https://colab.research.google.com> → **GitHub** tab → enter `NithiishSD` →
   choose `bigdata_spatial_project` → open `notebooks/forestgeo_demo.ipynb`
3. Click the **🔑 key icon** in the left sidebar → **Add new secret**
   - name: `MONGODB_URI`
   - value: your full Atlas connection string, password included
   - toggle **Notebook access** on
4. **Runtime → Run all**

### Why Colab Secrets, and not a variable in a cell

**Your GitHub repository is public.** An Atlas URI contains the database password. If it
is typed into a notebook cell and that notebook is committed, the credential is public
permanently — and bots scan GitHub for exactly this pattern within minutes.

Colab Secrets are stored against *your Google account*, never inside the `.ipynb`. The
notebook reads the value at runtime, and `safe_uri()` redacts the password before
anything is printed.

If a URI ever does leak: rotate the password in *Atlas → Database Access* immediately.

---

## 4. Demo-day checklist

**The day before**

- [ ] Run the whole notebook top to bottom; confirm every cell succeeds
- [ ] **Save the notebook with its outputs** — if the network fails live, the saved
      outputs are still on screen and the demo continues
- [ ] *File → Download → .ipynb* as a local backup
- [ ] Screenshot the map, the benchmark chart and the risk table

**30 minutes before**

- [ ] Open the notebook and **Run all** once, so the runtime is warm and the repo cloned
- [ ] Confirm the Atlas cluster is awake — M0 clusters idle out and the first query can
      take a few seconds
- [ ] Have `docs/img/fig2_union_before_after.png` and `fig4_critical_zone.png` open in
      separate tabs

**During**

- Do **not** use *Run all* live; run cells one at a time so you can talk over each
- Skip the map cell if the room's network is weak — the figures carry the same point

---

## 5. The 5-minute flow, mapped to notebook sections

| time | section | the line to land |
|---|---|---|
| 0:00 | title cell | "Four pressures, four unrelated datasets, one spatial database." |
| 0:30 | §3 what is in the database | "46,429 documents, all three GeoJSON types, every collection 2dsphere-indexed, zero rejected by MongoDB." |
| 1:15 | §4 the four operations | "I used `$geoIntersects` for roads crossing Mudumalai — a road that exits is not *inside*, so `$geoWithin` returns a much smaller number." |
| 2:15 | §5 the union | "MongoDB cannot build geometry. The union happens in Shapely and comes back as a queryable collection." |
| 3:00 | §5 validation + §6 cross-theme | "79 of 421 villages. And MongoDB's own two-predicate form returns 79 too." |
| 3:45 | §7 the index | "180× on a selective query — but only 1.3× on a broad one, and that second number is the more interesting result." |
| 4:30 | §8 the map | play the fire timeline |
| 4:50 | §9 limitations | observer bias; obscured coordinates |

---

## 6. If something breaks

| problem | fix |
|---|---|
| `userdata.SecretNotFoundError` | the secret is not named exactly `MONGODB_URI`, or *Notebook access* is off |
| `ServerSelectionTimeoutError` | Network Access does not include `0.0.0.0/0`, or the cluster is paused |
| `AuthenticationFailed` | password wrong, or contains `@ : / ?` unencoded |
| first query very slow | M0 was idle; it wakes on the first request |
| `ModuleNotFoundError: forestgeo` | the `pip install -e .` cell did not run, or the `%cd` failed |
| map cell hangs | skip it — show `fig4_critical_zone.png` instead |
| Colab itself is down | the downloaded `.ipynb` plus the saved outputs, or fall back to the local demo in `09_DEMO_RUNBOOK.md` |

---

## 7. What this architecture demonstrates

Worth saying explicitly in the viva, because it is a real engineering point rather than
a convenience:

- **The database moved from a laptop to a managed cloud cluster by changing one line in
  `.env`.** No query, no index definition and no application code changed. That is the
  payoff of reading configuration in exactly one place.
- **The notebook imports the same `forestgeo` package the pipeline uses.** It is not a
  reimplementation for demo purposes — the same `queries.py` that produced the CSVs
  produces the live results on screen.
- **Credentials never enter the repository.** `.env` is git-ignored locally, Colab
  Secrets hold the value in the cloud, and `safe_uri()` redacts the password anywhere
  the connection is printed.
