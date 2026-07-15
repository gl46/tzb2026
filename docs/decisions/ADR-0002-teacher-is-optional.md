# ADR-0002: Teacher is optional

Root imports must remain CPU-only. A Teacher is a remote/service adapter that can add optional
soft labels to `EpisodeTransitionV0`; its absence is valid. No raw Teacher output is labeled as
simulator ground truth and no Teacher code may directly control the robot.
