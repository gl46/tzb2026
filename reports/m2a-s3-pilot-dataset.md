# M2A S3 Pilot dataset

- status: **PASS_WITH_LIMITATIONS**
- fixed contract: 50/50 scene seeds, 25 dual-worker pairs
- valid adjacent-frame episodes: 550
- split: train=418, val=66, test=66
- READY shards: 11/11 validated
- failure/recovery: 454/550 (82.545%)
- failure types: `NONE=96`, `TRACKING_LOST=454`
- worker mappings measured: 17 standard, 8 swapped
- infrastructure quarantine: 15 failed Isaac/Hydra startup attempts
- quarantined published episodes: 0
- dataset manifest hash: `9843968cdbff17b6b4a291e30907f2c5dc855838ad3e4be7095a4bb8783449bc`
- manifest file SHA-256: `bef52bcfb84d6ecdb8e94c079a35a3a311f3ef24d00d8ca36e46c78db5680ebd`
- capture revision: `f007bd490d7cf7ba11d032af94fb2799e9d62e16`
- Oracle leakage: false
- Teacher soft labels: absent

## Limitations

- This adjacent-frame Pilot does not physically exercise `EMPTY_GRASP`,
  `WRONG_OBJECT`, or `RELEASE_FAILURE`.
- Infrastructure quarantine is reported separately from episode quarantine;
  no invalid attempt was published into a READY shard.
