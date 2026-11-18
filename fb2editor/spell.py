"""Spell checking with Hunspell dictionaries (Russian + English).

The dictionaries are loaded in a background thread; until they are ready no
words are marked.  Words the user adds are kept in ``user_words.txt`` next to
the application settings.
"""

from __future__ import annotations

import os
import re
import threading

from PySide6.QtCore import QObject, Signal

DICT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dicts")

WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:['’\-][A-Za-zА-Яа-яЁё]+)*")
_CYR = re.compile(r"[А-Яа-яЁё]")


class Speller(QObject):
    ready = Signal()
    changed = Signal()  # user dictionary changed: re-check visible text

    def __init__(self, user_dict_path: str, parent=None):
        super().__init__(parent)
        self.user_dict_path = user_dict_path
        self.dicts: dict[str, object] = {}
        self.loaded = False
        self.done = False  # loading finished (successfully or not)
        self.error = ""
        self._cache: dict[str, bool] = {}
        self.ignored: set[str] = set()
        self.user_words: set[str] = set()
        try:
            with open(user_dict_path, encoding="utf-8") as fh:
                self.user_words = {w.strip().lower() for w in fh if w.strip()}
        except OSError:
            pass
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            from spylls.hunspell import Dictionary

            for lang, name in (("en", "en_US"), ("ru", "ru_RU")):
                path = os.path.join(DICT_DIR, name)
                if os.path.exists(path + ".dic"):
                    self.dicts[lang] = Dictionary.from_files(path)
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
        if not self.dicts and not self.error:
            self.error = f"словари не найдены в {DICT_DIR}"
        self.loaded = bool(self.dicts)
        self.done = True
        self.ready.emit()

    # ------------------------------------------------------------------ #
    @staticmethod
    def lang_of(word: str) -> str:
        return "ru" if _CYR.search(word) else "en"

    def _lookup(self, word: str) -> bool:
        d = self.dicts.get(self.lang_of(word))
        if d is None:
            return True
        variants = [word, word.lower(), word.capitalize()]
        if "ё" in word.lower():
            variants.append(word.lower().replace("ё", "е"))
        if "’" in word:
            variants.append(word.replace("’", "'"))
        return any(d.lookup(v) for v in variants)

    def check(self, word: str) -> bool:
        """True if the word is spelled correctly (or cannot be judged)."""
        if not self.loaded or len(word) < 2:
            return True
        if word.isupper() and len(word) <= 6:  # abbreviations
            return True
        key = word.lower()
        if key in self.user_words or key in self.ignored:
            return True
        res = self._cache.get(word)
        if res is None:
            try:
                res = self._lookup(word)
                if not res and "-" in word:
                    res = all(self._lookup(p) for p in word.split("-") if len(p) > 1)
            except Exception:  # noqa: BLE001
                res = True
            if len(self._cache) > 200_000:
                self._cache.clear()
            self._cache[word] = res
        return res

    def suggest(self, word: str, limit: int = 7) -> list[str]:
        d = self.dicts.get(self.lang_of(word))
        if d is None:
            return []
        out = []
        try:
            for s in d.suggest(word):
                if s not in out:
                    out.append(s)
                if len(out) >= limit:
                    break
        except Exception:  # noqa: BLE001
            pass
        return out

    def add_word(self, word: str):
        self.user_words.add(word.lower())
        try:
            os.makedirs(os.path.dirname(self.user_dict_path), exist_ok=True)
            with open(self.user_dict_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(sorted(self.user_words)) + "\n")
        except OSError:
            pass
        self.changed.emit()

    def ignore(self, word: str):
        self.ignored.add(word.lower())
        self.changed.emit()
