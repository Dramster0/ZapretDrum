"""
Запуск и остановка стратегий zapret.

Каждый bat-файл стратегии сам запускает bin\\winws.exe (через `start /min`),
поэтому нам достаточно:
  - для запуска: выполнить .bat файл (он вернёт управление почти сразу,
    а winws.exe останется работать в фоне свёрнутым);
  - для остановки: завершить winws.exe из папки нашей установки.

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
from core.paths import ZAPRET_DIR
from core.diagnostic_log import logger

WINWS_PROCESS_NAME = "winws.exe"

IS_WINDOWS = sys.platform == "win32"
_launched_strategy: str | None = None
_launched_processes: dict[int, float] = {}


def inspect_processes() -> dict:
    own = {}
    foreign = 0
    unknown = 0
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() != WINWS_PROCESS_NAME:
            continue
        try:
            if Path(proc.exe()).resolve() == (ZAPRET_DIR / "bin/winws.exe").resolve():
                own[proc.pid] = proc.create_time()
            else:
                foreign += 1
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError):
            unknown += 1
    return {"own": own, "foreign": foreign, "unknown": unknown,
            "strategy": _launched_strategy if own and own == _launched_processes else None}


class ProcessManagerError(RuntimeError):
    pass


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise ProcessManagerError(
            "Управление zapret доступно только на Windows "
            "(winws.exe и драйвер WinDivert - компоненты Windows)."
        )


def _is_own_process(proc) -> bool:
    try:
        return ((proc.info.get("name") or "").lower() == WINWS_PROCESS_NAME
                and Path(proc.exe()).resolve() == (ZAPRET_DIR / "bin" / "winws.exe").resolve())
    except (psutil.Error, OSError):
        return False


def is_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if _is_own_process(proc):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def running_pids() -> list[int]:
    pids = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if _is_own_process(proc):
                pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def stop_all(timeout: float = 5.0) -> None:
    """Останавливает только winws.exe из нашей папки установки."""
    _require_windows()
    global _launched_strategy, _launched_processes

    procs = []
    for proc in psutil.process_iter(["name"]):
        try:
            if _is_own_process(proc):
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


    _, remaining = psutil.wait_procs(alive, timeout=timeout)
    if remaining:
        raise ProcessManagerError("Не удалось остановить свою копию winws.exe. Проверьте права администратора.")
    _launched_strategy, _launched_processes = None, {}
    logger.info("Собственные процессы winws остановлены")


def start_strategy(strategy: Strategy, wait_seconds: float = 2.5) -> None:
    """
    Запускает .bat стратегии. Предварительно останавливает уже запущенный
    winws.exe, чтобы стратегии не накладывались друг на друга.
    """
    _require_windows()
    global _launched_strategy, _launched_processes

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
    deadline = time.monotonic() + 5
    observed = inspect_processes()
    while not observed["own"] and time.monotonic() < deadline:
        time.sleep(0.1)
        observed = inspect_processes()
    if not observed["own"]:
        raise ProcessManagerError("Стратегия запущена, но работающий winws.exe не найден. Откройте диагностику и проверьте конфликты.")
    _launched_strategy, _launched_processes = strategy.file_name, observed["own"]
    logger.info("Запущена стратегия %s, подтверждено процессов: %s", strategy.file_name, len(observed["own"]))
