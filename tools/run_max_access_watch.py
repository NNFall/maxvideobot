from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "maxvideobot-bot-1"


def main() -> None:
    inspect = subprocess.run(
        ["docker", "inspect", CONTAINER], capture_output=True, text=True, timeout=15
    )
    if inspect.returncode:
        print(json.dumps({"status": "container_missing"}))
        return
    container = json.loads(inspect.stdout)[0]
    state_path = ROOT / "data" / "max_access_watch.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    scan_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_arguments = ["--since", state["last_log_scan_at"]] if state.get(
        "last_log_scan_at"
    ) else ["--tail", "5000"]
    logs = subprocess.Popen(
        ["docker", "logs", "--timestamps", *log_arguments, CONTAINER],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = threading.Timer(15, logs.kill)
    deadline.start()
    blocked_at = None
    try:
        for line in logs.stdout:
            if "profile is limited" in line.lower() and line.startswith("20"):
                value = line.split()[0]
                blocked_at = max(blocked_at, value) if blocked_at else value
        code = logs.wait()
    finally:
        deadline.cancel()
        logs.stdout.close()
    if code:
        print(json.dumps({"status": "log_unavailable", "exit_code": code}))
        return
    arguments = ["--recipient", "4533898", "--log-scan-at", scan_at]
    if blocked_at:
        arguments += ["--blocked-at", blocked_at]
    running = container["State"]["Running"]
    if running:
        command = ["docker", "exec", "-i", CONTAINER, "python", "-", *arguments]
    else:
        command = ["docker", "compose", "run", "--rm", "--no-deps", "-T",
                   "--entrypoint", "python", "bot", "-", *arguments]
    # Run only the probe, including when the normal bot is stopped.
    probe = (ROOT / "tools" / "max_access_watch.py").read_text(encoding="utf-8")
    source = ('__file__ = "/app/tools/max_access_watch.py"\n'
              f"exec(compile({probe!r}, __file__, 'exec'))\n")
    result = subprocess.run(
        command, input=source, cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", timeout=120,
    )
    if result.returncode:
        print(json.dumps({"status": "probe_failed", "exit_code": result.returncode,
                          "container_running": running}))
        return
    report = json.loads(result.stdout.strip())
    report["container_running"] = running
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
