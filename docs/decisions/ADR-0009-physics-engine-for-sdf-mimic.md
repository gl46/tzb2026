# ADR-0009: Physics backend required for the Panda SDF mimic constraint

Date: 2026-07-16 (Asia/Shanghai)
Status: **ACCEPTED — approved 2026-07-17 (Asia/Shanghai)**

## Context and bounded evidence

ADR-0008's pre-authorized q1-master decision probe recorded that q1 could
open but could not close: its physical-controller target/output was `0.010 m`,
while its feedback remained `0.040 m` (30 mm error). The approved fallback was
therefore applied as `PANDA_MIMIC_Q2_MASTER`.

The q2-master no-contact probe then passed all adapter/controller checks on
URDF SHA-256
`28c13961245e192984b5ab483da732b29bcd7af66eb65b12542932388af7295d`:

- symmetric `0.040 → 0.010 m` command: physical q2 reached `0.010000 m`;
  reported q1/q2 disparity was `0.000375 m`; both measured Gazebo finger-link
  positions moved about `0.030 m`;
- asymmetric `[0.010, 0.040]` command: the public action returned
  `INVALID_GOAL` / `ASYMMETRIC_MIMIC_COMMAND_REJECTED`, and the adapter
  recorded `physical_command_emitted: false`.

However, the runtime launch log contains the simulator's explicit rejection:

`Attempting to create a mimic constraint … physics engine does not support
mimic constraints, so no constraint will be created.`

This is not a q2 controller failure. It is an installed-physics capability
mismatch. `gz plugin --info` on the installed `gz-physics7-dartsim-plugin`
listed 93 interfaces and no `SetMimicConstraintFeature`; the locally installed
`gz-physics7-bullet-featherstone-plugin` does export
`SetMimicConstraintFeature`.

An isolated, non-persistent Bullet-Featherstone launch confirmed that it no
longer emits DART's “constraint not created” error. It also exposed a second
boundary defect: the current `ros_gz_sim` URDF spawn path logs the q1 follower
as mimicking joint `''` (empty leader), even after the q2 leader was declared
first. Thus merely selecting Bullet-Featherstone is not sufficient to meet the
required explicit-SDF audit.

`gz_ros2_control` still mirrors the follower state/link in the q2 probe, but
that is not an acceptable substitute for ADR-0008's required visible SDF
physical constraint. It must not promote S0.

## Proposed decision

For the Gazebo spawn only, introduce a deterministically generated SDF spawn
representation that explicitly encodes the q1 follower axis:

```xml
<mimic joint="panda_finger_joint2" axis="axis">
  <multiplier>1.0</multiplier><offset>0.0</offset><reference>0.0</reference>
</mimic>
```

and select the already installed `gz-physics-bullet-featherstone-plugin` in
both M1A worlds. MoveIt and robot_state_publisher continue to consume the
same controlled URDF. The new SDF must be mechanically diffed against that
URDF for every link, joint, transform, collision, limit, sensor and
ros2_control interface; it is a spawn representation, not a second robot
specification.

### Proposed deterministic generation boundary

The local Gazebo installation has been checked, without changing either world:
`gz sdf -p robot_ws/src/xh_sim/urdf/panda_controlled.urdf` produces an SDF
1.11 model, and `ros2 run ros_gz_sim create --help` exposes the `-file` spawn
input. After approval, the implementation will therefore add one
source-controlled generator/validator rather than maintain a hand-written
second robot model:

1. convert the controlled URDF with `gz sdf -p`;
2. inject only the q1 `<axis><mimic joint="panda_finger_joint2" axis="axis">`
   block shown above, with multiplier `1`, offset `0`, and reference `0`;
3. canonicalize and hash the generated SDF, mechanically compare it with the
   URDF, then retain the generated SDF and comparison manifest as run
   evidence; and
4. spawn that generated file through `ros_gz_sim create -file`.

This confirms that the proposed representation has an available deterministic
implementation route. It is not evidence that the constraint works: the
post-approval spawned-SDF and no-contact acceptance checks below remain
mandatory.

Keep the scene, q2-master joint protocol, controller interfaces, public
adapter, collision geometry, contact sensors, SRDF, limits, units, and
`positive = open` convention unchanged.

This is a formal physical-configuration change. It is approved only for M1A's
production and calibration worlds; the M0 historical world remains unchanged.
S0 remains blocked until the engine-capability gates below pass.

## Required engine-capability acceptance before S0

The physical-mimic audit is promoted to five independent, fail-closed
capability gates. A failure of any one writes the missing capability and stops
the run before S0; it is not retried as an S0, S1, or S2 attempt.

1. **Controller activation + one trajectory.** Both trajectory controllers
   are `active`, and one collision-checked arm plan → execution → feedback
   segment completes within a five-minute timebox. This directly guards
   `gz_ros2_control` issue #440's Bullet controller activation failure.
2. **Physical mimic.** The spawned generated SDF visibly contains q1's
   `<axis><mimic>` declaration, no backend-decline log is present, q1 has
   state-only interfaces, q2 has the sole command interface, `/joint_states`
   contains both, and the q2-master close/open has 1 mm joint tracking plus
   both finger-link world-pose displacements.
3. **Contact telemetry.** A calibration-only bilateral contact window proves
   that the left-finger, right-finger, and cube contact topics all publish
   Bullet-backed events. It is capability evidence, not one of S0's 13 runs.
4. **DetachableJoint round trip.** The existing
   `/xh/p0/red_cube/attach` and `/xh/p0/red_cube/detach` topics each produce
   their expected grasp-state transition. This is explicitly not a
   finger-contact grasp or an S3 success.
5. **Table rest stability.** Before a task action, the production red cube is
   sampled for five seconds and its total world-position excursion is below
   1 mm.

Every capability-audit evidence bundle must include the full `gz plugin --info`
interface list for Bullet-Featherstone, installed `gz-physics7` and
`gz_ros2_control` versions, and the SHA-256 values for the controlled URDF,
generated SDF, and executing generator. The generator's whitelist diff must
prove that the injected q1 mimic node is its only SDF semantic delta; its
mechanical comparison must cover transforms, collision geometry, sensors,
joint names/limits/units, plugins, and `ros2_control` interfaces.
The q1 `ros2_control` declaration must export **only** `position` and
`velocity` state interfaces with its `0.02 m` initial value. It must contain
no `mimic` or `multiplier` parameter: `gz_ros2_control` converts either
parameter pair into an active q1 velocity command, which would duplicate the
generated SDF/Bullet physical follower constraint. The q2 declaration remains
the sole position command interface. The generator's mechanical-equivalence
check and unit test enforce this fail-closed contract.

Only after all five gates pass, rerun the same-SHA home self-collision gate,
all 13 revised S0 conditions, and S1's 10 plan → execute → FK trials. Only
after those gates pass, apply the already approved fresh-SHA S2 allocation
reset (3 × 5); retain all historical attempts as historical.

After the five primary gates, a separate ten-minute, non-gating q1-only
command probe may record whether the historical q1-close failure was DART
specific. It must not alter the q2-master contract or reopen ADR-0008.

## Approval record

- Human approver: **APPROVED 2026-07-17 (Asia/Shanghai)**
- Explicit SDF spawn representation + Bullet-Featherstone engine: **APPROVED**
- Scope confirmation (M1A production + calibration worlds only): **APPROVED**
- Five independent engine-capability gates before S0: **REQUIRED**
- Implementation SHA: **PENDING — recorded only with a completed capability audit**

## Appendix A — approved Bullet opposed-axis compensation probe

Approved 2026-07-17 (Asia/Shanghai), with a two-hour diagnosis timebox.

The first independent Bullet GATE2 run preserves the complete controller
reference/output at `0.040 m`, but both fingers settle around `0.016 m`; its
uncommanded initial state is around `0.0133 m` despite a `0.020 m` initial
value, while the `0.010 m` close succeeds. The q1/q2 tracking residual is
approximately `4.7e-8 m`, no finger contact is observed, and the Bullet
plugin evidence records gz-physics7 Bullet-Featherstone `7.6.0`.

This was a force-balance hypothesis, not a completed root-cause finding.

The approved counterfactual changes only the generated **Bullet SDF** mimic
multiplier to `-1.0`. The controlled URDF, ros2_control parameters, joint
names, limits, units, contact geometry, action adapter, and semantic contract
remain `q1=q2` with `positive=open`. The generator manifest names this
`BULLET_OPPOSED_PRISMATIC_AXIS_SIGN` compensation and records both the
semantic multiplier (`+1`) and emitted SDF multiplier (`-1`).

The counterfactual was recorded by the completed
`m1a-20260717-bullet-opposed-axis-compensation-gate2` probe. Its generated SDF
had exactly the intended `-1` multiplier, but the passive state converged to
approximately zero (20 mm from the required initial state) and both open and
close commands remained at zero.

### A.2 Second counterfactual — q2 axis-frame normalization

Within the same approved two-hour GATE2 diagnosis timebox, the second
counterfactual normalized only the generated SDF representation: q2's SDF
axis became `+Y`, its SDF joint frame was rolled by `pi`, and the q2 child link
received the inverse relative roll. The temporary generator whitelist had
exactly two SDF-only deltas: that q2 axis-frame pair and q1's
`multiplier=+1` mimic node. It proved unchanged zero-pose link transforms,
12 collision transforms, and both sensor reference transforms before launch.

The counterfactual was recorded by
`m1a-20260717-bullet-q2-axis-frame-r1`. Its GATE1 passed, but GATE2 repeated
the original force-balance signature: passive q1/q2 were about `0.013295 m`,
open stalled at `0.015892 m` with a `0.024208 m` error, and close to `0.010 m`
passed. The source generator has therefore been restored to its direct,
single-mimic SDF representation; neither historical experimental encoding remains on the
production path. The two counterfactual bundles are retained as historical
evidence only; neither is valid for multiplier-sign inference because both
runs retained the controller-level q1 mimic loop identified below.

## Appendix B — post-timebox static actuation-path audit

**Status: repair approved 2026-07-17 (Asia/Shanghai).**

The two SDF-only counterfactuals do not resolve the proposed multiplier or
axis-frame encodings; they do not, by themselves, prove that Bullet's physical
constraint is the sole actuator in GATE2. A post-timebox, read-only audit of
the *installed* `ros-jazzy-gz-ros2-control` package found a second command
path that the prior approval record incorrectly described as state-only.

The installed package is `gz_ros2_control 1.2.19-1noble.20260615.171757`.
Its upstream release source is tag `1.2.19`, commit
`3632af2998895cd18c03717bd40c7acd547db24d`; the audited
`gz_system.cpp` SHA-256 is
`33cf54384d8893cfcdb523a30d08f4239daffcc06d4884762433fe64e93357ea`.
The initial audit incorrectly attributed `info_.mimic_joints` solely to q1
`<param>` nodes. The installed `hardware_interface`
`4.45.2-1noble.20260615.155429` parses the entire URDF: whenever a structural
URDF joint has `<mimic>` and its corresponding `<ros2_control><joint>` does
not carry `mimic="false"`, it appends a `MimicJoint` to `info_.mimic_joints`.
`gz_ros2_control` then iterates that list during every `write()` and creates
or overwrites q1's
`sim::components::JointVelocityCmd` with
`-(q1 - q2 * multiplier) * update_rate`. This happens although q1 exports no
ROS command interface.

Consequently the current configuration has both:

1. the generated SDF/Bullet q1 physical gear constraint; and
2. a `gz_ros2_control` velocity-level q1 mimic loop.

That violates ADR-0008's intended single physical master boundary. It is a
specific, source-level causal candidate for GATE2's resistance to opening; it
is not yet a runtime-proven final cause. The upstream Bullet implementation
also directly negates the SDF multiplier before setting its gear ratio, so the
historical `multiplier=-1` SDF test was not a compensating representation of
the engine's documented conversion.

The human-approved direct-parameter removal was applied. Its fresh `+1` run
(`m1a-20260717-clean-plus1-r1`) proves the parameter pair absent in the
generated-SDF manifest, but still logs q1 as mimicking q2 and repeats the
passive sag/open-stall signature. It is therefore contaminated and is not
valid multiplier-sign evidence.

The precise state-only realization is the standard parser opt-out:
`<ros2_control><joint name="panda_finger_joint1" mimic="false">` with q1's
existing `position`/`velocity` state interfaces. This is not a new physical
model: it retains the structural URDF/SDF physical mimic and public adapter,
while preventing the controller from becoming a second q1 actuator. It
changes no joint name, limit, unit, contact geometry, sensor frame, controller
endpoint, or external two-finger action semantics. The generator and unit test
fail closed unless that attribute and the absence of q1 mimic/multiplier
parameters are both preserved.

After rebuilding this exact opt-out, the clean acceptance sequence is: fresh
direct-SDF `multiplier=+1` GATE2 first; only if its no-command sag or open
stall recurs, a separately time-boxed ten-minute `multiplier=-1` GATE2 may
run. A passing GATE2 then advances fail-closed through GATE3–5, home
self-collision, S0, S1, and the fresh S2 allocation.

### B.1 Clean multiplier result and remaining gate

The required clean probes have completed. With `mimic="false"`, direct SDF
`+1` has no q1 controller-mimic log; the q2-master opens to `0.04 m` with a
`0.272 mm` maximum terminal error and closes to `0.01 m` with a `0.0011 mm`
error. The clean `-1` probe instead collapses both fingers to zero and cannot
open or close them. `+1` is therefore retained as the production encoding and
the multiplier sign is no longer an open hypothesis.

The `+1` run still fails GATE2's no-command initial-state check: both joints
settled at about `0.0183258 m`, which is `1.6742 mm` from `0.020 m` and exceeds
the approved `1 mm` tolerance. This is an independent q2 hold/initialization
problem. GATE3–5, S0, S1 and S2 remain prohibited until it is fixed without
restoring a q1 controller mimic or weakening that tolerance.
