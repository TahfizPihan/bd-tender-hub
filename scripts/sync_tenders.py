#!/usr/bin/env python3
"""Refresh the tender JSON and SQLite database for the BD Tender Hub app."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        subprocess.run([sys.executable, "-m", "scraper.collect"], cwd=str(ROOT), check=True)
        from backend.database import ensure_db
        ensure_db()
        print("Tender database refreshed successfully.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Collector failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
