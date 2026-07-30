# M2A S2 Isaac worker benchmark

- status: **PASS_WITH_LIMITATIONS**
- selected: `DUAL_INDEPENDENT_WORKERS`
- GPU0 single capture: 6.5406 sensor-frames/s
- GPU1 single capture: 6.5707 sensor-frames/s
- Dual capture: 12.3362 sensor-frames/s
- Dual end-to-end: 2096.31 valid short episodes/hour
- Invalid accepted episodes: 0

## Limitations

- benchmark duration is shorter than the requested 30-minute soak
- 100-episode memory-growth measurement was not completed
- CPU, RAM, and NVMe utilization are not sampled by the current runner
