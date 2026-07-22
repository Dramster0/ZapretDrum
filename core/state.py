"""
Небольшое персистентное состояние приложения (JSON-файл).

Хранит: установленную версию zapret, последнюю запущенную стратегию,
избранную стратегию, результаты последнего автотеста.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from core.paths import STATE_FILE, ensure_dirs

_lock = threading.Lock()


@dataclass
class AppState:
    installed_version: Optional[str] = None
    last_strategy: Optional[str] = None
    favorite_strategy: Optional[str] = None
    last_test_results: list[dict[str, Any]] = field(default_factory=list)
    autostart_enabled: bool = False
    tg_installed_version: Optional[str] = None
    zapret_conflict_dismissed: bool = False
    tg_conflict_dismissed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_state() -> AppState:
    ensure_dirs()
    if not STATE_FILE.exists():
        return AppState()
    try:
        with _lock:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return AppState(**{**AppState().to_dict(), **data})
    except Exception:
        # Повреждённый файл состояния не должен ронять приложение
        return AppState()


def save_state(state: AppState) -> None:
    ensure_dirs()
    with _lock:
        STATE_FILE.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
