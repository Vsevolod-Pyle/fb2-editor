"""Conversion between FB2 (FictionBook 2) XML and an editable QTextDocument.

The body of the book is flattened into a sequence of text blocks.  Every block
remembers in its block format:

* ``P_KIND`` – the FB2 leaf element it came from (p, v, subtitle, title …),
* ``P_PATH`` – the chain of FB2 containers it lives in, e.g.
  ``body:1/section:4/title:5``.  Each container gets a unique key, so the
  original nesting of sections, epigraphs, poems etc. can be rebuilt on save.

Everything that is not body text (description, binaries, stylesheet, container
attributes) is kept in :class:`Fb2Book` and written back unchanged.
"""

from __future__ import annotations

import base64
import io
import itertools
import re
import zipfile

from lxml import etree
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
)

FB_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"
HREF = f"{{{XLINK_NS}}}href"

_USER = QTextFormat.Property.UserProperty.value
P_KIND = _USER + 1
P_PATH = _USER + 2
P_ID = _USER + 3
P_RAW = _USER + 4
C_LINK_TYPE = _USER + 20
C_CODE = _USER + 21
C_STYLE = _USER + 22

OBJ = "￼"  # QTextDocument placeholder for inline objects (images)

CONTAINERS = {"section", "epigraph", "poem", "stanza", "cite", "title", "annotation"}
TEXT_LEAVES = {"p", "v", "subtitle", "text-author", "date"}
# Block kinds that are rendered bold by the editor itself (bold is not exported).
HEADING_KINDS = {"title", "subtitle"}

IMAGE_MAX_W = 560
IMAGE_MAX_H = 680

_WS = re.compile(r"[ \t\r\n]+")


def local(el) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def get_href(el) -> str:
    for k, v in el.attrib.items():
        if k.rsplit("}", 1)[-1] == "href":
            return v
    return ""


def fb(tag: str) -> str:
    return f"{{{FB_NS}}}{tag}"


# --------------------------------------------------------------------------- #
#  Book container
# --------------------------------------------------------------------------- #


class Fb2Book:
    """Non-text parts of a book kept alongside the editable document."""

    def __init__(self):
        self.description: bytes | None = None
        self.stylesheets: list[bytes] = []
        self.binaries: dict[str, tuple[str, bytes]] = {}  # id -> (content-type, raw bytes)
        self.attrs: dict[str, dict[str, str]] = {}  # container key -> attributes
        self._counter = itertools.count(1)

    def new_key(self, tag: str) -> str:
        return f"{tag}:{next(self._counter)}"

    @property
    def title(self) -> str:
        if not self.description:
            return ""
        try:
            desc = etree.fromstring(self.description)
        except etree.XMLSyntaxError:
            return ""
        for el in desc.iter():
            if local(el) == "book-title":
                return " ".join("".join(el.itertext()).split())
        return ""

    def add_image(self, image: QImage) -> str:
        """Store a pasted image and return its binary id."""
        big = image.width() * image.height() > 600_000 and not image.hasAlphaChannel()
        fmt, ctype, ext = ("JPG", "image/jpeg", "jpg") if big else ("PNG", "image/png", "png")
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, fmt, 90)
        buf.close()
        n = 1
        while f"image{n}.{ext}" in self.binaries:
            n += 1
        bid = f"image{n}.{ext}"
        self.binaries[bid] = (ctype, bytes(ba.data()))
        return bid


# --------------------------------------------------------------------------- #
#  Formats
# --------------------------------------------------------------------------- #


def path_depth(path: str, tag: str) -> int:
    return sum(1 for k in path.split("/") if k.startswith(tag + ":"))


def block_format(kind: str, path: str) -> QTextBlockFormat:
    """Visual + semantic block format for a block of the given FB2 kind."""
    bf = QTextBlockFormat()
    bf.setProperty(P_KIND, kind)
    bf.setProperty(P_PATH, path)
    bf.setLineHeight(140, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    parts = [k.split(":", 1)[0] for k in path.split("/") if k]
    left = 0
    if "epigraph" in parts:
        left += 140
    if "cite" in parts:
        left += 36
    if "annotation" in parts:
        left += 24
    if "poem" in parts:
        left += 48
    if kind == "title":
        bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        bf.setTopMargin(26)
        bf.setBottomMargin(10)
        bf.setHeadingLevel(min(6, max(1, path_depth(path, "section"))))
    elif kind == "subtitle":
        bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        bf.setTopMargin(12)
        bf.setBottomMargin(6)
    elif kind in ("text-author", "date"):
        bf.setAlignment(Qt.AlignmentFlag.AlignRight)
        bf.setBottomMargin(8)
    elif kind == "image":
        bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        bf.setTopMargin(10)
        bf.setBottomMargin(10)
    elif kind == "raw":
        bf.setAlignment(Qt.AlignmentFlag.AlignLeft)
        bf.setBackground(QColor(128, 128, 128, 40))
    elif kind == "v":
        bf.setAlignment(Qt.AlignmentFlag.AlignLeft)
    else:  # p
        bf.setAlignment(Qt.AlignmentFlag.AlignJustify)
        if "epigraph" not in parts:
            bf.setTextIndent(28)
        bf.setBottomMargin(2)
    bf.setLeftMargin(left)
    return bf


def base_char_format(kind: str, path: str) -> QTextCharFormat:
    cf = QTextCharFormat()
    if kind == "title":
        depth = path_depth(path, "section")
        cf.setFontWeight(QFont.Weight.Bold)
        cf.setProperty(QTextFormat.Property.FontSizeAdjustment, 2 if depth <= 1 else 1)
    elif kind == "subtitle":
        cf.setFontWeight(QFont.Weight.Bold)
    elif kind in ("text-author", "date"):
        cf.setFontItalic(True)
    elif kind == "raw":
        cf.setForeground(QColor(128, 128, 128))
    return cf


def plain_char_format(cf: QTextCharFormat) -> QTextCharFormat:
    """Strip the block-kind decoration (heading size/bold) from a char format."""
    out = QTextCharFormat(cf)
    out.clearProperty(QTextFormat.Property.FontSizeAdjustment)
    out.clearProperty(QTextFormat.Property.FontWeight)
    return out


def image_format(name: str, image: QImage | None) -> QTextImageFormat:
    f = QTextImageFormat()
    f.setName(name)
    if image is not None and not image.isNull():
        w, h = image.width(), image.height()
        scale = min(1.0, IMAGE_MAX_W / max(w, 1), IMAGE_MAX_H / max(h, 1))
        f.setWidth(w * scale)
        f.setHeight(h * scale)
    return f


def register_image(doc: QTextDocument, name: str, data: bytes) -> QImage:
    img = QImage.fromData(data)
    if img.isNull():
        img = QImage(64, 48, QImage.Format.Format_ARGB32)
        img.fill(QColor(160, 160, 160))
    doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(name), img)
    return img


# --------------------------------------------------------------------------- #
#  Loading
# --------------------------------------------------------------------------- #


def read_fb2_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".fb2")] or zf.namelist()
            data = zf.read(names[0])
    return data


def _normalize_ns(root):
    """Bring namespace-less or oddly declared files to the standard FB2 namespace."""
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if not el.tag.startswith("{"):
            el.tag = fb(el.tag)
        for k in list(el.attrib):
            if k.rsplit("}", 1)[-1] == "href" and k != HREF:
                el.attrib[HREF] = el.attrib.pop(k)


class _Loader:
    def __init__(self, doc: QTextDocument, book: Fb2Book):
        self.doc = doc
        self.book = book
        self.cursor = QTextCursor(doc)
        self.first = True
        self.images: dict[str, QImage] = {}

    # -- block emission ----------------------------------------------------- #
    def _new_block(self, kind: str, path: str, el=None):
        bf = block_format(kind, path)
        if kind == "title" and not self.first:
            prev = self.cursor.block()
            if block_kind(prev) == "title" and block_path(prev) == path:
                bf.setTopMargin(2)  # next line of the same multi-line title
        if el is not None and el.get("id"):
            bf.setProperty(P_ID, el.get("id"))
        cf = base_char_format(kind, path)
        if self.first:
            self.cursor.setBlockFormat(bf)
            self.cursor.setBlockCharFormat(cf)
            self.first = False
        else:
            self.cursor.insertBlock(bf, cf)
        return cf

    def _image(self, href: str) -> QTextImageFormat:
        name = href.lstrip("#")
        return image_format(name, self.images.get(name))

    def text_block(self, el, kind: str, path: str):
        base = self._new_block(kind, path, el)
        pieces: list[tuple[str, QTextCharFormat]] = []
        self._inline(el, base, pieces)
        # collapse whitespace like a reader does
        out = []
        prev_space = True
        for text, fmt in pieces:
            if isinstance(fmt, QTextImageFormat):
                out.append((text, fmt))
                prev_space = False
                continue
            text = _WS.sub(" ", text)
            if prev_space and text.startswith(" "):
                text = text[1:]
            if not text:
                continue
            prev_space = text.endswith(" ")
            out.append((text, fmt))
        while out and not isinstance(out[-1][1], QTextImageFormat) and out[-1][0].endswith(" "):
            t = out[-1][0].rstrip(" ")
            if t:
                out[-1] = (t, out[-1][1])
                break
            out.pop()
        for text, fmt in out:
            if isinstance(fmt, QTextImageFormat):
                self.cursor.insertImage(fmt)
            else:
                self.cursor.insertText(text, fmt)

    def _inline(self, el, fmt: QTextCharFormat, out: list):
        if el.text:
            out.append((el.text, fmt))
        for ch in el:
            tag = local(ch)
            if tag == "image":
                out.append((OBJ, self._image(get_href(ch))))
            elif tag:
                f = QTextCharFormat(fmt)
                if tag == "strong":
                    f.setFontWeight(QFont.Weight.Bold)
                elif tag == "emphasis":
                    f.setFontItalic(True)
                elif tag == "strikethrough":
                    f.setFontStrikeOut(True)
                elif tag == "sup":
                    f.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
                elif tag == "sub":
                    f.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
                elif tag == "code":
                    f.setFontFixedPitch(True)
                    f.setFontFamilies(["Consolas", "Courier New", "monospace"])
                    f.setProperty(C_CODE, True)
                elif tag == "a":
                    f.setAnchor(True)
                    f.setAnchorHref(get_href(ch))
                    f.setFontUnderline(True)
                    if ch.get("type"):
                        f.setProperty(C_LINK_TYPE, ch.get("type"))
                elif tag == "style":
                    name = ch.get("name", "")
                    if name.startswith("color:"):
                        f.setForeground(QColor(name[6:]))
                    elif name:
                        f.setProperty(C_STYLE, name)
                self._inline(ch, f, out)
            if ch.tail:
                out.append((ch.tail, fmt))

    # -- structure walk ----------------------------------------------------- #
    def container(self, el, path: str):
        emitted = False
        for ch in el:
            tag = local(ch)
            if not tag:
                continue
            if tag in CONTAINERS:
                key = self.book.new_key(tag)
                if ch.attrib:
                    self.book.attrs[key] = dict(ch.attrib)
                self.container(ch, f"{path}/{key}")
            elif tag in TEXT_LEAVES:
                in_title = path.rsplit("/", 1)[-1].startswith("title:")
                self.text_block(ch, "title" if in_title and tag == "p" else tag, path)
            elif tag == "empty-line":
                in_title = path.rsplit("/", 1)[-1].startswith("title:")
                self._new_block("title" if in_title else "p", path, ch)
            elif tag == "image":
                self._new_block("image", path, ch)
                self.cursor.insertImage(self._image(get_href(ch)))
            else:  # table and anything unknown: kept verbatim
                self._new_block("raw", path, ch)
                tail = ch.tail
                ch.tail = None
                raw = etree.tostring(ch, encoding="unicode")
                ch.tail = tail
                fmt = self.cursor.blockFormat()
                fmt.setProperty(P_RAW, raw)
                self.cursor.setBlockFormat(fmt)
                text = " ".join(" ".join(ch.itertext()).split()) or f"[{tag}]"
                self.cursor.insertText(f"⟦{tag}⟧ {text}", base_char_format("raw", path))
            emitted = True
        if not emitted:
            self._new_block("p", path)


def load_fb2(data: bytes) -> tuple[QTextDocument, Fb2Book]:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(data, parser)
    if root is None:
        raise ValueError("Файл не является корректным FB2/XML")
    _normalize_ns(root)
    book = Fb2Book()
    doc = QTextDocument()
    doc.setUndoRedoEnabled(False)
    loader = _Loader(doc, book)

    for el in root:
        tag = local(el)
        if tag == "binary":
            bid = el.get("id", "")
            try:
                raw = base64.b64decode("".join((el.text or "").split()))
            except ValueError:
                raw = b""
            book.binaries[bid] = (el.get("content-type", "image/jpeg"), raw)
            loader.images[bid] = register_image(doc, bid, raw)
        elif tag == "description":
            book.description = etree.tostring(el, encoding="utf-8")
        elif tag == "stylesheet":
            book.stylesheets.append(etree.tostring(el, encoding="utf-8"))

    cursor = loader.cursor
    cursor.beginEditBlock()
    for el in root:
        if local(el) == "body":
            key = book.new_key("body")
            if el.attrib:
                book.attrs[key] = dict(el.attrib)
            loader.container(el, key)
    if loader.first:  # no body at all
        key = book.new_key("body")
        loader.container(etree.Element("body"), f"{key}/{book.new_key('section')}")
    cursor.endEditBlock()

    doc.setUndoRedoEnabled(True)
    doc.setModified(False)
    return doc, book


def new_document_from_text(text: str) -> tuple[QTextDocument, Fb2Book]:
    """Small helper used for empty projects/tests: plain text paragraphs → FB2."""
    paras = "".join(f"<p>{_esc(t)}</p>" for t in text.split("\n"))
    xml = (
        f'<FictionBook xmlns="{FB_NS}" xmlns:l="{XLINK_NS}"><description><title-info>'
        "<book-title>Новая книга</book-title></title-info></description>"
        f"<body><section>{paras}</section></body></FictionBook>"
    )
    return load_fb2(xml.encode("utf-8"))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
#  Saving
# --------------------------------------------------------------------------- #

_WRAP_ORDER = ("a", "strong", "emphasis", "strikethrough", "sup", "sub", "code", "style-color", "style")


def _wrappers(cf: QTextCharFormat, kind: str) -> list[tuple[str, tuple]]:
    w = []
    if cf.isAnchor() and cf.anchorHref():
        attrs = [(HREF, cf.anchorHref())]
        lt = cf.property(C_LINK_TYPE)
        if lt:
            attrs.append(("type", str(lt)))
        w.append(("a", tuple(attrs)))
    if cf.fontWeight() >= 600 and kind not in HEADING_KINDS:
        w.append(("strong", ()))
    if cf.fontItalic() and kind not in ("text-author", "date"):
        w.append(("emphasis", ()))
    if cf.fontStrikeOut():
        w.append(("strikethrough", ()))
    va = cf.verticalAlignment()
    if va == QTextCharFormat.VerticalAlignment.AlignSuperScript:
        w.append(("sup", ()))
    elif va == QTextCharFormat.VerticalAlignment.AlignSubScript:
        w.append(("sub", ()))
    if cf.property(C_CODE):
        w.append(("code", ()))
    if (
        cf.hasProperty(QTextFormat.Property.ForegroundBrush)
        and not cf.isAnchor()
        and kind != "raw"
        and cf.foreground().style() != Qt.BrushStyle.NoBrush
    ):
        w.append(("style", (("name", "color:" + cf.foreground().color().name()),)))
    if cf.property(C_STYLE):
        w.append(("style", (("name", str(cf.property(C_STYLE))),)))
    return w


def _append_text(parent, text: str):
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _block_pieces(block):
    """Yield (text, QTextCharFormat) for every fragment of the block."""
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        if frag.isValid():
            yield frag.text(), frag.charFormat()
        it += 1


def _fill_inline(el, block, kind: str, skip_images: bool = False):
    stack: list[tuple[tuple, object]] = [((), el)]  # (wrapper, element)
    for text, cf in _block_pieces(block):
        if skip_images and cf.isImageFormat():
            continue
        wr = _wrappers(cf, kind)
        common = 0
        while common < len(wr) and common + 1 < len(stack) and stack[common + 1][0] == wr[common]:
            common += 1
        del stack[common + 1 :]
        for w in wr[common:]:
            child = etree.SubElement(stack[-1][1], fb(w[0]), dict(w[1]))
            stack.append((w, child))
        target = stack[-1][1]
        if cf.isImageFormat():
            name = cf.toImageFormat().name()
            for _ in text:
                etree.SubElement(target, fb("image"), {HREF: "#" + name})
        else:
            _append_text(target, text.replace(" ", " ").replace(" ", " "))


def block_kind(block) -> str:
    k = block.blockFormat().property(P_KIND)
    return k if isinstance(k, str) and k else "p"


def block_path(block) -> str:
    p = block.blockFormat().property(P_PATH)
    return p if isinstance(p, str) else ""


def _has_content(block) -> bool:
    return bool(block.text().replace(OBJ, "x").strip())


def save_fb2(doc: QTextDocument, book: Fb2Book) -> bytes:
    root = etree.Element(fb("FictionBook"), nsmap={None: FB_NS, "l": XLINK_NS})
    root.text = "\n"
    for ss in book.stylesheets:
        el = etree.fromstring(ss)
        el.tail = "\n"
        root.append(el)
    if book.description:
        desc = etree.fromstring(book.description)
    else:
        desc = etree.fromstring(
            f'<description xmlns="{FB_NS}"><title-info><book-title>Без названия</book-title>'
            "</title-info></description>"
        )
    desc.tail = "\n"
    root.append(desc)

    default_body = book.new_key("body")
    stack: list[tuple[str | None, object]] = [(None, root)]
    closed: set[str] = set()
    used_images: set[str] = set()
    last_path = f"{default_body}/{book.new_key('section')}"

    block = doc.begin()
    while block.isValid():
        kind = block_kind(block)
        path = block_path(block) or last_path
        if not path.startswith("body:"):
            path = f"{default_body}/{path}"
        last_path = path
        keys = path.split("/")
        i = 0
        while i < len(keys) and i + 1 < len(stack) and stack[i + 1][0] == keys[i]:
            i += 1
        for k, _el in stack[i + 1 :]:
            closed.add(k)
        del stack[i + 1 :]
        for k in keys[i:]:
            tag = k.split(":", 1)[0]
            attrs = dict(book.attrs.get(k, {}))
            if k in closed:
                attrs.pop("id", None)
            el = etree.SubElement(stack[-1][1], fb(tag), attrs)
            el.text = "\n"
            el.tail = "\n"
            stack.append((k, el))
        parent = stack[-1][1]
        parent_tag = local(parent)
        bf = block.blockFormat()
        extra = {}
        if bf.property(P_ID):
            extra["id"] = str(bf.property(P_ID))

        if kind == "raw" and bf.property(P_RAW):
            try:
                el = etree.fromstring(str(bf.property(P_RAW)))
                el.tail = "\n"
                parent.append(el)
            except etree.XMLSyntaxError:
                pass
        elif kind == "image":
            text_left = False
            for text, cf in _block_pieces(block):
                if cf.isImageFormat():
                    name = cf.toImageFormat().name()
                    el = etree.SubElement(parent, fb("image"), {HREF: "#" + name})
                    el.tail = "\n"
                elif text.strip():
                    text_left = True
            if text_left:
                el = etree.SubElement(parent, fb("p"))
                el.tail = "\n"
                _fill_inline(el, block, "p", skip_images=True)
        elif not _has_content(block):
            if parent_tag not in ("stanza", "poem"):
                el = etree.SubElement(parent, fb("empty-line"), extra)
                el.tail = "\n"
        else:
            tag = kind if kind in TEXT_LEAVES else "p"
            if tag == "v" and parent_tag != "stanza":
                tag = "p"
            if parent_tag == "stanza" and tag not in ("v", "subtitle"):
                tag = "v"
            el = etree.SubElement(parent, fb(tag), extra)
            el.tail = "\n"
            _fill_inline(el, block, kind)
        block = block.next()

    for el in root.iter(fb("image")):
        used_images.add(el.get(HREF, "").lstrip("#"))
    for el in desc.iter():
        if local(el) == "image":
            used_images.add(get_href(el).lstrip("#"))

    for bid, (ctype, raw) in book.binaries.items():
        if bid not in used_images:
            continue
        el = etree.SubElement(root, fb("binary"), {"id": bid, "content-type": ctype})
        el.text = "\n" + base64.encodebytes(raw).decode("ascii")
        el.tail = "\n"

    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


def text_of(doc: QTextDocument) -> str:
    """Plain text of the document (used by tests)."""
    return doc.toPlainText()
