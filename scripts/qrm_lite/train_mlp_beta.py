#!/usr/bin/env python3
"""Train bounded MLP residual heads with identical Isaac split/budget."""

from __future__ import annotations

import sys

from train_q012 import main


if __name__ == "__main__":
    arguments = [
        "--models", "Q1,Q2",
        "--epochs-coarse", "1",
        "--out-dir", "artifacts/qrm_lite/m2a-mlp",
        "--report", "reports/m2a-s4-qrm-beta-mlp.md",
        "--report-json", "reports/m2a-s4-qrm-beta-mlp.json",
        *sys.argv[1:],
    ]
    raise SystemExit(main(arguments))
