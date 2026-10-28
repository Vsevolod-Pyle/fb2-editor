import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QTextCharFormat, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fb2editor.app import MainWindow  # noqa: E402
from fb2editor.fb2doc import P_PATH, read_fb2_bytes  # noqa: E402
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


def test_window_fits_small_screens():
    w, _p = _window()
    # must fit a 1280px-wide screen (fonts on Windows are wider than on Linux)
    assert w.minimumSizeHint().width() <= 1150, w.minimumSizeHint()
    # hidden pages (the welcome screen) must not make the window wider than the books need
    assert w.content.minimumSizeHint().width() <= w.splitter.minimumSizeHint().width() + 40
    w.resize(1100, 700)
    app.processEvents()
    assert w.top_bar.layout().minimumSize().width() <= w.top_bar.width()
    w.resize(2400, 900)
    app.processEvents()
    assert w.font_box.isVisible()
    w.close()


def test_middle_bar_scrolls_both_books():
    w, _p = _window()
    L, R = w.left.editor, w.right.editor
    w.middle.bar.setValue(MIDDLE_HALF := w.middle.STEPS // 2)
    app.processEvents()
    assert L.verticalScrollBar().value() > 0 and R.verticalScrollBar().value() > 0
    w.sync.enabled = False
    w.middle.bar.setValue(w.middle.STEPS)
    app.processEvents()
    assert L.verticalScrollBar().value() == L.verticalScrollBar().maximum()
    assert R.verticalScrollBar().value() == R.verticalScrollBar().maximum()
    L.verticalScrollBar().setValue(0)
    app.processEvents()
    assert w.middle.bar.value() == 0 and MIDDLE_HALF
    w.close()


def test_footnotes():
    from fb2editor.editor import BookEditor
    from fb2editor.fb2doc import load_fb2

    here = os.path.dirname(os.path.abspath(__file__))
    doc, book = load_fb2(open(os.path.join(here, "sample.fb2"), "rb").read())
    ed = BookEditor("left")
    ed.set_book(doc, book)
    ed.resize(600, 400)
    ed.show()
    app.processEvents()
    title, body = ed.note_content("#n1")
    assert title == "1" and "Текст сноски." in body
    target = ed.note_target("#n1")[0]
    assert doc.findBlockByNumber(target).text() == "1"
    start = ed.textCursor().position()
    ed.jump_to_block(target)
    assert ed.textCursor().block().blockNumber() == target
    assert ed.go_back() and ed.textCursor().position() == start


def _wait_speller(speller, timeout=90000):
    # QTest.qWait keeps the GIL and starves the loader thread: sleep in Python instead
    import time

    deadline = time.time() + timeout / 1000
    while not speller.loaded and not speller.done and time.time() < deadline:
        time.sleep(0.05)
        app.processEvents()
    assert speller.loaded, speller.error


def test_spelling_numbers_progress_and_double_click():
    from fb2editor.spell import Speller

    sp = Speller(os.path.join(tempfile.mkdtemp(), "user_words.txt"))
    _wait_speller(sp)
    for w in ("переводчиками", "прочитавшие", "ёлка", "whispered", "Translator", "что-то"):
        assert sp.check(w), w
    for w in ("кароко", "переводчиак", "recieve"):
        assert not sp.check(w), w
    assert "переводчика" in sp.suggest("переводчиак")
    sp.add_word("Кароко")
    assert sp.check("кароко")

    w, p = _window()
    L, R = w.left.editor, w.right.editor
    _wait_speller(w.speller)
    c = L.textCursor()
    c.setPosition(L.document().findBlockByNumber(2).position())
    L.setTextCursor(c)
    L.insertPlainText("Ашибка ")
    R.setFocus()  # the word being typed is not underlined while the editor has focus
    L.refresh_spelling()
    words = [s.cursor.selectedText() for s in L._spell_sels]
    assert "Ашибка" in words, words

    # paragraph numbering and progress
    assert L.gutter.width() > 0
    w.update_progress()
    assert w.left.progress.text().startswith("¶ 1 / ")
    L.verticalScrollBar().setValue(L.verticalScrollBar().maximum())
    app.processEvents()
    w.update_progress()
    assert "100,0%" in w.left.progress.text(), w.left.progress.text()
    total = len(w.sync.index(L).content)
    assert w.left.progress.text().startswith(f"¶ {total} / {total}")

    # double click on a paragraph shows the matching paragraph in the other book
    w.sync.enabled = False
    number = 20
    src_rect = L.document().documentLayout().blockBoundingRect(L.document().findBlockByNumber(number))
    L.verticalScrollBar().setValue(int(src_rect.y()) - 100)
    R.verticalScrollBar().setValue(R.verticalScrollBar().maximum())
    app.processEvents()
    w.show_in_other(L, number)
    app.processEvents()
    assert R._flash_block == w.sync.paired_block(L, number)
    target = R.document().findBlockByNumber(R._flash_block)
    assert target.text().split(" ")[1] == L.document().findBlockByNumber(number).text().split(" ")[1]
    rect = R.document().documentLayout().blockBoundingRect(target)
    shown = rect.y() - R.verticalScrollBar().value()
    assert abs(shown - (src_rect.y() - L.verticalScrollBar().value())) < 2, shown
    L.document().setModified(False)
    w.close()


def test_project_notes():
    import json

    w, p = _window()
    L = w.left.editor
    doc = L.document()
    block = doc.findBlockByNumber(5)
    c = QTextCursor(doc)
    c.setPosition(block.position() + 4)
    c.setPosition(block.position() + 12, QTextCursor.MoveMode.KeepAnchor)
    quote = c.selectedText()
    L.setTextCursor(c)
    start, end = L.note_span()
    n = w.notes.add("left", L, start, end, "проверить термин")
    assert n["quote"] == quote and w.notes_panel.list.count() == 1
    assert L._note_sels and 5 in L._note_blocks

    # the note follows edits made before it
    c0 = QTextCursor(doc)
    c0.setPosition(doc.findBlockByNumber(2).position())
    c0.insertText("Вставка в начало. ")
    r = w.notes.range_of(n["id"])
    c1 = QTextCursor(doc)
    c1.setPosition(r[0])
    c1.setPosition(r[1], QTextCursor.MoveMode.KeepAnchor)
    assert c1.selectedText() == quote

    # stored in project.json only, not in the book
    w.save_state()
    data = json.load(open(os.path.join(p.root, "project.json"), encoding="utf-8"))
    assert data["notes"][0]["text"] == "проверить термин"
    assert "проверить термин" not in w._serialize("left").decode()

    # reload the original version (without the insertion): the quote is found again
    L.document().setModified(False)
    w._load_side("left", p.current("left"))
    r = w.notes.range_of(n["id"])
    c2 = QTextCursor(L.document())
    c2.setPosition(r[0])
    c2.setPosition(r[1], QTextCursor.MoveMode.KeepAnchor)
    assert c2.selectedText() == quote

    # jump from the panel
    L.verticalScrollBar().setValue(L.verticalScrollBar().maximum())
    w.goto_note(n["id"])
    assert L.textCursor().selectedText() == quote
    w.notes.edit(n["id"], "новый текст")
    assert w.notes.get(n["id"])["text"] == "новый текст"
    w.notes.remove(n["id"])
    assert not w.notes.items and not L._note_sels
    L.document().setModified(False)
    w.close()


def test_em_dash_shortcut():
    w, _p = _window()
    L = w.left.editor
    L.setFocus()
    w._set_active(L)
    c = L.textCursor()
    c.setPosition(L.document().findBlockByNumber(2).position())
    L.setTextCursor(c)
    QTest.keyClick(L, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(L, Qt.Key.Key_Underscore, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert L.document().findBlockByNumber(2).text().startswith("——")
    w.act["dash"].trigger()
    assert L.document().findBlockByNumber(2).text().startswith("———")
    L.document().setModified(False)
    w.close()


def _notes_book(nested: bool) -> bytes:
    """A book with 3 existing notes; nested=True keeps them inside a 'Примечания' section of the main body."""
    text = "".join(
        f'<section><title><p>Глава {c}</p></title><p>Начало главы {c} <a l:href="#n{c}" type="note">[{c}]</a> '
        f"и продолжение.</p><p>Второй абзац главы {c}.</p></section>" for c in (1, 2, 3))
    notes = "".join(f'<section id="n{c}"><title><p>{c}</p></title><p>Старое примечание {c}.</p></section>'
                    for c in (1, 2, 3))
    if nested:
        bodies = f"<body>{text}<section><title><p>Примечания</p></title>{notes}</section></body>"
    else:
        bodies = f'<body>{text}</body><body name="notes"><title><p>Примечания</p></title>{notes}</body>'
    return ('<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            'xmlns:l="http://www.w3.org/1999/xlink"><description><title-info><book-title>N</book-title>'
            f"</title-info></description>{bodies}</FictionBook>").encode()


def test_footnotes_join_existing_notes_and_keep_order():
    from fb2editor.editor import BookEditor
    from fb2editor.fb2doc import load_fb2, save_fb2
    from fb2editor.footnotes import add_footnote, paragraphs_of

    for nested in (False, True):
        doc, book = load_fb2(_notes_book(nested))
        ed = BookEditor("left")
        ed.set_book(doc, book)
        # select a formatted phrase in chapter 1's second paragraph and make it a note
        block = next(b for b in (doc.findBlockByNumber(i) for i in range(doc.blockCount()))
                     if b.text() == "Второй абзац главы 1.")
        c = QTextCursor(doc)
        c.setPosition(block.position() + 7)
        c.setPosition(block.position() + 12, QTextCursor.MoveMode.KeepAnchor)  # "абзац"
        f = QTextCharFormat()
        f.setFontItalic(True)
        c.mergeCharFormat(f)
        start, end = c.selectionStart(), c.selectionEnd()
        content = paragraphs_of(doc, start, end)
        nid, number = add_footnote(ed, start, end, content)
        assert number == 2, number  # between the old [1] and [2]
        out = save_fb2(doc, book).decode()
        # old notes 2 and 3 became 3 and 4
        assert out.count('type="note">[') == 4
        for n, target in ((1, "n1"), (2, nid), (3, "n2"), (4, "n3")):
            assert f'<a l:href="#{target}" type="note">[{n}]</a>' in out, (n, target, nested)
        # the new note sits in the same container, in reading order, with its italic kept
        i1, inew, i2 = out.index('<section id="n1">'), out.index(f'<section id="{nid}">'), out.index('<section id="n2">')
        assert i1 < inew < i2
        assert out.count("Примечания") == 1
        new_sec = out[inew:out.index("</section>", inew)]
        assert "<title>\n<p>2</p>" in new_sec and "<emphasis>абзац</emphasis>" in new_sec, new_sec
        assert '<section id="n2">\n<title>\n<p>3</p>' in out
        # a note at the very end of the text gets the last number
        last = next(b for b in (doc.findBlockByNumber(i) for i in range(doc.blockCount()))
                    if b.text() == "Второй абзац главы 3.")
        pos = last.position() + last.length() - 1
        assert add_footnote(ed, pos, pos, "Последнее.")[1] == 5
        # undo of the last note restores numbering and sections
        doc.undo()
        assert save_fb2(doc, book).decode() == out


def test_make_footnote_from_selection():
    from fb2editor.fb2doc import load_fb2, save_fb2
    from fb2editor.footnotes import add_footnote

    w, _p = _window()
    L = w.left.editor
    doc = L.document()
    block = doc.findBlockByNumber(3)
    c = QTextCursor(doc)
    c.setPosition(block.position() + block.length() - 1)
    c.insertText(" (прим. пер.: игра слов)")
    end = c.position()
    start = end - len(" (прим. пер.: игра слов)")
    nid, number = add_footnote(L, start, end, "Прим. пер.: игра слов.")
    assert number == 1
    assert doc.findBlockByNumber(3).text().endswith("[1]")
    # created later but earlier in the text: becomes [1], the first one becomes [2]
    early = doc.findBlockByNumber(2)
    nid2, number2 = add_footnote(L, early.position() + 3, early.position() + 3, "Раннее примечание.")
    assert number2 == 1
    assert doc.findBlockByNumber(3).text().endswith("[2]")
    # the notes are shown at the end of the book, in order
    assert doc.lastBlock().text() == "Прим. пер.: игра слов."
    title, body = L.note_content("#" + nid)
    assert title == "2" and "игра слов" in body

    out = save_fb2(doc, L.book).decode()
    assert f'<a l:href="#{nid}" type="note">[2]</a>' in out
    assert '<body name="notes">' in out and out.index(f'<section id="{nid2}">') < out.index(f'<section id="{nid}">')
    # reopened file: the notes body is reused
    doc2, book2 = load_fb2(out.encode())
    L.set_book(doc2, book2)
    end_pos = doc2.findBlockByNumber(5).position()
    assert add_footnote(L, end_pos, end_pos, "Третье.")[1] == 3
    assert save_fb2(doc2, book2).decode().count('<body name="notes">') == 1
    doc2.undo()
    assert save_fb2(doc2, book2).decode() == out
    L.document().setModified(False)
    w.close()


def test_jump_from_footnote_back_to_text():
    from fb2editor.editor import BookEditor
    from fb2editor.fb2doc import load_fb2

    doc, book = load_fb2(_notes_book(False))
    ed = BookEditor("left")
    ed.set_book(doc, book)
    ed.resize(700, 500)
    ed.show()
    app.processEvents()
    blocks = [doc.findBlockByNumber(i) for i in range(doc.blockCount())]
    note2_title = next(b for b in blocks if b.text() == "2" and "section" in b.blockFormat().property(P_PATH))
    note2_text = next(b for b in blocks if b.text() == "Старое примечание 2.")
    link_block = next(b for b in blocks if b.text().startswith("Начало главы 2"))
    ed.refresh_spelling()
    # the note number is shown as a link back to the text
    assert ed._back_titles.get(note2_title.blockNumber()) == "n2"
    assert ed.footnote_of_block(note2_text) == "n2"
    c = QTextCursor(note2_text)
    ed.setTextCursor(c)
    assert ed.jump_to_reference("n2")
    assert ed.textCursor().block() == link_block and ed.textCursor().selectedText() == "[2]"
    assert ed.go_back() and ed.textCursor().block() == note2_text


def test_single_book_projects(monkeypatch=None):
    from PySide6.QtWidgets import QFileDialog

    import fb2editor.app as appmod

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "book.fb2")
    with open(path, "wb") as fh:
        fh.write(_book("ru").replace(b"<book-title>T</book-title>", b"<book-title>Moya kniga</book-title><lang>ru</lang>"))
    store = ProjectStore(os.path.join(tmp, "data"))
    w = appmod.MainWindow(store)
    w.resize(1300, 800)
    w.show()
    orig = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))
    try:
        w.open_book()
        p = w.project
        assert p.single and p.name == "Moya kniga" and p.label("left") == "RU"
        assert w.left.editor.book is not None
        assert not w.right.isVisible() and not w.middle.isVisible()
        assert not w.act["two_books"].isChecked() and not w.act["sync"].isEnabled()
        # opening the same file again reopens its project instead of making a copy
        w.open_book()
        assert len(store.list()) == 1 and w.project.id == p.id
    finally:
        QFileDialog.getOpenFileName = orig
    # switch to two books: the right side waits for a second file
    w.act["two_books"].setChecked(True)
    assert not w.project.single and w.right.isVisible() and w.middle.isVisible()
    assert w.right.stack.currentIndex() == 1  # "open FB2" placeholder
    w.act["two_books"].setChecked(False)
    assert w.store.open(p.id).single
    w.close()
