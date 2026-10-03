"""
Purpose of the whole file: one place that knows how to reach MongoDB. Everything else calls get_db() and never thinks about URIs, timeouts or TLS. Because it's the only file touching the connection, your end-of-project switch to Atlas is one line in .env.
"""

#imports

#mongodb connection helpers we get the url from env and connection is here


from functools import lru_cache #used to memorise the function 

import certifi #it is bundle of trusted tls certificates

from pymongo import MongoClient #provide the interface for py-mongo entry point


from forestgeo.config import MONGODB_DB,MONGODB_URI
# @lru_cache(maxsize=1): a MongoClient is not a single connection. It owns a connection pool plus background threads that continuously monitor server health. Creating one per query would open sockets repeatedly, spawn threads you never clean up, and eventually exhaust file descriptors. Caching makes get_client() free to call from anywhere. maxsize=1 because there's only ever one distinct call — no arguments.

@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    kwargs = {"serverSelectionTimeoutMS": 10_000}
    if MONGODB_URI.startswith("mongodb+srv://"):
        kwargs["tlsCAFile"] = certifi.where() #atlas require tls certificate 
    return MongoClient(MONGODB_URI, **kwargs)

#return database handler
def get_db():
    """The project database (default name: forestgeo)."""
    return get_client()[MONGODB_DB]
# PyMongo's access pattern is indexing. client["forestgeo"] → database; database["villages"] → collection. So get_db()["villages"] is your villages collection, and neither exists on the server until you first write to it — MongoDB creates databases and collections lazily


#to hide the password while printing or ahowing the url public
def safe_uri() -> str:
    """The URI with any password redacted — safe to print or log."""
    if "@" not in MONGODB_URI:
        return MONGODB_URI
    scheme, rest = MONGODB_URI.split("://", 1)
    creds, host = rest.split("@", 1)
    return f"{scheme}://{creds.split(':', 1)[0]}:***@{host}"

