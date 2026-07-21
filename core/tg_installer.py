"""
Установка и обновление tg-ws-proxy (Flowseal/tg-ws-proxy) из GitHub Releases.

В отличие от zapret-discord-youtube, tg-ws-proxy распространяется одним
exe-файлом (не zip-архивом), поэтому логика значительно проще: скачиваем
подходящий ассет и кладём его в TG_DIR под фиксированным именем.

Папку `TgWsProxy_data` (настройки, секрет прокси, логи), которую сама
программа создаёт рядом с собой в режиме --portable, мы никогда не трогаем -
поэтому, в отличие от zapret, отдельный бэкап/восстановление пользовательских
настроек при обновлении не требуется: они просто остаются на месте.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from core import tg_manager
from core.paths import (
    TG_DIR,
    TG_EXE_PATH,
    TG_EXE_NAME,
    DOWNLOAD_TMP_DIR,
    TG_GITHUB_API_LATEST_RELEASE,
    TG_GITHUB_API_ALL_RELEASES,
    ensure_dirs,
)

ProgressCB = Optional[Callable[[str, float], None]]  # (сообщение, доля 0..1)


class TgInstallerError(RuntimeError):
    pass


@dataclass
class TgReleaseInfo:
    tag_name: str
    exe_url: str
    exe_name: str
    published_at: str
    notes: str


def _report(cb: ProgressCB, msg: str, frac: float) -> None:
    if cb:
        cb(msg, frac)


def _github_headers() -> dict:
    return {"User-Agent": "ZapretDrum", "Accept": "application/vnd.github+json"}


def _pick_asset(assets: list[dict]) -> dict | None:
    """
    tg-ws-proxy публикует несколько Windows-сборок (обычная, Windows 7
    x32/x64, иногда ARM64). Нам нужна обычная (Windows 10+), как самая
    массовая и без ограничений по функциональности.
    """
    exact = next((a for a in assets if a.get("name") == TG_EXE_NAME), None)
    if exact is not None:
        return exact

    fallback = [
        a
        for a in assets
        if a.get("name", "").lower().endswith(".exe")
        and "windows" in a["name"].lower()
        and "_7_" not in a["name"].lower()
        and "arm" not in a["name"].lower()
    ]
    return fallback[0] if fallback else None


def _parse_release(data: dict) -> TgReleaseInfo | None:
    asset = _pick_asset(data.get("assets", []))
    if asset is None:
        return None
    return TgReleaseInfo(
        tag_name=data.get("tag_name", "unknown"),
        exe_url=asset["browser_download_url"],
        exe_name=asset["name"],
        published_at=data.get("published_at", ""),
        notes=data.get("body", "") or "",
    )


def fetch_latest_release() -> TgReleaseInfo:
    try:
        resp = requests.get(TG_GITHUB_API_LATEST_RELEASE, headers=_github_headers(), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TgInstallerError(f"Не удалось связаться с GitHub API: {exc}") from exc

    release = _parse_release(resp.json())
    if release is None:
        raise TgInstallerError(
            "В последнем релизе tg-ws-proxy не найден подходящий .exe для Windows."
        )
    return release


def fetch_all_releases(limit: int = 30) -> list[TgReleaseInfo]:
    try:
        resp = requests.get(
            TG_GITHUB_API_ALL_RELEASES,
            headers=_github_headers(),
            params={"per_page": min(limit, 100)},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TgInstallerError(f"Не удалось связаться с GitHub API: {exc}") from exc

    releases = []
    for item in resp.json():
        release = _parse_release(item)
        if release is not None:
            releases.append(release)
    return releases


def is_installed() -> bool:
    return TG_EXE_PATH.exists()


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
                    _report(progress_cb, "Скачивание tg-ws-proxy...", min(written / total, 1.0))


def install_or_update(
    progress_cb: ProgressCB = None, release: TgReleaseInfo | None = None
) -> TgReleaseInfo:
    """
    (если release не передан - узнать последний релиз) -> скачать во
    временный файл -> остановить работающий процесс (Windows не даст
    перезаписать запущенный exe) -> заменить файл -> при необходимости
    запустить снова. Возвращает TgReleaseInfo установленной версии.
    """
    ensure_dirs()
    if release is None:
        _report(progress_cb, "Проверяю последнюю версию tg-ws-proxy...", 0.02)
        release = fetch_latest_release()

    was_running = tg_manager.is_running()
    if was_running:
        _report(progress_cb, "Останавливаю tg-ws-proxy перед обновлением...", 0.05)
        tg_manager.stop()

    tmp_path = DOWNLOAD_TMP_DIR / release.exe_name
    _download_file(release.exe_url, tmp_path, progress_cb)

    _report(progress_cb, "Устанавливаю...", 0.95)
    TG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_path), str(TG_EXE_PATH))

    if was_running:
        _report(progress_cb, "Запускаю tg-ws-proxy снова...", 0.98)
        tg_manager.start()

    _report(progress_cb, "Готово", 1.0)
    return release
