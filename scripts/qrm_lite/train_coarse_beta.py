#!/usr/bin/env python3
"""Train the coarse FailureContext on/off Beta comparison."""

from __future__ import annotations

import sys

from train_q012 import main


if __name__ == "__main__":
    arguments = [
        "--models", "Q0,Q2",
        "--epochs-mlp", "1",
        "--out-dir", "artifacts/qrm_lite/m2a-coarse",
        "--report", "reports/m2a-s4-qrm-beta-coarse.md",
        "--report-json", "reports/m2a-s4-qrm-beta-coarse.json",
        *sys.argv[1:],
    ]
    raise SystemExit(main(arguments))
