#!/usr/bin/env python3
"""Run the Node 2-authorized S5 smoke32 or two-epoch LoRA job."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import gc
import hashlib
import inspect
import json
import os
import random
import signal
import socket
import sys
import time
import traceback
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xh_agent.qwen_brain.client_v1 import COMMANDER_SYSTEM_PROMPT_V1
from xh_agent.qwen_brain.s5_data_v1 import canonical_json, sha256_file
from xh_agent.qwen_brain.s5_lora_v1 import (
    assert_exact_trainable_parameter_set,
    build_prompt_first_example,
    exact_target_paths,
    inventory_lora_targets,
    select_loss_positions,
    selected_logits_cross_entropy,
)
from xh_agent.qwen_brain.s5_training_node2_v1 import (
    S5SmokeSampleMetricV1,
    accumulation_groups,
    extract_direct_authorization,
    load_authorized_config,
    load_reconstructed_rows,
    select_smoke32,
)

GIB = 1024**3
_SMOKE_PROMOTION_GATE_NAMES = {
    "exact_microstep_update_counts",
    "adapter_changed",
    "frozen_base_unchanged",
    "allocated_memory",
    "reserved_memory",
    "optimized_fla_gdn",
    "fixed_probe_loss_decreased",
    "pre_repeated_forward_bit_exact",
    "post_repeated_forward_bit_exact",
    "adapter_on_off_delta_nonzero",
    "adapter_tensor_round_trip",
    "fresh_reload_bit_exact",
}
_RUNTIME_DISTRIBUTIONS = {
    "torch": "2.13.0",
    "transformers": "5.16.1",
    "peft": "0.20.0",
    "accelerate": "1.14.0",
    "kernels": "0.16.1",
    "safetensors": "0.8.0",
    "torchvision": "0.28.0",
    "flash-linear-attention": "0.5.2",
    "fla-core": "0.5.2",
    "einops": "0.8.2",
}


class S5TrainingDeadline(RuntimeError):
    pass


class S5PreparedPublicationInterruption(RuntimeError):
    pass


def _deadline_handler(signum: int, frame: object) -> None:
    del signum, frame
    raise S5TrainingDeadline("authorized training wall-clock deadline reached")


def _write_create_only(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    parent = path.parent
    if parent.exists() or parent.is_symlink():
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError("evidence parent must be a regular directory")
    else:
        parent.mkdir(parents=True, mode=0o755)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _tree_manifest(path: Path) -> list[dict[str, object]]:
    entries = []
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink() or (not candidate.is_file() and not candidate.is_dir()):
            raise ValueError("adapter tree contains a symlink or unsupported entry")
        if candidate.is_file():
            entries.append(
                {
                    "path": candidate.relative_to(path).as_posix(),
                    "size": candidate.stat().st_size,
                    "sha256": sha256_file(candidate),
                }
            )
    return entries


def _tree_sha256(path: Path) -> str:
    return hashlib.sha256(canonical_json(_tree_manifest(path)).encode()).hexdigest()


def _validate_runtime_identity(config: Any) -> dict[str, object]:
    observed = {
        distribution: metadata.version(distribution)
        for distribution in sorted(_RUNTIME_DISTRIBUTIONS)
    }
    if observed != dict(sorted(_RUNTIME_DISTRIBUTIONS.items())):
        raise ValueError("training environment distribution versions mismatch")
    if socket.gethostname().split(".")[0] != config.execution.host:
        raise ValueError("authorized training host mismatch")
    if Path(sys.prefix).resolve() != Path(config.execution.training_venv_path).resolve():
        raise ValueError("authorized training virtual environment mismatch")
    environment_report = Path(config.execution.environment_identity_report_path)
    if not environment_report.is_file() or environment_report.is_symlink():
        raise ValueError("frozen environment identity report is absent")
    if sha256_file(environment_report) != config.execution.environment_identity_sha256:
        raise ValueError("frozen environment identity digest mismatch")
    return {
        "hostname": socket.gethostname(),
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "distributions": observed,
        "environment_report": str(environment_report),
        "environment_report_sha256": sha256_file(environment_report),
    }


def _snapshot_tree_identity(path: Path) -> tuple[str, list[str]]:
    entries = []
    ignored_top_level_dirs = []
    for candidate in sorted(path.iterdir(), key=lambda item: item.name):
        if candidate.is_symlink():
            raise ValueError("snapshot top-level entries must not be symlinks")
        if candidate.is_dir():
            ignored_top_level_dirs.append(candidate.name)
            continue
        if not candidate.is_file():
            raise ValueError("snapshot contains a non-regular top-level entry")
        entries.append(
            {
                "name": candidate.name,
                "size": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
        )
    if len(entries) != 32:
        raise ValueError("snapshot must contain exactly 32 regular top-level files")
    return (
        hashlib.sha256(canonical_json(entries).encode()).hexdigest(),
        ignored_top_level_dirs,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_no_replace(source: Path, destination: Path) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("authorized publication requires Linux renameat2")
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = library.renameat2
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def _tensor_sha256(value: Any) -> str:
    tensor = value.detach().float().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(tuple(tensor.shape)).encode())
    digest.update(str(tensor.dtype).encode())
    digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _adapter_tensor_sha256(model: Any) -> str:
    digest = hashlib.sha256()
    for name, parameter in sorted(model.named_parameters(), key=lambda item: item[0]):
        if "lora_" not in name:
            continue
        value = parameter.detach().float().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _frozen_sample_sha256(model: Any) -> str:
    digest = hashlib.sha256()
    count = 0
    for name, parameter in sorted(model.named_parameters(), key=lambda item: item[0]):
        if parameter.requires_grad:
            continue
        value = parameter.detach().reshape(-1)
        if value.numel() == 0:
            continue
        sample = value[: min(1024, value.numel())].float().cpu().contiguous()
        digest.update(name.encode())
        digest.update(sample.numpy().tobytes())
        count += 1
        if count == 16:
            break
    if count != 16:
        raise ValueError("could not construct frozen parameter checksum sample")
    return digest.hexdigest()


def _memory(torch: Any) -> dict[str, int]:
    free, total = torch.cuda.mem_get_info()
    return {
        "free_bytes": int(free),
        "total_bytes": int(total),
        "allocated_bytes": int(torch.cuda.memory_allocated()),
        "reserved_bytes": int(torch.cuda.memory_reserved()),
        "max_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "max_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }


def _gdn_identity() -> dict[str, dict[str, object]]:
    import transformers.models.qwen3_5.modeling_qwen3_5 as modeling

    result = {}
    for name in (
        "torch_chunk_gated_delta_rule",
        "torch_recurrent_gated_delta_rule",
    ):
        outer = getattr(modeling, name)
        wrapper = inspect.getclosurevars(type(outer).forward).nonlocals["func"]
        closure = inspect.getclosurevars(wrapper).nonlocals
        implementation = closure["implementation"]
        result[name] = {
            "implementation_module": implementation.__module__,
            "implementation_qualname": implementation.__qualname__,
            "implementation_is_torch_function": (implementation is closure["torch_function"]),
            "is_new_implementation": closure["is_new_implementation"],
        }
    return result


def _is_fla_gdn(identity: dict[str, dict[str, object]]) -> bool:
    return all(
        str(item["implementation_module"]).startswith("fla.")
        and item["implementation_is_torch_function"] is False
        and item["is_new_implementation"] is True
        for item in identity.values()
    )


def _public_prompt_context(row: Any) -> dict[str, object]:
    context = row.context.model_dump(mode="json")
    if row.family.value == "VISUAL_CONDITION_SELECTION":
        context.pop("target_ref", None)
        context.pop("approach_pose_ref", None)
    return context


def _validate_training_images(config: Any, rows: list[Any]) -> tuple[Path, dict[str, object]]:
    image_root = Path(config.data.image_materialization_root)
    manifest_path = Path(config.data.image_materialization_manifest_path)
    if not image_root.is_dir() or image_root.is_symlink():
        raise ValueError("frozen TRAIN image root must be a regular directory")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("frozen TRAIN image manifest must be regular and non-symlink")
    if sha256_file(manifest_path) != config.data.image_materialization_manifest_sha256:
        raise ValueError("frozen TRAIN image manifest digest mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != config.data.image_materialization_schema:
        raise ValueError("TRAIN image manifest schema mismatch")
    expected_hashes = {row.image_sha256 for row in rows}
    expected_names = {f"{value}.png" for value in expected_hashes}
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise TypeError("TRAIN image manifest entries are absent")
    expected_entries = [
        {
            "image_sha256": value,
            "relative_path": f"images/{value}.png",
            "size_bytes": (image_root / f"{value}.png").stat().st_size,
        }
        for value in sorted(expected_hashes)
    ]
    actual_names = {path.name for path in image_root.iterdir()}
    if (
        entries != expected_entries
        or actual_names != expected_names
        or manifest.get("status") != "PASS"
        or manifest.get("experiment_identity")
        != config.data.image_materialization_experiment_identity
        or manifest.get("train_row_count") != config.data.train_rows
        or manifest.get("train_source_count") != config.data.train_sources
        or manifest.get("unique_image_count") != config.data.unique_train_image_count
        or manifest.get("total_image_bytes") != config.data.total_train_image_bytes
        or manifest.get("image_set_sha256") != config.data.image_set_sha256
        or manifest.get("train_sha256") != config.data.train_sha256
        or manifest.get("evaluation_images_materialized") is not False
        or manifest.get("monolithic_dataset_read") is not False
        or _canonical_sha256(entries) != config.data.image_set_sha256
    ):
        raise ValueError("TRAIN image materialization identity or exact set mismatch")
    for path in image_root.iterdir():
        if not path.is_file() or path.is_symlink():
            raise ValueError("TRAIN image root contains a non-regular entry")
        if sha256_file(path) != path.stem:
            raise ValueError("content-addressed TRAIN image does not match its filename")
    return image_root, manifest


def _prepare_example(
    processor: Any,
    tokenizer: Any,
    row: Any,
    *,
    image_root: Path,
    max_post_expansion_length: int,
) -> tuple[dict[str, Any], Any]:
    import torch
    from PIL import Image

    image_path = image_root / f"{row.image_sha256}.png"
    if not image_path.is_file() or image_path.is_symlink():
        raise ValueError("content-addressed TRAIN image must be regular and non-symlink")
    if sha256_file(image_path) != row.image_sha256:
        raise ValueError("training image digest mismatch")
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    user_text = (
        row.instruction
        + "\n已知上下文(JSON): "
        + json.dumps(_public_prompt_context(row), ensure_ascii=False, sort_keys=True)
    )
    messages = [
        {"role": "system", "content": COMMANDER_SYSTEM_PROMPT_V1},
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": user_text},
            ],
        },
    ]
    processor_output = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        enable_thinking=False,
    )
    target_ids = tokenizer.encode(row.target_json, add_special_tokens=False)
    example = build_prompt_first_example(
        processor_output,
        target_token_ids=target_ids,
        im_end_token_id=tokenizer.convert_tokens_to_ids("<|im_end|>"),
        pad_token_id=tokenizer.pad_token_id,
        max_post_expansion_length=max_post_expansion_length,
    )
    sequence_keys = {
        "input_ids": torch.tensor([example.input_ids], dtype=torch.long),
        "attention_mask": torch.tensor([example.attention_mask], dtype=torch.long),
        "mm_token_type_ids": torch.tensor([example.mm_token_type_ids], dtype=torch.long),
    }
    labels = torch.tensor([example.labels], dtype=torch.long)
    processor_output.update(sequence_keys)
    result = dict(processor_output)
    if any(
        key in result for key in ("labels", "offset_mapping", "assistant_masks", "assistant_mask")
    ):
        raise ValueError("processor output contains a forbidden production loss field")
    if result["input_ids"].shape != labels.shape:
        raise ValueError("prompt-first sequence and labels must have identical shape")
    return result, labels


def _save_adapter_staging_create_only(
    model: Any, destination: Path
) -> tuple[Path, list[dict[str, object]]]:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("adapter output parent must be an existing regular directory")
    staging = destination.with_name(f".{destination.name}.staging-noncandidate-{os.getpid()}")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(staging)
    try:
        model.save_pretrained(staging, safe_serialization=True)
        for path in staging.rglob("*"):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError("adapter staging contains an unsupported entry")
            if path.is_file():
                path.chmod(0o444)
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        for path in sorted(
            (candidate for candidate in staging.rglob("*") if candidate.is_dir()),
            key=lambda candidate: len(candidate.parts),
            reverse=True,
        ):
            _fsync_directory(path)
            path.chmod(0o555)
        _fsync_directory(staging)
        staging.chmod(0o555)
        return staging, _tree_manifest(staging)
    except BaseException as exc:
        _mark_failed_adapter_staging(staging, exc)
        raise


def _mark_failed_adapter_staging(staging: Path, error: BaseException) -> None:
    if not staging.is_dir() or staging.is_symlink():
        return
    marker = staging / "FAILED.json"
    with contextlib.suppress(OSError):
        staging.chmod(0o755)
    if not marker.exists() and not marker.is_symlink():
        with contextlib.suppress(OSError):
            _write_create_only(
                marker,
                (
                    json.dumps(
                        {
                            "schema_version": "QwenBrainS5FailedAdapterStagingV1",
                            "status": "FAILED_NONCANDIDATE",
                            "error_type": type(error).__name__,
                            "error": str(error),
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode(),
            )
    with contextlib.suppress(OSError):
        _fsync_directory(staging)
        staging.chmod(0o555)


def _publish_adapter_staging(
    staging: Path,
    destination: Path,
    expected_manifest: list[dict[str, object]],
) -> str:
    if _tree_manifest(staging) != expected_manifest:
        raise ValueError("adapter staging tree changed before publication")
    _rename_no_replace(staging, destination)
    _fsync_directory(destination.parent)
    if _tree_manifest(destination) != expected_manifest:
        raise ValueError("published adapter tree does not match staged manifest")
    return hashlib.sha256(canonical_json(expected_manifest).encode()).hexdigest()


def _receipt_paths(report_output: Path) -> tuple[Path, Path]:
    return (
        report_output.with_name(f"{report_output.name}.prepared.json"),
        report_output.with_name(f"{report_output.name}.publication.json"),
    )


def _json_payload(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _load_regular_json(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"receipt must be a regular non-symlink file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("receipt payload must be a JSON object")
    return payload


def _reconcile_interrupted_publication(arguments: argparse.Namespace) -> int | None:
    prepared_path, publication_path = _receipt_paths(arguments.report_output)
    if not prepared_path.exists() and not prepared_path.is_symlink():
        if publication_path.exists() or publication_path.is_symlink():
            raise ValueError("publication receipt exists without PREPARED receipt")
        return None
    if arguments.report_output.exists() or arguments.report_output.is_symlink():
        raise FileExistsError("training report identity is already consumed")
    prepared = _load_regular_json(prepared_path)
    if (
        prepared.get("schema_version") != "QwenBrainS5AdapterPreparedReceiptV1"
        or prepared.get("status") != "PREPARED"
        or prepared.get("adapter_destination") != str(arguments.adapter_output)
    ):
        raise ValueError("PREPARED receipt identity mismatch")
    manifest = prepared.get("staging_manifest")
    report = prepared.get("prepared_report")
    if not isinstance(manifest, list) or not isinstance(report, dict):
        raise TypeError("PREPARED receipt is missing manifest or prepared report")
    if (
        report.get("mode") != arguments.mode
        or report.get("config_sha256") != sha256_file(arguments.config)
        or report.get("authorization_sha256") != sha256_file(arguments.authorization)
        or report.get("train_sha256") != sha256_file(arguments.train)
    ):
        raise ValueError("reconciliation invocation identities do not match PREPARED receipt")
    if arguments.mode == "two-epoch" and (
        arguments.smoke_pass_report is None
        or report.get("promoted_from_smoke_report_sha256")
        != sha256_file(arguments.smoke_pass_report)
    ):
        raise ValueError("reconciliation smoke identity does not match PREPARED receipt")
    if not arguments.adapter_output.is_dir() or arguments.adapter_output.is_symlink():
        raise ValueError(
            "PREPARED receipt exists without a published adapter; staging must remain frozen"
        )
    observed_manifest = _tree_manifest(arguments.adapter_output)
    if observed_manifest != manifest:
        raise ValueError("published adapter does not match PREPARED manifest during reconciliation")
    tree_sha256 = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    if tree_sha256 != prepared.get("adapter_tree_sha256"):
        raise ValueError("PREPARED adapter tree identity mismatch during reconciliation")
    if publication_path.exists() or publication_path.is_symlink():
        publication = _load_regular_json(publication_path)
        if (
            publication.get("schema_version") != "QwenBrainS5AdapterPublicationReceiptV1"
            or publication.get("prepared_receipt_sha256") != sha256_file(prepared_path)
            or publication.get("adapter_destination") != str(arguments.adapter_output)
            or publication.get("adapter_tree_sha256") != tree_sha256
            or publication.get("published_manifest") != observed_manifest
        ):
            raise ValueError("existing publication receipt does not match PREPARED manifest")
        publication_payload = publication_path.read_bytes()
    else:
        publication = {
            "schema_version": "QwenBrainS5AdapterPublicationReceiptV1",
            "status": "RECONCILED_PUBLISHED",
            "publication_primitive": "LINUX_RENAMEAT2_RENAME_NOREPLACE",
            "reconciled_after_interruption": True,
            "prepared_receipt": str(prepared_path),
            "prepared_receipt_sha256": sha256_file(prepared_path),
            "adapter_destination": str(arguments.adapter_output),
            "adapter_tree_sha256": tree_sha256,
            "published_manifest": observed_manifest,
        }
        publication_payload = _json_payload(publication)
        _write_create_only(publication_path, publication_payload)
    report.update(
        {
            "status": "PASS",
            "promotion_pass": True,
            "prepared_receipt": str(prepared_path),
            "prepared_receipt_sha256": sha256_file(prepared_path),
            "publication_receipt": str(publication_path),
            "publication_receipt_sha256": hashlib.sha256(publication_payload).hexdigest(),
            "publication_reconciled_after_interruption": True,
            "released_memory_measurement": "RECONCILIATION_PROCESS_DID_NOT_LOAD_CUDA_RUNTIME",
            "released_memory": None,
            "no_candidate_service_started": True,
            "no_canonical_evaluation_executed": True,
        }
    )
    _write_create_only(arguments.report_output, _json_payload(report))
    return 0


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke32", "two-epoch"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--smoke-pass-report", type=Path)
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _validate_smoke_promotion(
    path: Path | None,
    *,
    config_sha256: str,
    authorization_sha256: str,
    train_sha256: str,
) -> dict[str, object]:
    if path is None:
        raise ValueError("two-epoch mode requires --smoke-pass-report")
    if not path.is_file() or path.is_symlink():
        raise ValueError("smoke report must be a regular non-symlink file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "QwenBrainS5TrainingRunReportV1":
        raise ValueError("smoke report schema mismatch")
    if payload.get("mode") != "smoke32" or payload.get("status") != "PASS":
        raise ValueError("two-epoch training requires a passing smoke32 report")
    if payload.get("promotion_pass") is not True:
        raise ValueError("smoke32 did not pass every promotion gate")
    if (
        payload.get("config_sha256") != config_sha256
        or payload.get("authorization_sha256") != authorization_sha256
        or payload.get("train_sha256") != train_sha256
    ):
        raise ValueError("smoke report identities do not match the two-epoch run")
    required_gates = payload.get("promotion_gates")
    if (
        not isinstance(required_gates, dict)
        or set(required_gates) != _SMOKE_PROMOTION_GATE_NAMES
        or not all(value is True for value in required_gates.values())
    ):
        raise ValueError("smoke report does not contain an all-true promotion gate set")
    return payload


def _model_inputs(encoded: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in encoded.items()
        if key
        in {
            "input_ids",
            "attention_mask",
            "pixel_values",
            "image_grid_thw",
            "mm_token_type_ids",
        }
    }


def _selected_probe_observation(
    torch: Any,
    model: Any,
    encoded: dict[str, Any],
    labels: Any,
) -> dict[str, object]:
    selection = select_loss_positions(encoded["input_ids"][0].tolist(), labels[0].tolist())
    predictors = torch.tensor(
        selection.predictor_positions,
        dtype=torch.long,
        device=encoded["input_ids"].device,
    )
    targets = torch.tensor(
        selection.targets,
        dtype=torch.long,
        device=encoded["input_ids"].device,
    )
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        output = model(
            **_model_inputs(encoded),
            labels=None,
            logits_to_keep=predictors,
            use_cache=False,
            return_dict=True,
        )
        logits = output.logits[0]
        loss = selected_logits_cross_entropy(logits, targets)
    if logits.dtype != torch.bfloat16:
        raise ValueError("fixed-probe selected logits storage dtype must be BF16")
    vocabulary_size = int(model.config.text_config.vocab_size)
    if logits.ndim != 2 or list(logits.shape) != [len(selection.targets), vocabulary_size]:
        raise ValueError("fixed-probe selected logits shape mismatch")
    fp32_logits = logits.detach().float().cpu().contiguous()
    return {
        "loss": float(loss.detach()),
        "logits": fp32_logits,
        "logits_sha256": _tensor_sha256(fp32_logits),
        "shape": list(logits.shape),
        "storage_dtype": str(logits.dtype),
        "comparison_dtype": str(fp32_logits.dtype),
        "target_count": len(selection.targets),
    }


def _set_adapter_enabled(model: Any, *, enabled: bool) -> None:
    adapter_model = model.base_model
    if enabled:
        adapter_model.enable_adapter_layers()
    else:
        adapter_model.disable_adapter_layers()


def _probe_report(observation: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in observation.items() if key != "logits"}


def _run(arguments: argparse.Namespace) -> int:
    reconciled = _reconcile_interrupted_publication(arguments)
    if reconciled is not None:
        return reconciled
    config = load_authorized_config(arguments.config)
    authorization = extract_direct_authorization(arguments.authorization)
    if (
        authorization.base_authorization.rank != config.lora.rank
        or authorization.base_authorization.alpha != config.lora.alpha
        or authorization.base_authorization.learning_rate != config.optimizer.learning_rate
        or authorization.effective_host != config.execution.host
        or authorization.host_amendment.effective_host != config.execution.host
    ):
        raise ValueError("direct authorization and frozen training config disagree")
    if (
        config.execution.publication_primitive != "LINUX_RENAMEAT2_RENAME_NOREPLACE"
        or config.execution.publication_evidence
        != "PREPARED_THEN_PUBLISH_THEN_PUBLICATION_RECEIPT_THEN_FINAL_REPORT"
        or config.execution.interrupted_publication_reconciliation
        != "PREPARED_MANIFEST_EXACT_MATCH_ONLY_NO_REPUBLISH_NO_DELETE"
    ):
        raise ValueError("authorized publication protocol mismatch")
    rows = load_reconstructed_rows(arguments.train, expected_sha256=config.data.train_sha256)
    mode: Literal["smoke32", "two-epoch"] = arguments.mode
    smoke_promotion: dict[str, object] | None = None
    if mode == "smoke32":
        selected_rows = None
        fixed_probe_sample_id = None
        fixed_probe_selection = config.gates.smoke_fixed_probe_selection
        expected_microsteps = config.gates.smoke_microsteps
        expected_updates = config.gates.smoke_optimizer_updates
    else:
        smoke_promotion = _validate_smoke_promotion(
            arguments.smoke_pass_report,
            config_sha256=sha256_file(arguments.config),
            authorization_sha256=sha256_file(arguments.authorization),
            train_sha256=sha256_file(arguments.train),
        )
        fixed_probe = smoke_promotion.get("fixed_probe")
        if not isinstance(fixed_probe, dict) or not isinstance(fixed_probe.get("sample_id"), str):
            raise ValueError("promoted smoke report fixed-probe identity is absent")
        fixed_probe_sample_id = fixed_probe["sample_id"]
        if fixed_probe_sample_id not in {row.sample_id for row in rows}:
            raise ValueError("promoted smoke fixed probe is not in reconstructed TRAIN")
        fixed_probe_selection = config.gates.two_epoch_fixed_probe_selection
        selected_rows = [row for _ in range(config.execution.epochs) for row in rows]
        expected_microsteps = config.gates.two_epoch_microsteps
        expected_updates = config.gates.two_epoch_optimizer_updates
    groups = accumulation_groups(
        microsteps=expected_microsteps,
        gradient_accumulation=config.execution.gradient_accumulation,
        base_learning_rate=config.optimizer.learning_rate,
        warmup_optimizer_updates=config.optimizer.warmup_optimizer_updates,
    )
    if (selected_rows is not None and len(selected_rows) != expected_microsteps) or len(
        groups
    ) != expected_updates:
        raise ValueError("frozen execution arithmetic mismatch")
    if arguments.dry_run:
        smoke = select_smoke32(rows)
        print(
            json.dumps(
                {
                    "schema_version": "QwenBrainS5TrainerDryRunV1",
                    "mode": mode,
                    "status": "PASS",
                    "optimizer_constructed": False,
                    "optimizer_step_executed": False,
                    "microsteps": expected_microsteps,
                    "optimizer_updates": expected_updates,
                    "final_group_size": groups[-1].sample_count,
                    "smoke_sample_ids": smoke.sample_ids,
                    "fixed_probe_sample_id": (
                        min(smoke.sample_ids) if mode == "smoke32" else fixed_probe_sample_id
                    ),
                    "fixed_probe_selection": fixed_probe_selection,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    runtime_identity = _validate_runtime_identity(config)
    import torch
    from peft import LoraConfig, PeftModel, TaskType, get_peft_model
    from peft.tuners.lora import LoraLayer
    from transformers import AutoProcessor, AutoTokenizer, Qwen3_5ForConditionalGeneration

    random.seed(config.execution.seed)
    torch.manual_seed(config.execution.seed)
    torch.cuda.manual_seed_all(config.execution.seed)
    torch.use_deterministic_algorithms(config.execution.deterministic_algorithms)
    torch.backends.cudnn.benchmark = config.execution.cudnn_benchmark
    torch.set_float32_matmul_precision(config.execution.matmul_precision)
    snapshot = Path(config.execution.snapshot_path)
    if not snapshot.is_dir() or snapshot.is_symlink():
        raise ValueError("snapshot must be a local regular directory")
    snapshot_tree_before, ignored_top_level_dirs_before = _snapshot_tree_identity(snapshot)
    if snapshot_tree_before != config.execution.snapshot_tree_sha256:
        raise ValueError("frozen snapshot tree digest mismatch")
    processor_file_identities = {
        "tokenizer_config.json": config.execution.tokenizer_config_sha256,
        "tokenizer.json": config.execution.tokenizer_json_sha256,
        "chat_template.jinja": config.execution.chat_template_sha256,
        "preprocessor_config.json": config.execution.preprocessor_config_sha256,
    }
    for name, expected_sha256 in processor_file_identities.items():
        path = snapshot / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_sha256:
            raise ValueError(f"frozen processor/tokenizer identity mismatch: {name}")
    report: dict[str, Any] = {
        "schema_version": "QwenBrainS5TrainingRunReportV1",
        "mode": mode,
        "status": "FAIL",
        "promotion_pass": False,
        "config_sha256": sha256_file(arguments.config),
        "authorization_sha256": sha256_file(arguments.authorization),
        "train_sha256": sha256_file(arguments.train),
        "seed": config.execution.seed,
        "rank": config.lora.rank,
        "alpha": config.lora.alpha,
        "learning_rate": config.optimizer.learning_rate,
        "expected_microsteps": expected_microsteps,
        "expected_optimizer_updates": expected_updates,
        "snapshot_tree_sha256_before": snapshot_tree_before,
        "ignored_top_level_dirs_before": ignored_top_level_dirs_before,
        "runtime_identity": runtime_identity,
        "promoted_from_smoke_report_sha256": (
            sha256_file(arguments.smoke_pass_report)
            if smoke_promotion is not None and arguments.smoke_pass_report is not None
            else None
        ),
        "matmul_precision": torch.get_float32_matmul_precision(),
        "processor_file_identities": processor_file_identities,
        "events": [],
    }
    model: Any = None
    optimizer: Any = None
    prepared_receipt_written = False
    publication_receipt_written = False
    started = time.monotonic()
    signal.signal(signal.SIGALRM, _deadline_handler)
    signal.alarm(2 * 3600 if mode == "smoke32" else 12 * 3600)
    try:
        if (
            arguments.report_output.exists()
            or arguments.report_output.is_symlink()
            or arguments.adapter_output.exists()
            or arguments.adapter_output.is_symlink()
        ):
            raise FileExistsError("report or adapter output already exists")
        if (
            not arguments.report_output.parent.is_dir()
            or arguments.report_output.parent.is_symlink()
            or not arguments.adapter_output.parent.is_dir()
            or arguments.adapter_output.parent.is_symlink()
        ):
            raise ValueError("report and adapter parents must be regular directories")
        initial_memory = _memory(torch)
        report["initial_memory"] = initial_memory
        if torch.cuda.device_count() != 1:
            raise ValueError("authorized host must expose exactly one CUDA device")
        if config.execution.cuda_device_index != 0:
            raise ValueError("authorized CUDA device index must remain zero")
        if torch.cuda.get_device_name(0) != config.execution.accelerator:
            raise ValueError("authorized accelerator identity mismatch")
        processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        if tokenizer.convert_tokens_to_ids(config.loss.target_terminator) != (
            config.loss.expected_target_terminator_id
        ):
            raise ValueError("frozen target terminator token ID mismatch")
        if tokenizer.pad_token_id != config.loss.expected_pad_token_id:
            raise ValueError("frozen padding token ID mismatch")
        model = Qwen3_5ForConditionalGeneration.from_pretrained(
            snapshot,
            local_files_only=True,
            dtype=torch.bfloat16,
            device_map={"": 0},
            low_cpu_mem_usage=True,
            use_kernels=False,
        )
        model.config.use_cache = False
        inventory = inventory_lora_targets(
            model,
            layer_types=list(model.config.text_config.layer_types),
            snapshot_tree_sha256=config.execution.snapshot_tree_sha256,
            config_sha256=sha256_file(snapshot / "config.json"),
            expected_target_count=config.lora.expected_target_count,
        )
        target_paths = exact_target_paths(inventory)
        if _canonical_sha256(target_paths) != config.gates.expected_target_path_sha256:
            raise ValueError("exact LoRA target path digest mismatch")
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        model = get_peft_model(
            model,
            LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                r=config.lora.rank,
                lora_alpha=config.lora.alpha,
                lora_dropout=config.lora.dropout,
                bias=config.lora.bias,
                target_modules=target_paths,
                modules_to_save=None,
            ),
            autocast_adapter_dtype=True,
        )
        model.config.use_cache = False
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.train()
        lora_modules = {
            name: module for name, module in model.named_modules() if isinstance(module, LoraLayer)
        }
        if len(lora_modules) != 208:
            raise ValueError("PEFT did not inject exactly 208 LoRA modules")
        matched_paths = []
        unmatched_modules = []
        for name in lora_modules:
            matches = [path for path in target_paths if name.endswith(path)]
            if len(matches) == 1:
                matched_paths.append(matches[0])
            else:
                unmatched_modules.append(name)
        if unmatched_modules or sorted(matched_paths) != target_paths:
            raise ValueError("PEFT LoRA module paths do not exactly match inventory")
        named_parameters = list(model.named_parameters())
        trainable = [
            (name, parameter) for name, parameter in named_parameters if parameter.requires_grad
        ]
        expected_trainable_suffixes = {
            f"{path}.lora_{side}.default.weight" for path in target_paths for side in ("A", "B")
        }
        actual_trainable_suffixes = set()
        unexpected_trainable = []
        for name, _ in trainable:
            matches = [suffix for suffix in expected_trainable_suffixes if name.endswith(suffix)]
            if len(matches) == 1:
                actual_trainable_suffixes.add(matches[0])
            else:
                unexpected_trainable.append(name)
        if (
            len(trainable) != config.gates.expected_trainable_tensor_count
            or actual_trainable_suffixes != expected_trainable_suffixes
            or unexpected_trainable
            or _canonical_sha256(sorted(actual_trainable_suffixes))
            != config.gates.expected_trainable_suffix_sha256
            or sum(parameter.numel() for _, parameter in trainable)
            != config.gates.expected_trainable_parameter_count
        ):
            raise ValueError("PEFT trainable tensor, suffix, or parameter identity mismatch")
        expected_trainable_names = {name for name, _ in trainable}
        report["lora_identity"] = {
            "target_count": len(target_paths),
            "target_path_sha256": _canonical_sha256(target_paths),
            "trainable_tensor_count": len(trainable),
            "trainable_parameter_count": sum(parameter.numel() for _, parameter in trainable),
            "trainable_suffix_sha256": _canonical_sha256(sorted(actual_trainable_suffixes)),
        }
        if {str(parameter.dtype) for _, parameter in trainable} != {"torch.float32"}:
            raise ValueError("all LoRA trainables must be FP32")
        if any(
            parameter.requires_grad
            for name, parameter in named_parameters
            if name not in expected_trainable_names
        ):
            raise ValueError("a frozen base, vision, or MTP parameter is trainable")
        optimizer = torch.optim.AdamW(
            [parameter for _, parameter in trainable],
            lr=config.optimizer.learning_rate,
            betas=config.optimizer.betas,
            eps=config.optimizer.epsilon,
            weight_decay=config.optimizer.weight_decay,
            foreach=config.optimizer.foreach,
            fused=config.optimizer.fused,
        )
        assert_exact_trainable_parameter_set(
            named_parameters,
            expected_trainable_names=expected_trainable_names,
            optimizer_parameters=[
                parameter for group in optimizer.param_groups for parameter in group["params"]
            ],
        )
        del named_parameters, lora_modules
        adapter_before = _adapter_tensor_sha256(model)
        frozen_before = _frozen_sample_sha256(model)
        gdn_before = _gdn_identity()
        if not _is_fla_gdn(gdn_before):
            raise ValueError("optimized FLA GDN identity gate failed")

        image_root, image_manifest = _validate_training_images(config, rows)
        report["image_materialization"] = {
            "root": str(image_root),
            "manifest_sha256": config.data.image_materialization_manifest_sha256,
            "image_set_sha256": image_manifest["image_set_sha256"],
            "unique_image_count": image_manifest["unique_image_count"],
        }
        sample_metrics = {}
        image_token_id = tokenizer.convert_tokens_to_ids("<|image_pad|>")
        for row in rows:
            encoded, _ = _prepare_example(
                processor,
                tokenizer,
                row,
                image_root=image_root,
                max_post_expansion_length=config.execution.max_post_expansion_length,
            )
            sample_metrics[row.sample_id] = {
                "sequence_length": int(encoded["input_ids"].shape[1]),
                "image_token_count": int(encoded["input_ids"].eq(image_token_id).sum().item()),
            }
        if mode == "smoke32":
            smoke = select_smoke32(
                rows,
                sample_metrics={
                    sample_id: S5SmokeSampleMetricV1(
                        sample_id=sample_id,
                        sequence_length=metric["sequence_length"],
                        image_token_count=metric["image_token_count"],
                    )
                    for sample_id, metric in sample_metrics.items()
                },
            )
            row_by_id = {row.sample_id: row for row in rows}
            selected_rows = [row_by_id[sample_id] for sample_id in smoke.sample_ids]
            report["smoke_selection"] = smoke.model_dump(mode="json")
        if selected_rows is None or len(selected_rows) != expected_microsteps:
            raise ValueError("runtime row selection does not match frozen microsteps")

        if mode == "smoke32":
            probe_sample_id = min(row.sample_id for row in selected_rows)
        else:
            if fixed_probe_sample_id is None:
                raise ValueError("two-epoch fixed-probe identity is absent")
            probe_sample_id = fixed_probe_sample_id
        row_by_id = {row.sample_id: row for row in rows}
        probe_encoded_cpu, probe_labels_cpu = _prepare_example(
            processor,
            tokenizer,
            row_by_id[probe_sample_id],
            image_root=image_root,
            max_post_expansion_length=config.execution.max_post_expansion_length,
        )
        probe_encoded = {
            key: value.cuda() if hasattr(value, "cuda") else value
            for key, value in probe_encoded_cpu.items()
        }
        probe_labels = probe_labels_cpu.cuda()
        model.eval()
        _set_adapter_enabled(model, enabled=False)
        probe_pre_off = _selected_probe_observation(torch, model, probe_encoded, probe_labels)
        _set_adapter_enabled(model, enabled=True)
        probe_pre_on_first = _selected_probe_observation(torch, model, probe_encoded, probe_labels)
        probe_pre_on_second = _selected_probe_observation(torch, model, probe_encoded, probe_labels)
        pre_repeated_bit_exact = torch.equal(
            probe_pre_on_first["logits"], probe_pre_on_second["logits"]
        )
        if not pre_repeated_bit_exact:
            raise ValueError("pre-training repeated fixed-probe logits are not bit-exact")
        report["fixed_probe"] = {
            "sample_id": probe_sample_id,
            "selection": fixed_probe_selection,
            "included_in_smoke32": (
                probe_sample_id in {row.sample_id for row in selected_rows}
                if mode == "smoke32"
                else True
            ),
            "promoted_from_smoke_report": mode == "two-epoch",
            "pre_adapter_off": _probe_report(probe_pre_off),
            "pre_adapter_on_first": _probe_report(probe_pre_on_first),
            "pre_adapter_on_second": _probe_report(probe_pre_on_second),
            "pre_repeated_bit_exact": pre_repeated_bit_exact,
        }
        model.train()

        torch.cuda.reset_peak_memory_stats()
        microstep = 0
        update = 0
        losses = []
        for group in groups:
            optimizer.zero_grad(set_to_none=True)
            group_losses = []
            for _ in range(group.sample_count):
                row = selected_rows[microstep]
                encoded, labels = _prepare_example(
                    processor,
                    tokenizer,
                    row,
                    image_root=image_root,
                    max_post_expansion_length=(config.execution.max_post_expansion_length),
                )
                encoded = {
                    key: value.cuda() if hasattr(value, "cuda") else value
                    for key, value in encoded.items()
                }
                labels = labels.cuda()
                selection = select_loss_positions(
                    encoded["input_ids"][0].tolist(), labels[0].tolist()
                )
                predictors = torch.tensor(
                    selection.predictor_positions,
                    dtype=torch.long,
                    device=encoded["input_ids"].device,
                )
                targets = torch.tensor(
                    selection.targets,
                    dtype=torch.long,
                    device=encoded["input_ids"].device,
                )
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    output = model(
                        **_model_inputs(encoded),
                        labels=None,
                        logits_to_keep=predictors,
                        use_cache=False,
                        return_dict=True,
                    )
                    loss = selected_logits_cross_entropy(output.logits[0], targets)
                if not bool(torch.isfinite(loss.detach())):
                    raise ValueError("nonfinite selected training loss")
                (loss / group.loss_divisor).backward()
                group_losses.append(float(loss.detach()))
                losses.append(float(loss.detach()))
                report["events"].append(
                    {
                        "event": "microstep",
                        "sample_id": row.sample_id,
                        "family": row.family.value,
                        "outcome": "REFUSE" if row.target_plan.refused else "PLAN",
                        "loss": float(loss.detach()),
                        "sequence_length": int(encoded["input_ids"].shape[1]),
                        "image_token_count": sample_metrics[row.sample_id]["image_token_count"],
                    }
                )
                microstep += 1
                del output, loss, encoded, labels
            for _, parameter in trainable:
                if parameter.grad is not None and not bool(torch.isfinite(parameter.grad).all()):
                    raise ValueError("nonfinite LoRA gradient")
            if any(
                parameter.grad is not None
                for name, parameter in model.named_parameters()
                if name not in expected_trainable_names
            ):
                raise ValueError("frozen parameter received a gradient")
            clip_before = torch.nn.utils.clip_grad_norm_(
                [parameter for _, parameter in trainable],
                config.optimizer.global_lora_gradient_clip,
            )
            if not bool(torch.isfinite(clip_before)):
                raise ValueError("nonfinite global LoRA gradient norm")
            for optimizer_group in optimizer.param_groups:
                optimizer_group["lr"] = group.learning_rate
            optimizer.step()
            update += 1
            for name, parameter in model.named_parameters():
                if name not in expected_trainable_names and parameter.grad is not None:
                    raise ValueError("frozen parameter gradient survived optimizer step")
            if _frozen_sample_sha256(model) != frozen_before:
                raise ValueError("frozen base checksum changed during training")
            if not _is_fla_gdn(_gdn_identity()):
                raise ValueError("optimized FLA GDN identity changed during training")
            memory = _memory(torch)
            if memory["max_reserved_bytes"] >= (config.gates.immediate_abort_reserved_gib * GIB):
                raise MemoryError("74 GiB reserved immediate-abort threshold crossed")
            report["events"].append(
                {
                    "event": "optimizer_update",
                    "sample_count": group.sample_count,
                    "learning_rate": group.learning_rate,
                    "mean_sample_loss": sum(group_losses) / len(group_losses),
                    "gradient_norm_before_clip": float(clip_before),
                    "memory": memory,
                }
            )
        if microstep != expected_microsteps or update != expected_updates:
            raise ValueError("executed microstep/update count mismatch")
        optimizer.zero_grad(set_to_none=True)
        model.eval()
        _set_adapter_enabled(model, enabled=True)
        probe_post_on_first = _selected_probe_observation(torch, model, probe_encoded, probe_labels)
        probe_post_on_second = _selected_probe_observation(
            torch, model, probe_encoded, probe_labels
        )
        post_repeated_bit_exact = torch.equal(
            probe_post_on_first["logits"], probe_post_on_second["logits"]
        )
        if not post_repeated_bit_exact:
            raise ValueError("post-training repeated fixed-probe logits are not bit-exact")
        _set_adapter_enabled(model, enabled=False)
        probe_post_off = _selected_probe_observation(torch, model, probe_encoded, probe_labels)
        _set_adapter_enabled(model, enabled=True)
        adapter_delta_max_abs = float(
            (probe_post_on_first["logits"] - probe_post_off["logits"]).abs().max()
        )
        fixed_probe_loss_decreased = probe_post_on_first["loss"] < probe_pre_on_first["loss"]
        if mode == "smoke32" and not fixed_probe_loss_decreased:
            raise ValueError("smoke32 fixed-probe selected-logit CE did not decrease")
        if adapter_delta_max_abs <= 0:
            raise ValueError("fixed-probe adapter on/off selected-logit delta is zero")
        report["fixed_probe"].update(
            {
                "post_adapter_on_first": _probe_report(probe_post_on_first),
                "post_adapter_on_second": _probe_report(probe_post_on_second),
                "post_adapter_off": _probe_report(probe_post_off),
                "post_repeated_bit_exact": post_repeated_bit_exact,
                "loss_decreased": fixed_probe_loss_decreased,
                "adapter_on_off_max_abs_delta": adapter_delta_max_abs,
            }
        )
        adapter_after = _adapter_tensor_sha256(model)
        frozen_after = _frozen_sample_sha256(model)
        if adapter_after == adapter_before:
            raise ValueError("authorized optimizer run did not change the adapter")
        if frozen_after != frozen_before:
            raise ValueError("frozen base checksum changed")
        if any(
            parameter.grad is not None
            for name, parameter in model.named_parameters()
            if name not in expected_trainable_names
        ):
            raise ValueError("frozen parameter gradient persisted")
        final_memory = _memory(torch)
        allocated_pass = (
            final_memory["max_allocated_bytes"] <= config.gates.max_memory_allocated_gib * GIB
        )
        reserved_pass = (
            final_memory["max_reserved_bytes"] <= config.gates.max_memory_reserved_gib * GIB
        )
        gdn_after = _gdn_identity()
        if not allocated_pass or not reserved_pass or not _is_fla_gdn(gdn_after):
            raise ValueError("memory or optimized-GDN promotion gate failed")

        adapter_staging, adapter_staging_manifest = _save_adapter_staging_create_only(
            model, arguments.adapter_output
        )
        tensor_before_reload = _adapter_tensor_sha256(model)
        post_in_process_logits = probe_post_on_first["logits"]
        optimizer = None
        model = None
        gc.collect()
        torch.cuda.empty_cache()
        try:
            base_reload = Qwen3_5ForConditionalGeneration.from_pretrained(
                snapshot,
                local_files_only=True,
                dtype=torch.bfloat16,
                device_map={"": 0},
                low_cpu_mem_usage=True,
                use_kernels=False,
            )
            base_reload.config.use_cache = False
            reloaded = PeftModel.from_pretrained(
                base_reload,
                adapter_staging,
                local_files_only=True,
                is_trainable=False,
            )
            reloaded.eval()
            reloaded.config.use_cache = False
            tensor_after_reload = _adapter_tensor_sha256(reloaded)
            if tensor_after_reload != tensor_before_reload:
                raise ValueError("adapter tensor round-trip mismatch")
            probe_reload = _selected_probe_observation(torch, reloaded, probe_encoded, probe_labels)
            fresh_reload_bit_exact = torch.equal(post_in_process_logits, probe_reload["logits"])
            if not fresh_reload_bit_exact:
                raise ValueError("fresh reload fixed-probe selected logits are not bit-exact")
        except BaseException as exc:
            _mark_failed_adapter_staging(adapter_staging, exc)
            raise
        promotion_gates = {
            "exact_microstep_update_counts": (
                microstep == expected_microsteps and update == expected_updates
            ),
            "adapter_changed": adapter_after != adapter_before,
            "frozen_base_unchanged": frozen_after == frozen_before,
            "allocated_memory": allocated_pass,
            "reserved_memory": reserved_pass,
            "optimized_fla_gdn": _is_fla_gdn(gdn_after),
            "fixed_probe_loss_decreased": (
                fixed_probe_loss_decreased if mode == "smoke32" else True
            ),
            "pre_repeated_forward_bit_exact": pre_repeated_bit_exact,
            "post_repeated_forward_bit_exact": post_repeated_bit_exact,
            "adapter_on_off_delta_nonzero": adapter_delta_max_abs > 0,
            "adapter_tensor_round_trip": tensor_after_reload == tensor_before_reload,
            "fresh_reload_bit_exact": fresh_reload_bit_exact,
        }
        if not all(promotion_gates.values()):
            raise ValueError("not every frozen promotion gate passed")
        snapshot_tree_after, ignored_top_level_dirs_after = _snapshot_tree_identity(snapshot)
        if snapshot_tree_after != snapshot_tree_before:
            raise ValueError("frozen snapshot tree changed during training")
        adapter_tree_sha256 = hashlib.sha256(
            canonical_json(adapter_staging_manifest).encode()
        ).hexdigest()
        report["fixed_probe"].update(
            {
                "fresh_reload": _probe_report(probe_reload),
                "fresh_reload_bit_exact": fresh_reload_bit_exact,
            }
        )
        microstep_events = [event for event in report["events"] if event["event"] == "microstep"]
        family_losses: dict[str, list[float]] = {}
        outcome_losses: dict[str, list[float]] = {}
        for event in microstep_events:
            family_losses.setdefault(event["family"], []).append(event["loss"])
            outcome_losses.setdefault(event["outcome"], []).append(event["loss"])
        report["loss_summary"] = {
            "sample_mean": sum(event["loss"] for event in microstep_events) / len(microstep_events),
            "by_family": {
                family: {
                    "sample_count": len(values),
                    "sample_mean": sum(values) / len(values),
                }
                for family, values in sorted(family_losses.items())
            },
            "by_outcome": {
                outcome: {
                    "sample_count": len(values),
                    "sample_mean": sum(values) / len(values),
                }
                for outcome, values in sorted(outcome_losses.items())
            },
        }
        report.update(
            {
                "status": "PASS",
                "promotion_pass": True,
                "promotion_gates": promotion_gates,
                "microsteps": microstep,
                "optimizer_updates": update,
                "loss_first": losses[0],
                "loss_last": losses[-1],
                "adapter_sha256_before": adapter_before,
                "adapter_sha256_after": adapter_after,
                "adapter_tree_sha256": adapter_tree_sha256,
                "adapter_tensor_round_trip_sha256": tensor_after_reload,
                "frozen_sample_sha256": frozen_after,
                "memory": final_memory,
                "gdn_identity": gdn_after,
                "elapsed_seconds": time.monotonic() - started,
                "vllm_gate_deferred": True,
                "snapshot_tree_sha256_after": snapshot_tree_after,
                "ignored_top_level_dirs_after": ignored_top_level_dirs_after,
            }
        )
        prepared_path, publication_path = _receipt_paths(arguments.report_output)
        if (
            prepared_path.exists()
            or prepared_path.is_symlink()
            or publication_path.exists()
            or publication_path.is_symlink()
        ):
            raise FileExistsError("adapter publication receipt identity is already consumed")
        prepared = {
            "schema_version": "QwenBrainS5AdapterPreparedReceiptV1",
            "status": "PREPARED",
            "publication_primitive": config.execution.publication_primitive,
            "publication_evidence": config.execution.publication_evidence,
            "adapter_staging": str(adapter_staging),
            "adapter_destination": str(arguments.adapter_output),
            "adapter_tree_sha256": adapter_tree_sha256,
            "adapter_tensor_sha256": tensor_after_reload,
            "staging_manifest": adapter_staging_manifest,
            "prepared_report": report,
        }
        prepared_payload = _json_payload(prepared)
        _write_create_only(prepared_path, prepared_payload)
        prepared_receipt_written = True
        published_tree_sha256 = _publish_adapter_staging(
            adapter_staging,
            arguments.adapter_output,
            adapter_staging_manifest,
        )
        if published_tree_sha256 != adapter_tree_sha256:
            raise ValueError("published adapter tree identity changed after PREPARED receipt")
        publication = {
            "schema_version": "QwenBrainS5AdapterPublicationReceiptV1",
            "status": "PUBLISHED",
            "publication_primitive": config.execution.publication_primitive,
            "reconciled_after_interruption": False,
            "prepared_receipt": str(prepared_path),
            "prepared_receipt_sha256": hashlib.sha256(prepared_payload).hexdigest(),
            "adapter_destination": str(arguments.adapter_output),
            "adapter_tree_sha256": published_tree_sha256,
            "published_manifest": _tree_manifest(arguments.adapter_output),
        }
        publication_payload = _json_payload(publication)
        _write_create_only(publication_path, publication_payload)
        publication_receipt_written = True
        report.update(
            {
                "prepared_receipt": str(prepared_path),
                "prepared_receipt_sha256": hashlib.sha256(prepared_payload).hexdigest(),
                "publication_receipt": str(publication_path),
                "publication_receipt_sha256": hashlib.sha256(publication_payload).hexdigest(),
                "publication_reconciled_after_interruption": False,
            }
        )
    except Exception as exc:
        if not prepared_receipt_written:
            if "adapter_staging" in locals():
                _mark_failed_adapter_staging(adapter_staging, exc)
            report["status"] = "FAIL"
            report["promotion_pass"] = False
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc)
            report["traceback"] = traceback.format_exc()
        else:
            report["defer_final_report_to_reconciliation"] = True
            report["interrupted_after_prepared_receipt"] = True
            report["publication_receipt_written"] = publication_receipt_written
            raise S5PreparedPublicationInterruption(
                "publication interrupted after PREPARED receipt; reconcile without retraining"
            ) from exc
    finally:
        signal.alarm(0)
        with contextlib.suppress(UnboundLocalError):
            del reloaded
        with contextlib.suppress(UnboundLocalError):
            del base_reload
        with contextlib.suppress(UnboundLocalError):
            del probe_reload
        with contextlib.suppress(UnboundLocalError):
            del probe_post_on_first, probe_post_on_second, probe_post_off
        with contextlib.suppress(UnboundLocalError):
            del probe_pre_off, probe_pre_on_first, probe_pre_on_second
        with contextlib.suppress(UnboundLocalError):
            del post_in_process_logits, probe_encoded, probe_labels
        with contextlib.suppress(UnboundLocalError):
            del probe_encoded_cpu, probe_labels_cpu
        with contextlib.suppress(UnboundLocalError):
            del processor, tokenizer
        optimizer = None
        model = None
        with contextlib.suppress(UnboundLocalError):
            del trainable
        gc.collect()
        try:
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            report["released_memory_measurement"] = config.execution.released_memory_measurement
            report["released_memory"] = _memory(torch)
        except Exception as release_exc:  # noqa: BLE001
            report["release_error"] = repr(release_exc)
        report["no_candidate_service_started"] = True
        report["no_canonical_evaluation_executed"] = True
        if not report.get("defer_final_report_to_reconciliation"):
            payload = _json_payload(report)
            _write_create_only(arguments.report_output, payload)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "promotion_pass": report["promotion_pass"],
                        "report": str(arguments.report_output),
                        "report_sha256": hashlib.sha256(payload).hexdigest(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    return 0 if report["status"] == "PASS" else 2


def main() -> int:
    arguments = _parse_arguments()
    try:
        return _run(arguments)
    except S5PreparedPublicationInterruption as exc:
        print(
            json.dumps(
                {
                    "status": "INTERRUPTED_AFTER_PREPARED",
                    "promotion_pass": False,
                    "error": str(exc),
                    "reconciliation_required": True,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 3
    except Exception as exc:  # noqa: BLE001 - early failures are durable evidence
        report = {
            "schema_version": "QwenBrainS5TrainingRunReportV1",
            "mode": arguments.mode,
            "status": "FAIL",
            "promotion_pass": False,
            "failure_phase": "BEFORE_RUNTIME_REPORT_INITIALIZATION",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "no_candidate_service_started": True,
            "no_canonical_evaluation_executed": True,
        }
        payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        _write_create_only(arguments.report_output, payload)
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "promotion_pass": False,
                    "report": str(arguments.report_output),
                    "report_sha256": hashlib.sha256(payload).hexdigest(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
