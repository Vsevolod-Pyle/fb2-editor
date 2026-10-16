"""Small dialogs: new project, save version."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

FB2_FILTER = "Книги FB2 (*.fb2 *.fb2.zip *.zip);;Все файлы (*)"


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 14pt; font-weight: 700;")
    return lbl


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


class FilePicker(QLineEdit):
    def __init__(self, start_dir_getter, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Выберите .fb2 файл…")
        self._start = start_dir_getter

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть книгу", self.text() or self._start(), FB2_FILTER)
        if path:
            self.setText(path)


class NewProjectDialog(QDialog):
    def __init__(self, start_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый проект")
        self.setMinimumWidth(560)
        self._start_dir = start_dir
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(_title("Новый проект"))
        lay.addWidget(_muted("Выберите две версии книги — оригинал и перевод. "
                             "Файлы копируются в проект, исходники не изменяются. "
                             "Вторую книгу можно добавить позже."))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Название"), 0, 0)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Например: «Остров сокровищ»")
        grid.addWidget(self.name, 0, 1, 1, 3)

        self.left_label = QLineEdit("RU")
        self.right_label = QLineEdit("EN")
        self.left_file = FilePicker(lambda: self._start_dir)
        self.right_file = FilePicker(lambda: self._start_dir)
        for row, (lab, picker) in enumerate(((self.left_label, self.left_file),
                                              (self.right_label, self.right_file)), start=1):
            lab.setMaximumWidth(64)
            lab.setToolTip("Короткая метка книги (язык)")
            grid.addWidget(QLabel("Слева" if row == 1 else "Справа"), row, 0)
            grid.addWidget(lab, row, 1)
            grid.addWidget(picker, row, 2)
            btn = QPushButton("Обзор…")
            btn.clicked.connect(picker.browse)
            grid.addWidget(btn, row, 3)
        self.left_file.textChanged.connect(self._autoname)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Создать проект")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addSpacing(6)
        lay.addLayout(buttons)

    def _autoname(self, path: str):
        if not self.name.text().strip() or getattr(self, "_auto", False):
            base = os.path.basename(path)
            for ext in (".zip", ".fb2"):
                if base.lower().endswith(ext):
                    base = base[: -len(ext)]
            self.name.setText(base)
            self._auto = True

    def _accept(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()


class SaveVersionDialog(QDialog):
    def __init__(self, labels: dict, dirty: dict, available: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сохранить версию")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(_title("Новая версия"))
        lay.addWidget(_muted("Версия добавится в историю проекта; предыдущие сохранения не изменятся."))
        self.note = QLineEdit()
        self.note.setPlaceholderText("Комментарий (необязательно), например: «вычитана глава 3»")
        lay.addWidget(self.note)
        self.checks = {}
        any_dirty = any(dirty.values())
        for side in ("left", "right"):
            cb = QCheckBox(f"{labels[side]}" + ("  — есть несохранённые изменения" if dirty[side] else ""))
            cb.setChecked(available[side] and (dirty[side] or not any_dirty))
            cb.setEnabled(available[side])
            self.checks[side] = cb
            lay.addWidget(cb)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addSpacing(6)
        lay.addLayout(buttons)

    def sides(self) -> list[str]:
        return [s for s, cb in self.checks.items() if cb.isChecked()]
