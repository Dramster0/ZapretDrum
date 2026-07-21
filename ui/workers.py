from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from core import process_manager
from core import service_manager
from core import app_updater
from core import tg_manager
from core import tg_installer
from core.installer import install_or_update, fetch_all_releases, InstallerError, ReleaseInfo
from core.strategies import Strategy
from core.tester import run_auto_test, StrategyTestResult


class InstallWorker(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(object)   # ReleaseInfo
    finished_error = pyqtSignal(str)

    def __init__(self, release: ReleaseInfo | None = None):
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            release: ReleaseInfo = install_or_update(
                progress_cb=lambda msg, frac: self.progress.emit(msg, frac),
                release=self.release,
            )
            self.finished_ok.emit(release)
        except InstallerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - показать пользователю любую ошибку
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class FetchReleasesWorker(QThread):
    finished_ok = pyqtSignal(list)   # list[ReleaseInfo]
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            releases = fetch_all_releases(limit=30)
            self.finished_ok.emit(releases)
        except InstallerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class StartStrategyWorker(QThread):
    finished_ok = pyqtSignal(str)      # file_name запущенной стратегии
    finished_error = pyqtSignal(str)

    def __init__(self, strategy: Strategy):
        super().__init__()
        self.strategy = strategy

    def run(self) -> None:
        try:
            process_manager.start_strategy(self.strategy)
            self.finished_ok.emit(self.strategy.file_name)
        except process_manager.ProcessManagerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class StopWorker(QThread):
    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            process_manager.stop_all()
            self.finished_ok.emit()
        except process_manager.ProcessManagerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class AutoTestWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(list)     # list[StrategyTestResult]
    finished_error = pyqtSignal(str)

    def __init__(self, strategies: list[Strategy]):
        super().__init__()
        self.strategies = strategies
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            results: list[StrategyTestResult] = run_auto_test(
                self.strategies,
                progress_cb=lambda msg, i, total: self.progress.emit(msg, i, total),
                cancel_cb=lambda: self._cancelled,
            )
            self.finished_ok.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка автотеста: {exc}")


class InstallServiceWorker(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(bool, str)   # (success, full_log)
    finished_error = pyqtSignal(str)

    def __init__(self, strategy: Strategy):
        super().__init__()
        self.strategy = strategy

    def run(self) -> None:
        try:
            success, full_log = service_manager.install_as_service(
                self.strategy, log_cb=lambda msg: self.log.emit(msg)
            )
            self.finished_ok.emit(success, full_log)
        except service_manager.ServiceError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class RemoveServiceWorker(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(bool, str)
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            success, full_log = service_manager.remove_service(
                log_cb=lambda msg: self.log.emit(msg)
            )
            self.finished_ok.emit(success, full_log)
        except service_manager.ServiceError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class CheckAppUpdateWorker(QThread):
    finished_ok = pyqtSignal(object)   # AppReleaseInfo | None
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            release = app_updater.check_for_app_update()
            self.finished_ok.emit(release)
        except app_updater.AppUpdateError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class DownloadAppUpdateWorker(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def __init__(self, release):
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            app_updater.download_and_launch_update(
                self.release,
                progress_cb=lambda msg, frac: self.progress.emit(msg, frac),
            )
            self.finished_ok.emit()
        except app_updater.AppUpdateError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class TgInstallWorker(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(object)   # TgReleaseInfo
    finished_error = pyqtSignal(str)

    def __init__(self, release=None):
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            release = tg_installer.install_or_update(
                progress_cb=lambda msg, frac: self.progress.emit(msg, frac),
                release=self.release,
            )
            self.finished_ok.emit(release)
        except tg_installer.TgInstallerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class TgFetchReleasesWorker(QThread):
    finished_ok = pyqtSignal(list)   # list[TgReleaseInfo]
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            releases = tg_installer.fetch_all_releases(limit=30)
            self.finished_ok.emit(releases)
        except tg_installer.TgInstallerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class TgStartWorker(QThread):
    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            tg_manager.start()
            self.finished_ok.emit()
        except tg_manager.TgManagerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class TgStopWorker(QThread):
    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            tg_manager.stop()
            self.finished_ok.emit()
        except tg_manager.TgManagerError as exc:
            self.finished_error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")


class FetchChangelogWorker(QThread):
    finished_ok = pyqtSignal(list)   # list[ChangelogEntry]
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            entries = app_updater.fetch_changelog()
            self.finished_ok.emit(entries)
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(f"Непредвиденная ошибка: {exc}")
