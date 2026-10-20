"""Creating FB2 footnotes from the editor.

A footnote is a section with an ``id`` inside ``<body name="notes">`` at the
end of the book, and a link ``<a l:href="#id" type="note">[N]</a>`` in the
text.  This is the standard FB2 way, so every reader shows it as a note.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextFormat

from .fb2doc import (
    C_LINK_TYPE,
    LINK_COLOR,
    P_ID,
    base_char_format,
    block_format,
    block_kind,
    block_path,
)

NOTES_TITLE = "Примечания"


def notes_body_key(doc, book) -> str | None:
    """Path key of the existing <body name="notes">, if the book has one."""
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


def _used_ids(doc, book) -> set[str]:
    ids = {a["id"] for a in book.attrs.values() if a.get("id")}
    b = doc.begin()
    while b.isValid():
        pid = b.blockFormat().property(P_ID)
        if pid:
            ids.add(str(pid))
        b = b.next()
    return ids


def _body_blocks(doc, body: str):
    b = doc.begin()
    while b.isValid():
        p = block_path(b)
        if p == body or p.startswith(body + "/"):
            yield b
        b = b.next()


def next_number(doc, body: str | None) -> int:
    """Next footnote number: one more than the largest numeric note title."""
    if body is None:
        return 1
    best, sections = 0, set()
    for b in _body_blocks(doc, body):
        keys = block_path(b).split("/")
        if len(keys) > 1 and keys[1].startswith("section:"):
            sections.add(keys[1])
            if block_kind(b) == "title":
                m = re.fullmatch(r"\D*(\d+)\D*", b.text().strip())
                if m:
                    best = max(best, int(m.group(1)))
    return max(best, len(sections)) + 1


def link_format(nid: str) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setAnchor(True)
    f.setAnchorHref("#" + nid)
    f.setProperty(C_LINK_TYPE, "note")
    f.setFontUnderline(True)
    f.setForeground(LINK_COLOR)
    return f


def _append_block(cursor: QTextCursor, kind: str, path: str, text: str, small: bool = False):
    bf, cf = block_format(kind, path), base_char_format(kind, path)
    if small:  # the number of a note: a title in FB2, but shown at text size
        cf.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
        bf.setTopMargin(14)
        bf.setBottomMargin(2)
    cursor.insertBlock(bf, cf)
    cursor.insertText(text, cf)


def add_footnote(editor, start: int, end: int, text: str) -> tuple[str, int]:
    """Replace [start, end) with a note link and append the note text at the end.

    Returns (note id, note number).  Everything is one undo step.
    """
    doc, book = editor.document(), editor.book
    paragraphs = [p.strip() for p in re.split(r"[\n  ]+", text) if p.strip()] or [""]
    body = notes_body_key(doc, book)
    number = next_number(doc, body)
    used = _used_ids(doc, book)
    nid, k = f"n{number}", 1
    while nid in used:
        k += 1
        nid = f"n{number}_{k}"

    c = QTextCursor(doc)
    c.beginEditBlock()
    # 1) the link in the text (replaces the selection)
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    c.insertText(f"[{number}]", link_format(nid))

    # 2) the note itself in <body name="notes">
    tail = QTextCursor(doc)
    if body is None:
        body = book.new_key("body")
        book.attrs[body] = {"name": "notes"}
        tail.movePosition(QTextCursor.MoveOperation.End)
        _append_block(tail, "title", f"{body}/{book.new_key('title')}", NOTES_TITLE)
    else:
        last = None
        for b in _body_blocks(doc, body):
            last = b
        tail.setPosition(last.position() + last.length() - 1)
    section = book.new_key("section")
    book.attrs[section] = {"id": nid}
    sec_path = f"{body}/{section}"
    _append_block(tail, "title", f"{sec_path}/{book.new_key('title')}", str(number), small=True)
    for p in paragraphs:
        _append_block(tail, "p", sec_path, p)
    c.endEditBlock()

    # text typed right after the link must not become part of it
    plain = QTextCharFormat(c.charFormat())
    plain.setAnchor(False)
    plain.setAnchorHref("")
    plain.clearProperty(C_LINK_TYPE)
    plain.setFontUnderline(False)
    plain.clearForeground()
    editor.setTextCursor(c)
    editor.setCurrentCharFormat(plain)
    return nid, number
