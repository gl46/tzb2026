# M1A S3 contact-gated constraint

- Status: `CONTACT_GATED_CONSTRAINT_VERIFIED`; mode: `CONTACT_GATED_CONSTRAINED_GRASP`.
- Real reset episodes: `10/10`; successes: `8`; release verified: `8`.
- Gate rejections: `2`; attach requests: `8`; runtime-blocked sessions: `0`.
- Preserved prior S3 batches: `19`.
- At least 8 of 10 real reset episodes met the gate, sent an observed constraint attach, executed the collision-checked transfer, and positively verified release/bin settling.
- Each attach event is emitted by the remote client only after its recorded gate passes; no Gazebo object pose write is used.
