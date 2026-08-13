from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/m2c/build_a3_bullet_native_closure.py"
DOCKERFILE_PATH = ROOT / "docker/m2c-a3-bullet-builder/Dockerfile"
SPEC = importlib.util.spec_from_file_location("m2c_a3_native_build", SCRIPT_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_builder_constants_match_governed_sources_and_adapter_contract() -> None:
    from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
        EXPECTED_AUDITED_BULLET_HEADERS,
        NATIVE_ADAPTER_PATH,
        NATIVE_CORE_PATH,
    )

    assert hashlib.sha256((ROOT / NATIVE_CORE_PATH).read_bytes()).hexdigest() == (
        BUILDER.CORE_SHA256
    )
    assert hashlib.sha256((ROOT / NATIVE_ADAPTER_PATH).read_bytes()).hexdigest() == (
        BUILDER.ADAPTER_SHA256
    )
    assert {
        f"/usr/include/bullet/{path}": digest for path, digest in BUILDER.EXPECTED_HEADERS.items()
    } == dict(EXPECTED_AUDITED_BULLET_HEADERS)
    assert BUILDER.BUILD_FLAGS == (
        "-std=c++17",
        "-O2",
        "-fPIC",
        "-shared",
        "-DBT_USE_DOUBLE_PRECISION",
        "-fno-fast-math",
        "-ffp-contract=off",
    )


def test_builder_rejects_mutable_or_wrong_source_before_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "src"
    include = tmp_path / "include"
    libraries = tmp_path / "lib"
    output = tmp_path / "output"
    source.mkdir()
    include.mkdir()
    libraries.mkdir()
    (source / BUILDER.CORE_NAME).write_text("wrong")
    (source / BUILDER.ADAPTER_NAME).write_text("wrong")
    compiler = tmp_path / "g++"
    compiler.write_text("not executed")

    called = False

    def unexpected(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True
        raise AssertionError("compiler must not run")

    monkeypatch.setattr(BUILDER, "_run", unexpected)
    args = argparse.Namespace(
        source_root=source,
        bullet_include_root=include,
        bullet_library_root=libraries,
        compiler=compiler,
        build_container_digest="sha256:" + "a" * 64,
        output_root=output,
    )
    with pytest.raises(BUILDER.BuildFailure, match="SHA-256 differs"):
        BUILDER.build(args)
    assert not called
    assert not output.exists()


def test_builder_dockerfile_is_network_free_query_only_and_content_addressed() -> None:
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE" in content
    assert "FROM ${BASE_IMAGE}" in content
    assert "ARG BASE_IMAGE_DIGEST" in content
    assert "build_a3_bullet_native_closure.py" in content
    assert "\nRUN " not in content
    assert "BT_USE_DOUBLE_PRECISION" not in content  # one governed source of flags
    forbidden = ("apt-get", "curl", "wget", "git clone", "/isaac-sim/", "--gpus")
    assert not any(token in content.lower() for token in forbidden)


def test_dynamic_contract_rejects_unexpected_needed_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared_object = tmp_path / "module.so"
    shared_object.write_bytes(b"elf")
    output = "\n".join(
        [
            "Shared library: [libBulletCollision-float64.so.3.24]",
            "Shared library: [libLinearMath-float64.so.3.24]",
            "Shared library: [libc.so.6]",
            "Shared library: [libevil.so]",
            "Shared library: [libgcc_s.so.1]",
            "Shared library: [libm.so.6]",
            "Shared library: [libstdc++.so.6]",
            "Library runpath: [/usr/lib/x86_64-linux-gnu]",
        ]
    )

    class Result:
        stdout = output

    monkeypatch.setattr(BUILDER, "_run", lambda *args, **kwargs: Result())
    with pytest.raises(BUILDER.BuildFailure, match="dynamic dependency"):
        BUILDER._dynamic_contract(shared_object)


def test_compile_dependency_closure_rejects_escape_but_not_audited_unused_header(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    include = tmp_path / "include"
    source.mkdir()
    include.mkdir()
    core = source / BUILDER.CORE_NAME
    adapter = source / BUILDER.ADAPTER_NAME
    actual_header = include / "actual.h"
    unused_audited_header = include / "audited-unused.h"
    for path in (core, adapter, actual_header, unused_audited_header):
        path.write_text(path.name)
    dependency_set = {core.resolve(), adapter.resolve(), actual_header.resolve()}
    assert {core.resolve(), adapter.resolve()}.issubset(dependency_set)
    assert all(
        path in {core.resolve(), adapter.resolve()} or include in path.parents
        for path in dependency_set
    )
    escaped = tmp_path / "evil.h"
    escaped.write_text("evil")
    assert include not in escaped.resolve().parents
