"""Error and crash logging.

* Python errors are written to ``error.log`` and shown in a message box
  instead of disappearing silently (a windowed .exe has no console).
* Hard crashes inside Qt are recorded by :mod:`faulthandler` in ``crash.log``;
  on the next start the user is told where to find the report.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback

from .projects import app_data_dir

_crash_file = None
_showing = False


def log_dir() -> str:
    return app_data_dir()


def error_log() -> str:
    return os.path.join(log_dir(), "error.log")


def crash_log() -> str:
    return os.path.join(log_dir(), "crash.log")


def _write(text: str):
    try:
        with open(error_log(), "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


def install() -> str | None:
    """Set up logging. Returns the path of a crash report left by the previous run, if any."""
    global _crash_file
    previous = None
    path = crash_log()
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            previous = os.path.join(log_dir(), time.strftime("crash-%Y%m%d-%H%M%S.log"))
            os.replace(path, previous)
    except OSError:
        previous = None
    try:
        _crash_file = open(path, "w", encoding="utf-8")
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError:
        pass
    # a windowed exe has no console: keep stray output instead of losing it
    if sys.stderr is None or sys.stdout is None:
        try:
            stream = open(error_log(), "a", encoding="utf-8", buffering=1)
            if sys.stderr is None:
                sys.stderr = stream
            if sys.stdout is None:
                sys.stdout = stream
        except OSError:
            pass
    sys.excepthook = _excepthook
    threading.excepthook = lambda args: _excepthook(args.exc_type, args.exc_value, args.exc_traceback)
    return previous


def _excepthook(etype, value, tb):
    global _showing
    text = "".join(traceback.format_exception(etype, value, tb))
    _write(time.strftime("\n=== %Y-%m-%d %H:%M:%S ===\n") + text)
    if _showing or threading.current_thread() is not threading.main_thread():
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        _showing = True
        QMessageBox.warning(
            None, "Ошибка",
            f"Произошла ошибка, но программа продолжает работать:\n\n{etype.__name__}: {value}\n\n"
            f"Подробности записаны в файл:\n{error_log()}")
    except Exception:  # noqa: BLE001
        pass
    finally:
        _showing = False
