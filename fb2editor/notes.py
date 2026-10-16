"""Project notes: comments attached to places in either book.

Notes live only in the project (``project.json``), never in the FB2 files.
Each note remembers its place as *paragraph number + offset + length* and the
quoted text.  While a book is open the place is tracked by live QTextCursors,
so it follows edits; when a book is (re)loaded the note is re-anchored, and
if the quote moved it is searched for nearby.
"""

from __future__ import annotations

import html
import time
from bisect import bisect_right
import uuid

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from .projects import SIDES

QUOTE_MAX = 300
SEARCH_RADIUS = 80  # paragraphs searched around the old place when re-anchoring


class NoteDialog(QDialog):
    def __init__(self, quote: str, text: str = "", label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Заметка")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        head = QLabel("Заметка" + (f" · {label}" if label else ""))
        head.setStyleSheet("font-size: 13pt; font-weight: 700;")
        lay.addWidget(head)
        if quote:
            q = QLabel(f"«{html.escape(_short(quote, 220))}»")
            q.setObjectName("muted")
            q.setWordWrap(True)
            lay.addWidget(q)
        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText("Комментарий…  (Ctrl+Enter — сохранить)")
        self.edit.setMinimumHeight(120)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.edit.setFocus()
        self.edit.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.accept()
            return True
        return super().eventFilter(obj, ev)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


def _short(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Notes(QObject):
    """All notes of the open project plus live cursors in the open books."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.editors: dict[str, object] = {}
        self._cursors: dict[str, tuple[QTextCursor, QTextCursor]] = {}

    # -- data ------------------------------------------------------------- #
    @property
    def items(self) -> list[dict]:
        if self.project is None:
            return []
        return self.project.data.setdefault("notes", [])

    def set_project(self, project):
        self.project = project
        self._cursors.clear()
        self.changed.emit()

    def get(self, nid: str) -> dict | None:
        return next((n for n in self.items if n["id"] == nid), None)

    def save(self):
        if self.project is None:
            return
        self.sync_back()
        try:
            self.project.save_state()
        except OSError:
            pass

    # -- anchoring --------------------------------------------------------- #
    def attach(self, side: str, editor):
        """(Re)create live cursors for the notes of one book after it was loaded."""
        self.editors[side] = editor
        for nid in [k for k in self._cursors if self._side_of(k) == side]:
            del self._cursors[nid]
        if editor.book is not None:
            doc = editor.document()
            for n in self.items:
                if n["side"] == side:
                    start, end = self._locate(doc, n)
                    self._cursors[n["id"]] = self._make(doc, start, end)
        self.refresh_editor(side)

    def _side_of(self, nid: str) -> str:
        n = self.get(nid)
        return n["side"] if n else ""

    @staticmethod
    def _make(doc, start: int, end: int):
        a = QTextCursor(doc)
        a.setPosition(start)
        b = QTextCursor(doc)
        b.setPosition(end)
        return a, b

    @staticmethod
    def _locate(doc, n: dict) -> tuple[int, int]:
        count = doc.blockCount()
        number = min(max(0, int(n.get("block", 0))), count - 1)
        block = doc.findBlockByNumber(number)
        offset = min(max(0, int(n.get("offset", 0))), max(0, block.length() - 1))
        start = block.position() + offset
        length = int(n.get("length", 0))
        quote = n.get("quote", "")
        end = min(start + length, doc.characterCount() - 1)

        def text_at(s, e):
            c = QTextCursor(doc)
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            return c.selectedText().replace(" ", "\n")

        if not quote or text_at(start, end) == quote or "\n" in quote:
            return start, end
        # the text moved: look for the quote in the nearby paragraphs, nearest first
        for dist in range(0, SEARCH_RADIUS):
            for num in {number - dist, number + dist}:
                if 0 <= num < count:
                    b = doc.findBlockByNumber(num)
                    i = b.text().find(quote)
                    if i >= 0:
                        return b.position() + i, b.position() + i + len(quote)
        return start, end

    def range_of(self, nid: str) -> tuple[int, int] | None:
        c = self._cursors.get(nid)
        if not c:
            return None
        return c[0].position(), max(c[0].position(), c[1].position())

    def sync_back(self):
        """Write the live cursor positions back into the stored notes."""
        for n in self.items:
            r = self.range_of(n["id"])
            ed = self.editors.get(n["side"])
            if r is None or ed is None or ed.book is None:
                continue
            doc = ed.document()
            block = doc.findBlock(r[0])
            n["block"] = block.blockNumber()
            n["offset"] = r[0] - block.position()
            n["length"] = r[1] - r[0]
            c = QTextCursor(doc)
            c.setPosition(r[0])
            c.setPosition(r[1], QTextCursor.MoveMode.KeepAnchor)
            quote = c.selectedText().replace(" ", "\n")
            if quote:
                n["quote"] = quote[:QUOTE_MAX]

    # -- editing ------------------------------------------------------------ #
    def add(self, side: str, editor, start: int, end: int, text: str) -> dict:
        doc = editor.document()
        block = doc.findBlock(start)
        c = QTextCursor(doc)
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        t = time.time()
        n = {
            "id": uuid.uuid4().hex[:10], "side": side, "text": text,
            "block": block.blockNumber(), "offset": start - block.position(), "length": end - start,
            "quote": c.selectedText().replace(" ", "\n")[:QUOTE_MAX], "created": t, "updated": t,
        }
        self.items.append(n)
        self._cursors[n["id"]] = self._make(doc, start, end)
        self.save()
        self.refresh_editor(side)
        self.changed.emit()
        return n

    def edit(self, nid: str, text: str):
        n = self.get(nid)
        if n:
            n["text"] = text
            n["updated"] = time.time()
            self.save()
            self.refresh_editor(n["side"])
            self.changed.emit()

    def remove(self, nid: str):
        n = self.get(nid)
        if not n:
            return
        self.items.remove(n)
        self._cursors.pop(nid, None)
        self.save()
        self.refresh_editor(n["side"])
        self.changed.emit()

    def refresh_editor(self, side: str):
        ed = self.editors.get(side)
        if ed is None:
            return
        ranges = []
        for n in self.items:
            if n["side"] == side:
                r = self.range_of(n["id"])
                if r:
                    ranges.append((r[0], r[1], n["id"], n.get("text", "")))
        ed.set_note_ranges(ranges)

    def ordered(self, side: str | None = None) -> list[dict]:
        out = [n for n in self.items if side in (None, n["side"])]

        def key(n):
            r = self.range_of(n["id"])
            pos = r[0] if r else n.get("block", 0) * 1000 + n.get("offset", 0)
            return SIDES.index(n["side"]) if n["side"] in SIDES else 9, pos

        return sorted(out, key=key)


class NotesPanel(QFrame):
    """Side panel with the list of notes."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.notes: Notes = win.notes
        self.setObjectName("notesPanel")
        self.setFixedWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 8, 0)
        self.title = QLabel("Заметки")
        self.title.setObjectName("sidebarTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.add_btn = QToolButton()
        self.add_btn.setToolTip("Новая заметка к выделенному месту (Ctrl+Alt+M)")
        self.add_btn.clicked.connect(win.add_note)
        self.close_btn = QToolButton()
        self.close_btn.setToolTip("Скрыть панель (Ctrl+Shift+M)")
        self.close_btn.clicked.connect(lambda: win.act["notes_panel"].setChecked(False))
        head.addWidget(self.add_btn)
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        self.filter = QComboBox()
        self.filter.addItem("Обе книги", None)
        for side in SIDES:
            self.filter.addItem(side, side)
        self.filter.currentIndexChanged.connect(self.refresh)
        f_row = QHBoxLayout()
        f_row.setContentsMargins(12, 0, 12, 0)
        f_row.addWidget(self.filter)
        lay.addLayout(f_row)

        self.list = QListWidget()
        self.list.setObjectName("notesList")
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setWordWrap(True)
        self.list.setSpacing(2)
        self.list.itemClicked.connect(lambda it: win.goto_note(it.data(Qt.ItemDataRole.UserRole)))
        self.list.itemDoubleClicked.connect(lambda it: win.edit_note(it.data(Qt.ItemDataRole.UserRole)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.empty = QLabel("Выделите текст в книге и нажмите\nCtrl+Alt+M или «+», чтобы оставить заметку.\n\n"
                            "Заметки хранятся только в проекте\nи не попадают в FB2 файлы.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty, 1)
        self.notes.changed.connect(self.refresh)

    def refresh(self):
        project = self.win.project
        for i, side in enumerate(SIDES, start=1):
            self.filter.setItemText(i, f"Только {project.label(side)}" if project else side)
        side = self.filter.currentData()
        notes = self.notes.ordered(side)
        current = self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
        self.list.clear()
        for n in notes:
            label = project.label(n["side"]) if project else n["side"]
            r = self.notes.range_of(n["id"])
            ed = self.notes.editors.get(n["side"])
            where = ""
            if r and ed is not None and ed.book is not None and ed.sync is not None:
                number = ed.document().findBlock(r[0]).blockNumber()
                content = ed.sync.index(ed).content
                where = f" · ¶ {max(1, bisect_right(content, number))}"
            stamp = time.strftime("%d.%m %H:%M", time.localtime(n.get("updated", n.get("created", 0))))
            quote = _short(n.get("quote", ""), 90)
            text = html.escape(n.get("text", "")).replace("\n", "<br>")
            body = (f"<div style='color:{self.win.colors['muted']}; font-size:8.5pt'>"
                    f"<b style='color:{self.win.colors['accent']}'>{html.escape(label)}</b>{where} · {stamp}</div>"
                    + (f"<div style='color:{self.win.colors['muted']}'><i>«{html.escape(quote)}»</i></div>"
                       if quote else "")
                    + f"<div style='margin-top:3px'>{text or '<i>(без текста)</i>'}</div>")
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            item.setToolTip(n.get("text", ""))
            lbl = QLabel(body)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setContentsMargins(10, 7, 10, 7)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            width = self.width() - 34
            lbl.setFixedWidth(width)
            item.setSizeHint(QSize(width, lbl.heightForWidth(width) + 6))
            self.list.addItem(item)
            self.list.setItemWidget(item, lbl)
            if n["id"] == current:
                self.list.setCurrentItem(item)
        has = bool(notes)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        total = len(self.notes.items)
        self.title.setText(f"Заметки · {total}" if total else "Заметки")

    def select(self, nid: str):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == nid:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it)
                return

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        nid = item.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Перейти к месту", lambda: self.win.goto_note(nid))
        m.addAction("Изменить…", lambda: self.win.edit_note(nid))
        m.addSeparator()
        m.addAction("Удалить", lambda: self.win.delete_note(nid))
        m.exec(self.list.mapToGlobal(pos))
