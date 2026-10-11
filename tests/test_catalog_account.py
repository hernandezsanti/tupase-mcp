from datetime import timedelta

import pytest

from tupase_mcp import account, catalog
from tupase_mcp.errors import InputError, TupaseError
from tupase_mcp.timeutil import parse_local

DESDE = parse_local("2026-10-12T00:00:00")


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _go(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.routes[(method, path)]

    def get(self, path, *, params=None):
        return self._go("GET", path, params=params)

    def post(self, path, *, json=None):
        return self._go("POST", path, json=json)

    def put(self, path, *, json=None):
        return self._go("PUT", path, json=json)


def test_list_disciplines_posts_utc_window_and_returns_elements():
    client = FakeClient(
        {("POST", "search/disciplines/search-by-location"): {"elements": [{"name": "Yoga"}]}}
    )
    out = catalog.list_disciplines(client, DESDE, DESDE + timedelta(days=1))
    assert out == [{"name": "Yoga"}]
    body = client.calls[0][2]["json"]
    assert body["startDateTimeFrom"] == "2026-10-12T03:00:00"
    assert body["startDateTimeTo"] == "2026-10-13T03:00:00"


def test_list_neighbourhoods_body_has_only_the_window():
    client = FakeClient(
        {("POST", "search/neighbourhoods/search-by-location"): {"elements": [{"id": 1}]}}
    )
    assert catalog.list_neighbourhoods(client, DESDE, DESDE + timedelta(days=1)) == [{"id": 1}]
    assert set(client.calls[0][2]["json"]) == {"startDateTimeFrom", "startDateTimeTo"}


def test_catalog_unexpected_shape_is_an_error():
    client = FakeClient({("POST", "search/disciplines/search-by-location"): {"x": 1}})
    with pytest.raises(TupaseError):
        catalog.list_disciplines(client, DESDE, DESDE + timedelta(days=1))


PROFILE = {
    "activationCode": None,
    "birthDate": "1990-01-02",
    "countryId": "UY",
    "deviceIdentifier": None,
    "email": "a@b.com",
    "firstName": "Ana",
    "lastName": "Pérez",
    "phone": "099111222",
    "userDocument": "1234567",
    "userLogicalId": "u1",
    "extra": "no se reenvía",
}


def routes(put_result=True):
    return {
        ("GET", "users/user-account/u1"): dict(PROFILE),
        ("GET", "users/user-account/status/u1"): {"status": "ACTIVE", "userLogicalId": "u1"},
        ("GET", "payment-preferences/user/u1"): {"mpPaymentPreferenceId": "p"},
        ("GET", "countries"): [{"id": "UY", "name": "Uruguay"}, {"id": "AR", "name": "Argentina"}],
        ("PUT", "users/user-account"): put_result,
    }


def test_simple_getters():
    client = FakeClient(routes())
    assert account.get_profile(client, "u1")["firstName"] == "Ana"
    assert account.get_status(client, "u1")["status"] == "ACTIVE"
    assert account.get_payment_preferences(client, "u1")["mpPaymentPreferenceId"] == "p"
    assert [c["id"] for c in account.list_countries(client)] == ["UY", "AR"]


def test_update_profile_merges_and_puts_full_object():
    client = FakeClient(routes())
    out = account.update_profile(client, "u1", {"telefono": "098000111", "nombre": None})
    body = client.calls[-1][2]["json"]
    assert client.calls[-1][:2] == ("PUT", "users/user-account")
    assert body["phone"] == "098000111" and body["firstName"] == "Ana"
    assert body["userLogicalId"] == "u1" and "extra" not in body
    assert out["phone"] == "098000111"


def test_update_profile_validates_country_against_catalog():
    client = FakeClient(routes())
    account.update_profile(client, "u1", {"pais_id": "AR"})
    assert client.calls[-1][2]["json"]["countryId"] == "AR"
    with pytest.raises(InputError, match="pais_id"):
        account.update_profile(FakeClient(routes()), "u1", {"pais_id": "XX"})


def test_update_profile_rejects_empty_and_unknown_changes():
    with pytest.raises(InputError):
        account.update_profile(FakeClient(routes()), "u1", {"nombre": None})
    with pytest.raises(InputError):
        account.update_profile(FakeClient(routes()), "u1", {"email": "x@y.com"})


def test_update_profile_requires_tupase_to_confirm():
    with pytest.raises(TupaseError):
        account.update_profile(FakeClient(routes(put_result=False)), "u1", {"telefono": "1"})
