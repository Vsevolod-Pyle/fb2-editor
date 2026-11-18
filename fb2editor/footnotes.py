"""Creating FB2 footnotes from the editor.

A footnote is a section with an ``id`` (normally inside ``<body name="notes">``
at the end of the book) and a link ``<a l:href="#id" type="note">[N]</a>`` in
the text — the standard FB2 way, so every reader shows it as a note.

New notes are put next to the notes the book already has (whatever container
they live in).  After every change the numeric note links are renumbered in
reading order and the note sections are sorted the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from .fb2doc import (
    C_LINK_TYPE,
    LINK_COLOR,
    OBJ,
    base_char_format,
    block_format,
    block_kind,
    block_path,
)

NOTES_TITLE = "Примечания"
NUM_RE = re.compile(r"^(\D{0,3}?)(\d+)(\D{0,3})$")


# --------------------------------------------------------------------------- #
#  Dialog with formatting kept
# --------------------------------------------------------------------------- #


class FootnoteDialog(QDialog):
    """Edit the text of a new footnote; bold/italic etc. of the selection are kept."""

    def __init__(self, fragment=None, label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Примечание")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        head = QLabel("Примечание" + (f" · {label}" if label else ""))
        head.setStyleSheet("font-size: 13pt; font-weight: 700;")
        lay.addWidget(head)
        hint = QLabel("Текст попадёт в раздел примечаний в конце книги, а в тексте появится ссылка [N]. "
                      "Номера расставляются по порядку в книге.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.setMinimumHeight(140)
        self.edit.setPlaceholderText("Текст примечания…  (Ctrl+B, Ctrl+I — жирный и курсив; Ctrl+Enter — сохранить)")
        if fragment is not None and not fragment.isEmpty():
            self.edit.textCursor().insertFragment(fragment)
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
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.accept()
                return True
            if ev.key() in (Qt.Key.Key_B, Qt.Key.Key_I):
                f = QTextCharFormat()
                cur = self.edit.currentCharFormat()
                if ev.key() == Qt.Key.Key_B:
                    f.setFontWeight(400 if cur.fontWeight() >= 600 else 700)
                else:
                    f.setFontItalic(not cur.fontItalic())
                self.edit.mergeCurrentCharFormat(f)
                return True
        return super().eventFilter(obj, ev)

    def paragraphs(self):
        return paragraphs_of(self.edit.document())


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _clean_format(cf: QTextCharFormat, heading: bool) -> QTextCharFormat:
    f = QTextCharFormat(cf)
    for prop in (QTextFormat.Property.FontSizeAdjustment, QTextFormat.Property.FontPointSize,
                 QTextFormat.Property.FontPixelSize, QTextFormat.Property.FontFamilies,
                 QTextFormat.Property.BackgroundBrush):
        f.clearProperty(prop)
    if heading:
        f.clearProperty(QTextFormat.Property.FontWeight)
    return f


def paragraphs_of(doc: QTextDocument, start: int = 0, end: int | None = None):
    """[[(text, char format), ...], ...] for the paragraphs in [start, end)."""
    if end is None:
        end = doc.characterCount() - 1
    out = []
    b = doc.findBlock(start)
    while b.isValid() and b.position() <= end:
        heading = block_kind(b) in ("title", "subtitle")
        pieces = []
        it = b.begin()
        while not it.atEnd():
            fr = it.fragment()
            it += 1
            s, e = max(fr.position(), start), min(fr.position() + fr.length(), end)
            if s >= e:
                continue
            text = fr.text()[s - fr.position():e - fr.position()]
            pieces.append((text, _clean_format(fr.charFormat(), heading)))
        if any(t.strip() for t, _f in pieces):
            out.append(pieces)
        b = b.next()
    return out


def link_format(nid: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setAnchor(True)
    f.setAnchorHref("#" + nid)
    f.setProperty(C_LINK_TYPE, "note")
    f.setFontUnderline(True)
    f.setForeground(LINK_COLOR)
    return f


def _section_ids(book) -> dict[str, str]:
    """section id -> container key."""
    return {a["id"]: k for k, a in book.attrs.items() if k.startswith("section:") and a.get("id")}


def notes_body_key(doc, book) -> str | None:
    b = doc.begin()
    seen = set()
    while b.isValid():
        key = block_path(b).split("/", 1)[0]
        if key and key not in seen:
            seen.add(key)
            if book.attrs.get(key, {}).get("name") == "notes":
                return key
        b = b.next()
    return None


@dataclass
class _Link:
    nid: str
    frags: list = field(default_factory=list)  # (position, text, format)

    @property
    def text(self):
        return "".join(t for _p, t, _f in self.frags)


def collect_note_links(doc, book) -> list[_Link]:
    """Links to note sections, in reading order (adjacent fragments merged)."""
    ids = _section_ids(book)
    links: list[_Link] = []
    b = doc.begin()
    while b.isValid():
        it = b.begin()
        while not it.atEnd():
            fr = it.fragment()
            it += 1
            cf = fr.charFormat()
            href = cf.anchorHref() if cf.isAnchor() else ""
            if not href.startswith("#") or href[1:] not in ids:
                continue
            last = links[-1] if links else None
            if last and last.nid == href[1:] and last.frags[-1][0] + len(last.frags[-1][1]) == fr.position():
                last.frags.append((fr.position(), fr.text(), cf))
            else:
                links.append(_Link(href[1:], [(fr.position(), fr.text(), cf)]))
        b = b.next()
    return links


def _section_blocks(doc) -> dict[str, list[int]]:
    """section key -> block numbers (only keys that are sections)."""
    out: dict[str, list[int]] = {}
    b = doc.begin()
    while b.isValid():
        for k in block_path(b).split("/"):
            if k.startswith("section:"):
                out.setdefault(k, []).append(b.blockNumber())
        b = b.next()
    return out


def _parent_of(doc, key: str, blocks: list[int]) -> str:
    path = block_path(doc.findBlockByNumber(blocks[0]))
    return path.split("/" + key, 1)[0]


# --------------------------------------------------------------------------- #
#  Renumbering
# --------------------------------------------------------------------------- #


def renumber_notes(doc, book) -> int:
    """Number note links 1..N in reading order and sort the note sections.

    Only links whose whole text is a number (like ``[3]``, ``3``, ``(3)``) are
    touched.  Returns the number of numbered notes.
    """
    ids = _section_ids(book)
    numbered: dict[str, int] = {}
    edits = []
    for link in collect_note_links(doc, book):
        if not NUM_RE.match(link.text.strip()):
            continue
        n = numbered.setdefault(link.nid, len(numbered) + 1)
        for pos, text, cf in link.frags:
            m = re.search(r"\d+", text)
            if m:
                if m.group() != str(n):
                    edits.append((pos + m.start(), pos + m.end(), str(n), cf))
                break
    blocks = _section_blocks(doc)
    # titles of the note sections ("1", "2", ...)
    for nid, n in numbered.items():
        key = ids.get(nid)
        for num in blocks.get(key, []):
            b = doc.findBlockByNumber(num)
            if block_kind(b) != "title":
                continue
            m = NUM_RE.match(b.text().strip())
            if m:
                i = b.text().find(m.group(2))
                if m.group(2) != str(n):
                    c = QTextCursor(doc)
                    c.setPosition(b.position() + i + 1)
                    edits.append((b.position() + i, b.position() + i + len(m.group(2)), str(n), c.charFormat()))
            break
    for s, e, text, cf in sorted(edits, key=lambda x: x[0], reverse=True):
        c = QTextCursor(doc)
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        c.insertText(text, cf)
    _sort_sections(doc, book, numbered)
    return len(numbered)


def _sort_sections(doc, book, numbered: dict[str, int]):
    ids = _section_ids(book)
    blocks = _section_blocks(doc)
    keys = [ids[nid] for nid in numbered if ids.get(nid) in blocks]
    if len(keys) < 2:
        return
    parents = {_parent_of(doc, k, blocks[k]) for k in keys}
    if len(parents) != 1:
        return
    parent = parents.pop()
    lo = min(blocks[k][0] for k in keys)
    hi = max(blocks[k][-1] for k in keys)
    # the region must consist only of sibling sections of the same parent
    order: list[str] = []
    for num in range(lo, hi + 1):
        path = block_path(doc.findBlockByNumber(num))
        if not path.startswith(parent + "/section:"):
            return
        key = path[len(parent) + 1:].split("/", 1)[0]
        if not order or order[-1] != key:
            if key in order:
                return  # not contiguous
            order.append(key)
    number_of = {ids[nid]: n for nid, n in numbered.items() if nid in ids}
    wanted = sorted((k for k in order if k in number_of), key=lambda k: number_of[k])
    wanted += [k for k in order if k not in number_of]
    if wanted == order:
        return
    # capture the blocks of every section, then rebuild the region in the new order
    captured: dict[str, list] = {k: [] for k in order}
    for num in range(lo, hi + 1):
        b = doc.findBlockByNumber(num)
        key = block_path(b)[len(parent) + 1:].split("/", 1)[0]
        pieces = []
        it = b.begin()
        while not it.atEnd():
            fr = it.fragment()
            it += 1
            pieces.append((fr.text(), fr.charFormat()))
        captured[key].append((b.blockFormat(), b.charFormat(), pieces))
    first = doc.findBlockByNumber(lo)
    last = doc.findBlockByNumber(hi)
    c = QTextCursor(doc)
    c.setPosition(first.position())
    c.setPosition(last.position() + last.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    c.removeSelectedText()
    start = True
    for key in wanted:
        for bf, bcf, pieces in captured[key]:
            if start:
                c.setBlockFormat(bf)
                c.setBlockCharFormat(bcf)
                start = False
            else:
                c.insertBlock(bf, bcf)
            for text, cf in pieces:
                if cf.isImageFormat():
                    for _ in text:
                        c.insertImage(cf.toImageFormat())
                else:
                    c.insertText(text, cf)


# --------------------------------------------------------------------------- #
#  Creating a footnote
# --------------------------------------------------------------------------- #


def _insert_block(cursor: QTextCursor, kind: str, path: str, pieces, small: bool = False):
    bf, cf = block_format(kind, path), base_char_format(kind, path)
    if small:  # the number of a note: a title in FB2, but shown at text size
        cf.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
        bf.setTopMargin(14)
        bf.setBottomMargin(2)
    cursor.insertBlock(bf, cf)
    if isinstance(pieces, str):
        pieces = [(pieces, cf)]
    for text, f in pieces:
        if f.isImageFormat():
            for _ in text:
                cursor.insertImage(f.toImageFormat())
        else:
            cursor.insertText(text.replace(" ", " "), f)


def _note_container(doc, book) -> tuple[str | None, int | None]:
    """(parent path for new note sections, block number to insert after)."""
    ids = _section_ids(book)
    blocks = _section_blocks(doc)
    targets = {link.nid for link in collect_note_links(doc, book)}
    keys = [ids[t] for t in targets if ids.get(t) in blocks]
    if keys:
        parents: dict[str, list[str]] = {}
        for k in keys:
            parents.setdefault(_parent_of(doc, k, blocks[k]), []).append(k)
        # the container holding most of the existing notes
        parent, ks = max(parents.items(), key=lambda kv: len(kv[1]))
        last = max(blocks[k][-1] for k in ks)
        return parent, last
    body = notes_body_key(doc, book)
    if body:
        last = None
        b = doc.begin()
        while b.isValid():
            p = block_path(b)
            if p == body or p.startswith(body + "/"):
                last = b.blockNumber()
            b = b.next()
        return body, last
    return None, None


def add_footnote(editor, start: int, end: int, content) -> tuple[str, int]:
    """Replace [start, end) with a note link and add the note to the book's notes.

    ``content`` is plain text or a list of paragraphs [[(text, format), ...]].
    Returns (note id, note number).  Everything is one undo step.
    """
    doc, book = editor.document(), editor.book
    if isinstance(content, str):
        content = [[(p.strip(), QTextCharFormat())]
                   for p in re.split(r"[\n  ]+", content) if p.strip()]
    content = content or [[("", QTextCharFormat())]]
    ids = set(_section_ids(book)) | {a["id"] for a in book.attrs.values() if a.get("id")}
    k = len(ids) + 1
    while f"n{k}" in ids:
        k += 1
    nid = f"n{k}"

    c = QTextCursor(doc)
    c.beginEditBlock()
    # 1) the note section, next to the existing notes
    parent, after = _note_container(doc, book)
    tail = QTextCursor(doc)
    if parent is None:
        parent = book.new_key("body")
        book.attrs[parent] = {"name": "notes"}
        tail.movePosition(QTextCursor.MoveOperation.End)
        _insert_block(tail, "title", f"{parent}/{book.new_key('title')}", NOTES_TITLE)
    else:
        last = doc.findBlockByNumber(after)
        tail.setPosition(last.position() + last.length() - 1)
    section = book.new_key("section")
    book.attrs[section] = {"id": nid}
    sec_path = f"{parent}/{section}"
    _insert_block(tail, "title", f"{sec_path}/{book.new_key('title')}", "0", small=True)
    for pieces in content:
        _insert_block(tail, "p", sec_path, pieces)

    # 2) the link in the text (replaces the selection; text before the notes is unaffected)
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    c.insertText("[0]", link_format(nid))
    link_end = c.position()

    # 3) numbers in reading order
    renumber_notes(doc, book)
    c.endEditBlock()

    number = 0
    for link in collect_note_links(doc, book):
        if link.nid == nid:
            m = re.search(r"\d+", link.text)
            number = int(m.group()) if m else 0
            link_end = link.frags[-1][0] + len(link.frags[-1][1])
            break

    c = QTextCursor(doc)
    c.setPosition(min(link_end, doc.characterCount() - 1))
    plain = QTextCharFormat(c.charFormat())
    plain.setAnchor(False)
    plain.setAnchorHref("")
    plain.clearProperty(C_LINK_TYPE)
    plain.setFontUnderline(False)
    plain.clearForeground()
    editor.setTextCursor(c)
    editor.setCurrentCharFormat(plain)
    return nid, number


__all__ = ["FootnoteDialog", "add_footnote", "renumber_notes", "paragraphs_of", "OBJ"]
