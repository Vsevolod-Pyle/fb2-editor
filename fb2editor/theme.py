"""Colours, stylesheet and icons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

LIGHT = {
    "window": "#f3f4f7",
    "surface": "#ffffff",
    "paper": "#fffdf9",
    "paper_text": "#1d1f24",
    "text": "#1f2328",
    "muted": "#6b7280",
    "border": "#e3e5ea",
    "hover": "#eceef3",
    "pressed": "#e1e4ec",
    "accent": "#4f63e8",
    "accent_text": "#ffffff",
    "accent_soft": "#e7eafd",
    "selection": "#c9d1fb",
    "danger": "#d64545",
    "dirty": "#e8a23a",
}

DARK = {
    "window": "#16171b",
    "surface": "#1e1f24",
    "paper": "#1a1b1f",
    "paper_text": "#dcdde1",
    "text": "#e4e5e9",
    "muted": "#9497a1",
    "border": "#2b2d34",
    "hover": "#2a2c33",
    "pressed": "#33363e",
    "accent": "#7f8cff",
    "accent_text": "#10121a",
    "accent_soft": "#272b45",
    "selection": "#3a4380",
    "danger": "#ff6b6b",
    "dirty": "#f0b450",
}

# Glyphs of the Windows icon fonts (Segoe Fluent Icons / Segoe MDL2 Assets)
# with a plain-text fallback for other systems.
GLYPHS = {
    "menu": ("", "≡"),
    "undo": ("", "↶"),
    "redo": ("", "↷"),
    "save": ("", "⤓"),
    "save_version": ("", "⧉"),
    "image": ("", "▣"),
    "find": ("", "⌕"),
    "zoom_in": ("", "+"),
    "zoom_out": ("", "−"),
    "sync": ("", "⇅"),
    "theme": ("", "◐"),
    "add": ("", "+"),
    "more": ("", "⋯"),
    "close": ("", "✕"),
    "open": ("", "↥"),
    "book": ("", "❏"),
    "clear": ("", "⌫"),
    "up": ("", "↑"),
    "down": ("", "↓"),
}

_icon_font: str | None = None


def icon_font() -> str | None:
    global _icon_font
    if _icon_font is None:
        fams = set(QFontDatabase.families())
        _icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _icon_font or None


def _canvas(size=40):
    ratio = 2.0
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def glyph_icon(name: str, color: str, size=40) -> QIcon:
    glyph, fallback = GLYPHS[name]
    fam = icon_font()
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(QColor(color))
    if fam:
        f = QFont(fam)
        f.setPixelSize(int(size * 0.48))
        text = glyph
    else:
        f = QFont()
        f.setPixelSize(int(size * 0.7))
        text = fallback
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return QIcon(pm)


def text_icon(text: str, color: str, *, bold=False, italic=False, strike=False, serif=True,
              underline_color: str | None = None, size=40) -> QIcon:
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont("Georgia" if serif else "Segoe UI")
    f.setPixelSize(int(size * 0.6))
    f.setBold(bold)
    f.setItalic(italic)
    f.setStrikeOut(strike)
    p.setFont(f)
    p.setPen(QColor(color))
    rect = QRectF(0, -size * 0.04, size, size)
    if underline_color:
        rect = QRectF(0, -size * 0.1, size, size)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    if underline_color:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(underline_color))
        p.drawRoundedRect(QRectF(size * 0.24, size * 0.72, size * 0.52, size * 0.11), 2, 2)
    p.end()
    return QIcon(pm)


def script_icon(sup: bool, color: str, size=40) -> QIcon:
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(color))
    f = QFont("Georgia")
    f.setPixelSize(int(size * 0.46))
    p.setFont(f)
    p.drawText(QRectF(size * 0.12, 0, size * 0.5, size), Qt.AlignmentFlag.AlignCenter, "x")
    f.setPixelSize(int(size * 0.28))
    p.setFont(f)
    y = size * 0.12 if sup else size * 0.48
    p.drawText(QRectF(size * 0.52, y, size * 0.36, size * 0.4), Qt.AlignmentFlag.AlignCenter, "2")
    p.end()
    return QIcon(pm)


def swatch_icon(color: str | None, border: str, size=20) -> QIcon:
    pm = _canvas(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(border), 1))
    if color:
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
        p.setPen(QPen(QColor("#d64545"), 1.6))
        p.drawLine(QPointF(5, size - 5), QPointF(size - 5, 5))
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4f63e8"))
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(s * 0.17, s * 0.22, s * 0.3, s * 0.56), s * 0.05, s * 0.05)
        p.setBrush(QColor("#c9d1fb"))
        p.drawRoundedRect(QRectF(s * 0.53, s * 0.22, s * 0.3, s * 0.56), s * 0.05, s * 0.05)
        p.end()
        icon.addPixmap(pm)
    return icon


def apply_palette(app: QApplication, c: dict):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["hover"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(c["accent_text"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    pal.setColor(QPalette.ColorRole.Link, QColor(c["accent"]))
    app.setPalette(pal)


def stylesheet(c: dict) -> str:
    return f"""
* {{ outline: none; }}
QMainWindow, QDialog {{ background: {c['window']}; }}
QWidget {{ color: {c['text']}; font-size: 10pt; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
            padding: 6px 8px; border-radius: 6px; }}

#topBar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
#sidebar {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}
#sidebarTitle {{ font-size: 11pt; font-weight: 600; }}
#muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
#sep {{ background: {c['border']}; min-width: 1px; max-width: 1px; margin: 8px 4px; }}

QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:pressed {{ background: {c['pressed']}; }}
QToolButton:checked {{ background: {c['accent_soft']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[popupMode="1"] {{ padding-right: 14px; }}
QToolButton::menu-button {{ border: none; width: 12px; border-radius: 6px; }}
QToolButton::menu-arrow {{ width: 8px; height: 8px; }}
QToolButton#textButton {{ padding: 5px 10px; font-weight: 500; }}

QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
               padding: 7px 14px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['accent_text']}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {QColor(c['accent']).lighter(108).name()}; }}
QPushButton#danger {{ color: {c['danger']}; }}

QLineEdit, QComboBox, QSpinBox, QFontComboBox {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
    selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; padding: 4px; outline: none; }}
QComboBox#flat {{ border: 1px solid transparent; background: transparent; }}
QComboBox#flat:hover {{ background: {c['hover']}; }}

QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['hover']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 8px; padding: 0px; margin: 1px 6px; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}

#pane {{ background: {c['paper']}; }}
#paneHeader {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
#badge {{ background: {c['accent_soft']}; color: {c['accent']}; border-radius: 6px; padding: 2px 8px;
          font-weight: 700; font-size: 9pt; }}
#paneTitle {{ font-weight: 600; }}
#progress {{ color: {c['muted']}; font-size: 9pt; padding: 0 4px; }}
#dirty {{ color: {c['dirty']}; font-size: 13pt; }}
QTextEdit#bookEditor {{ background: {c['paper']}; color: {c['paper_text']}; border: none;
    selection-background-color: {c['selection']}; selection-color: {c['paper_text']}; }}

#findBar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
#welcome {{ background: {c['window']}; }}
#welcomeTitle {{ font-size: 22pt; font-weight: 700; }}
#welcomeText {{ color: {c['muted']}; font-size: 11pt; }}
#emptyPane {{ background: {c['paper']}; }}

#middleBar {{ background: {c['surface']}; }}
QScrollBar#middleScroll {{ background: transparent; width: 18px; margin: 0; }}
QScrollBar#middleScroll::handle:vertical {{ background: {c['accent_soft']}; border: 1px solid {c['accent']};
    border-radius: 6px; min-height: 40px; margin: 0 3px; }}
QScrollBar#middleScroll::handle:vertical:hover {{ background: {c['accent']}; }}
#notePopup {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
#noteTitle {{ font-weight: 700; color: {c['accent']}; }}
#noteText {{ color: {c['text']}; }}
QSplitter::handle {{ background: {c['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QStatusBar QLabel {{ color: {c['muted']}; padding: 0 8px; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 4px; min-width: 36px; margin: 2px 0; }}

QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['border']};
    background: {c['surface']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
"""


ICON_SIZE = QSize(20, 20)
