"""Fija las formas reales de respuesta de Tupase (muestras anonimizadas en tests/fixtures)."""

import json
from pathlib import Path

import pytest

from tupase_mcp import account

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_activities_have_the_fields_search_relies_on():
    for element in load("activities"):
        assert {"activityId", "entityId", "entityName", "disciplineName", "startDateTime"} <= set(
            element
        )
        assert {"neighbourhood", "lat", "lon", "address", "city"} <= set(element["location"])


def test_reservations_have_the_fields_reservations_relies_on():
    for item in load("reservations"):
        assert {"reservationIdentityCode", "status", "qrUri", "activityInfo"} <= set(item)
        assert {"entityName", "disciplineName", "startDateTime"} <= set(item["activityInfo"])


def test_profile_has_the_fields_update_profile_sends():
    assert set(account.USER_FIELDS) <= set(load("profile"))


def test_status_and_countries_shapes():
    assert {"status", "userLogicalId"} <= set(load("status"))
    assert all({"id", "name"} <= set(country) for country in load("countries"))


def test_notifications_have_title_and_text():
    for item in load("notifications"):
        assert {"title", "subtitle", "text"} <= set(item)


@pytest.mark.parametrize(
    "name,keys",
    [("disciplines", {"discipline", "quantity"}), ("neighbourhoods", {"zone", "zoneId", "city"})],
)
def test_catalogs_are_lists_of_objects_with_known_keys(name, keys):
    data = load(name)
    assert data and all(keys <= set(item) for item in data)


def test_fixtures_contain_no_personal_data():
    blob = " ".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.json"))
    assert "@" not in blob
