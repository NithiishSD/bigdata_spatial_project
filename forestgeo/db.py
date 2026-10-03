"""MongoDB connection helpers. The URI comes from .env — never hard-coded."""

from __future__ import annotations

import logging
from functools import lru_cache

import certifi
from pymongo import MongoClient
from pymongo.database import Database

from forestgeo.config import MONGODB_DB, MONGODB_URI

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    """Cached MongoClient. Uses certifi's CA bundle for mongodb+srv (Atlas) URIs."""
    kwargs: dict = {"serverSelectionTimeoutMS": 10_000, "appname": "forestgeo"}
    if MONGODB_URI.startswith("mongodb+srv://"):
        kwargs["tlsCAFile"] = certifi.where()
    return MongoClient(MONGODB_URI, **kwargs)


def get_db() -> Database:
    """The project database (default name: forestgeo)."""
    return get_client()[MONGODB_DB]


def safe_uri() -> str:
    """The URI with any password redacted — safe to log or print."""
    uri = MONGODB_URI
    if "@" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
