from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config
from database.seed_effects import EFFECTS


TG_API = "https://api.telegram.org"


def _log(text: str = "") -> None:
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _source_demo_map() -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for effect in EFFECTS:
        demo_file_id = effect.get("demo_file_id")
        demo_type = effect.get("demo_type")
        effect_type = effect.get("type") or "video"
        button_name = effect.get("button_name")
        if not button_name or not demo_file_id or demo_type not in {"photo", "video"}:
            continue
        if str(demo_file_id).startswith(("http://", "https://")):
            continue
        if Path(str(demo_file_id)).exists():
            continue
        result[(str(button_name), str(effect_type))] = {
            "file_id": str(demo_file_id),
            "demo_type": str(demo_type),
        }
    return result


def _tg_get_file(token: str, file_id: str, timeout: int) -> dict[str, Any]:
    response = requests.get(
        f"{TG_API}/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram getFile failed: {payload.get('description') or payload}")
    result = payload.get("result") or {}
    if not result.get("file_path"):
        raise RuntimeError("Telegram getFile returned no file_path")
    return result


def _download_telegram_file(token: str, file_path: str, destination: Path, timeout: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(f"{TG_API}/file/bot{token}/{file_path}", stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with destination.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)


def _demo_path(media_dir: Path, file_id: str, telegram_file_path: str, demo_type: str) -> Path:
    suffix = Path(telegram_file_path).suffix
    if not suffix:
        suffix = ".mp4" if demo_type == "video" else ".jpg"
    digest = hashlib.sha1(file_id.encode("utf-8")).hexdigest()[:16]
    return media_dir / f"tg_demo_{digest}{suffix}"


def _is_existing_local_demo(value: str | None) -> bool:
    if not value:
        return False
    if value.startswith(("http://", "https://")):
        return True
    return Path(value).exists()


def _safe_error(error: Exception, token: str) -> str:
    return str(error).replace(token, "***")


def migrate(
    *,
    db_path: Path,
    media_dir: Path,
    token: str,
    dry_run: bool,
    overwrite: bool,
    include_inactive: bool,
    limit: int,
    sleep_sec: float,
    timeout: int,
) -> int:
    source = _source_demo_map()
    media_dir.mkdir(parents=True, exist_ok=True)

    query = """
        SELECT id, button_name, type, demo_file_id, demo_type, is_active
        FROM effects
    """
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY type ASC, sort_order DESC, id ASC"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query).fetchall()
    if limit > 0:
        rows = rows[:limit]

    stats = {
        "checked": 0,
        "eligible": 0,
        "downloaded": 0,
        "updated": 0,
        "skipped_existing": 0,
        "missing_source": 0,
        "failed": 0,
    }
    downloaded_by_file_id: dict[str, Path] = {}

    _log(f"DB: {db_path}")
    _log(f"Media dir: {media_dir}")
    _log(f"Rows: {len(rows)}")
    _log(f"Dry run: {dry_run}")
    _log(f"Overwrite: {overwrite}")
    _log(f"Include inactive: {include_inactive}")

    for row in rows:
        stats["checked"] += 1
        effect_id = int(row["id"])
        button_name = str(row["button_name"])
        effect_type = str(row["type"] or "video")
        current_demo = row["demo_file_id"]

        if current_demo and _is_existing_local_demo(str(current_demo)) and not overwrite:
            stats["skipped_existing"] += 1
            continue

        source_demo = source.get((button_name, effect_type))
        if not source_demo:
            stats["missing_source"] += 1
            continue

        stats["eligible"] += 1
        file_id = source_demo["file_id"]
        demo_type = source_demo["demo_type"]
        _log(f"[{effect_id}] {effect_type}/{demo_type}: {button_name}")

        try:
            if dry_run:
                _log("  would download and update demo_file_id")
                continue

            local_path = downloaded_by_file_id.get(file_id)
            if local_path is None or not local_path.exists():
                file_info = _tg_get_file(token, file_id, timeout)
                local_path = _demo_path(media_dir, file_id, str(file_info["file_path"]), demo_type)
                if not local_path.exists() or overwrite:
                    _download_telegram_file(token, str(file_info["file_path"]), local_path, timeout)
                    stats["downloaded"] += 1
                downloaded_by_file_id[file_id] = local_path

            conn.execute(
                "UPDATE effects SET demo_file_id = ?, demo_type = ? WHERE id = ?",
                (str(local_path), demo_type, effect_id),
            )
            conn.commit()
            stats["updated"] += 1
            _log(f"  saved: {local_path}")
        except Exception as error:
            stats["failed"] += 1
            _log(f"  ERROR: {_safe_error(error, token)}")
        time.sleep(max(0.0, sleep_sec))

    conn.close()
    _log("Done.")
    for key, value in stats.items():
        _log(f"{key}: {value}")
    return 1 if stats["failed"] else 0


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(
        description="Download Telegram demo file_id assets into MEDIA_DEMO_DIR and attach them to MAX effects.",
    )
    parser.add_argument("--db", default=cfg.database_path, help="SQLite database path")
    parser.add_argument("--media-dir", default=cfg.media_demo_dir, help="Directory for downloaded demo files")
    parser.add_argument(
        "--token",
        default=os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or cfg.bot_token,
        help="Telegram bot token that owns old file_id values. Defaults to TELEGRAM_BOT_TOKEN/BOT_TOKEN.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be migrated")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing local/URL demos")
    parser.add_argument("--include-inactive", action="store_true", help="Also migrate inactive effects")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N rows")
    parser.add_argument("--sleep", type=float, default=0.15, help="Sleep between Telegram requests")
    parser.add_argument("--timeout", type=int, default=120, help="HTTP timeout in seconds")
    args = parser.parse_args()

    if not args.token:
        _log("Telegram token is missing. Set BOT_TOKEN or TELEGRAM_BOT_TOKEN.")
        raise SystemExit(2)

    raise SystemExit(
        migrate(
            db_path=Path(args.db),
            media_dir=Path(args.media_dir),
            token=str(args.token),
            dry_run=bool(args.dry_run),
            overwrite=bool(args.overwrite),
            include_inactive=bool(args.include_inactive),
            limit=int(args.limit),
            sleep_sec=float(args.sleep),
            timeout=int(args.timeout),
        )
    )


if __name__ == "__main__":
    main()
