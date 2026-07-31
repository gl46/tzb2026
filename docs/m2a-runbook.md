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
make shadow-isaac
ISAAC_DATASET_ROOT=/path/to/isaac-industrial-v1-pilot \
LEROBOT_OUTPUT_ROOT=/path/to/lerobot-sample30 make lingbot-prep
make m2a-status
```

Flow is disabled. Only `*.READY` shards may be synchronized or trained.
SimulatorSupervision is an offline label stream and must not be passed to the
online observation, prompt, coarse head or MLP input.
M2A is Teacher-free: no Teacher adapter, soft label, checkpoint, or inference
service is required by data generation, training, Shadow, or closed-loop smoke.

`make isaac-benchmark` defaults to 3,000 capture frames for each of GPU0,
GPU1, and the dual-worker configuration. At the retained capture rate this is
the formal 30-minute-per-configuration soak and requires roughly 70 GB of
temporary NVMe space. Override `ISAAC_BENCHMARK_FRAMES` only for an explicitly
labelled smoke run.

Formal Qwen FailureContext runs use the immutable test split and seeds
`20260731` and `20260732`. The closed-loop entry point runs ten unseen scene
episodes by default and reports scene episodes separately from live decisions.

`make shadow-isaac` is P1 and evaluation-only. It reconstructs ten shadow
scenes from public tracks and public robot state, runs three explicit
joint-space physics probes per state, and forbids the output from Student
training. It does not infer or guess a camera-residual-to-joint mapping.

LingBot preparation is also offline-only and is not a Teacher path. The
revision lock is `configs/lingbot_lerobot.lock.yaml`. The exporter writes a
LeRobot v3 small sample with raw 9D named Panda joint targets; it never maps
those targets to LingBot control tokens. Current LingBot-World v2 is
non-commercial CC BY-NC-SA 4.0 and must not enter a commercial submission
without human license review.

S8 video evidence is deliberately partial. The retained QRM-FC clip is labelled
as a representative failure with B0 fallback. A success clip and synchronized
WRONG_OBJECT recovery clip must remain unavailable until a real capture exists;
do not relabel other footage.

The Pilot dataset remains an articulation-excitation adjacent-frame corpus.
Physical `EMPTY_GRASP`, `WRONG_OBJECT`, and `RELEASE_FAILURE` coverage is not
claimed: the repository has M1B acceptance evidence for parts of that chain,
but there is no official camera-residual-to-Isaac-joint action mapping that
would permit those records to be promoted into new policy-training episodes.
