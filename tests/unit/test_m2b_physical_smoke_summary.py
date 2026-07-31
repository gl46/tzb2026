from __future__ import annotations

from m2b.summarize_physical_failure_smoke import remote_json


def test_remote_json_reads_machine_evidence(monkeypatch) -> None:
    class Completed:
        returncode = 0
        stdout = '{"status":"PASS"}'
        stderr = ""

    monkeypatch.setattr(
        "m2b.summarize_physical_failure_smoke.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    assert remote_json("node", "/evidence.json") == {"status": "PASS"}
