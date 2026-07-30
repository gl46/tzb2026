"""Delegated public perception CLI marker; RGB-D runner remains scripts/run_geometric_rgbd.py."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="M1B RGB-D perception entry point")
    parser.add_argument("--snapshot", help="captured RGB-D snapshot directory")
    args = parser.parse_args()
    if not args.snapshot:
        parser.print_help()
        return 0
    raise SystemExit("use scripts/run_geometric_rgbd.py SNAPSHOT --output OUTPUT")


if __name__ == "__main__":
    raise SystemExit(main())
