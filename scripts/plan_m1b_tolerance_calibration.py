#!/usr/bin/env python3
"""Emit the immutable 81-trial, calibration-only M1B tolerance worklist."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--config",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    c=json.loads(a.config.read_text()); trials=[]
    for axis in c["offset_axes"]:
        for offset in c["offsets_m"]:
            for repetition in range(1,c["repetitions_per_point"]+1):
                trials.append({"axis":axis,"offset_m":offset,"repetition":repetition,"provenance":"CALIBRATION_ONLY_INITIALIZATION","required_distinct_instance_slot":repetition})
    payload={"schema_version":"M1BToleranceCalibrationWorklistV1","timebox_hours":3,"trials":trials,"trial_count":len(trials),"early_stop":"forbidden_except_infrastructure_failure","online_truth_access":False}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2)+"\n");print(json.dumps({"trial_count":len(trials)}));return 0
if __name__=="__main__": raise SystemExit(main())
