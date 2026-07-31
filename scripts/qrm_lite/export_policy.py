#!/usr/bin/env python3
"""Export a compact policy package manifest (no large weights)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--coarse', default='artifacts/qrm_lite/coarse_overfit.npz')
    p.add_argument('--mlp', default='artifacts/qrm_lite/mlp_refiner.npz')
    p.add_argument('--flow', default='artifacts/qrm_lite/flow_refiner.npz')
    p.add_argument('--out', default='artifacts/qrm_lite/export_manifest.json')
    a=p.parse_args()
    man={
      'coarse': a.coarse if Path(a.coarse).exists() else None,
      'mlp': a.mlp if Path(a.mlp).exists() else None,
      'flow': a.flow if Path(a.flow).exists() else None,
      'note': 'LoRA/adapters and large Qwen weights stay outside git',
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(man, indent=2))
    print(json.dumps(man, indent=2))
if __name__=='__main__':
    main()
