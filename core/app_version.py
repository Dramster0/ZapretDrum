"""Текущая версия самого ZapretDrum (не путать с версией zapret)."""
from __future__ import annotations

from core.paths import resource_path

_FALLBACK_VERSION = "0.0.0-dev"


def get_app_version() -> str:
    """
    Версия читается из файла VERSION, который лежит рядом с исходниками
    при разработке и бандлится внутрь .exe через PyInstaller --add-data
    при сборке (см. build_exe.bat). CI (GitHub Actions) перезаписывает
    этот файл значением из git-тега перед сборкой релиза.
    """
    try:
        return resource_path("VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return _FALLBACK_VERSION


def parse_version(v: str) -> tuple:
    """
    '1.2.3' -> (1, 2, 3). Нечисловые куски (например '1.2.3-beta')
    отбрасываются, чтобы сравнение не падало - для наших версий этого
    достаточно, т.к. релизы называются просто X.Y.Z.
    """
    parts = []
    for chunk in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)
