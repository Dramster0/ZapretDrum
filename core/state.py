"""
Небольшое персистентное состояние приложения (JSON-файл).

Хранит: установленную версию zapret, последнюю запущенную стратегию,
избранную стратегию, результаты последнего автотеста.
"""
from __future__ import annotations

import json
import threading
import math
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from core.paths import STATE_FILE, ensure_dirs
from core.storage import atomic_write
from core.diagnostic_log import logger

_lock = threading.Lock()
STATE_BACKUP = STATE_FILE.with_suffix(".json.bak")
_recovery_notice = ""


@dataclass
class AppState:
    installed_version: Optional[str] = None
    last_strategy: Optional[str] = None
    favorite_strategy: Optional[str] = None
    last_test_results: list[dict[str, Any]] = field(default_factory=list)
    last_test_at: Optional[str] = None
    last_test_version: Optional[str] = None
    last_test_baseline: list[dict[str, Any]] = field(default_factory=list)
    close_to_tray: bool = True
    tray_notifications: bool = True
    show_quick_start: bool = True
    autostart_enabled: bool = False
    tg_installed_version: Optional[str] = None
    zapret_conflict_dismissed: bool = False
    tg_conflict_dismissed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _valid_checks(value) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        latency = item.get("latency_ms")
        if (not isinstance(item.get("name"), str) or type(item.get("ok")) is not bool
                or not (item.get("error") is None or isinstance(item["error"], str))
                or not (latency is None or type(latency) in (int, float) and math.isfinite(latency) and latency >= 0)):
            return False
    return True


def _decode(raw: bytes) -> AppState:
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Настройки должны быть объектом JSON")
    defaults = AppState().to_dict()
    for key, value in data.items():
        if key not in defaults:
            continue  # Allow newer versions to add fields.
        expected = defaults[key]
        if expected is None:
            valid = value is None or isinstance(value, str)
        elif isinstance(expected, bool):
            valid = isinstance(value, bool)
        elif key == "last_test_baseline":
            valid = _valid_checks(value)
        else:
            valid = isinstance(value, list) and all(isinstance(item, dict) for item in value)
            if valid:
                for item in value:
                    latency = item.get("avg_latency_ms")
                    valid = (isinstance(item.get("strategy"), str)
                             and type(item.get("success")) is int and type(item.get("total")) is int
                             and 0 <= item["success"] <= item["total"]
                             and (latency is None or type(latency) in (int, float)
                                  and math.isfinite(latency) and latency >= 0)
                             and ("checks" not in item or _valid_checks(item["checks"])))
                    if not valid:
                        break
        if not valid:
            raise ValueError("Неверный формат настройки: " + key)
        defaults[key] = value
    return AppState(**defaults)


def recovery_notice() -> str:
    return _recovery_notice


def load_state() -> AppState:
    global _recovery_notice
    ensure_dirs()
    with _lock:
        if not STATE_FILE.exists() and not STATE_BACKUP.exists():
            return AppState()
        try:
            return _decode(STATE_FILE.read_bytes())
        except (OSError, ValueError, UnicodeError):
            logger.warning("Основной файл настроек недоступен или повреждён")
        try:
            state = _decode(STATE_BACKUP.read_bytes())
            _recovery_notice = "Настройки восстановлены из резервной копии. Проверьте избранную стратегию."
        except (OSError, ValueError, UnicodeError):
            state = AppState()
            _recovery_notice = "Настройки повреждены; применены значения по умолчанию. Компоненты и списки доменов сохранены."
        try:
            if STATE_FILE.exists():
                damaged_data = STATE_FILE.read_bytes()
                damaged = STATE_FILE.with_name("state.corrupt-" + hashlib.sha256(damaged_data).hexdigest()[:12] + ".json")
                if not damaged.exists():
                    atomic_write(damaged, damaged_data)
            atomic_write(STATE_FILE, json.dumps(state.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            logger.exception("Не удалось сохранить восстановленные настройки")
        logger.warning(_recovery_notice)
        return state


def save_state(state: AppState) -> None:
    ensure_dirs()
    with _lock:
        raw = json.dumps(state.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        _decode(raw)
        try:
            previous = STATE_FILE.read_bytes()
            _decode(previous)
        except (OSError, ValueError, UnicodeError):
            previous = raw
        atomic_write(STATE_BACKUP, previous)
        atomic_write(STATE_FILE, raw)
