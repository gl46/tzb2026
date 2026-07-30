cmake_minimum_required(VERSION 3.8)
project(xh_sim)
find_package(ament_cmake REQUIRED)
install(DIRECTORY worlds config launch urdf DESTINATION share/${PROJECT_NAME})
install(PROGRAMS
  scripts/panda_hand_mimic_adapter.py
  scripts/robot_description_relay.py
  scripts/generate_panda_spawn_sdf.py
  DESTINATION lib/${PROJECT_NAME}
)
ament_package()
