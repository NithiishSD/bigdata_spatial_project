"""Shared logging setup so every script prints the same readable INFO stream."""

from __future__ import annotations

import logging


def setup(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    # osmnx and urllib3 are chatty at INFO.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("osmnx").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")
