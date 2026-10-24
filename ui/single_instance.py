"""One GUI per data directory; a second launch activates the existing window."""
import hashlib

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from core.paths import APP_DATA_DIR, ensure_dirs


class SingleInstance(QObject):
    activated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        ensure_dirs()
        self.name = "ZapretDrum-" + hashlib.sha256(str(APP_DATA_DIR.resolve()).lower().encode()).hexdigest()[:24]
        self.lock = QLockFile(str(APP_DATA_DIR / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._activate)
        self.error = ""

    def acquire(self) -> bool:
        if not self.lock.tryLock(100):
            socket = QLocalSocket(self)
            socket.connectToServer(self.name)
            if socket.waitForConnected(1500):
                socket.disconnectFromServer()
            else:
                self.error = "ZapretDrum уже запускается или папка данных недоступна. Повторите открытие через несколько секунд."
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.error = "Не удалось создать канал управления приложением: " + self.server.errorString()
            self.lock.unlock()
            return False
        return True

    def _activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
        self.activated.emit()

    def release(self) -> None:
        """Release IPC resources explicitly, before Python/Qt teardown."""
        self.server.close()
        self.lock.unlock()
