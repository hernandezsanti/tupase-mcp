"""Favoritos de lugares en un JSON local (Tupase no tiene favoritos propios)."""

import json
import os
import tempfile
from pathlib import Path

import platformdirs


def default_path() -> Path:
    return Path(platformdirs.user_data_dir("tupase-mcp")) / "favorites.json"


class FavoritesStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()

    def list(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [f for f in data if isinstance(f, dict) and isinstance(f.get("entity_id"), str)]

    def ids(self) -> set[str]:
        return {f["entity_id"] for f in self.list()}

    def add(self, entity_id: str, lugar: str) -> bool:
        items = self.list()
        if any(f["entity_id"] == entity_id for f in items):
            return False
        items.append({"entity_id": entity_id, "lugar": lugar})
        self._write(items)
        return True

    def remove(self, entity_id: str) -> bool:
        items = self.list()
        kept = [f for f in items if f["entity_id"] != entity_id]
        if len(kept) == len(items):
            return False
        self._write(kept)
        return True

    def _write(self, items) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
