"""Small CSV readers for metadata and append-only market caches."""

from __future__ import annotations

import csv
from pathlib import Path


def read_csv_tail_records(path: str | Path, limit: int) -> list[dict[str, str]]:
    """Read the last ``limit`` records without loading an entire CSV file.

    Market cache files are written one record per physical line in ascending date
    order. Reading only their tail keeps dashboard summaries cheap even when each
    symbol has years of history.
    """
    source = Path(path)
    if limit <= 0 or not source.exists() or source.stat().st_size == 0:
        return []

    with source.open("rb") as handle:
        header = handle.readline().decode("utf-8-sig", errors="replace").rstrip("\r\n")
        if not header:
            return []
        handle.seek(0, 2)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count < limit + 1:
            step = min(4096, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    lines = b"".join(reversed(chunks)).splitlines()
    if position > 0 and lines:
        lines = lines[1:]
    decoded = [
        line.decode("utf-8", errors="replace")
        for line in lines
        if line.strip()
    ]
    if decoded and decoded[0].lstrip("\ufeff") == header.lstrip("\ufeff"):
        decoded = decoded[1:]
    return list(csv.DictReader([header, *decoded[-limit:]]))
