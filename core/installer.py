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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

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


def is_installed() -> bool:
    return (ZAPRET_DIR / "bin" / "winws.exe").exists()


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
    Архив с GitHub обычно распаковывается либо прямо в корень
    (bin/, lists/, general.bat, ...), либо в одну вложенную папку.
    Возвращаем папку, где реально лежит bin/winws.exe.
    """
    if (extract_dir / "bin").exists():
        return extract_dir
    children = [p for p in extract_dir.iterdir() if p.is_dir()]
    for child in children:
        if (child / "bin").exists():
            return child
    # fallback: если структура нестандартная - берём как есть
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

    zip_path = DOWNLOAD_TMP_DIR / release.zip_name
    extract_dir = DOWNLOAD_TMP_DIR / "extracted"

    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    _download_file(release.zip_url, zip_path, progress_cb)

    _report(progress_cb, "Сохраняю ваши пользовательские списки доменов...", 0.75)
    _backup_user_lists()

    _report(progress_cb, "Распаковываю архив...", 0.80)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise InstallerError("Скачанный архив повреждён, попробуйте ещё раз.") from exc

    src_root = _find_extracted_root(extract_dir)

    _report(progress_cb, "Устанавливаю новую версию...", 0.9)
    if ZAPRET_DIR.exists():
        shutil.rmtree(ZAPRET_DIR, ignore_errors=True)
    shutil.move(str(src_root), str(ZAPRET_DIR))

    _restore_user_lists()

    # уборка временных файлов
    shutil.rmtree(extract_dir, ignore_errors=True)
    zip_path.unlink(missing_ok=True)

    _report(progress_cb, "Готово", 1.0)
    return release
