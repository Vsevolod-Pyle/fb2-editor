"""Render the application icon to assets/icon.ico (used by the Windows build)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from fb2editor.theme import app_icon  # noqa: E402

app = QApplication([])
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
pm = app_icon().pixmap(256, 256)
if not pm.save(out, "ICO"):
    pm.save(out.replace(".ico", ".png"), "PNG")
    print("ICO writer not available, saved PNG")
else:
    print("saved", out)
