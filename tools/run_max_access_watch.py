from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    # Always launch only the probe; never start the stopped primary bot service.
    name = "maxvideobot-access-probe-" + uuid.uuid4().hex
    command = ["docker", "compose", "run", "--name", name, "--rm", "--no-deps", "-T",
               "--entrypoint", "python", "bot", "-"]
    probe = (ROOT / "tools" / "max_access_watch.py").read_text(encoding="utf-8")
    source = ('__file__ = "/app/tools/max_access_watch.py"\n'
              f"exec(compile({probe!r}, __file__, 'exec'))\n")
    try:
        result = subprocess.run(
            command, input=source, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", timeout=240,
        )
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "probe_timeout"}))
        raise SystemExit(1)
    finally:
        # Killing the Docker CLI alone does not stop its container.
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
    if result.returncode:
        print(json.dumps({"status": "probe_failed", "exit_code": result.returncode}))
        raise SystemExit(1)
    print(json.dumps(json.loads(result.stdout.strip()), ensure_ascii=False))


if __name__ == "__main__":
    main()
