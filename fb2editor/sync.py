"""Synchronised scrolling of the two books.

Books are aligned by chapters (blocks that start a title).  Inside a chapter,
if both sides have the same number of non-empty paragraphs, paragraphs are
matched one-to-one; otherwise the chapter is mapped proportionally.
"""

from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import QObject, QPointF, Qt

from .fb2doc import P_KIND, P_PATH


class _Index:
    __slots__ = ("revision", "content", "anchors")

    def __init__(self, doc):
        self.revision = doc.revision()
        self.content: list[int] = []  # block numbers of non-empty blocks
        self.anchors: list[int] = [0]  # indices into content where chapters start
        prev_kind, prev_path, prev_body = None, None, None
        b = doc.begin()
        while b.isValid():
            bf = b.blockFormat()
            kind = bf.property(P_KIND)
            path = bf.property(P_PATH) or ""
            body = path.split("/", 1)[0]
            if b.text().strip():
                new_title = kind == "title" and not (prev_kind == "title" and prev_path == path)
                new_body = prev_body is not None and body != prev_body
                if (new_title or new_body) and self.content and self.anchors[-1] != len(self.content):
                    self.anchors.append(len(self.content))
                self.content.append(b.blockNumber())
                prev_kind, prev_path, prev_body = kind, path, body
            b = b.next()


class ScrollSync(QObject):
    def __init__(self, a, b, parent=None):
        super().__init__(parent)
        self.editors = (a, b)
        self.enabled = True
        self.paused = False
        self._busy = False
        self._cache: dict[int, _Index] = {}
        for e in self.editors:
            e.sync = self
            e.verticalScrollBar().valueChanged.connect(lambda _v, src=e: self._on_scroll(src))

    # ---------------------------------------------------------------- #
    def index(self, editor) -> _Index:
        doc = editor.document()
        idx = self._cache.get(id(doc))
        if idx is None or idx.revision != doc.revision():
            idx = _Index(doc)
            self._cache = {k: v for k, v in self._cache.items() if k in {id(e.document()) for e in self.editors}}
            self._cache[id(doc)] = idx
        return idx

    @staticmethod
    def _block_y(editor, number: int) -> float:
        doc = editor.document()
        if number >= doc.blockCount():
            return doc.documentLayout().documentSize().height()
        return doc.documentLayout().blockBoundingRect(doc.findBlockByNumber(number)).y()

    def _content_y(self, editor, idx: _Index, k: int) -> float:
        if k >= len(idx.content):
            return editor.document().documentLayout().documentSize().height()
        return self._block_y(editor, idx.content[k])

    def _segment(self, idx: _Index, other: _Index, k: int):
        n = min(len(idx.anchors), len(other.anchors))
        anchors = idx.anchors[:n]
        i = max(0, bisect_right(anchors, k) - 1)
        s0 = idx.anchors[i]
        s1 = idx.anchors[i + 1] if i + 1 < n else len(idx.content)
        d0 = other.anchors[i]
        d1 = other.anchors[i + 1] if i + 1 < n else len(other.content)
        return s0, s1, d0, d1

    def content_index_at(self, editor, idx: _Index, y: float) -> int:
        doc = editor.document()
        pos = doc.documentLayout().hitTest(QPointF(doc.documentMargin() + 2, y), Qt.HitTestAccuracy.FuzzyHit)
        if pos < 0:
            return len(idx.content) - 1
        number = doc.findBlock(pos).blockNumber()
        return max(0, bisect_right(idx.content, number) - 1)

    def map_y(self, src, dst, y: float) -> float:
        si, di = self.index(src), self.index(dst)
        if not si.content or not di.content:
            return 0.0
        k = self.content_index_at(src, si, y)
        s0, s1, d0, d1 = self._segment(si, di, k)
        if s1 - s0 == d1 - d0 and s1 > s0:
            ya, yb = self._content_y(src, si, k), self._content_y(src, si, k + 1)
            f = 0.0 if yb <= ya else min(1.0, max(0.0, (y - ya) / (yb - ya)))
            t = d0 + (k - s0)
            ta, tb = self._content_y(dst, di, t), self._content_y(dst, di, t + 1)
            return ta + f * (tb - ta)
        ya = self._content_y(src, si, s0) if s0 else 0.0
        yb = self._content_y(src, si, s1)
        f = 0.0 if yb <= ya else min(1.0, max(0.0, (y - ya) / (yb - ya)))
        ta = self._content_y(dst, di, d0) if d0 else 0.0
        tb = self._content_y(dst, di, d1)
        return ta + f * (tb - ta)

    def paired_block(self, src, block_number: int) -> int:
        """Block number in the other editor that corresponds to a block of src."""
        dst = self.editors[1] if src is self.editors[0] else self.editors[0]
        si, di = self.index(src), self.index(dst)
        if not si.content or not di.content:
            return -1
        k = max(0, bisect_right(si.content, block_number) - 1)
        s0, s1, d0, d1 = self._segment(si, di, k)
        if s1 - s0 == d1 - d0:
            t = d0 + (k - s0)
        else:
            span = max(1, s1 - s0)
            t = d0 + int(round((k - s0) * (d1 - d0) / span))
        t = min(max(t, 0), len(di.content) - 1)
        return di.content[t]

    # ---------------------------------------------------------------- #
    def _on_scroll(self, src):
        if not self.enabled or self.paused or self._busy:
            return
        self.align(src)

    def align(self, src):
        dst = self.editors[1] if src is self.editors[0] else self.editors[0]
        if src.book is None or dst.book is None:
            return
        ratio = 0.3
        ref = src.verticalScrollBar().value() + src.viewport().height() * ratio
        y = self.map_y(src, dst, ref)
        self._busy = True
        try:
            dst.verticalScrollBar().setValue(int(round(y - dst.viewport().height() * ratio)))
        finally:
            self._busy = False
