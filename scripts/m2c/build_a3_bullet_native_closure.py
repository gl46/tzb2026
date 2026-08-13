#!/usr/bin/env python3
"""Build the ADR-0024 A.3 query-only Bullet module and emit a strict receipt.

This utility is deliberately independent of Isaac and the project Python
environment so it can run inside a small immutable build image.  It validates
every governed source/header/library byte before invoking the compiler, records
the complete compiler dependency list, rejects unexpected dynamic linkage, and
publishes create-only JSON receipts.  It never starts a simulator, opens a
scene, writes a controller target, or performs training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Iterable


SCHEMA_VERSION = "M2CA3NativeBuildReceiptV1"
INPUTS_SCHEMA_VERSION = "M2CA3CompileInputsV1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BASE_IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

CORE_NAME = "a3_bullet_self_ccd_v1.cpp"
ADAPTER_NAME = "a3_bullet_native_adapter_v1.cpp"
CORE_SHA256 = "48a1caa8d2f1c8fcb76a504377f399223018a26925c03f1d549db9bab833506f"
ADAPTER_SHA256 = "5de2750b6704e30eef1955d3e7f60692cc424777f23024aa064410585331c900"
COLLISION_LIBRARY_NAME = "libBulletCollision-float64.so.3.24"
LINEAR_MATH_LIBRARY_NAME = "libLinearMath-float64.so.3.24"
COLLISION_LIBRARY_SHA256 = "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2"
LINEAR_MATH_LIBRARY_SHA256 = "5d3fe859ad08f78fac1e51ed85dddd9e39da501a0d566e86e00da5565d9e5343"
EXPECTED_HEADERS = {
    "BulletCollision/CollisionShapes/btBoxShape.h": (
        "8ec85f0c79e746088a186979c174a1ec5007a150e5281030f2e8321e4c1eeac7"
    ),
    "BulletCollision/CollisionShapes/btCompoundShape.h": (
        "34413f9e250e66ec5f12f9c6e96c16b5f9eb06e842961c08085475b4c1478357"
    ),
    "BulletCollision/CollisionShapes/btConvexHullShape.h": (
        "209211f19fa98cc6a085d95266c4c15ee8a2bf3be5cc29403d858e8f26e97929"
    ),
    "BulletCollision/CollisionShapes/btConvexShape.h": (
        "8d636b8b1ef7ec75926d48b03a4a448a44373ecf362329ce2150586bae4fb0c9"
    ),
    "BulletCollision/CollisionShapes/btCylinderShape.h": (
        "097a80dbf01b8f5add103a0802ffab1201c285e7aaaf2aef8d94c17c193f6167"
    ),
    "BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h": (
        "7ba73189495d70659b257899352f3688585d8bff536db11f8c86cfa6931fe2e4"
    ),
    "BulletCollision/NarrowPhaseCollision/btConvexCast.h": (
        "5eca7f5931c6f954dc4d8b58ff75ec58112c46f96783b1c8de5a117c663a6c6b"
    ),
    "BulletCollision/NarrowPhaseCollision/btGjkConvexCast.h": (
        "3409007ce88c742edba270851d8122fead8c766febf2de193525e0cc2a4694db"
    ),
    "BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h": (
        "bc5e3baf33e296de9367c247b25b9cd8803decee3d57896f87ec161568bedff0"
    ),
    "BulletCollision/NarrowPhaseCollision/btSubSimplexConvexCast.h": (
        "74ffb324a2268abeca5c6757c09b238240be5de12a10f7443652df3f52d1c876"
    ),
    "BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h": (
        "5771fe6eb5b51e91ca83c00c746216b821920b7a147875e01422add194e81805"
    ),
    "LinearMath/btTransformUtil.h": (
        "add9774d16afa59c5cf0529df82133712cad28411e952b9c4cc00ffa8bfa37ee"
    ),
}
BUILD_FLAGS = (
    "-std=c++17",
    "-O2",
    "-fPIC",
    "-shared",
    "-DBT_USE_DOUBLE_PRECISION",
    "-fno-fast-math",
    "-ffp-contract=off",
)
LINK_FLAGS = (
    "-Wl,-rpath,/usr/lib/x86_64-linux-gnu",
    "-Wl,-z,defs",
    "-Wl,-z,now",
    "-Wl,-z,relro",
    "-Wl,--build-id=sha1",
)
EXPECTED_NEEDED = (
    "libBulletCollision-float64.so.3.24",
    "libLinearMath-float64.so.3.24",
    "libc.so.6",
    "libgcc_s.so.1",
    "libm.so.6",
    "libstdc++.so.6",
)
EXPECTED_RUNPATH = "/usr/lib/x86_64-linux-gnu"
LOGICAL_CORE_PATH = "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.cpp"
LOGICAL_ADAPTER_PATH = "src/xh_agent/policy/qrm_lite/a3_bullet_native_adapter_v1.cpp"


class BuildFailure(RuntimeError):
    """The byte closure or query-only native build failed closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BuildFailure(f"build input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise BuildFailure(f"build input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def require_sha256(path: Path, expected: str) -> None:
    if not SHA256_PATTERN.fullmatch(expected) or sha256_file(path) != expected:
        raise BuildFailure(f"build input SHA-256 differs: {path}")


def write_create_only(path: Path, payload: bytes, *, mode: int = 0o444) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise BuildFailure(f"short write while publishing: {path}")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_regular_file(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BuildFailure(f"published artifact is not regular: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            close_fds=True,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "1786540800"),
                "TZ": "UTC",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildFailure(f"build command failed: {argv[0]}") from exc


def _parse_dependencies(depfile: str, *, cwd: Path) -> tuple[Path, ...]:
    flattened = depfile.replace("\\\n", " ")
    if ":" not in flattened:
        raise BuildFailure("compiler dependency output is malformed")
    _, raw_dependencies = flattened.split(":", 1)
    paths = []
    for item in raw_dependencies.split():
        path = Path(item)
        if not path.is_absolute():
            path = cwd / path
        paths.append(path.resolve(strict=True))
    unique = tuple(sorted(set(paths), key=lambda value: str(value)))
    if not unique:
        raise BuildFailure("compiler dependency closure is empty")
    return unique


def _compiler_dependencies(
    compiler: Path, include_root: Path, sources: tuple[Path, ...]
) -> tuple[tuple[list[str], ...], tuple[Path, ...]]:
    commands: list[list[str]] = []
    dependencies: set[Path] = set()
    for source in sources:
        command = [
            str(compiler),
            "-std=c++17",
            "-DBT_USE_DOUBLE_PRECISION",
            f"-I{include_root}",
            "-M",
            str(source),
        ]
        commands.append(command)
        dependencies.update(_parse_dependencies(_run(command).stdout, cwd=source.parent))
    return tuple(commands), tuple(sorted(dependencies, key=lambda value: str(value)))


def _file_bindings(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in paths
    ]


def _dynamic_contract(shared_object: Path) -> tuple[tuple[str, ...], str]:
    output = _run(["/usr/bin/readelf", "-d", str(shared_object)]).stdout
    needed = tuple(sorted(re.findall(r"Shared library: \[([^]]+)\]", output)))
    runpaths = re.findall(r"Library runpath: \[([^]]+)\]", output)
    rpaths = re.findall(r"Library rpath: \[([^]]+)\]", output)
    if needed != EXPECTED_NEEDED or runpaths != [EXPECTED_RUNPATH] or rpaths:
        raise BuildFailure("native dynamic dependency or RUNPATH closure differs")
    return needed, runpaths[0]


def build(args: argparse.Namespace) -> dict[str, Any]:
    if not BASE_IMAGE_PATTERN.fullmatch(args.build_container_digest):
        raise BuildFailure("build container is not an immutable sha256 ID")
    source_root = args.source_root.resolve(strict=True)
    include_root = args.bullet_include_root.resolve(strict=True)
    library_root = args.bullet_library_root.resolve(strict=True)
    compiler = args.compiler.resolve(strict=True)
    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise BuildFailure("output root is not empty/create-only")

    core = source_root / CORE_NAME
    adapter = source_root / ADAPTER_NAME
    collision_library = library_root / COLLISION_LIBRARY_NAME
    linear_math_library = library_root / LINEAR_MATH_LIBRARY_NAME
    require_sha256(core, CORE_SHA256)
    require_sha256(adapter, ADAPTER_SHA256)
    require_sha256(collision_library, COLLISION_LIBRARY_SHA256)
    require_sha256(linear_math_library, LINEAR_MATH_LIBRARY_SHA256)
    for relative, digest in EXPECTED_HEADERS.items():
        require_sha256(include_root / relative, digest)

    compiler_version = _run([str(compiler), "--version"]).stdout.splitlines()[0]
    compiler_include_raw = _run([str(compiler), "-print-file-name=include"]).stdout.strip()
    if not compiler_include_raw:
        raise BuildFailure("compiler builtin include root is absent")
    compiler_include_root = Path(compiler_include_raw).resolve(strict=True)
    dependency_commands, dependencies = _compiler_dependencies(
        compiler, include_root, (core, adapter)
    )
    dependency_set = set(dependencies)
    if not {core.resolve(), adapter.resolve()}.issubset(dependency_set):
        raise BuildFailure("compiler dependency closure omits a governed source")
    if any(
        path != core.resolve()
        and path != adapter.resolve()
        and include_root not in path.parents
        and Path("/usr/include") not in path.parents
        and compiler_include_root not in path.parents
        for path in dependency_set
    ):
        raise BuildFailure("compiler dependency closure escapes the frozen header roots")

    output_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    shared_object = output_root / "libm2c_a3_bullet_float64.so"
    compile_command = [
        str(compiler),
        *BUILD_FLAGS,
        f"-I{include_root}",
        str(core),
        str(adapter),
        str(collision_library),
        str(linear_math_library),
        *LINK_FLAGS,
        "-o",
        str(shared_object),
    ]
    _run(compile_command)
    os.chmod(shared_object, 0o555)
    needed, runpath = _dynamic_contract(shared_object)

    input_data = {
        "schema_version": INPUTS_SCHEMA_VERSION,
        "build_container_digest": args.build_container_digest,
        "compiler": {
            "path": str(compiler),
            "sha256": sha256_file(compiler),
            "version": compiler_version,
            "builtin_include_root": str(compiler_include_root),
        },
        "dependencies": _file_bindings(dependencies),
        "explicit_libraries": _file_bindings((collision_library, linear_math_library)),
        "dependency_commands": dependency_commands,
        "compile_command": compile_command,
        "build_flags": list(BUILD_FLAGS),
        "link_flags": list(LINK_FLAGS),
    }
    inputs_path = output_root / "compiler-inputs.json"
    inputs_payload = canonical_json_bytes(input_data) + b"\n"
    write_create_only(inputs_path, inputs_payload)

    build_manifest_core = {
        "schema_version": "A3BulletFloat64BuildManifestV1",
        "bullet_package_version": "3.24+dfsg-2.1build1",
        "scalar_abi": "float64",
        "compiler": {"path": str(compiler), "sha256": sha256_file(compiler)},
        "compiler_version": compiler_version,
        "build_flags": list(BUILD_FLAGS),
        "native_core": {"path": LOGICAL_CORE_PATH, "sha256": CORE_SHA256},
        "native_adapter": {"path": LOGICAL_ADAPTER_PATH, "sha256": ADAPTER_SHA256},
        "audited_bullet_headers": [
            {"path": str(include_root / path), "sha256": digest}
            for path, digest in EXPECTED_HEADERS.items()
        ],
        "complete_transitive_compile_manifest": {
            "path": str(inputs_path),
            "sha256": hashlib.sha256(inputs_payload).hexdigest(),
        },
        "bullet_collision_library": {
            "path": str(collision_library),
            "sha256": COLLISION_LIBRARY_SHA256,
        },
        "bullet_linear_math_library": {
            "path": str(linear_math_library),
            "sha256": LINEAR_MATH_LIBRARY_SHA256,
        },
        "native_shared_object": {
            "path": str(shared_object),
            "sha256": sha256_file(shared_object),
        },
        "immutable_build_container_digest": args.build_container_digest,
        "absolute_float64_rpath_only": True,
        "no_fast_math": True,
    }
    build_manifest = {
        **build_manifest_core,
        "build_manifest_sha256": canonical_sha256(build_manifest_core),
    }
    build_manifest_path = output_root / "a3-bullet-build-manifest.json"
    build_manifest_payload = canonical_json_bytes(build_manifest) + b"\n"
    write_create_only(build_manifest_path, build_manifest_payload)

    receipt_core = {
        "schema_version": SCHEMA_VERSION,
        "status": "BUILT_QUERY_ONLY",
        "build_container_digest": args.build_container_digest,
        "source_bindings": {
            CORE_NAME: CORE_SHA256,
            ADAPTER_NAME: ADAPTER_SHA256,
        },
        "audited_header_bindings": dict(sorted(EXPECTED_HEADERS.items())),
        "bullet_package_version": "3.24+dfsg-2.1build1",
        "bullet_collision_library_sha256": COLLISION_LIBRARY_SHA256,
        "bullet_linear_math_library_sha256": LINEAR_MATH_LIBRARY_SHA256,
        "compiler_path": str(compiler),
        "compiler_sha256": sha256_file(compiler),
        "compiler_version": compiler_version,
        "build_flags": list(BUILD_FLAGS),
        "link_flags": list(LINK_FLAGS),
        "compiler_inputs_sha256": hashlib.sha256(inputs_payload).hexdigest(),
        "adapter_build_manifest_sha256": hashlib.sha256(build_manifest_payload).hexdigest(),
        "native_shared_object_sha256": sha256_file(shared_object),
        "native_shared_object_size_bytes": shared_object.stat().st_size,
        "dynamic_needed": list(needed),
        "dynamic_runpath": runpath,
        "query_only": True,
        "isaac_started": False,
        "physical_execution_performed": False,
        "training_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_execution_eligible": False,
    }
    receipt = {**receipt_core, "receipt_sha256": canonical_sha256(receipt_core)}
    receipt_path = output_root / "native-build-receipt.json"
    write_create_only(receipt_path, canonical_json_bytes(receipt) + b"\n")
    fsync_regular_file(shared_object)
    fsync_directory(output_root)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bullet-include-root", type=Path, required=True)
    parser.add_argument("--bullet-library-root", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--build-container-digest", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        receipt = build(parse_args())
    except BuildFailure as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
