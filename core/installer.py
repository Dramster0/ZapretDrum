"""
Установка и обновление zapret-discord-youtube из GitHub Releases.

Логика:
  1. Спросить GitHub API какой latest release (tag_name + assets).
  2. Скачать .zip ассет (предпочитаем .zip, т.к. его проще всего распаковать
     без внешних утилит).
  3. Распаковать во временную папку, затем переложить в ZAPRET_DIR.
  4. При обновлении - сохранить пользовательские списки доменов и вернуть
     их обратно после распаковки новой версии.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import zipfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from core import process_manager
from core.paths import (
    ZAPRET_DIR,
    DOWNLOAD_TMP_DIR,
    BACKUP_DIR,
    USER_LIST_NAMES,
    GITHUB_API_LATEST_RELEASE,
    GITHUB_API_ALL_RELEASES,
    ensure_dirs,
)

ProgressCB = Optional[Callable[[str, float], None]]  # (сообщение, доля 0..1)


class InstallerError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    tag_name: str
    zip_url: str
    zip_name: str
    published_at: str
    notes: str
    warning: str = ""


def _report(cb: ProgressCB, msg: str, frac: float) -> None:
    if cb:
        cb(msg, frac)


def _github_headers() -> dict:
    # GitHub API отдаёт 403 без User-Agent
    return {"User-Agent": "ZapretDrum", "Accept": "application/vnd.github+json"}


def _parse_release(data: dict) -> ReleaseInfo | None:
    assets = data.get("assets", [])
    zip_asset = next((a for a in assets if a["name"].lower().endswith(".zip")), None)
    if zip_asset is None:
        return None
    return ReleaseInfo(
        tag_name=data.get("tag_name", "unknown"),
        zip_url=zip_asset["browser_download_url"],
        zip_name=zip_asset["name"],
        published_at=data.get("published_at", ""),
        notes=data.get("body", "") or "",
    )


def fetch_latest_release() -> ReleaseInfo:
    """Запрашивает информацию о последнем релизе через GitHub API."""
    try:
        resp = requests.get(GITHUB_API_LATEST_RELEASE, headers=_github_headers(), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise InstallerError(f"Не удалось связаться с GitHub API: {exc}") from exc

    release = _parse_release(resp.json())
    if release is None:
        raise InstallerError("В последнем релизе не найден .zip архив.")
    return release


def fetch_all_releases(limit: int = 30) -> list[ReleaseInfo]:
    """
    Возвращает список релизов (от новых к старым, максимум `limit` штук) -
    для выбора конкретной версии для установки, как в лаунчерах игр.
    """
    try:
        resp = requests.get(
            GITHUB_API_ALL_RELEASES,
            headers=_github_headers(),
            params={"per_page": min(limit, 100)},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise InstallerError(f"Не удалось связаться с GitHub API: {exc}") from exc

    releases = []
    for item in resp.json():
        release = _parse_release(item)
        if release is not None:
            releases.append(release)
    return releases


IS_WINDOWS = sys.platform == "win32"

# Службы, которые держат файлы zapret заблокированными: сама служба zapret
# и драйвер WinDivert (WinDivert64.sys остаётся загруженным в ядре даже
# после остановки winws.exe - из-за этого папку bin нельзя удалить целиком,
# пока драйвер не выгружен).
_LOCKING_SERVICES = ("zapret", "WinDivert", "WinDivert14")


def _winws_path() -> Path:
    return ZAPRET_DIR / "bin" / "winws.exe"


def is_installed() -> bool:
    if _winws_path().exists():
        return True
    # Самовосстановление: если из-за прошлых сбоев новая версия оказалась
    # вложена в подпапку (ZAPRET_DIR/zapret-discord-youtube-x.y.z/...),
    # вытаскиваем её содержимое на нужный уровень.
    return repair_install_layout()


def release_locks() -> None:
    """
    Освобождает файлы zapret перед заменой/удалением: останавливает
    winws.exe, службу zapret и драйвер WinDivert. Ошибки игнорируются -
    это best-effort, дальше установка всё равно устойчива к остаткам.
    """
    if not IS_WINDOWS:
        return
    try:
        if process_manager.is_running():
            process_manager.stop_all()
    except Exception:  # noqa: BLE001
        pass
    for name in _LOCKING_SERVICES:
        from core.service_manager import service_belongs_to_install
        if not service_belongs_to_install(name):
            continue
        try:
            subprocess.run(
                ["sc", "stop", name],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1.0)  # даём драйверу время выгрузиться


def _remove_path(p: Path) -> bool:
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink()
    except OSError:
        pass
    return not p.exists()


def _clear_dir_contents(directory: Path) -> list[str]:
    """Удаляет всё содержимое папки (саму папку не трогаем). Возвращает
    список того, что удалить не удалось (занято драйвером/антивирусом/Проводником)."""
    leftovers: list[str] = []
    if not directory.is_dir():
        return leftovers
    for child in list(directory.iterdir()):
        if not _remove_path(child):
            leftovers.append(str(child))
    return leftovers


def _merge_move(src: Path, dst: Path, failures: list[str]) -> None:
    """
    Переносит СОДЕРЖИМОЕ src внутрь dst, перезаписывая совпадающие файлы и
    сливая папки. В отличие от shutil.move(src, dst) НИКОГДА не создаёт
    вложенную папку, даже если dst уже существует.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dst / item.name
        if item.is_dir() and not item.is_symlink():
            if target.exists() and not target.is_dir():
                if not _remove_path(target):
                    failures.append(str(target))
                    continue
            _merge_move(item, target, failures)
        else:
            try:
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))
            except OSError:
                failures.append(str(target))
    try:
        src.rmdir()
    except OSError:
        pass


def repair_install_layout() -> bool:
    """
    Чинит раскладку, в которой настоящая установка оказалась вложена в
    подпапку внутри ZAPRET_DIR (а в самой ZAPRET_DIR лежат только остатки
    вроде пустого bin/ и lists/). Возвращает True, если после ремонта
    winws.exe на месте. Безопасно вызывать многократно.
    """
    if _winws_path().exists() or not ZAPRET_DIR.is_dir():
        return False
    try:
        for child in list(ZAPRET_DIR.iterdir()):
            if child.is_dir() and (child / "bin" / "winws.exe").exists():
                _merge_move(child, ZAPRET_DIR, [])
                return _winws_path().exists()
    except OSError:
        return False
    return False


def remove_install() -> list[str]:
    """
    Полное удаление установленного zapret. Возвращает список файлов/папок,
    которые удалить не удалось (обычно - занятые драйвером WinDivert до
    перезагрузки); пустой список = всё удалено.
    """
    release_locks()
    if not ZAPRET_DIR.exists():
        return []
    shutil.rmtree(ZAPRET_DIR, ignore_errors=True)
    if not ZAPRET_DIR.exists():
        return []
    leftovers = _clear_dir_contents(ZAPRET_DIR)
    try:
        ZAPRET_DIR.rmdir()
        return []
    except OSError:
        return leftovers


def _download_file(url: str, dest: Path, progress_cb: ProgressCB) -> None:
    with requests.get(url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0)) or None
        written = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                written += len(chunk)
                if total:
                    _report(progress_cb, "Скачивание архива...", min(written / total, 1.0))


def _find_extracted_root(extract_dir: Path) -> Path:
    """
    Возвращает папку, в которой реально лежит bin/winws.exe: корень архива,
    либо его вложенная папка (на глубину до 2 уровней).
    """
    candidates = [extract_dir]
    try:
        level1 = [p for p in extract_dir.iterdir() if p.is_dir()]
        candidates += level1
        for d in level1:
            candidates += [p for p in d.iterdir() if p.is_dir()]
    except OSError:
        pass
    for c in candidates:
        if (c / "bin" / "winws.exe").exists():
            return c
    for c in candidates:
        if (c / "bin").exists():
            return c
    return extract_dir


def _backup_user_lists() -> None:
    if not ZAPRET_DIR.exists():
        return
    ensure_dirs()
    for rel in USER_LIST_NAMES:
        src = ZAPRET_DIR / rel
        if src.exists():
            dst = BACKUP_DIR / Path(rel).name
            shutil.copy2(src, dst)


def _restore_user_lists() -> None:
    for rel in USER_LIST_NAMES:
        backup = BACKUP_DIR / Path(rel).name
        if backup.exists():
            dst = ZAPRET_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, dst)


def _service_running() -> bool:
    try:
        from core import service_manager
        return (service_manager.service_belongs_to_install("zapret")
                and service_manager.get_service_status() == "running")
    except Exception:  # noqa: BLE001
        return False


def _start_service() -> bool:
    try:
        from core.service_manager import service_belongs_to_install
        if not service_belongs_to_install("zapret"):
            return False
        result = subprocess.run(
            ["sc", "start", "zapret"],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
        return result.returncode in (0, 1056)
    except Exception:  # noqa: BLE001
        return False


def install_or_update(progress_cb: ProgressCB = None, release: ReleaseInfo | None = None) -> ReleaseInfo:
    """
    Полный цикл: (если release не передан - узнать последний релиз) ->
    скачать -> сохранить пользовательские списки -> заменить папку ->
    вернуть списки. Возвращает ReleaseInfo установленной версии.
    """
    ensure_dirs()
    if release is None:
        _report(progress_cb, "Проверяю последнюю версию...", 0.02)
        release = fetch_latest_release()

    job_dir = Path(tempfile.mkdtemp(prefix="zapret-update-", dir=DOWNLOAD_TMP_DIR))
    zip_path = job_dir / "release.zip"
    extract_dir = job_dir / "extracted"
    extract_dir.mkdir()

    _download_file(release.zip_url, zip_path, progress_cb)

    _report(progress_cb, "Распаковываю архив...", 0.80)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                if not (extract_dir / entry.filename).resolve().is_relative_to(extract_dir.resolve()):
                    raise InstallerError("Архив содержит файл за пределами папки установки.")
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise InstallerError("Скачанный архив повреждён, попробуйте ещё раз.") from exc

    src_root = _find_extracted_root(extract_dir)
    if not (src_root / "bin" / "winws.exe").is_file() or not (src_root / "service.bat").is_file():
        raise InstallerError("В архиве нет обязательных файлов zapret. Старая установка сохранена.")
    for relative in USER_LIST_NAMES:
        source = ZAPRET_DIR / relative
        if source.is_file():
            target = src_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    # Освобождаем файлы: останавливаем winws.exe, службу zapret и драйвер
    # WinDivert. Если этого не сделать, часть старых файлов остаётся занята.
    service_was_running = IS_WINDOWS and _service_running()
    _report(progress_cb, "Останавливаю zapret перед обновлением...", 0.82)
    release_locks()

    # Directory renames are all-or-nothing. Do not merge versions or delete
    # the old files until the new directory has taken its place.
    _report(progress_cb, "Устанавливаю новую версию...", 0.9)
    previous = job_dir / "previous"
    try:
        if ZAPRET_DIR.exists():
            ZAPRET_DIR.rename(previous)
        try:
            src_root.rename(ZAPRET_DIR)
        except OSError:
            if previous.exists() and not ZAPRET_DIR.exists():
                previous.rename(ZAPRET_DIR)
            raise
    except OSError as exc:
        if service_was_running and _winws_path().exists():
            _start_service()
        raise InstallerError(
            "Не удалось заменить установку целиком. Новая версия не применена. "
            f"Предыдущие файлы сохранены в {ZAPRET_DIR if ZAPRET_DIR.exists() else previous}. "
            "Закройте использующие их программы и повторите обновление. " + str(exc)
        ) from exc

    if service_was_running:
        if not _start_service():
            release.warning = "Файлы обновлены, но службу zapret запустить не удалось. Проверьте её состояние на главной странице."

    # уборка временных файлов
    shutil.rmtree(job_dir, ignore_errors=True)

    _report(progress_cb, "Готово", 1.0)
    return release
