# M1A S3 contact-gated constraint

- Status: `CONTACT_GATED_CONSTRAINT_VERIFIED`; mode: `CONTACT_GATED_CONSTRAINED_GRASP`.
- Real reset episodes: `10/10`; successes: `10`; release verified: `10`.
- Gate rejections: `0`; attach requests: `10`; runtime-blocked sessions: `0`.
- Preserved prior S3 batches: `18`.
- At least 8 of 10 real reset episodes met the gate, sent an observed constraint attach, executed the collision-checked transfer, and positively verified release/bin settling.
- Each attach event is emitted by the remote client only after its recorded gate passes; no Gazebo object pose write is used.
