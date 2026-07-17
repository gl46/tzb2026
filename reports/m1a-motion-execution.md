# M1A S1 MoveIt execution gate

- Status: `VERIFIED_MOVEIT_EXECUTION`
- Reason: 10/10 three-segment MoveIt trials passed all recorded gates.
- Same URDF sha256: `84b0d2dc67dea0071a696e4e09211d0ff44d9694e57d7b2a3aa8978f37e5081c` / `84b0d2dc67dea0071a696e4e09211d0ff44d9694e57d7b2a3aa8978f37e5081c`
- Enabled robot/world collision pairs: `[['panda_link1', 'work_table'], ['panda_link2', 'work_table'], ['panda_link3', 'work_table'], ['panda_link4', 'work_table'], ['panda_link5', 'work_table'], ['panda_link6', 'work_table'], ['panda_link7', 'work_table'], ['panda_link8', 'work_table'], ['panda_hand', 'work_table'], ['panda_leftfinger', 'work_table'], ['panda_rightfinger', 'work_table'], ['panda_leftfinger', 'object_red_cube'], ['panda_rightfinger', 'object_red_cube'], ['panda_leftfinger', 'bin_a'], ['panda_rightfinger', 'bin_a'], ['panda_hand', 'bin_a']]`
- SRDF adjacent self-pairs: `[['panda_link0', 'panda_link1'], ['panda_link1', 'panda_link2'], ['panda_link2', 'panda_link3'], ['panda_link3', 'panda_link4'], ['panda_link4', 'panda_link5'], ['panda_link5', 'panda_link6'], ['panda_link6', 'panda_link7'], ['panda_link7', 'panda_link8'], ['panda_link8', 'panda_hand'], ['panda_hand', 'panda_leftfinger'], ['panda_hand', 'panda_rightfinger']]`
- ADJACENT_SELF_PAIRS audit: `PASS_EXACT_MATCH_TO_ADJACENT_SELF_PAIRS`
