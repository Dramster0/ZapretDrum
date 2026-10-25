"""Local zapret snapshots. No downloads or automatic changes on startup."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.paths import APP_DATA_DIR, ZAPRET_DIR, DOWNLOAD_TMP_DIR
from core.state import load_state
from core.storage import atomic_write
from core.diagnostic_log import logger

RECOVERY_DIR = APP_DATA_DIR / "recovery"
TRANSACTION_FILE = RECOVERY_DIR / "transaction.json"
COMPONENT_FIELDS = ("installed_version", "last_strategy", "favorite_strategy", "last_test_results",
                    "last_test_at", "last_test_version", "last_test_baseline")


@dataclass
class Backup:
    path: Path
    version: str
    created_at: str


def _plain_tree(root: Path) -> None:
    """Reject links/junctions before copying or deleting an owned tree."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        for path in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("Папка содержит ссылку или junction; операция отменена: " + path.name)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_backups() -> list[Backup]:
    found = []
    if not RECOVERY_DIR.exists():
        return found
    for folder in sorted(RECOVERY_DIR.glob("backup-*"), reverse=True):
        try:
            if folder.resolve().parent != RECOVERY_DIR.resolve():
                continue
            metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
            if (isinstance(metadata, dict) and metadata.get("schema") == 1 and isinstance(metadata.get("state"), dict)
                    and isinstance(metadata.get("files"), dict)
                    and (folder / "files/bin/winws.exe").is_file()
                    and (folder / "files/service.bat").is_file()):
                found.append(Backup(folder, str(metadata["state"].get("installed_version") or "неизвестна"), str(metadata["created_at"])))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def latest_backup() -> Backup | None:
    backups = available_backups()
    return backups[0] if backups else None


def capture_backup() -> Backup | None:
    if not (ZAPRET_DIR / "bin/winws.exe").is_file() or not (ZAPRET_DIR / "service.bat").is_file():
        return None
    _plain_tree(ZAPRET_DIR)
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    folder = RECOVERY_DIR / ("backup-" + created.strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8])
    folder.mkdir()
    try:
        shutil.copytree(ZAPRET_DIR, folder / "files")
        checksums = {p.relative_to(folder / "files").as_posix(): _digest(p)
                     for p in (folder / "files").rglob("*") if p.is_file()}
        state = load_state().to_dict()
        metadata = {"schema": 1, "created_at": created.isoformat(), "files": checksums,
                    "state": {key: state[key] for key in COMPONENT_FIELDS}}
        latest = latest_backup()
        if latest:
            try:
                old_metadata = json.loads((latest.path / "metadata.json").read_text(encoding="utf-8"))
                old_root = latest.path / "files"
                _plain_tree(latest.path)
                old_files = {p.relative_to(old_root).as_posix(): p for p in old_root.rglob("*") if p.is_file()}
                if (old_metadata["state"] == metadata["state"] and old_metadata["files"] == checksums
                        and old_files.keys() == checksums.keys()
                        and all(_digest(path) == checksums[name] for name, path in old_files.items())):
                    # Retrying a failed update must not fill the disk with identical snapshots.
                    shutil.rmtree(folder, ignore_errors=True)
                    return latest
            except (OSError, ValueError, KeyError, TypeError):
                pass
        atomic_write(folder / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"))
        logger.info("Сохранена резервная копия zapret: %s", state["installed_version"])
        return Backup(folder, state["installed_version"] or "неизвестна", created.isoformat())
    except Exception:
        logger.exception("Резервная копия не создана; замена установки отменена")
        shutil.rmtree(folder, ignore_errors=True)
        raise


def begin_transaction(version: str) -> None:
    atomic_write(TRANSACTION_FILE, json.dumps({"version": version, "started_at": datetime.now(timezone.utc).isoformat()}).encode("utf-8"))


def finish_transaction() -> None:
    TRANSACTION_FILE.unlink(missing_ok=True)
    # Keep two complete generations; leave incomplete/unknown directories alone.
    for backup in available_backups()[2:]:
        try:
            _plain_tree(backup.path)
            shutil.rmtree(backup.path)
        except OSError:
            logger.warning("Не удалось убрать старую резервную копию")


def pending_notice() -> str:
    if TRANSACTION_FILE.exists():
        return ("Предыдущая замена zapret не завершилась подтверждённым успехом. "
                "Проверьте диагностику; при необходимости верните сохранённую версию во вкладке «Обновление».")
    return ""


def restore_previous(backup_id: str | None = None, progress_cb=None):
    from core.installer import InstallerError, ReleaseInfo, _apply_prepared_install
    from core.state import _decode

    backups = available_backups()
    backup = next((entry for entry in backups if entry.path.name == backup_id), None) if backup_id else next(iter(backups), None)
    if backup is None:
        raise InstallerError("Сохранённой версии пока нет. Она появится после следующего обновления zapret.")
    _plain_tree(backup.path)
    metadata = json.loads((backup.path / "metadata.json").read_text(encoding="utf-8"))
    # Validate both paths and content before stopping any running component.
    expected = metadata["files"]
    root = backup.path / "files"
    actual = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
    if actual.keys() != expected.keys() or any(_digest(path) != expected[name] for name, path in actual.items()):
        raise InstallerError("Резервная копия повреждена или изменена. Текущая установка сохранена.")
    restored = _decode(json.dumps(metadata["state"]).encode("utf-8")).to_dict()
    DOWNLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="zapret-restore-", dir=DOWNLOAD_TMP_DIR))
    prepared = job / "prepared"
    try:
        shutil.copytree(root, prepared)
    except Exception:
        shutil.rmtree(job, ignore_errors=True)
        raise
    release = ReleaseInfo(backup.version, "", "", "", "")
    logger.info("Начат откат zapret к версии %s", backup.version)
    return _apply_prepared_install(prepared, job, release, progress_cb,
                                   {key: restored[key] for key in COMPONENT_FIELDS})
