import json

from tupase_mcp.favorites import FavoritesStore


def test_add_list_remove(tmp_path):
    store = FavoritesStore(tmp_path / "sub" / "favorites.json")
    assert store.list() == []
    assert store.add("e1", "Estudio Sol") is True
    assert store.add("e1", "Estudio Sol") is False
    assert store.add("e2", "Pádel Ñandú") is True
    assert store.ids() == {"e1", "e2"}
    assert store.remove("e1") is True
    assert store.remove("e1") is False
    assert store.list() == [{"entity_id": "e2", "lugar": "Pádel Ñandú"}]


def test_persists_across_instances(tmp_path):
    path = tmp_path / "favorites.json"
    FavoritesStore(path).add("e1", "A")
    assert FavoritesStore(path).ids() == {"e1"}


def test_corrupt_empty_or_non_list_file_is_empty(tmp_path):
    path = tmp_path / "favorites.json"
    store = FavoritesStore(path)
    for content in [
        "",
        "{no es json",
        json.dumps({"a": 1}),
        json.dumps([1, "x", {"lugar": "sin id"}]),
    ]:
        path.write_text(content, encoding="utf-8")
        assert store.list() == []
    path.write_text("{no es json", encoding="utf-8")
    assert store.add("e1", "A") is True
    assert store.ids() == {"e1"}
