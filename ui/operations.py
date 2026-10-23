"""Serialize UI actions and keep worker threads alive until they finish."""
from functools import wraps
from inspect import signature

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QMessageBox


def exclusive_action(method):
    accepts_arguments = len(signature(method).parameters) > 1
    @wraps(method)
    def guarded(self, *args, **kwargs):
        window = getattr(self, "main_window", self)
        operations = window.operations
        if operations.active:
            return
        operations.active = True
        operations.in_callback = True
        window.set_operation_enabled(False, self)
        try:
            # clicked(bool) can reach the variadic wrapper even when the
            # original slot takes no arguments.
            return method(self, *(args if accepts_arguments else ()), **kwargs)
        except Exception as exc:
            QMessageBox.warning(window, "Не удалось выполнить действие", str(exc))
        finally:
            operations.in_callback = False
            operations.finish_if_idle()
    return guarded


class Operations(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.in_callback = False
        self.workers = set()
        self.after_finish = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.finish_if_idle)

    def start(self, worker):
        self.workers.add(worker)
        worker.finished.connect(lambda: self._worker_finished(worker))
        try:
            worker.start()
        except Exception:
            self.workers.discard(worker)
            raise
        self.timer.start()

    def _worker_finished(self, worker):
        self.workers.discard(worker)
        QTimer.singleShot(0, self.finish_if_idle)

    def finish_if_idle(self):
        # The result signal is delivered before finished; defer unlocking until
        # the thread and any modal result dialog have both finished.
        if self.in_callback or self.window.has_modal_dialog():
            self.timer.start()
            return
        if self.workers:
            return
        self.timer.stop()
        if self.active:
            self.active = False
            self.window.set_operation_enabled(True)
            self.window.set_busy(False)
        self.window.finish_pending_exit()
        if self.after_finish and not self.window._exit_requested:
            callback, self.after_finish = self.after_finish, None
            QTimer.singleShot(0, callback)

    def defer(self, callback):
        self.after_finish = callback
