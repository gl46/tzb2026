// ADR-0024 A.3 flat, query-only adapter for the pinned Bullet float64 core.
//
// This translation unit constructs only conservative convex shapes from
// byte-bound parameters.  It owns no world, controller, articulation, target,
// or simulation object and therefore cannot actuate or step Isaac.

#include <cmath>
#include <cstddef>
#include <limits>
#include <memory>

#include <BulletCollision/CollisionShapes/btBoxShape.h>
#include <BulletCollision/CollisionShapes/btConvexHullShape.h>
#include <BulletCollision/CollisionShapes/btConvexShape.h>
#include <BulletCollision/CollisionShapes/btCylinderShape.h>
#include <LinearMath/btQuaternion.h>
#include <LinearMath/btTransform.h>
#include <LinearMath/btVector3.h>

#ifndef BT_USE_DOUBLE_PRECISION
#error "ADR-0024 A.3 native adapter requires Bullet float64"
#endif

static_assert(sizeof(btScalar) == sizeof(double),
              "ADR-0024 A.3 native adapter scalar ABI is not float64");

extern "C" int m2c_a3_child_pair_ccd_detailed_v1(
    const btConvexShape*, const btTransform*, const btTransform*,
    const btConvexShape*, const btTransform*, const btTransform*, double,
    double, double*, int*, int*, int*, int*, int*);

namespace {

constexpr int kBox = 1;
constexpr int kCylinderZ = 2;
constexpr int kConvexHull = 3;

bool finite_positive(double value) {
  return std::isfinite(value) && value > 0.0;
}

bool hull_is_nondegenerate(const double* vertices_xyz,
                           std::size_t vertex_count, double tolerance_m) {
  if (!vertices_xyz || vertex_count < 4 || !finite_positive(tolerance_m) ||
      tolerance_m > 1e-6) {
    return false;
  }
  const btScalar tolerance(tolerance_m);
  const btScalar volume_tolerance = tolerance * tolerance * tolerance;
  const btVector3 a(vertices_xyz[0], vertices_xyz[1], vertices_xyz[2]);
  for (std::size_t b_index = 1; b_index < vertex_count; ++b_index) {
    const btVector3 b(vertices_xyz[b_index * 3], vertices_xyz[b_index * 3 + 1],
                      vertices_xyz[b_index * 3 + 2]);
    const btVector3 ab = b - a;
    if (ab.length2() <= tolerance * tolerance) {
      continue;
    }
    for (std::size_t c_index = b_index + 1; c_index < vertex_count;
         ++c_index) {
      const btVector3 c(vertices_xyz[c_index * 3],
                        vertices_xyz[c_index * 3 + 1],
                        vertices_xyz[c_index * 3 + 2]);
      const btVector3 normal = ab.cross(c - a);
      if (normal.length2() <= volume_tolerance * volume_tolerance) {
        continue;
      }
      for (std::size_t d_index = c_index + 1; d_index < vertex_count;
           ++d_index) {
        const btVector3 d(vertices_xyz[d_index * 3],
                          vertices_xyz[d_index * 3 + 1],
                          vertices_xyz[d_index * 3 + 2]);
        if (std::abs(normal.dot(d - a)) > volume_tolerance) {
          return true;
        }
      }
    }
  }
  return false;
}

std::unique_ptr<btConvexShape> make_shape(
    int kind, const double* parameters, std::size_t parameter_count,
    const double* vertices_xyz, std::size_t vertex_count,
    double hull_construction_tolerance_m, double outward_padding_m,
    double collision_margin_m) {
  if (!parameters || !finite_positive(outward_padding_m) ||
      outward_padding_m < 0.002 || !finite_positive(collision_margin_m) ||
      collision_margin_m < 0.04 ||
      !finite_positive(hull_construction_tolerance_m) ||
      hull_construction_tolerance_m > 1e-6) {
    return nullptr;
  }
  const double expansion = outward_padding_m + collision_margin_m;
  std::unique_ptr<btConvexShape> result;
  if (kind == kBox) {
    if (parameter_count != 3 || vertex_count != 0 || vertices_xyz != nullptr ||
        !finite_positive(parameters[0]) || !finite_positive(parameters[1]) ||
        !finite_positive(parameters[2])) {
      return nullptr;
    }
    result = std::make_unique<btBoxShape>(btVector3(
        parameters[0] * 0.5 + expansion,
        parameters[1] * 0.5 + expansion,
        parameters[2] * 0.5 + expansion));
  } else if (kind == kCylinderZ) {
    if (parameter_count != 2 || vertex_count != 0 || vertices_xyz != nullptr ||
        !finite_positive(parameters[0]) || !finite_positive(parameters[1])) {
      return nullptr;
    }
    result = std::make_unique<btCylinderShapeZ>(btVector3(
        parameters[0] + expansion, parameters[0] + expansion,
        parameters[1] * 0.5 + expansion));
  } else if (kind == kConvexHull) {
    if (parameter_count != 1 || parameters[0] != 1.0 ||
        !hull_is_nondegenerate(vertices_xyz, vertex_count,
                               hull_construction_tolerance_m)) {
      return nullptr;
    }
    auto hull = std::make_unique<btConvexHullShape>();
    for (std::size_t index = 0; index < vertex_count; ++index) {
      const double x = vertices_xyz[index * 3];
      const double y = vertices_xyz[index * 3 + 1];
      const double z = vertices_xyz[index * 3 + 2];
      if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
        return nullptr;
      }
      // Every decoded vertex is retained. Bullet's support mapping therefore
      // represents their convex hull; the combined spherical margin is an
      // outward-only envelope, not a geometry-equality claim.
      hull->addPoint(btVector3(x, y, z), false);
    }
    hull->recalcLocalAabb();
    hull->setMargin(btScalar(expansion));
    result = std::move(hull);
  } else {
    return nullptr;
  }
  if (!result) {
    return nullptr;
  }
  if (kind != kConvexHull) {
    // Dimensions above already include both outward additions. Setting the
    // configured margin adjusts Bullet's implicit dimensions while preserving
    // that conservative outer extent.
    result->setMargin(btScalar(collision_margin_m));
  }
  const btScalar disc = result->getAngularMotionDisc();
  if (!std::isfinite(disc) || disc <= btScalar(0.0)) {
    return nullptr;
  }
  return result;
}

bool make_transform(const double* values, btTransform* output) {
  if (!values || !output) {
    return false;
  }
  for (int index = 0; index < 7; ++index) {
    if (!std::isfinite(values[index])) {
      return false;
    }
  }
  const double norm = std::sqrt(values[3] * values[3] + values[4] * values[4] +
                                values[5] * values[5] + values[6] * values[6]);
  if (std::abs(norm - 1.0) > 1e-9) {
    return false;
  }
  btQuaternion rotation(values[4], values[5], values[6], values[3]);
  output->setIdentity();
  output->setOrigin(btVector3(values[0], values[1], values[2]));
  output->setRotation(rotation);
  return true;
}

}  // namespace

extern "C" int m2c_a3_flat_child_pair_ccd_v1(
    int kind_a, const double* parameters_a, std::size_t parameter_count_a,
    const double* vertices_a, std::size_t vertex_count_a,
    double hull_construction_tolerance_a, double outward_padding_a,
    double collision_margin_a,
    const double* from_a_values, const double* to_a_values,
    int kind_b, const double* parameters_b, std::size_t parameter_count_b,
    const double* vertices_b, std::size_t vertex_count_b,
    double hull_construction_tolerance_b, double outward_padding_b,
    double collision_margin_b,
    const double* from_b_values, const double* to_b_values,
    double contact_distance_threshold_m, double toi_tolerance,
    double* time_of_impact, int* failure_code, int* iterations,
    int* discrete_start_clear, int* discrete_end_clear,
    int* continuous_query_completed) {
  if (time_of_impact) {
    *time_of_impact = std::numeric_limits<double>::quiet_NaN();
  }
  if (failure_code) {
    *failure_code = -200;
  }
  if (iterations) {
    *iterations = 0;
  }
  if (discrete_start_clear) {
    *discrete_start_clear = 0;
  }
  if (discrete_end_clear) {
    *discrete_end_clear = 0;
  }
  if (continuous_query_completed) {
    *continuous_query_completed = 0;
  }
  if (!time_of_impact || !failure_code || !iterations ||
      !discrete_start_clear || !discrete_end_clear ||
      !continuous_query_completed) {
    return 2;
  }
  auto shape_a = make_shape(kind_a, parameters_a, parameter_count_a, vertices_a,
                            vertex_count_a, hull_construction_tolerance_a,
                            outward_padding_a, collision_margin_a);
  auto shape_b = make_shape(kind_b, parameters_b, parameter_count_b, vertices_b,
                            vertex_count_b, hull_construction_tolerance_b,
                            outward_padding_b, collision_margin_b);
  btTransform from_a, to_a, from_b, to_b;
  if (!shape_a || !shape_b || !make_transform(from_a_values, &from_a) ||
      !make_transform(to_a_values, &to_a) ||
      !make_transform(from_b_values, &from_b) ||
      !make_transform(to_b_values, &to_b)) {
    if (failure_code) {
      *failure_code = -200;
    }
    return 2;
  }
  return m2c_a3_child_pair_ccd_detailed_v1(
      shape_a.get(), &from_a, &to_a, shape_b.get(), &from_b, &to_b,
      contact_distance_threshold_m, toi_tolerance, time_of_impact,
      failure_code, iterations, discrete_start_clear, discrete_end_clear,
      continuous_query_completed);
}
