"""
Запуск и остановка стратегий zapret.

Каждый bat-файл стратегии сам запускает bin\\winws.exe (через `start /min`),
поэтому нам достаточно:
  - для запуска: выполнить .bat файл (он вернёт управление почти сразу,
    а winws.exe останется работать в фоне свёрнутым);
  - для остановки: найти и завершить все процессы winws.exe.

Модуль работает только на Windows; на других ОС вызовы - no-op с понятной
ошибкой, чтобы GUI можно было хотя бы открыть и посмотреть на Linux/mac
при разработке.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil

from core.strategies import Strategy

WINWS_PROCESS_NAME = "winws.exe"

IS_WINDOWS = sys.platform == "win32"


class ProcessManagerError(RuntimeError):
    pass


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise ProcessManagerError(
            "Управление zapret доступно только на Windows "
            "(winws.exe и драйвер WinDivert - компоненты Windows)."
        )


def is_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == WINWS_PROCESS_NAME:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def running_pids() -> list[int]:
    pids = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info["name"] or "").lower() == WINWS_PROCESS_NAME:
                pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def stop_all(timeout: float = 5.0) -> None:
    """Останавливает все запущенные winws.exe (мягко, потом принудительно)."""
    _require_windows()

    procs = []
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == WINWS_PROCESS_NAME:
                procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for proc in procs:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def start_strategy(strategy: Strategy, wait_seconds: float = 0.0) -> None:
    """
    Запускает .bat стратегии. Предварительно останавливает уже запущенный
    winws.exe, чтобы стратегии не накладывались друг на друга.
    """
    _require_windows()

    if not strategy.path.exists():
        raise ProcessManagerError(f"Файл стратегии не найден: {strategy.path}")

    if is_running():
        stop_all()

    creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    subprocess.Popen(
        ["cmd.exe", "/c", str(strategy.path)],
        cwd=str(strategy.path.parent),
        creationflags=creationflags,
    )

    if wait_seconds > 0:
        time.sleep(wait_seconds)
