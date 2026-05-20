from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config

TG_API = "https://api.telegram.org"


def _log(text: str = "") -> None:
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _effect_rows(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, button_name, prompt, demo_file_id, demo_type, type, is_active, sort_order, created_at
                FROM effects
                ORDER BY type ASC, sort_order DESC, id ASC
                """
            ).fetchall()
        ]


def _group_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["button_name"]), str(row.get("type") or "video")


def _rank(row: dict[str, Any]) -> tuple[int, int, int]:
    return int(row.get("is_active") or 0), int(row.get("sort_order") or 0), int(row.get("id") or 0)


def _grouped(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_group_key(row)].append(row)
    for key in groups:
        groups[key].sort(key=_rank, reverse=True)
    return groups


def _telegram_like(value: str | None) -> bool:
    return bool(value) and not str(value).startswith(("http://", "https://")) and not Path(str(value)).exists()


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


def _demo_path(media_dir: Path, file_id: str, telegram_file_path: str, demo_type: str | None) -> Path:
    suffix = Path(telegram_file_path).suffix
    if not suffix:
        suffix = ".mp4" if demo_type == "video" else ".jpg"
    digest = hashlib.sha1(file_id.encode("utf-8")).hexdigest()[:16]
    return media_dir / f"tg_demo_{digest}{suffix}"


def _safe_error(error: Exception, token: str) -> str:
    return str(error).replace(token, "***")


def _resolve_demo(
    *,
    source_demo: str | None,
    source_demo_type: str | None,
    token: str,
    media_dir: Path,
    dry_run: bool,
    timeout: int,
    cache: dict[str, str],
) -> str | None:
    if not source_demo:
        return None
    source_demo = str(source_demo)
    if not _telegram_like(source_demo):
        return source_demo
    if source_demo in cache:
        return cache[source_demo]
    if dry_run:
        cache[source_demo] = f"<download {source_demo_type or 'media'}>"
        return cache[source_demo]
    file_info = _tg_get_file(token, source_demo, timeout)
    destination = _demo_path(media_dir, source_demo, str(file_info["file_path"]), source_demo_type)
    if not destination.exists():
        _download_telegram_file(token, str(file_info["file_path"]), destination, timeout)
    cache[source_demo] = str(destination)
    return cache[source_demo]


def _backup(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.name}.before-effect-sync-{_utc_stamp()}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def sync_effects(
    *,
    source_db: Path,
    target_db: Path,
    media_dir: Path,
    token: str,
    dry_run: bool,
    no_backup: bool,
    timeout: int,
    sleep_sec: float,
) -> int:
    source_rows = _effect_rows(source_db)
    target_rows = _effect_rows(target_db)
    source_groups = _grouped(source_rows)
    target_groups = _grouped(target_rows)
    demo_cache: dict[str, str] = {}

    stats = {
        "source_total": len(source_rows),
        "target_before": len(target_rows),
        "updated": 0,
        "inserted": 0,
        "deactivated_extra": 0,
        "demo_rows": 0,
        "errors": 0,
    }

    _log(f"Source DB: {source_db}")
    _log(f"Target DB: {target_db}")
    _log(f"Media dir: {media_dir}")
    _log(f"Dry run: {dry_run}")

    if not dry_run and not no_backup:
        backup_path = _backup(target_db)
        _log(f"Backup: {backup_path}")

    media_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect(target_db)
    try:
        for key, source_group in sorted(source_groups.items(), key=lambda item: (item[0][1], item[0][0])):
            target_group = target_groups.get(key, [])
            for idx, source in enumerate(source_group):
                try:
                    demo_file_id = _resolve_demo(
                        source_demo=source.get("demo_file_id"),
                        source_demo_type=source.get("demo_type"),
                        token=token,
                        media_dir=media_dir,
                        dry_run=dry_run,
                        timeout=timeout,
                        cache=demo_cache,
                    )
                    demo_type = source.get("demo_type") if demo_file_id else None
                    if demo_file_id:
                        stats["demo_rows"] += 1

                    values = (
                        source["button_name"],
                        source["prompt"],
                        demo_file_id,
                        demo_type,
                        source.get("type") or "video",
                        int(source.get("is_active") or 0),
                        int(source.get("sort_order") or 0),
                        source.get("created_at") or datetime.utcnow().isoformat(timespec="seconds"),
                    )

                    if idx < len(target_group):
                        target_id = int(target_group[idx]["id"])
                        stats["updated"] += 1
                        if not dry_run:
                            conn.execute(
                                """
                                UPDATE effects
                                SET button_name = ?, prompt = ?, demo_file_id = ?, demo_type = ?,
                                    type = ?, is_active = ?, sort_order = ?, created_at = ?
                                WHERE id = ?
                                """,
                                (*values, target_id),
                            )
                    else:
                        stats["inserted"] += 1
                        if not dry_run:
                            conn.execute(
                                """
                                INSERT INTO effects
                                    (button_name, prompt, demo_file_id, demo_type, type, is_active, sort_order, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                values,
                            )
                    time.sleep(max(0.0, sleep_sec))
                except Exception as error:
                    stats["errors"] += 1
                    _log(f"ERROR {key}: {_safe_error(error, token)}")

            if len(target_group) > len(source_group):
                for extra in target_group[len(source_group) :]:
                    stats["deactivated_extra"] += 1
                    if not dry_run:
                        conn.execute("UPDATE effects SET is_active = 0 WHERE id = ?", (int(extra["id"]),))

        for key, target_group in target_groups.items():
            if key in source_groups:
                continue
            for extra in target_group:
                stats["deactivated_extra"] += 1
                if not dry_run:
                    conn.execute("UPDATE effects SET is_active = 0 WHERE id = ?", (int(extra["id"]),))

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    target_after = len(_effect_rows(target_db)) if not dry_run else stats["target_before"] + stats["inserted"]
    stats["target_after"] = target_after
    _log("Done.")
    for key, value in stats.items():
        _log(f"{key}: {value}")
    return 1 if stats["errors"] else 0


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Sync MAX effects from an actual Telegram SQLite database.")
    parser.add_argument("--source-db", required=True, help="Actual Telegram SQLite DB path")
    parser.add_argument("--target-db", default=cfg.database_path, help="MAX SQLite DB path")
    parser.add_argument("--media-dir", default=cfg.media_demo_dir, help="Directory for local demo files")
    parser.add_argument(
        "--token",
        default=os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or cfg.bot_token,
        help="Telegram bot token that owns source demo file_id values.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying target DB")
    parser.add_argument("--no-backup", action="store_true", help="Do not create target DB backup")
    parser.add_argument("--timeout", type=int, default=120, help="HTTP timeout in seconds")
    parser.add_argument("--sleep", type=float, default=0.05, help="Sleep between demo downloads")
    args = parser.parse_args()

    if not args.token:
        _log("Telegram token is missing. Set BOT_TOKEN or TELEGRAM_BOT_TOKEN.")
        raise SystemExit(2)

    raise SystemExit(
        sync_effects(
            source_db=Path(args.source_db),
            target_db=Path(args.target_db),
            media_dir=Path(args.media_dir),
            token=str(args.token),
            dry_run=bool(args.dry_run),
            no_backup=bool(args.no_backup),
            timeout=int(args.timeout),
            sleep_sec=float(args.sleep),
        )
    )


if __name__ == "__main__":
    main()
