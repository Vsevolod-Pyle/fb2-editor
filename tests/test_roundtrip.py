import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import etree  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fb2editor.fb2doc import load_fb2, save_fb2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
app = QApplication.instance() or QApplication([])


def _text(xml: bytes) -> str:
    root = etree.fromstring(xml)
    ns = {"f": "http://www.gribuser.ru/xml/fictionbook/2.0"}
    return " ".join(" ".join(t.split()) for b in root.findall("f:body", ns) for t in b.itertext() if t.strip())


def test_roundtrip_is_stable():
    data = open(os.path.join(HERE, "sample.fb2"), "rb").read()
    doc, book = load_fb2(data)
    out1 = save_fb2(doc, book)
    doc2, book2 = load_fb2(out1)
    out2 = save_fb2(doc2, book2)
    assert out1 == out2
    assert _text(data) == _text(out1)
    for marker in (b'<section id="ch1">', b"<strong>", b"<emphasis>", b'type="note"', b"<sub>", b"<sup>",
                   b"<stanza>", b"<epigraph>", b"<text-author>", b"<cite>", b'name="notes"',
                   b'name="color:#cc0000"', b"<table>", b'<binary id="cover.png"', b"<empty-line/>"):
        assert marker in out1, marker
    assert book.title == "Пробная книга"
    from fb2editor.fb2doc import block_kind
    kinds = []
    b = doc.begin()
    while b.isValid():
        kinds.append((block_kind(b), b.text()))
        b = b.next()
    assert ("title", "Глава первая") in kinds and ("title", "Начало") in kinds
    assert ("v", "Вторая строка") in kinds and ("subtitle", "* * *") in kinds


if __name__ == "__main__":
    test_roundtrip_is_stable()
    print("ok")
