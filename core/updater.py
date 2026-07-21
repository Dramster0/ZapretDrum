"""
Проверка наличия обновлений zapret (без скачивания - только сравнение версий).
Само скачивание/установка делает core.installer.install_or_update().
"""
from __future__ import annotations

from dataclasses import dataclass

from core.installer import fetch_latest_release, InstallerError, ReleaseInfo
from core.state import load_state


@dataclass
class UpdateCheckResult:
    installed_version: str | None
    latest: ReleaseInfo | None
    update_available: bool
    error: str | None = None


def check_for_updates() -> UpdateCheckResult:
    state = load_state()
    try:
        latest = fetch_latest_release()
    except InstallerError as exc:
        return UpdateCheckResult(
            installed_version=state.installed_version,
            latest=None,
            update_available=False,
            error=str(exc),
        )

    update_available = state.installed_version != latest.tag_name
    return UpdateCheckResult(
        installed_version=state.installed_version,
        latest=latest,
        update_available=update_available,
    )
