"""
Самообновление ZapretDrum (не путать с core.installer, который обновляет
zapret - внешний инструмент).

Идея: у вас есть свой GitHub-репозиторий (APPUPDATE_GITHUB_OWNER/REPO в
core/paths.py), куда GitHub Actions автоматически публикует
ZapretDrum-Setup.exe при каждом новом теге версии (см.
.github/workflows/release.yml). Приложение проверяет там последний релиз,
и если версия новее текущей - предлагает скачать и поставить обновление
одной кнопкой, без похода в браузер.

Технически: скачивается Setup.exe, затем отдельный помощник дожидается
закрытия приложения и запускает установщик в тихом режиме (/VERYSILENT).
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from core.app_version import get_app_version, is_newer
from core.paths import (
    APPUPDATE_API_LATEST_RELEASE,
    APPUPDATE_API_ALL_RELEASES,
    DOWNLOAD_TMP_DIR,
    ensure_dirs,
)

IS_WINDOWS = sys.platform == "win32"

ProgressCB = Optional[Callable[[str, float], None]]


class AppUpdateError(RuntimeError):
    pass


@dataclass
class AppReleaseInfo:
    tag_name: str
    version: str            # tag_name без ведущей 'v'
    setup_url: str
    setup_name: str
    notes: str
    published_at: str = ""


def _headers() -> dict:
    return {"User-Agent": "ZapretDrum", "Accept": "application/vnd.github+json"}


@dataclass
class ChangelogEntry:
    version: str
    published_at: str   # ISO-строка вида '2026-07-04T18:48:00Z'
    notes: str


def fetch_changelog(limit: int = 15) -> list[ChangelogEntry]:
    """
    Список последних релизов ZapretDrum (версия + дата + текст релиза) -
    для окна "Что нового?". Не бросает исключение при сетевой ошибке -
    просто возвращает пустой список, чтобы окно могло показать
    заглушку вместо падения.
    """
    try:
        resp = requests.get(
            APPUPDATE_API_ALL_RELEASES,
            headers=_headers(),
            params={"per_page": min(limit, 100)},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    entries = []
    for item in resp.json():
        entries.append(
            ChangelogEntry(
                version=item.get("tag_name", "").lstrip("vV") or "?",
                published_at=item.get("published_at", "") or "",
                notes=(item.get("body", "") or "").strip(),
            )
        )
    return entries


def check_for_app_update() -> AppReleaseInfo | None:
    """
    Возвращает информацию о новом релизе ZapretDrum, если он новее текущей
    версии, иначе None. Бросает AppUpdateError при сетевых проблемах.
    """
    try:
        resp = requests.get(APPUPDATE_API_LATEST_RELEASE, headers=_headers(), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AppUpdateError(f"Не удалось проверить обновления ZapretDrum: {exc}") from exc

    data = resp.json()
    assets = data.get("assets", [])
    setup_asset = next(
        (a for a in assets if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()),
        None,
    )
    if setup_asset is None:
        raise AppUpdateError("В последнем релизе ZapretDrum не найден установщик (.exe).")

    tag_name = data.get("tag_name", "")
    version = tag_name.lstrip("vV")
    current = get_app_version()

    if not is_newer(version, current):
        return None

    return AppReleaseInfo(
        tag_name=tag_name,
        version=version,
        setup_url=setup_asset["browser_download_url"],
        setup_name=setup_asset["name"],
        notes=data.get("body", "") or "",
        published_at=data.get("published_at", "") or "",
    )


def download_update_installer(
    release: AppReleaseInfo, progress_cb: ProgressCB = None
) -> Path:
    """
    Скачивает установщик обновления. Запуск откладывается до закрытия
    приложения, чтобы установщик не пытался заменить работающий .exe.
    """
    if not IS_WINDOWS:
        raise AppUpdateError("Самообновление доступно только на Windows.")

    ensure_dirs()
    setup_path = DOWNLOAD_TMP_DIR / release.setup_name

    def report(msg: str, frac: float) -> None:
        if progress_cb:
            progress_cb(msg, frac)

    report("Скачиваю установщик...", 0.05)
    try:
        with requests.get(release.setup_url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            written = 0
            with open(setup_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written += len(chunk)
                    if total:
                        report("Скачиваю установщик...", min(written / total, 1.0))
    except requests.RequestException as exc:
        raise AppUpdateError(f"Не удалось скачать установщик: {exc}") from exc

    report("Установщик скачан. Подготавливаю обновление...", 1.0)
    return setup_path


def launch_installer_after_app_exit(setup_path: Path) -> None:
    """Запускает скрытый помощник, который дождётся закрытия приложения,
    а затем запустит установщик в тихом режиме."""
    if not IS_WINDOWS:
        raise AppUpdateError("Самообновление доступно только на Windows.")

    helper_path = DOWNLOAD_TMP_DIR / "install_app_update.ps1"
    installer_literal = "'" + str(setup_path).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$parentPid = {os.getpid()}\n"
        f"$installerPath = {installer_literal}\n"
        "while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {\n"
        "    Start-Sleep -Milliseconds 400\n"
        "}\n"
        "Start-Process -FilePath $installerPath -ArgumentList "
        "@('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait\n"
    )
    try:
        helper_path.write_text(script, encoding="utf-8")
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", str(helper_path),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise AppUpdateError(f"Не удалось запустить установку обновления: {exc}") from exc
