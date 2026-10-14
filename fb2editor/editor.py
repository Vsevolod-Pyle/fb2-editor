"""Rich text editor widget for one side of the book pair."""

from __future__ import annotations

import os
import re

import html

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QKeyEvent,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
)

from .fb2doc import (
    OBJ,
    P_ID,
    P_KIND,
    P_PATH,
    Fb2Book,
    base_char_format,
    block_format,
    block_kind,
    block_path,
    image_format,
    plain_char_format,
)

# Paragraph styles offered in the UI: id -> (label, shortcut)
STYLES = {
    "normal": ("Обычный текст", "Ctrl+Alt+0"),
    "title": ("Заголовок главы", "Ctrl+Alt+1"),
    "subtitle": ("Подзаголовок", "Ctrl+Alt+2"),
    "epigraph": ("Эпиграф", "Ctrl+Alt+3"),
    "cite": ("Цитата", "Ctrl+Alt+4"),
    "poem": ("Стихи", "Ctrl+Alt+5"),
    "author": ("Подпись автора", "Ctrl+Alt+6"),
}

_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _keys(path: str) -> list[str]:
    return [k for k in path.split("/") if k]


def section_path(path: str) -> str:
    """Path of the innermost section (or body) that contains the block."""
    keys = _keys(path)
    while keys and not keys[-1].startswith(("section:", "body:")):
        keys.pop()
    return "/".join(keys)


def style_of_block(block) -> str:
    kind = block_kind(block)
    path = block_path(block)
    if kind == "title":
        return "title"
    if kind == "subtitle":
        return "subtitle"
    if kind in ("text-author", "date"):
        return "author"
    if kind == "v" or "/poem:" in path:
        return "poem"
    if "/epigraph:" in path:
        return "epigraph"
    if "/cite:" in path:
        return "cite"
    return "normal"


class NotePopup(QFrame):
    """Small window with the text of a footnote."""

    def __init__(self, editor: "BookEditor", target: int, title: str, text_html: str):
        super().__init__(editor, Qt.WindowType.Popup)
        self.setObjectName("notePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        head = QLabel(title or "Сноска")
        head.setObjectName("noteTitle")
        body = QLabel(text_html or "<i>Текст сноски пуст</i>")
        body.setObjectName("noteText")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setMaximumWidth(460)
        body.setMinimumWidth(min(460, max(200, len(body.text()) * 4)))
        lay.addWidget(head)
        lay.addWidget(body)
        row = QHBoxLayout()
        row.addStretch(1)
        go = QPushButton("Перейти к сноске")
        go.setToolTip("Ctrl+щелчок по ссылке — сразу перейти; Alt+← — вернуться")
        go.clicked.connect(lambda: (self.close(), editor.jump_to_block(target)))
        row.addWidget(go)
        lay.addLayout(row)

    def show_at(self, pos: QPoint):
        self.adjustSize()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), pos.x() - 30), area.right() - self.width())
        y = pos.y() + 14
        if y + self.height() > area.bottom():
            y = pos.y() - self.height() - 24
        self.move(x, y)
        self.show()


class BookEditor(QTextEdit):
    focused = Signal()
    zoomRequested = Signal(int)
    formatChanged = Signal()
    noteJumped = Signal()

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self.book: Fb2Book | None = None
        self.sync = None  # ScrollSync, set by the main window
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptRichText(True)
        self.setTabChangesFocus(False)
        self.setObjectName("bookEditor")
        self._pair_block = -1
        self._find_selections: list = []
        self._ids_rev = -1
        self._ids: dict[str, tuple[int, str | None]] = {}
        self._back: list[int] = []
        self._press_pos = None
        self.viewport().setMouseTracking(True)
        self.cursorPositionChanged.connect(self.formatChanged)
        self.currentCharFormatChanged.connect(lambda _f: self.formatChanged.emit())

    # ------------------------------------------------------------------ #
    #  Document
    # ------------------------------------------------------------------ #
    def set_book(self, doc: QTextDocument | None, book: Fb2Book | None):
        self.book = book
        if doc is None:
            doc = QTextDocument()
            doc.setPlainText("")
        doc.setParent(self)  # the editor deletes its previous child document itself
        self.setDocument(doc)
        self._pair_block = -1
        self._ids_rev = -1
        self._back.clear()
        self._update_extra()
        self.setReadOnly(book is None)

    def apply_view(self, font: QFont):
        doc = self.document()
        modified = doc.isModified()  # changing the view is not an edit
        doc.setDefaultFont(font)
        doc.setDocumentMargin(max(18, int(font.pointSizeF() * 2.4)))
        doc.setModified(modified)

    # ------------------------------------------------------------------ #
    #  Character formatting
    # ------------------------------------------------------------------ #
    def _merge(self, fmt: QTextCharFormat):
        """Apply to the selection, or to the text typed next when nothing is selected."""
        self.mergeCurrentCharFormat(fmt)

    def toggle_bold(self):
        f = QTextCharFormat()
        on = self.currentCharFormat().fontWeight() < 600
        f.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        self._merge(f)

    def toggle_italic(self):
        f = QTextCharFormat()
        f.setFontItalic(not self.currentCharFormat().fontItalic())
        self._merge(f)

    def toggle_strike(self):
        f = QTextCharFormat()
        f.setFontStrikeOut(not self.currentCharFormat().fontStrikeOut())
        self._merge(f)

    def toggle_valign(self, align):
        f = QTextCharFormat()
        cur = self.currentCharFormat().verticalAlignment()
        f.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal if cur == align else align)
        self._merge(f)

    def set_color(self, color: QColor | None):
        c = self.textCursor()
        if color is None:
            if c.hasSelection():
                self._clear_props(c, [QTextFormat.Property.ForegroundBrush])
            else:
                f = self.currentCharFormat()
                f.clearProperty(QTextFormat.Property.ForegroundBrush)
                self.setCurrentCharFormat(f)
        else:
            f = QTextCharFormat()
            f.setForeground(color)
            self._merge(f)

    def clear_formatting(self):
        c = self.textCursor()
        if not c.hasSelection():
            return
        props = [
            QTextFormat.Property.ForegroundBrush,
            QTextFormat.Property.FontItalic,
            QTextFormat.Property.FontStrikeOut,
            QTextFormat.Property.TextVerticalAlignment,
        ]
        c.beginEditBlock()
        self._clear_props(c, props)
        heading = style_of_block(self.document().findBlock(c.selectionStart())) in ("title", "subtitle")
        if not heading:
            f = QTextCharFormat()
            f.setFontWeight(QFont.Weight.Normal)
            c.mergeCharFormat(f)
        c.endEditBlock()

    def _clear_props(self, cursor: QTextCursor, props):
        """Remove properties from the char formats inside the selection."""
        doc = self.document()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.beginEditBlock()
        block = doc.findBlock(start)
        while block.isValid() and block.position() <= end:
            it = block.begin()
            spans = []
            while not it.atEnd():
                frag = it.fragment()
                fs, fe = frag.position(), frag.position() + frag.length()
                s, e = max(fs, start), min(fe, end)
                if s < e:
                    f = frag.charFormat()
                    for p in props:
                        f.clearProperty(p)
                    spans.append((s, e, f))
                it += 1
            for s, e, f in spans:
                c = QTextCursor(doc)
                c.setPosition(s)
                c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
                c.setCharFormat(f)
            block = block.next()
        cursor.endEditBlock()

    # ------------------------------------------------------------------ #
    #  Paragraph styles
    # ------------------------------------------------------------------ #
    def current_style(self) -> str:
        return style_of_block(self.textCursor().block())

    def _selected_blocks(self):
        c = self.textCursor()
        doc = self.document()
        b = doc.findBlock(c.selectionStart())
        last = doc.findBlock(c.selectionEnd())
        out = []
        while b.isValid():
            out.append(b)
            if b == last:
                break
            b = b.next()
        return out

    def _set_block(self, block, kind: str, path: str, recolor_chars=True):
        c = QTextCursor(block)
        old = block.blockFormat()
        bf = block_format(kind, path)
        for prop in (P_KIND, P_PATH):
            old.clearProperty(prop)
        for prop_id, value in old.properties().items():
            if prop_id >= QTextFormat.Property.UserProperty.value and not bf.hasProperty(prop_id):
                bf.setProperty(prop_id, value)
        c.setBlockFormat(bf)
        if recolor_chars:
            base = base_char_format(kind, path)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            f = QTextCharFormat()
            if kind in ("title", "subtitle"):
                f.setFontWeight(QFont.Weight.Bold)
                adj = base.property(QTextFormat.Property.FontSizeAdjustment) or 0
                f.setProperty(QTextFormat.Property.FontSizeAdjustment, adj)
            else:
                f.setFontWeight(QFont.Weight.Normal)
                f.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
            f.setFontItalic(kind in ("text-author", "date"))
            if c.hasSelection():
                c.mergeCharFormat(f)
            c.mergeBlockCharFormat(f)

    def set_style(self, style: str):
        if self.isReadOnly() or self.book is None:
            return
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for block in self._selected_blocks():
            self._apply_style(block, style)
        cursor.endEditBlock()
        self.formatChanged.emit()

    def _apply_style(self, block, style: str):
        book = self.book
        path = block_path(block)
        sec = section_path(path) or f"{book.new_key('body')}/{book.new_key('section')}"
        prev = block.previous()
        prev_path = block_path(prev) if prev.isValid() else ""
        prev_kind = block_kind(prev) if prev.isValid() else ""

        def child_container(p: str, tag: str) -> str | None:
            """Key of the container `tag` directly below `sec` in path p."""
            if not p.startswith(sec + "/"):
                return None
            first = _keys(p[len(sec) + 1:])
            return first[0] if first and first[0].startswith(tag + ":") else None

        if style == "normal":
            self._set_block(block, "p", sec)
        elif style == "subtitle":
            self._set_block(block, "subtitle", sec)
        elif style == "title":
            if block_kind(block) == "title":
                return
            joined = child_container(prev_path, "title")
            if joined and prev_kind == "title":
                self._set_block(block, "title", f"{sec}/{joined}")
                f = block.blockFormat()
                f.setTopMargin(2)
                QTextCursor(block).setBlockFormat(f)
                return
            at_start = not prev.isValid() or not (prev_path == sec or prev_path.startswith(sec + "/"))
            if not at_start and sec.rsplit("/", 1)[-1].startswith("section:"):
                # split the section: this block and everything after it go to a new sibling
                parent = sec.rsplit("/", 1)[0]
                new_sec = f"{parent}/{book.new_key('section')}"
                b = block.next()
                while b.isValid():
                    bp = block_path(b)
                    if bp != sec and not bp.startswith(sec + "/"):
                        break
                    f = b.blockFormat()
                    f.setProperty(P_PATH, new_sec + bp[len(sec):])
                    QTextCursor(b).setBlockFormat(f)
                    b = b.next()
                sec = new_sec
            elif not at_start:
                # body level without sections: wrap from here into a new section
                new_sec = f"{sec}/{book.new_key('section')}"
                b = block.next()
                while b.isValid() and block_path(b).startswith(sec):
                    f = b.blockFormat()
                    f.setProperty(P_PATH, new_sec + block_path(b)[len(sec):])
                    QTextCursor(b).setBlockFormat(f)
                    b = b.next()
                sec = new_sec
            self._set_block(block, "title", f"{sec}/{book.new_key('title')}")
        elif style in ("epigraph", "cite"):
            key = child_container(prev_path, style) or book.new_key(style)
            self._set_block(block, "p", f"{sec}/{key}")
        elif style == "poem":
            poem = child_container(prev_path, "poem")
            if poem and "/stanza:" in prev_path and prev_kind == "v":
                stanza = prev_path.split(f"{poem}/", 1)[1].split("/")[0]
                self._set_block(block, "v", f"{sec}/{poem}/{stanza}")
            else:
                poem = poem or book.new_key("poem")
                self._set_block(block, "v", f"{sec}/{poem}/{book.new_key('stanza')}")
        elif style == "author":
            for tag in ("poem", "epigraph", "cite"):
                key = child_container(prev_path, tag)
                if key:
                    self._set_block(block, "text-author", f"{sec}/{key}")
                    return
            self._set_block(block, "text-author", f"{sec}/{book.new_key('cite')}")


    # ------------------------------------------------------------------ #
    #  Footnotes and links
    # ------------------------------------------------------------------ #
    def _id_index(self) -> dict:
        """id -> (first block number, container key or None)."""
        doc = self.document()
        if self._ids_rev == doc.revision():
            return self._ids
        key_ids = {}
        if self.book:
            for key, attrs in self.book.attrs.items():
                for name, value in attrs.items():
                    if name.rsplit("}", 1)[-1] == "id" and value:
                        key_ids[key] = value
        ids: dict[str, tuple[int, str | None]] = {}
        b = doc.begin()
        while b.isValid():
            pid = b.blockFormat().property(P_ID)
            if pid and str(pid) not in ids:
                ids[str(pid)] = (b.blockNumber(), None)
            for k in block_path(b).split("/"):
                i = key_ids.get(k)
                if i and i not in ids:
                    ids[i] = (b.blockNumber(), k)
            b = b.next()
        self._ids, self._ids_rev = ids, doc.revision()
        return ids

    def note_target(self, href: str):
        if not href.startswith("#"):
            return None
        return self._id_index().get(href[1:])

    def note_content(self, href: str) -> tuple[str, str]:
        """(title, html text) of the footnote the link points to."""
        target = self.note_target(href)
        if not target:
            return "", ""
        number, key = target
        block = self.document().findBlockByNumber(number)
        titles, paras = [], []
        while block.isValid():
            path = block_path(block)
            if key is None:
                if block.blockNumber() != number:
                    break
            elif key not in path.split("/"):
                break
            text = block.text().replace(OBJ, "").strip()
            if text:
                if block_kind(block) == "title":
                    titles.append(text)
                else:
                    paras.append(text)
            if sum(len(p) for p in paras) > 3000:
                paras.append("…")
                break
            block = block.next()
        if not paras and titles:
            paras, titles = titles, []
        body = "".join(f"<p style='margin:0 0 6px 0'>{html.escape(p)}</p>" for p in paras)
        return " ".join(titles), body

    def jump_to_block(self, number: int):
        doc = self.document()
        block = doc.findBlockByNumber(number)
        if not block.isValid():
            return
        self._back.append(self.textCursor().position())
        self._move_to(block.position())
        self.noteJumped.emit()

    def go_back(self) -> bool:
        if not self._back:
            return False
        self._move_to(self._back.pop())
        return True

    def _move_to(self, position: int):
        doc = self.document()
        c = QTextCursor(doc)
        c.setPosition(min(max(0, position), doc.characterCount() - 1))
        self.setTextCursor(c)
        rect = doc.documentLayout().blockBoundingRect(c.block())
        self.verticalScrollBar().setValue(int(rect.y() - self.viewport().height() * 0.3))

    def _open_link(self, href: str, global_pos: QPoint, jump: bool):
        target = self.note_target(href)
        if target:
            if jump:
                self.jump_to_block(target[0])
            else:
                title, body = self.note_content(href)
                NotePopup(self, target[0], title, body).show_at(global_pos)
        elif href.startswith(("http://", "https://", "mailto:")) and jump:
            QDesktopServices.openUrl(QUrl(href))

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        href = self.anchorAt(e.position().toPoint())
        if href:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            if self.note_target(href) and not (e.buttons() & Qt.MouseButton.LeftButton):
                title, body = self.note_content(href)
                tip = (f"<b>{html.escape(title)}</b><br>" if title else "") + body
                QToolTip.showText(e.globalPosition().toPoint(), f"<div style='max-width:420px'>{tip}</div>",
                                  self.viewport())
            elif href.startswith("http"):
                QToolTip.showText(e.globalPosition().toPoint(), f"{href}<br><i>Ctrl+щелчок — открыть</i>",
                                  self.viewport())
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            QToolTip.hideText()

    def mousePressEvent(self, e):
        self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        pos = e.position().toPoint()
        if e.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        moved = (pos - self._press_pos).manhattanLength() > 4
        self._press_pos = None
        if moved or self.textCursor().hasSelection():
            return
        href = self.anchorAt(pos)
        if href:
            ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._open_link(href, e.globalPosition().toPoint(), jump=ctrl)

    def _leave_link_format(self):
        """Text typed right after a link must not become part of the link."""
        c = self.textCursor()
        if c.hasSelection():
            return
        fmt = c.charFormat()
        if not fmt.isAnchor():
            return
        after = QTextCursor(c)
        if after.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor) \
                and after.charFormat().isAnchor() and after.charFormat().anchorHref() == fmt.anchorHref() \
                and not c.atBlockEnd():
            return  # typing inside the link text
        clean = QTextCharFormat(fmt)
        clean.setAnchor(False)
        clean.clearProperty(QTextFormat.Property.AnchorHref)
        clean.clearProperty(QTextFormat.Property.ForegroundBrush)
        clean.setFontUnderline(False)
        clean.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        self.setCurrentCharFormat(clean)

    # ------------------------------------------------------------------ #
    #  Keyboard / mouse
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Left and e.modifiers() == Qt.KeyboardModifier.AltModifier:
            if self.go_back():
                return
        if e.text() and e.text().isprintable() and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._leave_link_format()
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.isReadOnly() and self.book:
            c = self.textCursor()
            block = c.block()
            kind = block_kind(block)
            if kind in ("title", "subtitle", "image", "text-author", "date") and c.atBlockEnd():
                path = section_path(block_path(block))
                c.beginEditBlock()
                if c.hasSelection():
                    c.removeSelectedText()
                c.insertBlock(block_format("p", path), plain_char_format(c.charFormat()))
                fmt = QTextCharFormat()
                fmt.setFontWeight(QFont.Weight.Normal)
                fmt.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
                fmt.setFontItalic(False)
                c.setBlockCharFormat(fmt)
                c.setCharFormat(fmt)
                c.endEditBlock()
                self.setTextCursor(c)
                self.setCurrentCharFormat(fmt)
                self.ensureCursorVisible()
                return
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # FB2 has no line breaks inside a paragraph: Shift+Enter = Enter
                e = QKeyEvent(e.type(), e.key(), Qt.KeyboardModifier.NoModifier, e.text())
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        mods = e.modifiers()
        delta = e.angleDelta().y() or e.angleDelta().x()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if delta:
                self.zoomRequested.emit(1 if delta > 0 else -1)
            e.accept()
            return
        if mods & Qt.KeyboardModifier.AltModifier:
            # scroll only this side – lets the user re-align the two books
            sb = self.verticalScrollBar()
            if self.sync:
                self.sync.paused = True
            sb.setValue(sb.value() - delta)
            if self.sync:
                self.sync.paused = False
            e.accept()
            return
        super().wheelEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit()

    # ------------------------------------------------------------------ #
    #  Highlighting of the paired paragraph and search hits
    # ------------------------------------------------------------------ #
    def set_pair_block(self, number: int):
        if number != self._pair_block:
            self._pair_block = number
            self._update_extra()

    def set_find_hits(self, cursors: list[QTextCursor]):
        self._find_selections = cursors
        self._update_extra()

    def _update_extra(self):
        sels = []
        pal = self.palette()
        if self._pair_block >= 0:
            block = self.document().findBlockByNumber(self._pair_block)
            if block.isValid():
                s = QTextEdit.ExtraSelection()
                col = QColor(pal.highlight().color())
                col.setAlpha(38)
                s.format.setBackground(col)
                s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                c = QTextCursor(block)
                c.clearSelection()
                s.cursor = c
                sels.append(s)
                # full width only covers one line: also tint the whole paragraph text
                s2 = QTextEdit.ExtraSelection()
                s2.format.setBackground(col)
                c2 = QTextCursor(block)
                c2.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                s2.cursor = c2
                sels.append(s2)
        for c in self._find_selections:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(255, 200, 0, 120))
            s.cursor = c
            sels.append(s)
        self.setExtraSelections(sels)

    # ------------------------------------------------------------------ #
    #  Clipboard
    # ------------------------------------------------------------------ #
    plain_paste = False

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData):
        if self.isReadOnly() or self.book is None:
            return
        if source.hasImage() and not source.text().strip():
            img = QImage(source.imageData())
            if not img.isNull():
                self.insert_image(img)
                return
        if source.hasUrls() and not source.hasText():
            done = False
            for url in source.urls():
                p = url.toLocalFile()
                if p and os.path.splitext(p)[1].lower() in _IMG_EXT:
                    img = QImage(p)
                    if not img.isNull():
                        self.insert_image(img)
                        done = True
            if done:
                return
        if source.hasHtml() and not self.plain_paste:
            self._insert_html(source.html())
        elif source.hasText():
            self._insert_plain(source.text())

    def paste_plain(self):
        self.plain_paste = True
        try:
            self.paste()
        finally:
            self.plain_paste = False

    def insert_image(self, img: QImage):
        name = self.book.add_image(img)
        self.document().addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(name), img)
        c = self.textCursor()
        c.beginEditBlock()
        c.removeSelectedText()
        block = c.block()
        if not block.text().strip():
            self._set_block(block, "image", section_path(block_path(block)), recolor_chars=False)
            c.insertImage(image_format(name, img))
        else:
            c.insertImage(image_format(name, img))
        c.endEditBlock()
        self.setTextCursor(c)

    def _typing_format(self) -> QTextCharFormat:
        f = QTextCharFormat(self.textCursor().charFormat())
        f.setAnchor(False)
        f.clearProperty(QTextFormat.Property.AnchorHref)
        f.setFontUnderline(False)
        return f

    def _new_paragraph(self, c: QTextCursor):
        """Start a new paragraph during paste; headings do not propagate."""
        block = c.block()
        kind = block_kind(block)
        if kind in ("title", "subtitle", "image", "text-author", "date"):
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Normal)
            fmt.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
            fmt.setFontItalic(False)
            c.insertBlock(block_format("p", section_path(block_path(block))), fmt)
            # text that followed the cursor moved into the new paragraph: drop heading looks
            rest = QTextCursor(c)
            rest.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            if rest.hasSelection():
                rest.mergeCharFormat(fmt)
            c.setCharFormat(fmt)
        else:
            c.insertBlock()

    def _insert_plain(self, text: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
        paras = [p.strip() if i else p.rstrip() for i, p in enumerate(re.split(r"\n\s*\n|\n", text))]
        if len(paras) > 1:
            paras = [p for p in paras if p]
        c = self.textCursor()
        c.beginEditBlock()
        c.removeSelectedText()
        fmt = self._typing_format()
        for i, p in enumerate(paras):
            if i:
                self._new_paragraph(c)
                fmt = QTextCharFormat(c.charFormat())
            c.insertText(p, fmt)
        c.endEditBlock()
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def _insert_html(self, html: str):
        own = "qrichtext" in html
        tmp = QTextDocument()
        tmp.setHtml(html)
        blocks = []
        b = tmp.begin()
        while b.isValid():
            blocks.append(b)
            b = b.next()
        while blocks and not blocks[0].text().strip():
            blocks.pop(0)
        while blocks and not blocks[-1].text().strip():
            blocks.pop()
        if not blocks:
            return
        c = self.textCursor()
        c.beginEditBlock()
        c.removeSelectedText()
        base = self._typing_format()
        for i, block in enumerate(blocks):
            if i:
                self._new_paragraph(c)
                base = QTextCharFormat(c.charFormat())
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                it += 1
                src = frag.charFormat()
                if src.isImageFormat():
                    img = tmp.resource(QTextDocument.ResourceType.ImageResource.value,
                                       QUrl(src.toImageFormat().name()))
                    if isinstance(img, QImage) and not img.isNull():
                        name = self.book.add_image(img)
                        self.document().addResource(QTextDocument.ResourceType.ImageResource.value,
                                                    QUrl(name), img)
                        c.insertImage(image_format(name, img))
                    continue
                f = QTextCharFormat(base)
                heading = block_kind(c.block()) in ("title", "subtitle")
                if not heading:
                    f.setFontWeight(QFont.Weight.Bold if src.fontWeight() >= 600 else QFont.Weight.Normal)
                f.setFontItalic(src.fontItalic())
                f.setFontStrikeOut(src.fontStrikeOut())
                f.setVerticalAlignment(src.verticalAlignment())
                if src.isAnchor() and src.anchorHref():
                    f.setAnchor(True)
                    f.setAnchorHref(src.anchorHref())
                    f.setFontUnderline(True)
                if src.hasProperty(QTextFormat.Property.ForegroundBrush):
                    col = src.foreground().color()
                    if own or (col.hsvSaturation() >= 80 and col.value() >= 60):
                        f.setForeground(col)
                    else:
                        f.clearProperty(QTextFormat.Property.ForegroundBrush)
                for prop in range(QTextFormat.Property.UserProperty.value, QTextFormat.Property.UserProperty.value + 40):
                    if src.hasProperty(prop):
                        f.setProperty(prop, src.property(prop))
                c.insertText(frag.text().replace(OBJ, ""), f)
        c.endEditBlock()
        self.setTextCursor(c)
        self.ensureCursorVisible()
