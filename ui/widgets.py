from __future__ import annotations

import hashlib

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QFont, QPen
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QPushButton,
)

from ui.theme import SUCCESS, DANGER, TEXT_SECONDARY, TEXT_PRIMARY, ACCENT, BORDER, BG_ELEVATED

AVATAR_PALETTE = [
    "#e0203f", "#6b5bd6", "#2f9e6f", "#d68a1f",
    "#2f8fd6", "#c94ea3", "#4bb0a0", "#b56bd6",
]


class Card(QFrame):
    """Прямоугольная карточка-контейнер с закруглёнными углами (см. QSS #card)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(10)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class StatusDot(QLabel):
    """Маленький кружок-индикатор: зелёный = запущено, красный = нет."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        color = SUCCESS if active else DANGER
        self.setStyleSheet(f"background-color: {color}; border-radius: 6px;")


def _avatar_color(seed: str) -> str:
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return AVATAR_PALETTE[h % len(AVATAR_PALETTE)]


def _abbreviation(name: str) -> str:
    lower = name.lower()
    if "simple fake" in lower:
        return "SF"
    if "tls" in lower:
        return "TL"
    if "alt" in lower:
        digits = "".join(ch for ch in lower.split("alt", 1)[1] if ch.isdigit())
        return f"A{digits}" if digits else "AL"
    return "GN"


def make_avatar(name: str, size: int = 36) -> QLabel:
    label = QLabel(_abbreviation(name))
    label.setObjectName("avatar")
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    color = _avatar_color(name)
    label.setStyleSheet(
        f"background-color: {color}; border-radius: {size // 2}px; "
        f"color: white; font-weight: 700; font-size: 11px;"
    )
    return label


class StrategyRow(QWidget):
    """Одна строка списка стратегий: аватар, имя/тип и пинг/статус справа."""

    clicked = pyqtSignal(str)  # передаёт file_name стратегии

    def __init__(self, name: str, file_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.file_name = file_name
        self.setObjectName("strategyRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(12)

        layout.addWidget(make_avatar(name))

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.type_label = QLabel("ZAPRET | BAT")
        self.type_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; letter-spacing: 0.5px;")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.type_label)
        layout.addLayout(text_col)

        layout.addStretch(1)

        self.ping_label = QLabel("—")
        self.ping_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self.ping_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.ping_label)

        self._active = False
        self._selected = False

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.clicked.emit(self.file_name)
        super().mousePressEvent(event)

    def set_ping_text(self, text: str, ok: bool | None) -> None:
        color = TEXT_SECONDARY
        if ok is True:
            color = SUCCESS
        elif ok is False:
            color = DANGER
        self.ping_label.setText(text)
        self.ping_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")

    def set_active(self, active: bool) -> None:
        """Стратегия сейчас реально запущена."""
        self._active = active
        self._restyle()

    def set_selected(self, selected: bool) -> None:
        """Стратегия выбрана пользователем (но не обязательно запущена)."""
        self._selected = selected
        self._restyle()

    def _restyle(self) -> None:
        highlighted = self._active or self._selected
        self.setObjectName("strategyRowActive" if highlighted else "strategyRow")
        self.style().unpolish(self)
        self.style().polish(self)
        if self._active:
            self.type_label.setText("● РАБОТАЕТ СЕЙЧАС")
            self.type_label.setStyleSheet(f"color: {SUCCESS}; font-size: 10px; font-weight: 700;")
        else:
            self.type_label.setText("ZAPRET | BAT")
            self.type_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; letter-spacing: 0.5px;")


class PowerButton(QWidget):
    """
    Большая круглая кнопка подключения с тонким кольцом снаружи —
    как на референсе. Рисуется вручную через QPainter.
    """

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(230, 230)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._connected = False
        self._busy = False

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        accent = QColor(ACCENT)
        idle = QColor(BORDER)
        main_color = accent if self._connected else idle

        # внешнее тонкое кольцо
        ring_pen = QPen(main_color if self._connected else QColor(BG_ELEVATED))
        ring_pen.setWidthF(1.5)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer_r = min(w, h) / 2 - 4
        painter.drawEllipse(QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2))

        # внутренний залитый круг
        inner_r = outer_r - 32
        if self._connected:
            painter.setBrush(main_color)
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QColor(BG_ELEVATED))
            border_pen = QPen(QColor(BORDER))
            border_pen.setWidthF(1.5)
            painter.setPen(border_pen)
        painter.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        # иконка питания (символ) - кольцо с разрывом сверху + вертикальная чёрточка в разрыве
        icon_color = QColor("white") if self._connected else QColor(TEXT_SECONDARY)
        icon_pen = QPen(icon_color, 3)
        icon_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(icon_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        icon_r = 15
        icon_cy = cy - 8
        gap_half_deg = 35  # половина разрыва в кольце, по центру сверху (90°)
        start_angle = int((90 + gap_half_deg) * 16)
        span_angle = int((360 - gap_half_deg * 2) * 16)
        painter.drawArc(
            QRectF(cx - icon_r, icon_cy - icon_r, icon_r * 2, icon_r * 2),
            start_angle,
            span_angle,
        )
        painter.drawLine(
            int(cx), int(icon_cy - icon_r - 4),
            int(cx), int(icon_cy - 2),
        )

        # текст статуса
        painter.setPen(icon_color)
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        text = "Подключено" if self._connected else ("Подключение..." if self._busy else "Отключено")
        painter.drawText(
            QRectF(cx - inner_r, icon_cy + icon_r + 10, inner_r * 2, 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            text,
        )


class MainTitleBar(QWidget):
    """
    Кастомный заголовок главного окна взамен системного: иконка, название,
    свернуть/развернуть/закрыть. Перетаскивание окна сделано вручную через
    события мыши (безопасно, чистый Qt, без обращений к нативному API
    Windows).

    Разворачивание на весь экран управляется самим MainWindow вручную
    (через геометрию, а не через showMaximized()/isMaximized()) - у
    безрамочных окон в Windows системное состояние "развёрнуто" после
    сворачивания в трей иногда теряется, и кнопка разворота перестаёт
    работать. Эта кнопка просто просит окно переключиться, ничего не
    решая сама.
    """

    def __init__(self, window: QWidget, title: str, icon_path=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.window_ref = window
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)

        if icon_path is not None:
            icon_label = QLabel()
            from PyQt6.QtGui import QIcon
            icon_label.setPixmap(QIcon(str(icon_path)).pixmap(16, 16))
            layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setObjectName("titleBarLabel")
        layout.addWidget(title_label)
        layout.addStretch(1)

        min_btn = QPushButton("—")
        min_btn.setObjectName("titleBarButton")
        min_btn.setFixedSize(46, 40)
        min_btn.setCursor(Qt.CursorShape.ArrowCursor)
        min_btn.clicked.connect(window.showMinimized)
        layout.addWidget(min_btn)

        self.maximize_btn = QPushButton("☐")
        self.maximize_btn.setObjectName("titleBarButton")
        self.maximize_btn.setFixedSize(46, 40)
        self.maximize_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.maximize_btn.clicked.connect(window.toggle_maximize)
        layout.addWidget(self.maximize_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("titleBarCloseButton")
        close_btn.setFixedSize(46, 40)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn)

    def update_maximize_icon(self, is_maximized: bool) -> None:
        self.maximize_btn.setText("❐" if is_maximized else "☐")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window_ref.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.window_ref.is_custom_maximized:
                return
            self.window_ref.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.window_ref.toggle_maximize()


class ResizeGrip(QWidget):
    """
    Маленький уголок для изменения размера окна мышью в правом нижнем
    углу - тоже чистый Qt (перетаскивание считает дельту и вызывает
    self.window_ref.resize(...)), без нативных вызовов ОС."""

    def __init__(self, window: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.window_ref = window
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._start_mouse = None
        self._start_size = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.window_ref.is_custom_maximized:
            self._start_mouse = event.globalPosition().toPoint()
            self._start_size = self.window_ref.size()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start_mouse is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._start_mouse
            new_w = max(self.window_ref.minimumWidth(), self._start_size.width() + delta.x())
            new_h = max(self.window_ref.minimumHeight(), self._start_size.height() + delta.y())
            self.window_ref.resize(new_w, new_h)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._start_mouse = None


class DialogTitleBar(QWidget):
    """
    Упрощённый заголовок для диалоговых окон: название + закрыть.
    Ресайз тут не нужен, поэтому перетаскивание сделано вручную мышью
    (без нативного WM_NCHITTEST - это надёжно и просто для окна без ресайза).
    """

    def __init__(self, dialog: QWidget, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.dialog_ref = dialog
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("titleBarLabel")
        layout.addWidget(title_label)
        layout.addStretch(1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("titleBarCloseButton")
        close_btn.setFixedSize(46, 40)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.dialog_ref.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.dialog_ref.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None


def nav_icon_button(icon: str, tooltip: str):
    from PyQt6.QtWidgets import QPushButton

    btn = QPushButton(icon)
    btn.setObjectName("navIcon")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setFixedSize(44, 44)
    return btn


def nav_button(icon: str, text: str):
    """Кнопка навигации с иконкой и подписью (для широкого сайдбара)."""
    from PyQt6.QtWidgets import QPushButton

    btn = QPushButton(f"{icon}   {text}")
    btn.setObjectName("navButton")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(42)
    return btn
