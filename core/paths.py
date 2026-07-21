"""
Общие пути и константы приложения.

Всё, что связано с расположением файлов на диске, собрано здесь,
чтобы не размазывать os.getenv(...) по всему проекту.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ZapretDrum"

GITHUB_OWNER = "Flowseal"
GITHUB_REPO = "zapret-discord-youtube"
GITHUB_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
GITHUB_API_ALL_RELEASES = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
)
GITHUB_RELEASES_PAGE = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
)

# --- репозиторий САМОГО ZapretDrum (для самообновления приложения) ---
# ЗАМЕНИТЕ на свой логин/репозиторий после того, как создадите его на GitHub!
APPUPDATE_GITHUB_OWNER = "Dramster0"
APPUPDATE_GITHUB_REPO = "ZapretDrum"
APPUPDATE_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{APPUPDATE_GITHUB_OWNER}/{APPUPDATE_GITHUB_REPO}/releases/latest"
)
APPUPDATE_API_ALL_RELEASES = (
    f"https://api.github.com/repos/{APPUPDATE_GITHUB_OWNER}/{APPUPDATE_GITHUB_REPO}/releases"
)
APPUPDATE_RELEASES_PAGE = (
    f"https://github.com/{APPUPDATE_GITHUB_OWNER}/{APPUPDATE_GITHUB_REPO}/releases"
)

# Куда открывать "Нашли баг?" / "By Dramster"
DEVELOPER_TELEGRAM_URL = "https://t.me/Dramster1"


def _app_data_root() -> Path:
    """%LOCALAPPDATA%/ZapretDrum на Windows, ~/.local/share/ZapretDrum где угодно ещё."""
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


APP_DATA_DIR = _app_data_root()
ZAPRET_DIR = APP_DATA_DIR / "zapret"          # сюда распаковывается сам zapret
DOWNLOAD_TMP_DIR = APP_DATA_DIR / "tmp"        # временные архивы при скачивании
BACKUP_DIR = APP_DATA_DIR / "user_lists_backup"  # бэкап пользовательских списков при обновлении
STATE_FILE = APP_DATA_DIR / "state.json"
LOG_FILE = APP_DATA_DIR / "zapret_gui.log"

# Файлы/папки, которые сохраняем при обновлении (пользовательские правки)
USER_LIST_NAMES = [
    "lists/list-general-user.txt",
    "lists/list-exclude-user.txt",
    "lists/ipset-exclude-user.txt",
]

# Имена bat-файлов, которые НЕ являются стратегиями запуска (утилитарные)
NON_STRATEGY_BAT_HINTS = (
    "service",
    "uninstall",
    "check_update",
    "setup",
    "hosts",
    "status",
)


def ensure_dirs() -> None:
    for d in (APP_DATA_DIR, DOWNLOAD_TMP_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def resource_path(relative: str) -> Path:
    """
    Путь к файлу, упакованному вместе с приложением (например, иконка).
    Работает и при запуске из исходников, и из собранного PyInstaller .exe
    (--add-data кладёт файлы во временную папку sys._MEIPASS).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base / relative
