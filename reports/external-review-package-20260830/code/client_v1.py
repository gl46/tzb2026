"""OpenAI-compatible multimodal client with raw, append-only attempt records."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from xh_agent.qwen_brain.contracts_v1 import (
    CommanderAttemptRecordV1,
    CommanderPlanV1,
    CommanderRequestV1,
)

COMMANDER_SYSTEM_PROMPT_V1 = """你是工业机器人系统的低频任务指挥体。你只做符号任务分解，不直接控制机器人。

只输出一个 JSON 对象，且顶层必须恰有两个键: subtasks, rationale。
- subtasks: 数组。每项恰有 agent, skill_plan, preconditions, expected_postconditions。
- agent: 只能是 A、B、C。
- skill_plan: 每步恰有 step_id, primitive, parameters, depends_on。
- primitive 只能是现有 exact-plan phase 命令:
  CARTESIAN_POSE, GRIPPER_POSITION, ATTACH_CONTACT_ENTITY,
  REMOVE_ATTACHMENT, PUBLIC_RGBD_CAPTURE, PUBLIC_TRACK_REASSOCIATION。
- parameters 必须严格使用以下逐原语 wire shape，不得增删或改名:
  CARTESIAN_POSE={"pose_ref":"symbol","planner_resolution_required":true}
  GRIPPER_POSITION={"position_ref":"OPEN或CLOSE","planner_resolution_required":true}
  ATTACH_CONTACT_ENTITY={"target_ref":"symbol","contact_policy":"BOUND_BILATERAL_CONTACT","planner_resolution_required":true}
  REMOVE_ATTACHMENT={"target_ref":"symbol","planner_resolution_required":true}
  PUBLIC_RGBD_CAPTURE={"observation_ref":"symbol"}
  PUBLIC_TRACK_REASSOCIATION={"target_ref":"symbol"}
- 不得输出真实坐标、轨迹或关节值。symbol 必须是字母开头且只含字母、数字、点、冒号、下划线或连字符的符号引用。执行层随后独立做 exact-plan 合成和验证。
- preconditions / expected_postconditions 每项恰有 predicate, arguments。
- predicate 只能是 IMAGE_CLEAR, REGION_COUNT_RESOLVED, TARGET_TRACK_BOUND,
  DESTINATION_REGISTERED, AGENT_AVAILABLE, NO_SAFETY_BLOCKER, GRASP_CONFIRMED,
  PARTS_PACKED, BIN_READY, BIN_AT_DESTINATION, TASK_COMPLETE,
  FRESH_PUBLIC_OBSERVATION。
- 若图像不清、必要对象或区域无法识别、指令超出装箱/料格放置/料箱搬运范围，
  不得猜测：输出 {"subtasks":[],"rationale":"REFUSE: <中文原因>"}。
- 多执行体是逻辑执行体；不要声称物理多臂并发。
- rationale 必须简短说明分工和依赖，不得输出思维链。
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _urlopen(outbound: request.Request, timeout_s: float):
    """Open the internal commander endpoint without ambient desktop proxies."""
    return request.build_opener(request.ProxyHandler({})).open(
        outbound, timeout=timeout_s
    )


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise TypeError("response choice has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise TypeError("response message content is not a string")
    return content


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip() in {"```", "```json"} and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise TypeError("model content is not a JSON object")
    return value


class QwenCommanderClientV1:
    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        evidence_dir: Path,
        timeout_s: float = 600.0,
        max_attempts: int = 2,
        max_tokens: int = 2048,
        guided_json: bool = True,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.evidence_dir = evidence_dir
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.max_tokens = max_tokens
        self.guided_json = guided_json

    def command(
        self,
        *,
        case_id: str,
        instruction: str,
        image_path: Path,
        context: dict[str, Any] | None = None,
    ) -> CommanderPlanV1:
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        commander_request = CommanderRequestV1(
            case_id=case_id,
            instruction=instruction,
            image_path=str(image_path.resolve()),
            image_sha256=_sha256(image_path),
            context=context or {},
        )
        correction: str | None = None
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            user_text = instruction
            if context:
                user_text += "\n已知上下文(JSON): " + json.dumps(
                    context, ensure_ascii=False, sort_keys=True
                )
            if correction is not None:
                user_text += (
                    "\n上一次输出未通过严格 schema。请完全重写 JSON，不要解释。校验错误: "
                    + correction
                )
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": COMMANDER_SYSTEM_PROMPT_V1},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
                            {"type": "text", "text": user_text},
                        ],
                    },
                ],
                "temperature": 0.0,
                "max_tokens": self.max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            if self.guided_json:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "commander_plan_v1",
                        "schema": CommanderPlanV1.model_json_schema(),
                    },
                }
            started = datetime.now(timezone.utc).isoformat()
            then = time.monotonic()
            status: int | None = None
            response_text = ""
            content: str | None = None
            plan: CommanderPlanV1 | None = None
            validation_error: str | None = None
            try:
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                outbound = request.Request(
                    f"{self.endpoint}/v1/chat/completions",
                    data=encoded,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _urlopen(outbound, self.timeout_s) as incoming:
                    status = incoming.status
                    response_text = incoming.read().decode("utf-8")
                content = _extract_content(json.loads(response_text))
                plan = CommanderPlanV1.model_validate(_extract_json_object(content))
            except error.HTTPError as exc:
                status = exc.code
                response_text = exc.read().decode("utf-8", errors="replace")
                validation_error = f"HTTPError: {exc}"
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - all model deviations are evidence
                validation_error = f"{type(exc).__name__}: {exc}"
                last_error = exc
            elapsed = time.monotonic() - then
            record = CommanderAttemptRecordV1(
                case_id=case_id,
                attempt=attempt,
                endpoint=self.endpoint,
                model=self.model,
                started_at_utc=started,
                elapsed_s=elapsed,
                request=commander_request,
                http_request_body=body,
                http_status=status,
                http_response_body=response_text,
                parsed_content=content,
                validation_status="PASS" if plan is not None else "FAIL",
                validation_error=validation_error,
                accepted_plan=plan,
            )
            self._write_attempt(record)
            if plan is not None:
                return plan
            correction = validation_error or "unknown validation failure"
        assert last_error is not None
        raise ValueError(
            f"commander output failed validation after {self.max_attempts} attempts: {last_error}"
        ) from last_error

    def _write_attempt(self, record: CommanderAttemptRecordV1) -> None:
        case_dir = self.evidence_dir / record.case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        destination = case_dir / f"attempt-{record.attempt:02d}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(destination, flags, 0o444)
        try:
            payload = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
