"""Main window of FB2 Translation Editor."""

from __future__ import annotations

import os
import sys
from bisect import bisect_right
import time
from functools import partial

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QSize, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import (
    QAction,
    QCursor,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .dialogs import FB2_FILTER, NewProjectDialog, SaveVersionDialog
from .editor import STYLES, BookEditor
from .fb2doc import block_kind, block_path, load_fb2, read_fb2_bytes, save_fb2
from .projects import SIDES, Project, ProjectStore
from .notes import NoteDialog, Notes, NotesPanel
from .spell import Speller
from .sync import ScrollSync

APP_NAME = "FB2 Translation Editor"

COLORS = [
    ("Красный", "#d93a3a"),
    ("Оранжевый", "#e8820c"),
    ("Жёлтый", "#c9a400"),
    ("Зелёный", "#2f9e44"),
    ("Бирюзовый", "#0c9aa6"),
    ("Синий", "#2f6fe0"),
    ("Фиолетовый", "#8a3ffc"),
    ("Серый", "#868e96"),
]

ZOOM_MIN, ZOOM_MAX, ZOOM_DEFAULT = 7, 40, 13


def hline(vertical=True) -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    f.setFixedWidth(1)
    return f


# --------------------------------------------------------------------------- #
#  Sidebar with the list of projects
# --------------------------------------------------------------------------- #


class ProjectDelegate(QStyledItemDelegate):
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def sizeHint(self, option, index):
        return QSize(200, 52)

    def paint(self, p, option, index):
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, p, option.widget)
        c = self.win.colors
        r = option.rect.adjusted(14, 7, -10, -7)
        name = index.data(Qt.ItemDataRole.DisplayRole)
        sub = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        p.save()
        f = QFont(option.font)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(c["text"]))
        fm = p.fontMetrics()
        p.drawText(r.adjusted(0, 0, 0, -r.height() // 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, r.width()))
        f.setWeight(QFont.Weight.Normal)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(QColor(c["muted"]))
        fm = p.fontMetrics()
        p.drawText(r.adjusted(0, r.height() // 2, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(sub, Qt.TextElideMode.ElideRight, r.width()))
        p.restore()


class Sidebar(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("sidebar")
        self.setFixedWidth(260)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 10, 0)
        title = QLabel("Проекты")
        title.setObjectName("sidebarTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.add_btn = QToolButton()
        self.add_btn.setToolTip("Новый проект (Ctrl+N)")
        self.add_btn.clicked.connect(win.new_project)
        head.addWidget(self.add_btn)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setItemDelegate(ProjectDelegate(win))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemClicked.connect(self._clicked)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        lay.addWidget(self.list, 1)

    def refresh(self, current_id: str | None):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.win.store.list():
            sides = " · ".join(p.label(s) for s in SIDES if p.versions(s))
            stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(p.updated))
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{sides or 'нет книг'}  ·  {stamp}")
            item.setToolTip(p.name)
            self.list.addItem(item)
            if p.id == current_id:
                item.setSelected(True)
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def _clicked(self, item):
        pid = item.data(Qt.ItemDataRole.UserRole)
        if not self.win.project or self.win.project.id != pid:
            if not self.win.open_project(pid):
                self.refresh(self.win.project.id if self.win.project else None)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Открыть", lambda: self.win.open_project(pid))
        m.addAction("Переименовать…", lambda: self.win.rename_project(pid))
        m.addAction("Открыть папку проекта", lambda: self.win.open_folder(pid))
        m.addSeparator()
        m.addAction("Удалить проект…", lambda: self.win.delete_project(pid))
        m.exec(self.list.mapToGlobal(pos))



# --------------------------------------------------------------------------- #
#  Responsive top bar and the shared scroll bar between the books
# --------------------------------------------------------------------------- #


class TopBar(QFrame):
    """Tool bar that hides less important controls when the window is narrow."""

    def __init__(self, win):
        super().__init__()
        self.win = win

    def minimumSizeHint(self):
        return QSize(360, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.win._fit_toolbar()


class MiddleBar(QFrame):
    """A scroll bar between the two books that scrolls both of them at once."""

    WIDTH = 18
    STEPS = 10000

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("middleBar")
        self.setFixedWidth(self.WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        self.bar = QScrollBar(Qt.Orientation.Vertical)
        self.bar.setObjectName("middleScroll")
        self.bar.setRange(0, self.STEPS)
        self.bar.setSingleStep(40)
        self.bar.setToolTip("Прокрутка обеих книг сразу")
        lay.addWidget(self.bar)
        self._updating = False
        self.bar.valueChanged.connect(self._moved)
        self.bar.sliderMoved.connect(self._show_chapter)

    def lead(self):
        for ed in (self.win.left.editor, self.win.right.editor):
            if ed.book:
                return ed
        return None

    def update_from_books(self):
        ed = self.lead()
        if ed is None or self.bar.isSliderDown():
            return
        sb = ed.verticalScrollBar()
        total = sb.maximum() + sb.pageStep()
        self._updating = True
        try:
            self.bar.setPageStep(max(1, int(self.STEPS * sb.pageStep() / max(1, total))))
            self.bar.setValue(int(round(self.STEPS * sb.value() / max(1, sb.maximum()))))
        finally:
            self._updating = False

    def _moved(self, value: int):
        if self._updating:
            return
        frac = value / self.STEPS
        eds = [e for e in (self.win.left.editor, self.win.right.editor) if e.book]
        if not eds:
            return
        sync = self.win.sync
        if sync.enabled and len(eds) == 2:
            sb = eds[0].verticalScrollBar()
            sb.setValue(int(round(frac * sb.maximum())))
        else:
            sync.paused = True
            try:
                for ed in eds:
                    sb = ed.verticalScrollBar()
                    sb.setValue(int(round(frac * sb.maximum())))
            finally:
                sync.paused = False

    def _show_chapter(self, _value: int):
        ed = self.lead()
        if ed is None:
            return
        title = self.win.chapter_title(ed)
        if title:
            QToolTip.showText(QCursor.pos(), title, self.bar)

# --------------------------------------------------------------------------- #
#  One side: header + editor
# --------------------------------------------------------------------------- #


class Pane(QFrame):
    def __init__(self, win, side: str):
        super().__init__()
        self.win = win
        self.side = side
        self.setObjectName("pane")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QFrame()
        header.setObjectName("paneHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 6, 6)
        h.setSpacing(8)
        self.badge = QLabel("RU")
        self.badge.setObjectName("badge")
        self.badge.setToolTip("Метка книги — двойной щелчок, чтобы изменить")
        self.badge.installEventFilter(self)
        self.title = QLabel("")
        self.title.setObjectName("paneTitle")
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.dirty = QLabel("●")
        self.dirty.setObjectName("dirty")
        self.dirty.setToolTip("Есть несохранённые изменения")
        self.dirty.hide()
        self.progress = QLabel("")
        self.progress.setObjectName("progress")
        self.progress.setToolTip("Номер абзаца в строке чтения и сколько книги пройдено")
        self.progress.setMinimumWidth(1)  # may be clipped in a very narrow window
        self.versions = QComboBox()
        self.versions.setObjectName("flat")
        self.versions.setToolTip("Какую версию файла показывать")
        self.versions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.versions.setMinimumContentsLength(8)
        self.versions.setMaximumWidth(330)
        self.versions.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.versions.activated.connect(self._version_chosen)
        self.menu_btn = QToolButton()
        self.menu_btn.setToolTip("Действия с файлом")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Открыть другой FB2 файл…", lambda: win.import_file(side))
        menu.addAction("Экспортировать текущую версию…", lambda: win.export_side(side))
        menu.addSeparator()
        menu.addAction("Изменить метку…", lambda: win.relabel(side))
        menu.addAction("Удалить выбранную версию…", lambda: win.delete_version(side))
        menu.addSeparator()
        menu.addAction("Показать папку с версиями", lambda: win.open_folder(win.project.id if win.project else None))
        self.menu_btn.setMenu(menu)
        h.addWidget(self.badge)
        h.addWidget(self.title, 1)
        h.addWidget(self.dirty)
        h.addWidget(self.progress)
        h.addWidget(self.versions)
        h.addWidget(self.menu_btn)
        lay.addWidget(header)

        self.stack = QStackedWidget()
        self.editor = BookEditor(side)
        self.stack.addWidget(self.editor)
        empty = QFrame()
        empty.setObjectName("emptyPane")
        el = QVBoxLayout(empty)
        el.addStretch(1)
        self.empty_label = QLabel("Книга ещё не выбрана")
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Открыть FB2 файл…")
        btn.setObjectName("primary")
        btn.clicked.connect(lambda: win.import_file(side))
        el.addWidget(self.empty_label)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        el.addLayout(row)
        el.addStretch(1)
        self.stack.addWidget(empty)
        lay.addWidget(self.stack, 1)

    def eventFilter(self, obj, ev):
        if obj is self.badge and ev.type() == QEvent.Type.MouseButtonDblClick:
            self.win.relabel(self.side)
            return True
        return super().eventFilter(obj, ev)

    def show_empty(self, empty: bool):
        self.stack.setCurrentIndex(1 if empty else 0)

    def fill_versions(self, project: Project | None):
        self.versions.blockSignals(True)
        self.versions.clear()
        if project:
            cur = project.current(self.side)
            vs = project.versions(self.side)
            for v in reversed(vs):
                self.versions.addItem(v.label(project.number_of(self.side, v)), v.id)
                if cur and v.id == cur.id:
                    self.versions.setCurrentIndex(self.versions.count() - 1)
            self.versions.setVisible(bool(vs))
            self.badge.setText(project.label(self.side))
        self.versions.blockSignals(False)

    def _version_chosen(self, index: int):
        vid = self.versions.itemData(index)
        self.win.switch_version(self.side, vid)


# --------------------------------------------------------------------------- #
#  Find / replace bar
# --------------------------------------------------------------------------- #


class FindBar(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("findBar")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(6)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Найти…")
        self.find.setClearButtonEnabled(True)
        self.find.setMinimumWidth(140)
        self.replace = QLineEdit()
        self.replace.setPlaceholderText("Заменить на…")
        self.replace.setMinimumWidth(110)
        self.case = QCheckBox("Аа")
        self.case.setToolTip("Учитывать регистр")
        self.both = QCheckBox("В обеих книгах")
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.prev_btn = QToolButton()
        self.prev_btn.setToolTip("Предыдущее (Shift+Enter)")
        self.next_btn = QToolButton()
        self.next_btn.setToolTip("Следующее (Enter / F3)")
        rep = QPushButton("Заменить")
        rep_all = QPushButton("Заменить все")
        self.close_btn = QToolButton()
        self.close_btn.setToolTip("Закрыть (Esc)")
        for w in (self.find, self.prev_btn, self.next_btn, self.case, self.both, hline(), self.replace, rep, rep_all):
            h.addWidget(w)
        h.addWidget(self.info, 1)
        h.addWidget(self.close_btn)
        self.find.textChanged.connect(lambda: win.find_update())
        self.case.toggled.connect(lambda: win.find_update())
        self.both.toggled.connect(lambda: win.find_update())
        self.find.returnPressed.connect(lambda: win.find_next(False))
        self.prev_btn.clicked.connect(lambda: win.find_next(True))
        self.next_btn.clicked.connect(lambda: win.find_next(False))
        rep.clicked.connect(win.replace_one)
        rep_all.clicked.connect(win.replace_all)
        self.close_btn.clicked.connect(win.close_find)
        self.find.installEventFilter(self)
        self.replace.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self.win.close_find()
                return True
            if obj is self.find and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.win.find_next(True)
                return True
            if obj is self.replace and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.win.replace_one()
                return True
        return super().eventFilter(obj, ev)


# --------------------------------------------------------------------------- #
#  Main window
# --------------------------------------------------------------------------- #


class MainWindow(QMainWindow):
    def __init__(self, store: ProjectStore | None = None):
        super().__init__()
        self.store = store or ProjectStore()
        self.settings = self.store.settings
        self.project: Project | None = None
        self.loaded: dict[str, str | None] = {s: None for s in SIDES}  # side -> version id
        self.dark = self.settings.get("theme", "light") == "dark"
        self.colors = theme.DARK if self.dark else theme.LIGHT
        self.last_color = self.settings.get("last_color", COLORS[0][1])
        self.zoom = int(self.settings.get("zoom", ZOOM_DEFAULT))
        self.font_family = self.settings.get("font", "Georgia")

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1400, 860)

        self.notes = Notes(self)
        self._build_actions()
        self._build_ui()
        self.active = self.left.editor
        self.speller = Speller(os.path.join(self.store.base, "user_words.txt"), self)
        self.speller.ready.connect(self._speller_ready)
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.setInterval(60)
        self._progress_timer.timeout.connect(self.update_progress)
        self.sync = ScrollSync(self.left.editor, self.right.editor, self)
        self.sync.enabled = bool(self.settings.get("sync", True))
        self.act["sync"].setChecked(self.sync.enabled)
        for pane in (self.left, self.right):
            ed = pane.editor
            ed.focused.connect(partial(self._set_active, ed))
            ed.zoomRequested.connect(self.change_zoom)
            ed.formatChanged.connect(self._update_format_state)
            ed.cursorPositionChanged.connect(partial(self._cursor_moved, ed))
            ed.verticalScrollBar().valueChanged.connect(lambda _v: self.middle.update_from_books())
            ed.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self.middle.update_from_books())
            ed.noteJumped.connect(lambda: self.statusBar().showMessage(
                "Переход к сноске. Alt+← — вернуться к тексту", 5000))
            ed.blockDoubleClicked.connect(partial(self.show_in_other, ed))
            ed.noteClicked.connect(self._note_clicked)
            ed.noteAddRequested.connect(partial(self._add_note_from, ed))
            ed.noteEditRequested.connect(self.edit_note)
            ed.noteDeleteRequested.connect(self.delete_note)
            ed.set_speller(self.speller)
            ed.set_spell_enabled(self.act["spell"].isChecked())
            ed.set_show_numbers(self.act["numbers"].isChecked())
            ed.verticalScrollBar().valueChanged.connect(lambda _v: self._progress_timer.start())
            ed.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self._progress_timer.start())
        self.apply_theme()
        self.apply_view()

        self._state_timer = QTimer(self)
        self._state_timer.setInterval(15000)
        self._state_timer.timeout.connect(self.save_state)
        self._state_timer.start()

        geo = self.settings.get("geometry")
        restored = False
        if geo:
            try:
                restored = self.restoreGeometry(bytes.fromhex(geo))
            except ValueError:
                restored = False
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if not restored:
                self.resize(int(avail.width() * 0.9), int(avail.height() * 0.88))
                self.move(avail.center() - self.rect().center())
            elif not self.isMaximized() and (self.width() > avail.width() or self.height() > avail.height()):
                self.resize(min(self.width(), avail.width()), min(self.height(), avail.height()))
        self.sidebar.setVisible(self.settings.get("sidebar", True))
        if self.settings.get("notes_panel", False):
            self.act["notes_panel"].setChecked(True)
        self.act["sidebar"].setChecked(self.sidebar.isVisible())

        self.sidebar.refresh(None)
        last = self.settings.get("last_project")
        if last and self.store.open(last):
            QTimer.singleShot(0, lambda: self.open_project(last))
        else:
            self._show_welcome()

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _build_actions(self):
        self.act: dict[str, QAction] = {}

        def add(key, text, slot, shortcuts=(), checkable=False, tip=None):
            a = QAction(text, self)
            if shortcuts:
                a.setShortcuts([QKeySequence(s) for s in shortcuts])
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.setCheckable(checkable)
            sc = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            a.setToolTip(f"{tip or text}" + (f"  ({sc})" if sc else ""))
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(slot)
            self.addAction(a)
            self.act[key] = a
            return a

        ed = lambda name, *args: (lambda *_: getattr(self.active, name)(*args))  # noqa: E731
        add("sidebar", "Проекты", self.toggle_sidebar, ["Ctrl+\\"], True, "Показать/скрыть список проектов")
        add("new", "Новый проект", self.new_project, ["Ctrl+N"])
        add("undo", "Отменить", ed("undo"), ["Ctrl+Z"])
        add("redo", "Повторить", ed("redo"), ["Ctrl+Y", "Ctrl+Shift+Z"])
        add("bold", "Жирный", ed("toggle_bold"), ["Ctrl+B"], tip="Жирный")
        add("italic", "Курсив", ed("toggle_italic"), ["Ctrl+I"])
        add("strike", "Зачёркнутый", ed("toggle_strike"), ["Ctrl+Shift+X"])
        add("sup", "Верхний индекс", ed("toggle_valign", QTextCharFormat.VerticalAlignment.AlignSuperScript),
            ["Ctrl+."])
        add("sub", "Нижний индекс", ed("toggle_valign", QTextCharFormat.VerticalAlignment.AlignSubScript),
            ["Ctrl+,"])
        add("color", "Цвет текста", lambda: self.active.set_color(QColor(self.last_color)), ["Ctrl+Shift+C"],
            tip="Цвет текста")
        add("clear", "Очистить форматирование", ed("clear_formatting"), ["Ctrl+Space"])
        add("image", "Вставить картинку…", self.insert_image_file, ["Ctrl+Shift+I"])
        add("paste_plain", "Вставить без форматирования", ed("paste_plain"), ["Ctrl+Shift+V"])
        add("find", "Найти и заменить", self.open_find, ["Ctrl+F", "Ctrl+H"])
        add("add_note", "Добавить заметку", self.add_note, ["Ctrl+Alt+M"],
            tip="Заметка к выделенному месту (видна только в проекте)")
        add("notes_panel", "Заметки", self.toggle_notes_panel, ["Ctrl+Shift+M"], True,
            "Показать/скрыть список заметок")
        add("find_next", "Найти далее", lambda: self.find_next(False), ["F3"])
        add("find_prev", "Найти назад", lambda: self.find_next(True), ["Shift+F3"])
        add("zoom_in", "Крупнее", lambda: self.change_zoom(1), ["Ctrl++", "Ctrl+=", "Ctrl+Shift++"])
        add("zoom_out", "Мельче", lambda: self.change_zoom(-1), ["Ctrl+-", "Ctrl+Num+-"])
        add("zoom_reset", "Обычный размер", lambda: self.change_zoom(0), ["Ctrl+0"])
        add("sync", "Синхронная прокрутка", self.toggle_sync, ["Ctrl+L"], True,
            "Синхронная прокрутка (Alt+колесо — прокрутить только одну книгу)")
        add("align", "Выровнять книги", self.align_now, ["Ctrl+Shift+L"],
            tip="Выровнять вторую книгу по текущей")
        add("theme", "Тёмная тема", self.toggle_theme, ["Ctrl+Shift+D"], True)
        add("spell", "Проверка орфографии", self.toggle_spell, ["F7"], True,
            "Проверка орфографии (правый щелчок по слову — варианты исправления)")
        add("numbers", "Номера абзацев", self.toggle_numbers, ["Ctrl+Shift+N"], True)
        add("save", "Сохранить", self.quick_save, ["Ctrl+S"],
            tip="Быстрое сохранение — перезаписывает один и тот же слот")
        add("save_version", "Сохранить как новую версию…", self.save_version, ["Ctrl+Shift+S"])
        add("switch", "Перейти в другую книгу", self.switch_editor, ["Ctrl+Tab", "F6"])
        for key, (label, sc) in STYLES.items():
            add(f"style_{key}", label, partial(self._set_style, key), [sc])
        self.act["theme"].setChecked(self.dark)
        self.act["spell"].blockSignals(True)
        self.act["spell"].setChecked(bool(self.settings.get("spell", True)))
        self.act["spell"].blockSignals(False)
        self.act["numbers"].blockSignals(True)
        self.act["numbers"].setChecked(bool(self.settings.get("numbers", True)))
        self.act["numbers"].blockSignals(False)

    def _tool(self, key: str, icon_kind: str | None = None) -> QToolButton:
        b = QToolButton()
        b.setDefaultAction(self.act[key])
        b.setAutoRaise(True)
        b.setIconSize(theme.ICON_SIZE)
        b.setProperty("iconKind", icon_kind or key)
        self._tools.append(b)
        self._tool_btns[key] = b
        return b

    def _build_ui(self):
        self._tools: list[QToolButton] = []
        self._tool_btns: dict[str, QToolButton] = {}
        self._fitting = False
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = Sidebar(self)
        outer.addWidget(self.sidebar)
        self.notes_panel = NotesPanel(self)
        self.notes_panel.hide()
        outer.addWidget(self.notes_panel)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        outer.addWidget(main, 1)

        # -- top bar ------------------------------------------------------ #
        top = TopBar(self)
        top.setObjectName("topBar")
        self.top_bar = top
        t = QHBoxLayout(top)
        t.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        t.setContentsMargins(8, 6, 10, 6)
        t.setSpacing(2)
        t.addWidget(self._tool("sidebar", "menu"))
        self.project_label = QLabel("")
        self.project_label.setMaximumWidth(220)
        self.project_label.setStyleSheet("font-weight:600; padding: 0 8px;")
        t.addWidget(self.project_label)
        t.addWidget(hline())
        t.addWidget(self._tool("undo"))
        t.addWidget(self._tool("redo"))
        t.addWidget(hline())

        self.style_box = QComboBox()
        self.style_box.setToolTip("Стиль абзаца")
        self.style_box.setMinimumWidth(150)
        for key, (label, sc) in STYLES.items():
            self.style_box.addItem(label, key)
            self.style_box.setItemData(self.style_box.count() - 1, f"{label}  ({sc})", Qt.ItemDataRole.ToolTipRole)
        self.style_box.activated.connect(lambda i: self._set_style(self.style_box.itemData(i)))
        t.addWidget(self.style_box)
        t.addSpacing(4)
        for key in ("bold", "italic", "strike", "sup", "sub"):
            self.act[key].setCheckable(True)
            t.addWidget(self._tool(key))

        self.color_btn = QToolButton()
        self.color_btn.setDefaultAction(self.act["color"])
        self.color_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.color_btn.setIconSize(theme.ICON_SIZE)
        self.color_menu = QMenu(self)
        self.color_btn.setMenu(self.color_menu)
        t.addWidget(self.color_btn)
        t.addWidget(self._tool("clear"))
        t.addWidget(self._tool("image"))
        t.addWidget(hline())
        t.addWidget(self._tool("find"))
        t.addWidget(self._tool("add_note"))
        t.addWidget(self._tool("notes_panel"))
        t.addStretch(1)

        self.font_box = QFontComboBox()
        self.font_box.setToolTip("Шрифт для чтения (только отображение)")
        self.font_box.setMaximumWidth(180)
        self.font_box.setMinimumWidth(110)
        self.font_box.setCurrentFont(QFont(self.font_family))
        self.font_box.currentFontChanged.connect(self._font_changed)
        t.addWidget(self.font_box)
        t.addSpacing(4)
        t.addWidget(self._tool("zoom_out"))
        self.zoom_label = QToolButton()
        self.zoom_label.setObjectName("textButton")
        self.zoom_label.setToolTip("Размер текста — нажмите, чтобы сбросить (Ctrl+0)")
        self.zoom_label.clicked.connect(lambda: self.change_zoom(0))
        self.zoom_label.setMinimumWidth(64)
        t.addWidget(self.zoom_label)
        t.addWidget(self._tool("zoom_in"))
        t.addWidget(hline())
        t.addWidget(self._tool("sync"))
        t.addWidget(self._tool("spell"))
        t.addWidget(self._tool("numbers"))
        t.addWidget(self._tool("theme"))
        t.addWidget(hline())

        self.save_btn = QToolButton()
        self.save_btn.setDefaultAction(self.act["save"])
        self.save_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_btn.setIconSize(theme.ICON_SIZE)
        self.save_btn.setProperty("iconKind", "save")
        self._tools.append(self.save_btn)
        t.addWidget(self.save_btn)
        vbtn = self._tool("save_version")
        vbtn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.act["save_version"].setIconText("Версия")
        t.addWidget(vbtn)
        self.version_btn = vbtn
        mv.addWidget(top)

        self.find_bar = FindBar(self)
        self.find_bar.hide()
        mv.addWidget(self.find_bar)

        # -- content ------------------------------------------------------ #
        self.content = QStackedWidget()
        self.left = Pane(self, "left")
        self.right = Pane(self, "right")
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.left)
        self.middle = MiddleBar(self)
        self.splitter.addWidget(self.middle)
        self.splitter.addWidget(self.right)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([1000, MiddleBar.WIDTH, 1000])
        self.content.addWidget(self.splitter)

        welcome = QFrame()
        welcome.setObjectName("welcome")
        wl = QVBoxLayout(welcome)
        wl.addStretch(2)
        title = QLabel("Редактор перевода FB2")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("Откройте оригинал и перевод рядом, листайте их синхронно\n"
                      "и правьте текст прямо в книге — как в обычной читалке.")
        text.setObjectName("welcomeText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Создать проект")
        btn.setObjectName("primary")
        btn.setMinimumWidth(200)
        btn.clicked.connect(self.new_project)
        wl.addWidget(title)
        wl.addSpacing(8)
        wl.addWidget(text)
        wl.addSpacing(20)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        wl.addLayout(row)
        wl.addStretch(3)
        self.content.addWidget(welcome)
        mv.addWidget(self.content, 1)

        self.setCentralWidget(root)

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.status_pos = QLabel("")
        self.status_info = QLabel("")
        sb.addPermanentWidget(self.status_pos)
        sb.addPermanentWidget(self.status_info)

    # ------------------------------------------------------------------ #
    #  Theme / view
    # ------------------------------------------------------------------ #
    def _fit_toolbar(self):
        """Collapse secondary controls step by step until the tool bar fits."""
        if self._fitting:
            return
        self._fitting = True
        try:
            b = self._tool_btns
            text_btns = (self.save_btn, self.version_btn)
            steps = [
                lambda on: [x.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if on
                                                 else Qt.ToolButtonStyle.ToolButtonIconOnly) for x in text_btns],
                lambda on: self.font_box.setVisible(on),
                lambda on: self.project_label.setVisible(on),
                lambda on: [b[k].setVisible(on) for k in ("sup", "sub")],
                lambda on: [b[k].setVisible(on) for k in ("clear", "image")],
                lambda on: [b[k].setVisible(on) for k in ("theme", "numbers", "spell")],
                lambda on: [b[k].setVisible(on) for k in ("find", "add_note", "undo", "redo")],
            ]
            for step in steps:
                step(True)
            lay = self.top_bar.layout()
            for step in steps:
                lay.activate()
                if lay.sizeHint().width() <= self.top_bar.width():
                    break
                step(False)
        finally:
            self._fitting = False

    def chapter_title(self, ed: BookEditor) -> str:
        """Title of the chapter shown at the top of the editor."""
        idx = self.sync.index(ed)
        if not idx.content:
            return ""
        y = ed.verticalScrollBar().value() + ed.viewport().height() * 0.3
        k = self.sync.content_index_at(ed, idx, y)
        anchor = max((a for a in idx.anchors if a <= k), default=0)
        block = ed.document().findBlockByNumber(idx.content[anchor])
        parts = [block.text()]
        nxt = block.next()
        while nxt.isValid() and block_kind(nxt) == "title" and block_path(nxt) == block_path(block) \
                and len(parts) < 3:
            parts.append(nxt.text())
            nxt = nxt.next()
        return " · ".join(t.strip() for t in parts if t.strip())[:120]

    def apply_theme(self):
        c = self.colors = theme.DARK if self.dark else theme.LIGHT
        app = QApplication.instance()
        theme.apply_palette(app, c)
        app.setStyleSheet(theme.stylesheet(c))
        col = c["text"]
        icons = {
            "bold": theme.text_icon("B", col, bold=True, serif=False),
            "italic": theme.text_icon("I", col, italic=True),
            "strike": theme.text_icon("S", col, strike=True, serif=False),
            "sup": theme.script_icon(True, col),
            "sub": theme.script_icon(False, col),
        }
        for key, a in self.act.items():
            if key in icons:
                a.setIcon(icons[key])
            elif key in theme.GLYPHS:
                a.setIcon(theme.glyph_icon(key, col))
        self.act["sidebar"].setIcon(theme.glyph_icon("menu", col))
        self.act["clear"].setIcon(theme.glyph_icon("clear", col))
        self.act["save_version"].setIcon(theme.glyph_icon("save_version", col))
        self.act["image"].setIcon(theme.glyph_icon("image", col))
        self.sidebar.add_btn.setIcon(theme.glyph_icon("add", col))
        self.act["add_note"].setIcon(theme.glyph_icon("note", col))
        self.act["notes_panel"].setIcon(theme.glyph_icon("notes", col))
        self.notes_panel.add_btn.setIcon(theme.glyph_icon("add", col))
        self.notes_panel.close_btn.setIcon(theme.glyph_icon("close", col))
        self.notes_panel.refresh()
        self.find_bar.prev_btn.setIcon(theme.glyph_icon("up", col))
        self.find_bar.next_btn.setIcon(theme.glyph_icon("down", col))
        self.find_bar.close_btn.setIcon(theme.glyph_icon("close", col))
        self.act["spell"].setIcon(theme.text_icon("Аб", col, serif=False, underline_color="#e5484d"))
        self.act["numbers"].setIcon(theme.text_icon("¶", col))
        for pane in (self.left, self.right):
            pane.menu_btn.setIcon(theme.glyph_icon("more", col))
            g = pane.editor.gutter
            g.bg, g.fg, g.current = QColor(c["paper"]), QColor(c["muted"]), QColor(c["accent"])
            g.update()
            pane.editor._update_extra()
        self._update_color_button()

    def _update_color_button(self):
        c = self.colors
        self.act["color"].setIcon(theme.text_icon("A", c["text"], serif=False, underline_color=self.last_color))
        m = self.color_menu
        m.clear()
        for name, hexv in COLORS:
            m.addAction(theme.swatch_icon(hexv, c["border"]), name, partial(self._pick_color, hexv))
        m.addSeparator()
        m.addAction(theme.swatch_icon(None, c["border"]), "Без цвета", lambda: self.active.set_color(None))
        m.addAction("Другой цвет…", self._custom_color)

    def _pick_color(self, hexv: str):
        self.last_color = hexv
        self.settings["last_color"] = hexv
        self._update_color_button()
        self.active.set_color(QColor(hexv))

    def _custom_color(self):
        col = QColorDialog.getColor(QColor(self.last_color), self, "Цвет текста")
        if col.isValid():
            self._pick_color(col.name())

    def toggle_theme(self, on: bool):
        self.dark = on
        self.settings["theme"] = "dark" if on else "light"
        self.apply_theme()

    def apply_view(self):
        f = QFont(self.font_family)
        f.setPointSizeF(self.zoom)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        anchors = [self._top_anchor(p.editor) for p in (self.left, self.right)]
        for p in (self.left, self.right):
            p.editor.apply_view(f)
        for p, a in zip((self.left, self.right), anchors):
            self._restore_anchor(p.editor, a)
        self.zoom_label.setText(f"{round(self.zoom / ZOOM_DEFAULT * 100)}%")

    def change_zoom(self, step: int):
        z = ZOOM_DEFAULT if step == 0 else max(ZOOM_MIN, min(ZOOM_MAX, self.zoom + step))
        if z != self.zoom:
            self.zoom = z
            self.settings["zoom"] = z
            self.apply_view()

    def _font_changed(self, font: QFont):
        self.font_family = font.family()
        self.settings["font"] = self.font_family
        self.apply_view()

    def toggle_sidebar(self, on: bool):
        self.sidebar.setVisible(on)
        self.settings["sidebar"] = on

    def toggle_sync(self, on: bool):
        self.sync.enabled = on
        self.settings["sync"] = on
        if on:
            self.sync.align(self.active)
        self.statusBar().showMessage("Синхронная прокрутка включена" if on else
                                     "Синхронная прокрутка выключена", 2500)

    def align_now(self):
        self.sync.align(self.active)

    # ------------------------------------------------------------------ #
    #  Active editor & formatting state
    # ------------------------------------------------------------------ #
    def _set_active(self, ed: BookEditor):
        self.active = ed
        self._update_format_state()
        self._cursor_moved(ed)

    def switch_editor(self):
        other = self.right.editor if self.active is self.left.editor else self.left.editor
        other.setFocus()

    def _set_style(self, key: str):
        self.active.set_style(key)
        self.active.setFocus()

    def _update_format_state(self):
        ed = self.active
        f = ed.currentCharFormat()
        style = ed.current_style()
        heading = style in ("title", "subtitle")
        self.act["bold"].setChecked(f.fontWeight() >= 600 and not heading)
        self.act["italic"].setChecked(f.fontItalic() and style != "author")
        self.act["strike"].setChecked(f.fontStrikeOut())
        self.act["sup"].setChecked(f.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSuperScript)
        self.act["sub"].setChecked(f.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSubScript)
        i = self.style_box.findData(style)
        if i >= 0 and i != self.style_box.currentIndex():
            self.style_box.setCurrentIndex(i)

    def _cursor_moved(self, ed: BookEditor):
        if ed is not self.active:
            return
        other = self.right.editor if ed is self.left.editor else self.left.editor
        block = ed.textCursor().block()
        if ed.book and other.book:
            other.set_pair_block(self.sync.paired_block(ed, block.blockNumber()))
        ed.set_pair_block(-1)
        if ed.book is None:
            self.status_pos.setText("")
            return
        content = self.sync.index(ed).content
        k = bisect_right(content, block.blockNumber())
        self.status_pos.setText(f"{self.project.label(ed.side) if self.project else ''}  ·  "
                                f"курсор: абзац {max(1, k)} из {len(content)}")


    # ------------------------------------------------------------------ #
    #  Notes
    # ------------------------------------------------------------------ #
    def toggle_notes_panel(self, on: bool):
        self.notes_panel.setVisible(on)
        self.settings["notes_panel"] = on
        if on:
            self.notes_panel.refresh()

    def add_note(self):
        self._add_note_from(self.active)

    def _add_note_from(self, ed: BookEditor):
        if not self.project or ed.book is None:
            self.statusBar().showMessage("Откройте книгу, чтобы оставить заметку", 3000)
            return
        start, end = ed.note_span()
        c = QTextCursor(ed.document())
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        dlg = NoteDialog(c.selectedText().replace("\u2029", " "), "", self.project.label(ed.side), self)
        if dlg.exec() != NoteDialog.DialogCode.Accepted:
            return
        n = self.notes.add(ed.side, ed, start, end, dlg.text())
        if not self.act["notes_panel"].isChecked():
            self.act["notes_panel"].setChecked(True)
        self.notes_panel.select(n["id"])
        self.statusBar().showMessage("Заметка добавлена", 2500)

    def edit_note(self, nid: str):
        n = self.notes.get(nid)
        if not n or not self.project:
            return
        dlg = NoteDialog(n.get("quote", ""), n.get("text", ""), self.project.label(n["side"]), self)
        if dlg.exec() == NoteDialog.DialogCode.Accepted:
            self.notes.edit(nid, dlg.text())
            self.notes_panel.select(nid)

    def delete_note(self, nid: str):
        n = self.notes.get(nid)
        if not n:
            return
        preview = (n.get("text") or n.get("quote") or "")[:80]
        if QMessageBox.question(self, "Удалить заметку", f"Удалить заметку «{preview}»?") == \
                QMessageBox.StandardButton.Yes:
            self.notes.remove(nid)

    def goto_note(self, nid: str):
        n = self.notes.get(nid)
        if not n:
            return
        ed = self.pane(n["side"]).editor
        r = self.notes.range_of(nid)
        if ed.book is None or r is None:
            self.statusBar().showMessage("Книга для этой заметки не открыта", 3000)
            return
        doc = ed.document()
        c = QTextCursor(doc)
        c.setPosition(r[0])
        c.setPosition(r[1], QTextCursor.MoveMode.KeepAnchor)
        ed.setTextCursor(c)
        rect = doc.documentLayout().blockBoundingRect(c.block())
        ed.verticalScrollBar().setValue(int(rect.y() - ed.viewport().height() * 0.3))
        ed.flash_block(c.block().blockNumber())
        ed.setFocus()

    def _note_clicked(self, nid: str):
        if not self.act["notes_panel"].isChecked():
            self.act["notes_panel"].setChecked(True)
        self.notes_panel.select(nid)

    # ------------------------------------------------------------------ #
    #  Reading progress, spelling, numbering, double click
    # ------------------------------------------------------------------ #
    def update_progress(self):
        for pane in (self.left, self.right):
            ed = pane.editor
            if ed.book is None:
                pane.progress.setText("")
                continue
            idx = self.sync.index(ed)
            total = len(idx.content)
            if not total:
                pane.progress.setText("")
                continue
            sb = ed.verticalScrollBar()
            if sb.value() >= sb.maximum() and sb.maximum() > 0:
                k = total - 1
            else:
                # the first paragraph visible at the top of the page
                k = self.sync.content_index_at(ed, idx, sb.value() + 4)
            pct = (k + 1) * 100 / total
            pane.progress.setText(f"¶ {k + 1} / {total}  ·  {pct:.1f}%".replace(".", ","))

    def _speller_ready(self):
        if not self.speller.loaded:
            self.statusBar().showMessage(f"Проверка орфографии недоступна: {self.speller.error}", 8000)

    def toggle_spell(self, on: bool):
        self.settings["spell"] = on
        for p in (self.left, self.right):
            p.editor.set_spell_enabled(on)

    def toggle_numbers(self, on: bool):
        self.settings["numbers"] = on
        for p in (self.left, self.right):
            p.editor.set_show_numbers(on)

    def show_in_other(self, src: BookEditor, number: int):
        """Double click: bring the matching paragraph of the other book next to this one."""
        dst = self.right.editor if src is self.left.editor else self.left.editor
        if src.book is None or dst.book is None:
            return
        target = self.sync.paired_block(src, number)
        if target < 0:
            return
        s_doc, d_doc = src.document(), dst.document()
        s_rect = s_doc.documentLayout().blockBoundingRect(s_doc.findBlockByNumber(number))
        d_rect = d_doc.documentLayout().blockBoundingRect(d_doc.findBlockByNumber(target))
        on_screen = s_rect.y() - src.verticalScrollBar().value()
        on_screen = min(max(0.0, on_screen), dst.viewport().height() * 0.8)
        self.sync.paused = True
        try:
            dst.verticalScrollBar().setValue(int(round(d_rect.y() - on_screen)))
        finally:
            self.sync.paused = False
        dst.set_pair_block(target)
        dst.flash_block(target)

    # ------------------------------------------------------------------ #
    #  Projects
    # ------------------------------------------------------------------ #
    def _show_welcome(self):
        self.content.setCurrentIndex(1)
        self.project_label.setText("")
        self._update_title()

    def _start_dir(self) -> str:
        return self.settings.get("last_dir", os.path.expanduser("~"))

    def _remember_dir(self, path: str):
        self.settings["last_dir"] = os.path.dirname(path)

    def new_project(self):
        dlg = NewProjectDialog(self._start_dir(), self)
        if dlg.exec() != NewProjectDialog.DialogCode.Accepted:
            return
        if not self.maybe_save():
            return
        p = self.store.create(dlg.name.text().strip(), dlg.left_label.text().strip() or "RU",
                              dlg.right_label.text().strip() or "EN")
        for side, picker in (("left", dlg.left_file), ("right", dlg.right_file)):
            path = picker.text().strip()
            if path:
                try:
                    data = read_fb2_bytes(path)
                    load_fb2(data)  # validate
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.warning(self, APP_NAME, f"Не удалось открыть {path}:\n{exc}")
                    continue
                p.import_file(side, path, data)
                self._remember_dir(path)
        self._open(p)

    def open_project(self, pid: str) -> bool:
        if self.project and self.project.id == pid:
            return True
        if not self.maybe_save():
            return False
        p = self.store.open(pid)
        if not p:
            QMessageBox.warning(self, APP_NAME, "Проект не найден.")
            return False
        self._open(p)
        return True

    def _open(self, p: Project):
        self.save_state()
        self.project = p
        p.data["opened"] = time.time()
        p.save_state()
        self.settings["last_project"] = p.id
        self.store.save_settings()
        self.content.setCurrentIndex(0)
        self.project_label.setText(p.name)
        self._fit_toolbar()
        self.notes.set_project(p)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for side in SIDES:
                self._load_side(side, p.current(side))
        finally:
            QApplication.restoreOverrideCursor()
        self.sidebar.refresh(p.id)
        sizes = p.state.get("splitter")
        if sizes and len(sizes) == 3:
            self.splitter.setSizes(sizes)
        QTimer.singleShot(30, self._restore_positions)
        self._update_title()

    def pane(self, side: str) -> Pane:
        return self.left if side == "left" else self.right

    def _load_side(self, side: str, version) -> bool:
        pane = self.pane(side)
        pane.fill_versions(self.project)
        if version is None:
            pane.editor.set_book(None, None)
            pane.show_empty(True)
            pane.title.setText("")
            self.loaded[side] = None
            self._hook_doc(pane)
            self.notes.attach(side, pane.editor)
            return True
        try:
            doc, book = load_fb2(read_fb2_bytes(self.project.path_of(version)))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Не удалось открыть версию:\n{exc}")
            pane.editor.set_book(None, None)
            pane.show_empty(True)
            self.loaded[side] = None
            return False
        pane.editor.set_book(doc, book)
        f = QFont(self.font_family)
        f.setPointSizeF(self.zoom)
        pane.editor.apply_view(f)
        pane.show_empty(False)
        pane.title.setText(book.title)
        pane.title.setToolTip(book.title)
        self.loaded[side] = version.id
        self._hook_doc(pane)
        self.notes.attach(side, pane.editor)
        self.notes.changed.emit()
        return True

    def _hook_doc(self, pane: Pane):
        doc = pane.editor.document()
        doc.contentsChanged.connect(self._progress_timer.start)
        self._progress_timer.start()
        doc.modificationChanged.connect(lambda m, p=pane: (p.dirty.setVisible(m), self._update_title()))
        pane.dirty.setVisible(doc.isModified())

    def _update_title(self):
        dirty = any(self.pane(s).editor.document().isModified() for s in SIDES if self.loaded.get(s))
        name = self.project.name if self.project else ""
        self.setWindowTitle(("• " if dirty else "") + (f"{name} — " if name else "") + APP_NAME)

    def rename_project(self, pid: str):
        p = self.project if self.project and self.project.id == pid else self.store.open(pid)
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Переименовать проект", "Название:", text=p.name)
        if ok and name.strip():
            p.name = name.strip()
            if self.project and self.project.id == pid:
                self.project_label.setText(p.name)
                self._update_title()
            self.sidebar.refresh(self.project.id if self.project else None)

    def delete_project(self, pid: str):
        p = self.store.open(pid)
        if not p:
            return
        r = QMessageBox.question(self, "Удалить проект",
                                 f"Удалить проект «{p.name}» вместе со всеми сохранёнными версиями?\n"
                                 "Исходные файлы на диске не затрагиваются.")
        if r != QMessageBox.StandardButton.Yes:
            return
        if self.project and self.project.id == pid:
            for side in SIDES:
                self.pane(side).editor.document().setModified(False)
            self.project = None
            self.notes.set_project(None)
            for side in SIDES:
                self.pane(side).editor.set_book(None, None)
                self.loaded[side] = None
            self.settings.pop("last_project", None)
            self._show_welcome()
        self.store.delete(pid)
        self.sidebar.refresh(self.project.id if self.project else None)

    def open_folder(self, pid: str | None):
        if not pid:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.store.dir, pid)))

    def relabel(self, side: str):
        if not self.project:
            return
        text, ok = QInputDialog.getText(self, "Метка книги", "Короткая метка (например, RU или EN):",
                                        text=self.project.label(side))
        if ok and text.strip():
            self.project.set_label(side, text.strip()[:12])
            self.pane(side).badge.setText(self.project.label(side))
            self.sidebar.refresh(self.project.id)

    # ------------------------------------------------------------------ #
    #  Versions / files
    # ------------------------------------------------------------------ #
    def _ask_side_unsaved(self, side: str) -> bool:
        """Ask about unsaved changes on one side. False = cancelled."""
        ed = self.pane(side).editor
        if not (self.loaded[side] and ed.document().isModified()):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"В книге {self.project.label(side)} есть несохранённые изменения.")
        save = box.addButton("Сохранить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Не сохранять", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is cancel:
            return False
        if box.clickedButton() is save:
            return self._quick_save_side(side)
        return True

    def maybe_save(self) -> bool:
        if not self.project:
            return True
        for side in SIDES:
            if not self._ask_side_unsaved(side):
                return False
        return True

    def switch_version(self, side: str, vid: str):
        if not self.project or vid == self.loaded.get(side):
            return
        if not self._ask_side_unsaved(side):
            self.pane(side).fill_versions(self.project)
            return
        v = self.project.version(side, vid)
        if not v:
            return
        pos = self._top_anchor(self.pane(side).editor)
        self.project.set_current(side, vid)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._load_side(side, v)
        finally:
            QApplication.restoreOverrideCursor()
        QTimer.singleShot(30, lambda: self._restore_anchor(self.pane(side).editor, pos))
        self.statusBar().showMessage(f"Открыта версия: {v.label(self.project.number_of(side, v))}", 4000)

    def import_file(self, side: str):
        if not self.project:
            self.new_project()
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть FB2", self._start_dir(), FB2_FILTER)
        if not path:
            return
        if not self._ask_side_unsaved(side):
            return
        try:
            data = read_fb2_bytes(path)
            load_fb2(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Не удалось открыть файл:\n{exc}")
            return
        self._remember_dir(path)
        v = self.project.import_file(side, path, data)
        self._load_side(side, v)
        self.sidebar.refresh(self.project.id)

    def export_side(self, side: str):
        ed = self.pane(side).editor
        if not self.project or not ed.book:
            return
        v = self.project.current(side)
        name = f"{self.project.name} ({self.project.label(side)}).fb2"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт FB2", os.path.join(self._start_dir(), name),
                                              "Книги FB2 (*.fb2)")
        if not path:
            return
        try:
            data = save_fb2(ed.document(), ed.book)
            with open(path, "wb") as fh:
                fh.write(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Не удалось сохранить файл:\n{exc}")
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Экспортировано: {path}" + (" (с текущими правками)" if v else ""), 5000)

    def delete_version(self, side: str):
        if not self.project:
            return
        vid = self.loaded.get(side)
        v = self.project.version(side, vid)
        if not v:
            return
        if v.kind == "original":
            QMessageBox.information(self, APP_NAME, "Оригинал удалить нельзя — он хранится как исходная версия.")
            return
        num = self.project.number_of(side, v)
        if QMessageBox.question(self, APP_NAME, f"Удалить версию «{v.label(num)}»?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.pane(side).editor.document().setModified(False)
        self.project.delete_version(side, vid)
        self._load_side(side, self.project.current(side))

    def _serialize(self, side: str) -> bytes | None:
        ed = self.pane(side).editor
        try:
            return save_fb2(ed.document(), ed.book)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Ошибка при сохранении {self.project.label(side)}:\n{exc}")
            return None

    def _after_save(self, side: str, version):
        self.loaded[side] = version.id
        self.pane(side).editor.document().setModified(False)
        self.pane(side).fill_versions(self.project)

    def _quick_save_side(self, side: str) -> bool:
        data = self._serialize(side)
        if data is None:
            return False
        v = self.project.quick_save(side, data)
        self._after_save(side, v)
        return True

    def quick_save(self):
        if not self.project:
            return
        sides = [s for s in SIDES if self.loaded[s] and self.pane(s).editor.document().isModified()]
        if not sides:
            self.statusBar().showMessage("Нет изменений для сохранения", 2500)
            return
        ok = [s for s in sides if self._quick_save_side(s)]
        self.sidebar.refresh(self.project.id)
        if ok:
            labels = ", ".join(self.project.label(s) for s in ok)
            self.statusBar().showMessage(f"Сохранено ({labels}) — {time.strftime('%H:%M:%S')}", 4000)

    def save_version(self):
        if not self.project:
            return
        labels = {s: self.project.label(s) for s in SIDES}
        dirty = {s: bool(self.loaded[s]) and self.pane(s).editor.document().isModified() for s in SIDES}
        avail = {s: bool(self.loaded[s]) for s in SIDES}
        if not any(avail.values()):
            return
        dlg = SaveVersionDialog(labels, dirty, avail, self)
        if dlg.exec() != SaveVersionDialog.DialogCode.Accepted:
            return
        note = dlg.note.text().strip()
        for side in dlg.sides():
            data = self._serialize(side)
            if data is None:
                continue
            v = self.project.add_version(side, data, "manual", note)
            self._after_save(side, v)
        self.sidebar.refresh(self.project.id)
        self.statusBar().showMessage("Новая версия сохранена", 4000)

    # ------------------------------------------------------------------ #
    #  Images
    # ------------------------------------------------------------------ #
    def insert_image_file(self):
        ed = self.active
        if not ed.book:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Вставить картинку", self._start_dir(),
                                              "Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "Не удалось открыть изображение.")
            return
        self._remember_dir(path)
        ed.insert_image(img)
        ed.setFocus()

    # ------------------------------------------------------------------ #
    #  Find / replace
    # ------------------------------------------------------------------ #
    def open_find(self):
        self.find_bar.show()
        c = self.active.textCursor()
        if c.hasSelection() and " " not in c.selectedText():
            self.find_bar.find.setText(c.selectedText())
        self.find_bar.find.setFocus()
        self.find_bar.find.selectAll()
        self.find_update()

    def close_find(self):
        self.find_bar.hide()
        for p in (self.left, self.right):
            p.editor.set_find_hits([])
        self.active.setFocus()

    def _find_flags(self, backward=False):
        f = QTextDocument.FindFlag(0)
        if self.find_bar.case.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            f |= QTextDocument.FindFlag.FindBackward
        return f

    def _find_targets(self):
        if self.find_bar.both.isChecked():
            return [p.editor for p in (self.left, self.right) if p.editor.book]
        return [self.active] if self.active.book else []

    def find_update(self):
        text = self.find_bar.find.text()
        total = 0
        for p in (self.left, self.right):
            ed = p.editor
            hits = []
            if text and ed in self._find_targets():
                doc = ed.document()
                c = doc.find(text, 0, self._find_flags())
                while not c.isNull() and len(hits) < 5000:
                    hits.append(c)
                    c = doc.find(text, c, self._find_flags())
            ed.set_find_hits(hits)
            total += len(hits)
        self.find_bar.info.setText(f"Найдено: {total}" if text else "")

    def find_next(self, backward=False):
        text = self.find_bar.find.text()
        if not text or not self.find_bar.isVisible():
            if not self.find_bar.isVisible():
                self.open_find()
            return
        ed = self.active
        doc = ed.document()
        c = doc.find(text, ed.textCursor(), self._find_flags(backward))
        if c.isNull():
            start = QTextCursor(doc)
            if backward:
                start.movePosition(QTextCursor.MoveOperation.End)
            c = doc.find(text, start, self._find_flags(backward))
        if not c.isNull():
            ed.setTextCursor(c)
            ed.ensureCursorVisible()

    def replace_one(self):
        ed = self.active
        text = self.find_bar.find.text()
        if not text or ed.isReadOnly():
            return
        c = ed.textCursor()
        same = c.selectedText() == text if self.find_bar.case.isChecked() else \
            c.selectedText().lower() == text.lower()
        if c.hasSelection() and same:
            c.insertText(self.find_bar.replace.text())
        self.find_next(False)
        self.find_update()

    def replace_all(self):
        text = self.find_bar.find.text()
        if not text:
            return
        rep = self.find_bar.replace.text()
        count = 0
        for ed in self._find_targets():
            if ed.isReadOnly():
                continue
            doc = ed.document()
            cur = QTextCursor(doc)
            cur.beginEditBlock()
            c = doc.find(text, 0, self._find_flags())
            while not c.isNull():
                c.insertText(rep)
                count += 1
                c = doc.find(text, c, self._find_flags())
            cur.endEditBlock()
        self.find_update()
        self.statusBar().showMessage(f"Заменено: {count}", 4000)

    # ------------------------------------------------------------------ #
    #  Reading position
    # ------------------------------------------------------------------ #
    def _top_anchor(self, ed: BookEditor):
        doc = ed.document()
        if not ed.book or doc.isEmpty():
            return None
        y = ed.verticalScrollBar().value()
        layout = doc.documentLayout()
        pos = ed.cursorForPosition(ed.viewport().rect().topLeft()).position()
        block = doc.findBlock(pos)
        rect = layout.blockBoundingRect(block)
        frac = (y - rect.y()) / rect.height() if rect.height() > 0 else 0.0
        return {"block": block.blockNumber(), "frac": max(0.0, min(1.0, frac)),
                "cursor": ed.textCursor().position()}

    def _restore_anchor(self, ed: BookEditor, anchor):
        if not anchor or not ed.book:
            return
        doc = ed.document()
        block = doc.findBlockByNumber(min(anchor.get("block", 0), doc.blockCount() - 1))
        rect = doc.documentLayout().blockBoundingRect(block)
        y = rect.y() + rect.height() * anchor.get("frac", 0.0)
        sb = ed.verticalScrollBar()
        self.sync.paused = True
        try:
            c = QTextCursor(doc)
            c.setPosition(min(max(0, anchor.get("cursor", block.position())), doc.characterCount() - 1))
            ed.setTextCursor(c)
            sb.setValue(int(round(y)))
        finally:
            self.sync.paused = False

    def _restore_positions(self):
        if not self.project:
            return
        st = self.project.state
        for side in SIDES:
            self._restore_anchor(self.pane(side).editor, st.get(side))
        active = st.get("active", "left")
        self.pane(active).editor.setFocus()

    def save_state(self):
        if self.project:
            st = self.project.state
            for side in SIDES:
                a = self._top_anchor(self.pane(side).editor)
                if a:
                    st[side] = a
            st["active"] = self.active.side
            st["splitter"] = self.splitter.sizes()
            self.notes.sync_back()
            try:
                self.project.save_state()
            except OSError:
                pass
        self.settings["geometry"] = bytes(self.saveGeometry().data()).hex()
        try:
            self.store.save_settings()
        except OSError:
            pass

    def closeEvent(self, e: QCloseEvent):
        if not self.maybe_save():
            e.ignore()
            return
        self.save_state()
        e.accept()


def _install_translations(app: QApplication):
    tr = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if tr.load(QLocale(QLocale.Language.Russian), "qtbase", "_", path):
        app.installTranslator(tr)


def main():
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fb2.translation.editor")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text" if sys.platform == "win32" else app.font().family())
    font.setPointSizeF(10)
    app.setFont(font)
    _install_translations(app)
    win = MainWindow()
    win.show()
    return app.exec()
