# M2A S0 topology audit

- Isaac: `root@labserver`, NVIDIA GeForce RTX 3080, NVIDIA GeForce RTX 3080
- Train: `node2`, NVIDIA A100-SXM4-80GB
- Isaac version: `6.0.1`
- Worker strategy: one process per physical RTX 3080
- Camera products: `policy_rgbd`, `front_rgbd`, `overhead_rgbd`, `side_rgbd`
- Estimated short-episode bytes: `5454120.681393798`
- Network baseline: `{'coordinator_to_isaac': {'bytes': 33554432, 'elapsed_s': 23.843012749995978, 'method': 'coordinator random-byte SSH upload to remote /dev/null', 'status': 'PASS', 'throughput_mbps': 11.258453737145498}, 'coordinator_to_train': {'bytes': 33554432, 'elapsed_s': 26.791492332995404, 'method': 'coordinator random-byte SSH upload to remote /dev/null', 'status': 'PASS', 'throughput_mbps': 10.019429028572809}, 'scope': 'coordinator upload legs used for remote execution; direct Isaac-to-train SSH was unavailable'}`
- Teacher used: no
- Teacher kill-rule events: none
