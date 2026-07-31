# M2A Isaac Industrial Pilot dataset card

- version: `isaac-industrial-v1-pilot`
- status: `READY`
- valid adjacent-frame episodes: 550
- split: train=418, val=66, test=66
- manifest hash: `9843968cdbff17b6b4a291e30907f2c5dc855838ad3e4be7095a4bb8783449bc`
- policy inputs: public RGB-D, public tracks, robot state, TaskSpec, FailureContext
- privileged simulator truth: offline labels/evaluation only
- Teacher soft labels: absent
- known scope: articulation-excitation adjacent-frame corpus; not physical grasp/release recovery trajectories
