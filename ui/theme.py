"""Тёмная тема приложения (QSS) + палитра цветов — в духе ArnUnlock."""

ACCENT = "#e0203f"
ACCENT_HOVER = "#c81636"
ACCENT_SOFT = "rgba(224, 32, 63, 0.14)"
BG = "#0a0a0d"
BG_ELEVATED = "#151519"
BG_CARD = "#18181d"
BG_ROW = "#1d1d22"
BORDER = "#28282f"
TEXT_PRIMARY = "#f2f2f5"
TEXT_SECONDARY = "#8b8b95"
SUCCESS = "#3ba55d"
DANGER = "#ed4245"
WARNING = "#faa61a"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    color: {TEXT_PRIMARY};
}}

QMainWindow, QWidget#root {{
    background-color: {BG};
    border-radius: 12px;
}}
QWidget#root[zdMaximized="true"] {{
    border-radius: 0px;
}}

QDialog {{
    background-color: {BG};
}}

QWidget#dialogRoot {{
    background-color: {BG};
    border-radius: 12px;
}}

QWidget#titleBar {{
    background-color: {BG};
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QLabel#titleBarLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}
QPushButton#titleBarButton {{
    background: transparent;
    border: none;
    color: {TEXT_SECONDARY};
    font-size: 14px;
}}
QPushButton#titleBarButton:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
}}
QPushButton#titleBarCloseButton {{
    background: transparent;
    border: none;
    color: {TEXT_SECONDARY};
    font-size: 15px;
    border-top-right-radius: 12px;
}}
QPushButton#titleBarCloseButton:hover {{
    background-color: {DANGER};
    color: white;
}}

QWidget#sidebar {{
    background-color: {BG};
    border-right: 1px solid {BORDER};
}}

QLabel#brand {{
    font-size: 15px;
    font-weight: 700;
    padding: 4px;
}}

QLineEdit {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 18px;
}}
QPushButton:hover {{
    background-color: {BG_ROW};
}}

QPushButton#navIcon {{
    background: transparent;
    border: none;
    border-radius: 12px;
    font-size: 18px;
    padding: 12px;
    color: {TEXT_SECONDARY};
}}
QPushButton#navIcon:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
}}
QPushButton#navIcon:checked {{
    background-color: {ACCENT_SOFT};
    color: {ACCENT};
}}

QPushButton#navButton {{
    text-align: left;
    padding: 11px 14px;
    border: none;
    border-radius: 10px;
    background: transparent;
    font-size: 13px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}
QPushButton#navButton:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
}}
QPushButton#navButton:checked {{
    background-color: {ACCENT};
    color: white;
}}

QWidget#card {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}

QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 700;
}}

QLabel#pageSubtitle {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

QLabel#sectionLabel {{
    font-size: 11px;
    font-weight: 700;
    color: {TEXT_SECONDARY};
    letter-spacing: 1px;
}}

QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 12px 22px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primaryButton:disabled {{ background-color: #2c2c33; color: {TEXT_SECONDARY}; }}

QPushButton#dangerButton {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 10px;
    padding: 12px 22px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#dangerButton:hover {{ background-color: rgba(237, 66, 69, 0.12); }}

QPushButton#dangerButtonSmall {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#dangerButtonSmall:hover {{ background-color: rgba(237, 66, 69, 0.12); }}

QPushButton#secondaryButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#secondaryButton:hover {{ background-color: {BG_ROW}; }}
QPushButton#secondaryButton:disabled {{ color: {TEXT_SECONDARY}; }}
QPushButton#secondaryButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: white;
}}

QWidget#strategyRow {{
    background-color: {BG_ROW};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QWidget#strategyRowActive {{
    background-color: rgba(224, 32, 63, 0.18);
    border: 2px solid {ACCENT};
    border-radius: 10px;
}}

QLabel#avatar {{
    border-radius: 18px;
    color: white;
    font-weight: 700;
    font-size: 12px;
}}

QProgressBar {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 8px;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QTextEdit#logView {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    color: {TEXT_SECONDARY};
    padding: 10px;
}}

QTextEdit#changelogView {{
    background-color: transparent;
    border: none;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}

QPushButton#sidebarFooterLink {{
    background: transparent;
    border: none;
    text-align: left;
    color: {TEXT_SECONDARY};
    font-size: 13px;
    font-weight: 600;
    padding: 3px 8px;
}}
QPushButton#sidebarFooterLink:hover {{
    color: {TEXT_PRIMARY};
    text-decoration: underline;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: transparent;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background: transparent;
    border: none;
}}
"""
