// Independent Orocos KDL comparison tool for ControlledPandaReadOnlyFKProviderV1.
//
// This executable is deliberately separate from the production Python FK
// provider.  It loads the exact URDF through ROS kdl_parser, constructs an
// independent KDL chain from `world` to each collision link, and prints one
// canonical CSV row per link.  It never opens a controller, Isaac, or a scene.

#include <kdl/chain.hpp>
#include <kdl/chainfksolverpos_recursive.hpp>
#include <kdl/frames.hpp>
#include <kdl/jntarray.hpp>
#include <kdl_parser/kdl_parser.hpp>

#include <array>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <string>

namespace {

constexpr std::array<const char*, 9> kJointNames = {
    "panda_joint1",       "panda_joint2",       "panda_joint3",
    "panda_joint4",       "panda_joint5",       "panda_joint6",
    "panda_joint7",       "panda_finger_joint1", "panda_finger_joint2",
};

constexpr std::array<const char*, 12> kCollisionLinks = {
    "panda_hand",        "panda_leftfinger", "panda_link0",
    "panda_link1",       "panda_link2",      "panda_link3",
    "panda_link4",       "panda_link5",      "panda_link6",
    "panda_link7",       "panda_link8",      "panda_rightfinger",
};

bool ParseFinite(const char* raw, double* value) {
  char* end = nullptr;
  *value = std::strtod(raw, &end);
  return end != raw && *end == '\0' && std::isfinite(*value);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 12) {
    std::cerr << "usage: controlled_panda_fk_kdl_verifier_v1 URDF state_index q1 ... q7 finger1 finger2\n";
    return 2;
  }
  char* state_end = nullptr;
  const long state_index = std::strtol(argv[2], &state_end, 10);
  if (state_end == argv[2] || *state_end != '\0' || state_index < 0) {
    std::cerr << "malformed state index\n";
    return 3;
  }
  std::map<std::string, double> positions;
  for (std::size_t index = 0; index < kJointNames.size(); ++index) {
    double value = 0.0;
    if (!ParseFinite(argv[index + 3], &value)) {
      std::cerr << "non-finite or malformed joint position\n";
      return 4;
    }
    positions.emplace(kJointNames[index], value);
  }
  if (std::abs(positions.at("panda_finger_joint1") -
               positions.at("panda_finger_joint2")) > 1e-12) {
    std::cerr << "finger mimic relation differs\n";
    return 5;
  }

  KDL::Tree tree;
  if (!kdl_parser::treeFromFile(argv[1], tree)) {
    std::cerr << "kdl_parser rejected URDF\n";
    return 6;
  }

  std::cout << std::setprecision(std::numeric_limits<double>::max_digits10);
  for (const char* link : kCollisionLinks) {
    KDL::Chain chain;
    if (!tree.getChain("world", link, chain)) {
      std::cerr << "KDL chain is unavailable: " << link << '\n';
      return 7;
    }
    KDL::JntArray state(chain.getNrOfJoints());
    unsigned int joint_index = 0;
    for (unsigned int segment_index = 0; segment_index < chain.getNrOfSegments();
         ++segment_index) {
      const KDL::Joint& joint = chain.getSegment(segment_index).getJoint();
      if (joint.getType() == KDL::Joint::None) {
        continue;
      }
      const auto found = positions.find(joint.getName());
      if (found == positions.end() || joint_index >= state.rows()) {
        std::cerr << "KDL chain contains an unbound joint: " << joint.getName() << '\n';
        return 8;
      }
      state(joint_index++) = found->second;
    }
    if (joint_index != state.rows()) {
      std::cerr << "KDL chain joint coverage differs\n";
      return 9;
    }
    KDL::ChainFkSolverPos_recursive solver(chain);
    KDL::Frame frame;
    if (solver.JntToCart(state, frame) < 0) {
      std::cerr << "KDL FK failed: " << link << '\n';
      return 10;
    }
    double qx = 0.0;
    double qy = 0.0;
    double qz = 0.0;
    double qw = 0.0;
    frame.M.GetQuaternion(qx, qy, qz, qw);
    if (qw < 0.0 ||
        (qw == 0.0 && (qx < 0.0 || (qx == 0.0 && (qy < 0.0 || (qy == 0.0 && qz < 0.0)))))) {
      qw = -qw;
      qx = -qx;
      qy = -qy;
      qz = -qz;
    }
    std::cout << state_index << ',' << link << ',' << frame.p.x() << ',' << frame.p.y()
              << ',' << frame.p.z()
              << ',' << qw << ',' << qx << ',' << qy << ',' << qz << '\n';
  }
  return 0;
}
