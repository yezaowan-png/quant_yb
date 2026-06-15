"""Fail fast when project checks are not running in the agreed QYTX env."""

from __future__ import annotations

import os
import sys
from pathlib import Path


EXPECTED_PYTHON = Path(r"E:\anaconda3\envs\QYTX\python.exe")


def _normalize(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def main() -> int:
    actual = Path(sys.executable)
    print(f"python: {actual}")
    print(f"version: {sys.version.split()[0]}")

    if _normalize(actual) != _normalize(EXPECTED_PYTHON):
        print(f"ERROR: expected project Python is {EXPECTED_PYTHON}")
        print("Run project checks with the QYTX interpreter, not bare python.")
        return 1

    try:
        import pandas as pd
        import yaml
    except Exception as exc:
        print(f"ERROR: failed to import required packages: {exc}")
        return 1

    print(f"pandas: {pd.__version__}")
    print(f"pyyaml: {yaml.__version__}")
    print("environment: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
