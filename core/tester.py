"""
Автоподбор стратегии.

Идея простая и прозрачная (в отличие от чёрного ящика test zapret.ps1):
для каждой найденной стратегии по очереди
  1. останавливаем текущий winws.exe,
  2. запускаем стратегию, даём время на инициализацию драйвера,
  3. делаем несколько тестовых HTTP-запросов к Discord и YouTube,
  4. считаем успешные ответы и среднюю задержку,
после чего сортируем стратегии по числу успехов и задержке.

Тестовые запросы идут через `requests`, с своим DNS/сокетами (не через
системный прокси), поэтому результат отражает именно то, что видит
обычное приложение на этой машине.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from core.process_manager import start_strategy, stop_all, ProcessManagerError
from core.strategies import Strategy

# Каждая проверка: (человекочитаемое имя, URL, ожидаемые коды ответа)
CHECKS: list[tuple[str, str, tuple[int, ...]]] = [
    ("Discord API", "https://discord.com/api/v9/gateway", (200,)),
    ("YouTube", "https://www.youtube.com/generate_204", (204,)),
    ("Discord CDN", "https://cdn.discordapp.com/", (200, 404)),
]

REQUEST_TIMEOUT = 5.0
WARMUP_SECONDS = 2.5  # время на инициализацию winws.exe/драйвера после запуска

ProgressCB = Optional[Callable[[str, int, int], None]]  # (текст, текущий шаг, всего шагов)
CancelCB = Optional[Callable[[], bool]]  # вернуть True -> прервать тест


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
    def success_count(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def total_checks(self) -> int:
        return len(self.checks)

    @property
    def avg_latency_ms(self) -> Optional[float]:
        ok_latencies = [c.latency_ms for c in self.checks if c.ok and c.latency_ms is not None]
        if not ok_latencies:
            return None
        return sum(ok_latencies) / len(ok_latencies)

    @property
    def score(self) -> tuple[int, float]:
        """Больше успехов лучше; при равенстве - меньше задержка лучше."""
        latency = self.avg_latency_ms if self.avg_latency_ms is not None else float("inf")
        return (-self.success_count, latency)


def _run_checks() -> list[CheckResult]:
    results = []
    session = requests.Session()
    for name, url, expected_codes in CHECKS:
        start = time.perf_counter()
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            elapsed_ms = (time.perf_counter() - start) * 1000
            ok = resp.status_code in expected_codes
            results.append(CheckResult(name=name, ok=ok, latency_ms=elapsed_ms))
        except requests.RequestException as exc:
            results.append(CheckResult(name=name, ok=False, latency_ms=None, error=str(exc)))
    return results


def run_auto_test(
    strategies: list[Strategy],
    progress_cb: ProgressCB = None,
    cancel_cb: CancelCB = None,
) -> list[StrategyTestResult]:
    """
    Прогоняет все переданные стратегии и возвращает результаты,
    отсортированные от лучшей к худшей. Гарантированно останавливает
    winws.exe в конце (в т.ч. при отмене/ошибке).
    """
    results: list[StrategyTestResult] = []
    total = len(strategies)

    try:
        for i, strategy in enumerate(strategies, start=1):
            if cancel_cb and cancel_cb():
                break

            if progress_cb:
                progress_cb(f"Тестирую: {strategy.name}", i, total)

            try:
                start_strategy(strategy, wait_seconds=WARMUP_SECONDS)
            except ProcessManagerError as exc:
                results.append(
                    StrategyTestResult(
                        strategy=strategy,
                        checks=[CheckResult(name="Запуск", ok=False, latency_ms=None, error=str(exc))],
                    )
                )
                continue

            checks = _run_checks()
            results.append(StrategyTestResult(strategy=strategy, checks=checks))
    finally:
        stop_all()

    results.sort(key=lambda r: r.score)
    return results
