# ADR-0024 A.3 query-only native builder.
#
# The build context is assembled from byte-verified inputs.  The base must be
# supplied by immutable image ID; networking is disabled by the invoking
# command.  This image contains no Isaac, controller, or robot execution path.

ARG BASE_IMAGE=m2c-a3-build-base:4a46e0a6f5c2024a
FROM ${BASE_IMAGE}
ARG BASE_IMAGE_DIGEST

LABEL org.opencontainers.image.base.digest="${BASE_IMAGE_DIGEST}" \
      org.opencontainers.image.title="M2C ADR-0024 A.3 query-only builder" \
      xh.m2c.teacher-used="false" \
      xh.m2c.physical-execution="false"

COPY usr/include/bullet/ /usr/include/bullet/
COPY usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24 \
     /usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24
COPY usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24 \
     /usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24
COPY src/a3_bullet_self_ccd_v1.cpp /opt/m2c-a3/src/a3_bullet_self_ccd_v1.cpp
COPY src/a3_bullet_native_adapter_v1.cpp /opt/m2c-a3/src/a3_bullet_native_adapter_v1.cpp
COPY build_a3_bullet_native_closure.py /opt/m2c-a3/build_a3_bullet_native_closure.py
