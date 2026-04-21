"""Curated smoke-test runner for Optiland.

This module provides a small, stable regression suite we can run before
feature commits to protect core math, file I/O, GUI logic, and visualization.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SMOKE_TESTS = [
    "tests/gui/test_catalog_pipeline.py",
    "tests/test_gui/test_catalog_importers.py",
    "tests/test_fileio/test_zemax_reader.py",
    "tests/gui/test_surface_service.py",
    "tests/analysis/test_spot_reference.py",
    "tests/visualization/system/test_optic_viewer_projection.py",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Optiland's curated smoke-test suite to catch regressions in "
            "catalog import, file I/O, analysis, visualization, and GUI logic."
        )
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the smoke-test selection and exit.",
    )
    args, pytest_args = parser.parse_known_args()
    args.pytest_args = pytest_args
    return args


def main() -> None:
    """Run the curated smoke-test suite."""
    args = _parse_args()
    if args.list:
        print("Optiland smoke suite:")
        for path in SMOKE_TESTS:
            print(f"  - {path}")
        return

    command = [sys.executable, "-m", "pytest", *SMOKE_TESTS, *args.pytest_args]
    raise SystemExit(subprocess.call(command, cwd=_project_root()))


if __name__ == "__main__":
    main()
