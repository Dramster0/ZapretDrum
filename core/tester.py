"""HTTP probes with cooperative cancellation and restoration of the prior state."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional

import requests

from core import process_manager, service_manager
from core.diagnostic_log import logger
from core.strategies import Strategy, find_strategy

CHECKS = [
    ("Discord API", "https://discord.com/api/v9/gateway", (200,)),
    ("YouTube", "https://www.youtube.com/generate_204", (204,)),
    ("Discord CDN", "https://cdn.discordapp.com/", (200, 404)),
]
REQUEST_TIMEOUT = (3.0, 5.0)
WARMUP_SECONDS = 2.5
ProgressCB = Optional[Callable[[str, int, int], None]]
CancelCB = Optional[Callable[[], bool]]


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency_ms: Optional[float]
    error: Optional[str] = None


@dataclass
class StrategyTestResult:
    strategy: Strategy
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def success_count(self):
        return sum(c.ok for c in self.checks)

    @property
    def total_checks(self):
        return len(self.checks)

    @property
    def avg_latency_ms(self):
        values = [c.latency_ms for c in self.checks if c.ok and c.latency_ms is not None]
        return sum(values) / len(values) if values else None

    @property
    def score(self):
        return (-self.success_count, self.avg_latency_ms if self.avg_latency_ms is not None else float("inf"))

    def to_dict(self):
        return {"strategy": self.strategy.file_name, "success": self.success_count,
                "total": self.total_checks, "avg_latency_ms": self.avg_latency_ms,
                "checks": [asdict(check) for check in self.checks]}


@dataclass
class TestRun:
    results: list[StrategyTestResult] = field(default_factory=list)
    baseline: list[CheckResult] = field(default_factory=list)
    completed_at: str = ""
    cancelled: bool = False
    error: str = ""
    restoration: str = ""
    total: int = 0


def _run_checks(cancel_cb: CancelCB = None) -> list[CheckResult]:
    results = []
    with requests.Session() as session:
        session.trust_env = False
        for name, url, expected_codes in CHECKS:
            if cancel_cb and cancel_cb():
                break
            start = time.perf_counter()
            try:
                # Only headers are needed; never download an unbounded response body.
                with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True) as response:
                    elapsed = (time.perf_counter() - start) * 1000
                    ok = response.status_code in expected_codes
                    results.append(CheckResult(name, ok, elapsed, None if ok else f"HTTP {response.status_code}"))
            except requests.RequestException as exc:
                if isinstance(exc, requests.Timeout):
                    reason = "Превышено время ожидания"
                elif isinstance(exc, requests.exceptions.SSLError):
                    reason = "Ошибка защищённого соединения (TLS)"
                else:
                    reason = "Не удалось подключиться"
                results.append(CheckResult(name, False, None, reason))
                logger.info("Автоподбор, %s: %s", name, type(exc).__name__)
    return results


def run_auto_test(strategies: list[Strategy], progress_cb: ProgressCB = None,
                  cancel_cb: CancelCB = None) -> TestRun:
    run = TestRun(total=len(strategies))
    cancelled = lambda: bool(cancel_cb and cancel_cb())
    observed = process_manager.inspect_processes()
    service, service_error = service_manager.get_service_status_details()
    if observed["foreign"] or observed["unknown"]:
        raise RuntimeError("Обнаружен сторонний winws или его путь недоступен. Сначала откройте диагностику.")
    if service == "unknown":
        raise RuntimeError(service_error + " Откройте диагностику.")
    if service not in ("running", "stopped", "not_installed"):
        raise RuntimeError("Служба zapret не готова к проверке (" + service + "). Повторите после её остановки или запуска.")
    if service != "not_installed" and not service_manager.service_belongs_to_install("zapret"):
        raise RuntimeError("Служба zapret принадлежит другой установке. Автоподбор не запущен.")
    previous = find_strategy(observed["strategy"]) if observed["strategy"] else None
    if observed["own"] and service != "running" and previous is None:
        raise RuntimeError("Работающая стратегия не определена. Остановите обход на главной и повторите автоподбор.")
    if cancelled() or not strategies:
        run.cancelled = cancelled()
        return run
    changed = False
    service_touched = False

    def progress(message):
        if progress_cb:
            progress_cb(message, len(run.results), run.total)

    try:
        progress("Подготавливаю проверку без обхода…")
        if service == "running":
            service_touched = True
            service_manager.set_owned_service_running(False)
        changed = True
        process_manager.stop_all()
        if process_manager.is_running():
            raise RuntimeError("winws продолжает работать; сравнение без обхода невозможно.")
        run.baseline = _run_checks(cancel_cb)
        for strategy in strategies:
            if cancelled():
                break
            progress("Проверяю: " + strategy.name)
            try:
                process_manager.start_strategy(strategy, wait_seconds=WARMUP_SECONDS)
            except process_manager.ProcessManagerError as exc:
                if cancelled():
                    break
                run.results.append(StrategyTestResult(strategy, [CheckResult("Запуск", False, None, str(exc))]))
                continue
            if cancelled():
                break
            checks = _run_checks(cancel_cb)
            if len(checks) != len(CHECKS) or cancelled():
                break
            run.results.append(StrategyTestResult(strategy, checks))
        run.cancelled = cancelled()
    except Exception as exc:
        logger.exception("Ошибка автоподбора")
        run.error = str(exc)
    finally:
        progress("Восстанавливаю прежнее состояние…")
        cleanup_errors = []
        if changed:
            try:
                process_manager.stop_all()
            except Exception as exc:
                cleanup_errors.append("Не удалось остановить тестовую стратегию: " + str(exc))
        try:
            if service_touched and not cleanup_errors:
                service_manager.set_owned_service_running(True)
                run.restoration = "Прежняя служба запущена снова."
            elif service_touched:
                cleanup_errors.append("Прежняя служба не запущена: сначала нужно остановить тестовую стратегию.")
            elif changed and previous and not cleanup_errors:
                process_manager.start_strategy(previous)
                run.restoration = "Прежняя стратегия восстановлена: " + previous.name
            elif changed and not cleanup_errors:
                run.restoration = "Обход оставлен выключенным, как до проверки."
        except Exception as exc:
            cleanup_errors.append("Не удалось восстановить прежний обход: " + str(exc))
        if cleanup_errors:
            run.error = "\n".join(filter(None, [run.error, *cleanup_errors]))
            logger.error(run.error)
        run.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    run.results.sort(key=lambda result: result.score)
    return run
