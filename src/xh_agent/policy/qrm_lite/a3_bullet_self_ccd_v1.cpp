// ADR-0024 A.3 query-only Bullet 3.24 child-pair CCD backend core.
//
// This file exposes no Isaac/controller/scene API. The caller owns byte-bound
// convex shapes and transforms. Every call performs separate discrete GJK
// checks at both ends and one moving-vs-moving btContinuousConvexCollision.
// A failure callback, iteration exhaustion, non-finite output, or near contact
// is rejection. Production builds must define BT_USE_DOUBLE_PRECISION and link
// only the two float64 libraries pinned by the Phase-2 addendum.

#include <cmath>
#include <cstdint>

#include <BulletCollision/CollisionShapes/btConvexShape.h>
#include <BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h>
#include <BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h>
#include <BulletCollision/NarrowPhaseCollision/btGjkPairDetector.h>
#include <BulletCollision/NarrowPhaseCollision/btPointCollector.h>
#include <BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h>
#include <LinearMath/btTransformUtil.h>

#ifndef BT_USE_DOUBLE_PRECISION
#error "ADR-0024 A.3 requires a Bullet float64 build"
#endif

namespace {

struct FailClosedCastResult final : btConvexCast::CastResult {
  int failure_code = 0;
  int iterations = 0;
  void reportFailure(int error, int count) override {
    failure_code = error;
    iterations = count;
  }
};

bool finite_vector(const btVector3& value) {
  return std::isfinite(value.x()) && std::isfinite(value.y()) &&
         std::isfinite(value.z());
}

bool finite_transform(const btTransform& value) {
  return finite_vector(value.getOrigin()) &&
         finite_vector(value.getBasis().getColumn(0)) &&
         finite_vector(value.getBasis().getColumn(1)) &&
         finite_vector(value.getBasis().getColumn(2));
}

bool discrete_distance(const btConvexShape* a, const btTransform& transform_a,
                       const btConvexShape* b, const btTransform& transform_b,
                       btScalar* distance) {
  btVoronoiSimplexSolver simplex;
  btGjkEpaPenetrationDepthSolver penetration;
  btGjkPairDetector detector(a, b, a->getShapeType(), b->getShapeType(),
                             a->getMargin(), b->getMargin(), &simplex,
                             &penetration);
  btGjkPairDetector::ClosestPointInput input;
  input.m_transformA = transform_a;
  input.m_transformB = transform_b;
  btPointCollector collector;
  detector.getClosestPoints(input, collector, nullptr);
  if (!collector.m_hasResult || !std::isfinite(collector.m_distance)) {
    return false;
  }
  *distance = collector.m_distance;
  return true;
}

bool conservative_no_contact_certificate(
    const btConvexShape* a, const btTransform& from_a,
    const btTransform& to_a, const btConvexShape* b,
    const btTransform& from_b, const btTransform& to_b,
    btScalar start_distance, btScalar reject_distance) {
  btVector3 linear_a, angular_a, linear_b, angular_b;
  btTransformUtil::calculateVelocity(from_a, to_a, btScalar(1.0), linear_a,
                                     angular_a);
  btTransformUtil::calculateVelocity(from_b, to_b, btScalar(1.0), linear_b,
                                     angular_b);
  const btScalar radius_a = a->getAngularMotionDisc();
  const btScalar radius_b = b->getAngularMotionDisc();
  const btScalar displacement_a = linear_a.length() + angular_a.length() * radius_a;
  const btScalar displacement_b = linear_b.length() + angular_b.length() * radius_b;
  if (!std::isfinite(radius_a) || !std::isfinite(radius_b) ||
      !std::isfinite(displacement_a) || !std::isfinite(displacement_b)) {
    return false;
  }
  // Triangle inequality: no point pair can close by more than the sum of the
  // two conservative angular/linear motion discs during this cast.  Strict
  // comparison resolves equality and numeric ambiguity toward rejection.
  return start_distance > reject_distance + displacement_a + displacement_b;
}

}  // namespace

extern "C" int m2c_a3_child_pair_ccd_detailed_v1(
    const btConvexShape* shape_a, const btTransform* from_a,
    const btTransform* to_a, const btConvexShape* shape_b,
    const btTransform* from_b, const btTransform* to_b,
    double contact_distance_threshold_m, double toi_tolerance,
    double* time_of_impact, int* failure_code, int* iterations,
    int* discrete_start_clear, int* discrete_end_clear,
    int* continuous_query_completed) {
  if (!shape_a || !shape_b || !from_a || !to_a || !from_b || !to_b ||
      !time_of_impact || !failure_code || !iterations ||
      !discrete_start_clear || !discrete_end_clear ||
      !continuous_query_completed ||
      !std::isfinite(contact_distance_threshold_m) ||
      contact_distance_threshold_m < 0.001 || !std::isfinite(toi_tolerance) ||
      toi_tolerance <= 0.0 || toi_tolerance > 1e-6 ||
      !finite_transform(*from_a) || !finite_transform(*to_a) ||
      !finite_transform(*from_b) || !finite_transform(*to_b)) {
    return 2;
  }
  *time_of_impact = 2.0;
  *failure_code = 0;
  *iterations = 0;
  *discrete_start_clear = 0;
  *discrete_end_clear = 0;
  *continuous_query_completed = 0;
  const btScalar threshold(contact_distance_threshold_m);
  btScalar start_distance = btScalar(0.0);
  btScalar end_distance = btScalar(0.0);
  if (!discrete_distance(shape_a, *from_a, shape_b, *from_b,
                         &start_distance) ||
      !discrete_distance(shape_a, *to_a, shape_b, *to_b, &end_distance)) {
    return 2;
  }
  *discrete_start_clear = start_distance > threshold ? 1 : 0;
  *discrete_end_clear = end_distance > threshold ? 1 : 0;
  if (start_distance <= threshold || end_distance <= threshold) {
    return 1;
  }

  btVoronoiSimplexSolver simplex;
  btGjkEpaPenetrationDepthSolver penetration;
  btContinuousConvexCollision query(shape_a, shape_b, &simplex, &penetration);
  FailClosedCastResult result;
  result.m_allowedPenetration = btScalar(0.0);
  const bool hit = query.calcTimeOfImpact(*from_a, *to_a, *from_b, *to_b, result);
  *failure_code = result.failure_code;
  *iterations = result.iterations;
  if (result.failure_code != 0) {
    return 2;
  }
  if (hit) {
    *continuous_query_completed = 1;
    if (!std::isfinite(result.m_fraction) ||
        result.m_fraction < btScalar(-toi_tolerance) ||
        result.m_fraction > btScalar(1.0 + toi_tolerance)) {
      return 2;
    }
    *time_of_impact = result.m_fraction;
    return 1;
  }
  // Bullet returns false for both a certified miss and several ambiguous
  // early exits that do not call reportFailure.  Never equate false with
  // CLEAR unless an independent conservative motion-disc certificate proves
  // that the starting separation cannot close to the rejection threshold.
  if (!conservative_no_contact_certificate(
          shape_a, *from_a, *to_a, shape_b, *from_b, *to_b,
          start_distance, threshold)) {
    *failure_code = -100;
    return 2;
  }
  *continuous_query_completed = 1;
  return 0;
}

extern "C" int m2c_a3_child_pair_ccd_v1(
    const btConvexShape* shape_a, const btTransform* from_a,
    const btTransform* to_a, const btConvexShape* shape_b,
    const btTransform* from_b, const btTransform* to_b,
    double contact_distance_threshold_m, double toi_tolerance,
    double* time_of_impact, int* failure_code, int* iterations) {
  int discrete_start_clear = 0;
  int discrete_end_clear = 0;
  int continuous_query_completed = 0;
  return m2c_a3_child_pair_ccd_detailed_v1(
      shape_a, from_a, to_a, shape_b, from_b, to_b,
      contact_distance_threshold_m, toi_tolerance, time_of_impact,
      failure_code, iterations, &discrete_start_clear, &discrete_end_clear,
      &continuous_query_completed);
}
