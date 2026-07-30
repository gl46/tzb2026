# M2A Isaac Data and QRM Beta runbook

Required topology:

```bash
export ISAAC_HOST=root@labserver
export ISAAC_PROJECT_ROOT=/var/tmp/m2a-isaac-project-20260731
export ISAAC_SOURCE_ROOT=/var/tmp/m2a-isaac-source-20260731
export ISAAC_DATA_ROOT=/var/tmp/xh-data/isaac-industrial
export TRAIN_HOST=node2
export TRAIN_PROJECT_ROOT=/home/gl/xh-202607-m2a
export TRAIN_DATA_ROOT=/home/gl/xh-data/isaac-industrial
export DATASET_VERSION=isaac-industrial-v1-pilot
```

Primary entry points:

```bash
make m2a-doctor
make isaac-contract
make isaac-benchmark
make isaac-pilot
make isaac-validate
make isaac-sync
make qrm-beta-train
make qrm-beta-eval
make qrm-beta-closed-loop
make m2a-status
```

Flow is disabled. Only `*.READY` shards may be synchronized or trained.
SimulatorSupervision is an offline label stream and must not be passed to the
online observation, prompt, coarse head or MLP input.

Formal Qwen FailureContext runs use the immutable test split and seeds
`20260731` and `20260732`. The closed-loop entry point runs ten unseen scene
episodes by default and reports scene episodes separately from live decisions.
