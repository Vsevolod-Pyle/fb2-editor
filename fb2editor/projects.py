"""Projects: a pair of books (two sides) with a history of saved versions.

Layout on disk (inside the user's AppData folder)::

    projects/<project-id>/project.json
    projects/<project-id>/left/0001-original.fb2
    projects/<project-id>/left/quick.fb2
    projects/<project-id>/right/...

Every side has a list of versions.  The first one is the imported original and
is never overwritten.  "Save version" always adds a new entry, "Quick save"
adds a single ``quick`` entry the first time and overwrites it afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass

SIDES = ("left", "right")


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "FB2 Translation Editor")
    os.makedirs(path, exist_ok=True)
    return path


def _now() -> float:
    return time.time()


def _atomic_write(path: str, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@dataclass
class Version:
    id: str
    file: str  # relative to project dir
    kind: str  # original | import | manual | quick
    created: float
    updated: float
    note: str = ""
    source: str = ""  # original file path for imported versions

    def to_json(self):
        return self.__dict__.copy()

    @staticmethod
    def from_json(d):
        return Version(**{k: d.get(k, "") for k in Version.__dataclass_fields__})

    def label(self, number: int) -> str:
        stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(self.updated or self.created))
        name = {
            "original": "Оригинал",
            "import": "Импорт",
            "manual": f"Версия {number}",
            "quick": "Быстрое сохранение",
        }.get(self.kind, self.kind)
        text = f"{name} · {stamp}"
        if self.note:
            text += f" · {self.note}"
        return text


class Project:
    def __init__(self, root: str, data: dict):
        self.root = root
        self.data = data

    # -- basic properties --------------------------------------------------- #
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def name(self) -> str:
        return self.data.get("name", "Без названия")

    @name.setter
    def name(self, value: str):
        self.data["name"] = value
        self.save()

    @property
    def state(self) -> dict:
        return self.data.setdefault("state", {})

    def side(self, side: str) -> dict:
        return self.data.setdefault("sides", {}).setdefault(side, {"label": "", "versions": [], "current": None})

    def label(self, side: str) -> str:
        return self.side(side).get("label") or ("RU" if side == "left" else "EN")

    def set_label(self, side: str, label: str):
        self.side(side)["label"] = label
        self.save()

    def versions(self, side: str) -> list[Version]:
        return [Version.from_json(v) for v in self.side(side).get("versions", [])]

    def version(self, side: str, vid: str | None) -> Version | None:
        for v in self.versions(side):
            if v.id == vid:
                return v
        return None

    def current(self, side: str) -> Version | None:
        s = self.side(side)
        v = self.version(side, s.get("current"))
        if v is None:
            vs = self.versions(side)
            v = vs[-1] if vs else None
        return v

    def set_current(self, side: str, vid: str):
        self.side(side)["current"] = vid
        self.save()

    def path_of(self, v: Version) -> str:
        return os.path.join(self.root, v.file)

    def number_of(self, side: str, v: Version) -> int:
        n = 0
        for x in self.versions(side):
            if x.kind in ("manual", "original", "import"):
                n += 1
            if x.id == v.id:
                return n
        return n

    @property
    def updated(self) -> float:
        return self.data.get("updated", self.data.get("created", 0))

    # -- persistence -------------------------------------------------------- #
    def save(self):
        self.data["updated"] = _now()
        _atomic_write(os.path.join(self.root, "project.json"),
                      json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8"))

    def save_state(self):
        """Persist reading position etc. without touching the 'updated' stamp."""
        _atomic_write(os.path.join(self.root, "project.json"),
                      json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8"))

    # -- versions ----------------------------------------------------------- #
    def _next_file(self, side: str, kind: str) -> str:
        os.makedirs(os.path.join(self.root, side), exist_ok=True)
        n = len(self.side(side).get("versions", [])) + 1
        while True:
            rel = f"{side}/{n:04d}-{kind}.fb2"
            if not os.path.exists(os.path.join(self.root, rel)):
                return rel
            n += 1

    def add_version(self, side: str, data: bytes, kind: str, note: str = "", source: str = "") -> Version:
        rel = self._next_file(side, kind) if kind != "quick" else f"{side}/quick.fb2"
        os.makedirs(os.path.join(self.root, side), exist_ok=True)
        _atomic_write(os.path.join(self.root, rel), data)
        t = _now()
        v = Version(uuid.uuid4().hex[:12], rel, kind, t, t, note, source)
        self.side(side).setdefault("versions", []).append(v.to_json())
        self.side(side)["current"] = v.id
        self.save()
        return v

    def quick_save(self, side: str, data: bytes) -> Version:
        for raw in self.side(side).get("versions", []):
            if raw.get("kind") == "quick":
                _atomic_write(os.path.join(self.root, raw["file"]), data)
                raw["updated"] = _now()
                self.side(side)["current"] = raw["id"]
                self.save()
                return Version.from_json(raw)
        return self.add_version(side, data, "quick")

    def import_file(self, side: str, path: str, data: bytes) -> Version:
        kind = "original" if not self.side(side).get("versions") else "import"
        return self.add_version(side, data, kind, note=os.path.basename(path), source=path)

    def delete_version(self, side: str, vid: str) -> bool:
        vs = self.side(side).get("versions", [])
        for i, raw in enumerate(vs):
            if raw["id"] == vid:
                if raw.get("kind") == "original":
                    return False
                try:
                    os.remove(os.path.join(self.root, raw["file"]))
                except OSError:
                    pass
                del vs[i]
                if self.side(side).get("current") == vid:
                    self.side(side)["current"] = vs[-1]["id"] if vs else None
                self.save()
                return True
        return False


class ProjectStore:
    def __init__(self, base: str | None = None):
        self.base = base or app_data_dir()
        self.dir = os.path.join(self.base, "projects")
        os.makedirs(self.dir, exist_ok=True)
        self.settings_path = os.path.join(self.base, "settings.json")
        self.settings = self._load_settings()

    # -- settings ----------------------------------------------------------- #
    def _load_settings(self) -> dict:
        try:
            with open(self.settings_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        _atomic_write(self.settings_path, json.dumps(self.settings, ensure_ascii=False, indent=2).encode("utf-8"))

    # -- projects ----------------------------------------------------------- #
    def list(self) -> list[Project]:
        out = []
        for name in os.listdir(self.dir):
            p = self.open(name)
            if p:
                out.append(p)
        out.sort(key=lambda p: p.data.get("opened", p.updated), reverse=True)
        return out

    def open(self, pid: str) -> Project | None:
        root = os.path.join(self.dir, pid)
        try:
            with open(os.path.join(root, "project.json"), encoding="utf-8") as fh:
                return Project(root, json.load(fh))
        except (OSError, ValueError):
            return None

    def create(self, name: str, left_label="RU", right_label="EN") -> Project:
        pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        root = os.path.join(self.dir, pid)
        os.makedirs(root)
        t = _now()
        p = Project(root, {
            "id": pid, "name": name, "created": t, "updated": t, "opened": t,
            "sides": {
                "left": {"label": left_label, "versions": [], "current": None},
                "right": {"label": right_label, "versions": [], "current": None},
            },
            "state": {},
        })
        p.save()
        return p

    def delete(self, pid: str):
        shutil.rmtree(os.path.join(self.dir, pid), ignore_errors=True)
