import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fb2editor.app import MainWindow  # noqa: E402
from fb2editor.fb2doc import read_fb2_bytes  # noqa: E402
from fb2editor.projects import ProjectStore  # noqa: E402

app = QApplication.instance() or QApplication([])


def _book(lang: str, chapters=4, paras=12) -> bytes:
    word = "Глава" if lang == "ru" else "Chapter"
    secs = []
    for c in range(1, chapters + 1):
        ps = "".join(f"<p>{word} {c}.{i} " + "text " * (5 + (i * 7 + c) % 30) + "</p>" for i in range(1, paras + 1))
        secs.append(f"<section><title><p>{word} {c}</p></title>{ps}</section>")
    return (
        '<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
        'xmlns:l="http://www.w3.org/1999/xlink"><description><title-info><book-title>T</book-title>'
        f"</title-info></description><body>{''.join(secs)}</body></FictionBook>"
    ).encode()


def _window():
    tmp = tempfile.mkdtemp()
    for lang in ("ru", "en"):
        with open(f"{tmp}/{lang}.fb2", "wb") as fh:
            fh.write(_book(lang))
    store = ProjectStore(os.path.join(tmp, "data"))
    w = MainWindow(store)
    w.resize(1300, 800)
    w.show()
    p = store.create("Test")
    for side, lang in (("left", "ru"), ("right", "en")):
        p.import_file(side, f"{tmp}/{lang}.fb2", read_fb2_bytes(f"{tmp}/{lang}.fb2"))
    w._open(p)
    QTest.qWait(100)
    return w, p


def test_sync_scroll_matches_paragraphs():
    w, _p = _window()
    L, R = w.left.editor, w.right.editor

    def ids(e):
        # the books are aligned on a line at 30% of the window height;
        # look a couple of pixels around it to ignore sub-pixel rounding at paragraph borders
        out = set()
        for dy in (-2, 2):
            pt = e.viewport().rect().center()
            pt.setY(int(e.viewport().height() * 0.3) + dy)
            out.add(e.cursorForPosition(pt).block().text().split(" ")[1])
        return out

    for value in (300, 900, 1500, 2100):
        L.verticalScrollBar().setValue(value)
        app.processEvents()
        assert ids(L) & ids(R), (value, ids(L), ids(R))
    R.verticalScrollBar().setValue(1200)
    app.processEvents()
    assert ids(L) & ids(R)
    w.close()


def test_editing_and_saving():
    w, p = _window()
    L = w.left.editor
    L.setFocus()
    w._set_active(L)
    c = L.textCursor()
    c.setPosition(L.document().findBlockByNumber(3).position())
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    L.setTextCursor(c)
    QTest.keyClick(L, Qt.Key.Key_Return)
    L.insertPlainText("Новая глава")
    QTest.keyClick(L, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert L.current_style() == "title"
    QTest.keyClick(L, Qt.Key.Key_Return)
    assert L.current_style() == "normal"
    L.insertPlainText("Это ")
    QTest.keyClick(L, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    L.insertPlainText("жирное")
    QTest.keyClick(L, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(L, Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier)
    L.insertPlainText(" и курсив")
    QTest.keyClick(L, Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(L, Qt.Key.Key_Return)

    img = QImage(80, 50, QImage.Format.Format_RGB32)
    img.fill(QColor("#e07a2f"))
    md = QMimeData()
    md.setImageData(img)
    L.insertFromMimeData(md)
    QTest.keyClick(L, Qt.Key.Key_Return)
    md2 = QMimeData()
    md2.setHtml("<p>Вставка <b>html</b> <span style='color:#222'>серый</span> <i>курсив</i></p><p>второй</p>")
    L.insertFromMimeData(md2)
    c = L.textCursor()
    c.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
    L.setTextCursor(c)
    w._pick_color("#2f6fe0")
    c.clearSelection()
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    L.setTextCursor(c)

    assert L.document().isModified()
    w.quick_save()
    L.insertPlainText(" ещё")
    w.quick_save()
    kinds = [v.kind for v in p.versions("left")]
    assert kinds == ["original", "quick"], kinds
    L.insertPlainText("!")
    data = w._serialize("left")
    p.add_version("left", data, "manual", "test")
    assert [v.kind for v in p.versions("left")] == ["original", "quick", "manual"]

    out = data.decode()
    assert "<section>\n<title>\n<p>Новая глава</p>\n</title>\n<p>Это <strong>жирное</strong>" \
           "<emphasis> и курсив</emphasis></p>" in out, out[:3000]
    assert '<image l:href="#image1.png"/>' in out
    assert '<binary id="image1.png" content-type="image/png">' in out
    assert "<p>Вставка <strong>html</strong> серый <emphasis>курсив</emphasis></p>" in out
    assert "<style name=\"color:#2f6fe0\">второй ещё!</style>" in out or \
           '<style name="color:#2f6fe0">второй</style> ещё!' in out
    assert out.count("<section>") == 5

    # zoom shortcuts are shared by both books
    z = w.zoom
    QTest.keyClick(L, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert w.zoom == z + 1
    assert w.right.editor.document().defaultFont().pointSizeF() == z + 1
    QTest.keyClick(L, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    assert w.zoom == z

    w.save_state()
    assert "left" in p.state and "block" in p.state["left"]
    L.document().setModified(False)
    w.close()


if __name__ == "__main__":
    test_sync_scroll_matches_paragraphs()
    test_editing_and_saving()
    print("ok")
