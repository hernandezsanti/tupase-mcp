import httpx
import pytest
import respx

from tupase_mcp import reservations
from tupase_mcp.errors import TupaseError


class FakeClient:
    def __init__(self, get=None, post=None):
        self._get = get
        self._post = post
        self.calls = []

    def get(self, path, *, params=None):
        self.calls.append(("GET", path, params))
        if isinstance(self._get, Exception):
            raise self._get
        return self._get(path, params) if callable(self._get) else self._get

    def post(self, path, *, json=None):
        self.calls.append(("POST", path, json))
        return self._post


def reservation(
    code="ABC", status="CONFIRMED", entity="Estudio Sol", start="2026-10-14T21:00:00", **extra
):
    base = {
        "reservationIdentityCode": code,
        "status": status,
        "statusStr": "Confirmada",
        "qrUri": "https://qr.example/abc.png",
        "activityInfo": {"entityName": entity, "disciplineName": "Yoga", "startDateTime": start},
    }
    base.update(extra)
    return base


def cupo(entity="Estudio Sol", when="14/10/2026 18:00"):
    return {"title": f"Se te ha asignado un cupo para {entity}", "subtitle": f"Clase el {when}"}


def test_match_cupo_asignado_exactly_one_match():
    pending = reservation(status="PENDING_CONFIRMATION")
    assert reservations.match_cupo_asignado(pending, [cupo()])
    assert not reservations.match_cupo_asignado(pending, [])
    assert not reservations.match_cupo_asignado(pending, [cupo(entity="Otro")])
    assert not reservations.match_cupo_asignado(pending, [cupo(when="14/10/2026 19:00")])


def test_match_cupo_asignado_two_matches_is_failsafe_false():
    pending = reservation(status="PENDING_CONFIRMATION")
    assert not reservations.match_cupo_asignado(pending, [cupo(), cupo()])


def test_match_cupo_asignado_ignores_garbage():
    pending = reservation(status="PENDING_CONFIRMATION")
    junk = [
        None,
        "x",
        {"title": cupo()["title"], "subtitle": "sin fecha"},
        {"title": cupo()["title"], "subtitle": "31/02/2026 10:00"},
    ]
    assert not reservations.match_cupo_asignado(pending, junk)
    assert not reservations.match_cupo_asignado({"status": "PENDING_CONFIRMATION"}, [cupo()])


def test_get_reservations_confirms_pending_with_notification():
    raw = [reservation("A", status="PENDING_CONFIRMATION"), reservation("B")]

    def get(path, params):
        return raw if "reservations" in path else {"items": [cupo()]}

    result = reservations.get_reservations(FakeClient(get=get), "u1")
    by_code = {r["codigo"]: r for r in result}
    assert by_code["A"]["estado"] == "CONFIRMED" and by_code["A"]["estado_texto"] == "Confirmada"
    assert by_code["B"]["estado"] == "CONFIRMED"
    assert by_code["A"]["inicio"] == "2026-10-14T18:00:00-03:00"


def test_get_reservations_skips_notifications_when_nothing_pending():
    client = FakeClient(get=lambda path, params: [reservation("B")])
    reservations.get_reservations(client, "u1")
    assert [c[1] for c in client.calls] == ["users/reservations/user/u1"]


def test_get_reservations_degrades_when_notifications_fail():
    def get(path, params):
        if "notifications" in path:
            raise TupaseError("boom")
        return [reservation("A", status="PENDING_CONFIRMATION")]

    result = reservations.get_reservations(FakeClient(get=get), "u1")
    assert result[0]["estado"] == "PENDING_CONFIRMATION"


def test_get_reservations_pagination_params():
    client = FakeClient(get=lambda path, params: [])
    reservations.get_reservations(client, "u1", page=2, page_size=5)
    assert client.calls[0][2] == {"page": 2, "pageSize": 5}


def test_list_reservations_requires_list():
    with pytest.raises(TupaseError):
        reservations.list_reservations(FakeClient(get=lambda p, q: {"x": 1}), "u1")


def test_list_notifications_returns_items():
    client = FakeClient(get=lambda p, q: {"items": [cupo()]})
    assert reservations.list_notifications(client) == [cupo()]
    assert client.calls[0][2] == {"page": 0, "limit": 50}


def test_find_reservation_by_code():
    client = FakeClient(get=lambda p, q: [reservation("A"), reservation("B")])
    assert reservations.find_reservation(client, "u1", "B")["reservationIdentityCode"] == "B"
    assert reservations.find_reservation(client, "u1", "Z") is None


def test_create_reservation_body():
    client = FakeClient(post={"reservationIdentityCode": "N1"})
    out = reservations.create_reservation(
        client, "u1", "e1", "a1", "Yoga", "2026-10-14T21:00:00", 1760000000
    )
    assert out["reservationIdentityCode"] == "N1"
    assert client.calls[0] == (
        "POST",
        "users/reservations",
        {
            "timeStamp": 1760000000,
            "entityId": "e1",
            "userLogicalId": "u1",
            "activityDate": "2026-10-14T21:00:00",
            "activityId": "a1",
            "activityName": "Yoga",
        },
    )


def test_cancel_reservation_sends_utc_date_only():
    client = FakeClient(post={"status": "CANCELLED"})
    reservations.cancel_reservation(client, "ABC", "2026-10-14T21:00:00")
    assert client.calls[0] == (
        "POST",
        "users/reservations/cancel",
        {"activityDateStr": "2026-10-14", "reservationIdentityId": "ABC"},
    )


@respx.mock
def test_fetch_qr_image_returns_bytes():
    respx.get("https://qr.example/abc.png").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )
    with httpx.Client() as http:
        assert reservations.fetch_qr_image(http, "https://qr.example/abc.png") == b"\x89PNG"


def test_fetch_qr_image_rejects_non_https():
    with httpx.Client() as http, pytest.raises(TupaseError):
        reservations.fetch_qr_image(http, "http://qr.example/abc.png")


@respx.mock
def test_fetch_qr_image_failure_is_unsafe_error():
    respx.get("https://qr.example/abc.png").mock(return_value=httpx.Response(404))
    with httpx.Client() as http, pytest.raises(TupaseError) as info:
        reservations.fetch_qr_image(http, "https://qr.example/abc.png")
    assert not info.value.safe_for_user


def test_normalize_reservation_is_robust_to_odd_input():
    empty = reservations.normalize_reservation(True)
    assert isinstance(empty, dict) and empty["codigo"] is None and empty["inicio"] is None
    assert reservations.normalize_reservation([])["inicio"] is None
    no_info = reservations.normalize_reservation(
        {"reservationIdentityCode": "A", "activityInfo": "x"}
    )
    assert no_info["codigo"] == "A" and no_info["inicio"] is None
    bad_date = reservations.normalize_reservation(
        {"activityInfo": {"startDateTime": "no-es-fecha"}}
    )
    assert bad_date["inicio"] is None


@respx.mock
def test_fetch_qr_image_rejects_oversized_bodies():
    respx.get("https://qr.example/big.png").mock(
        return_value=httpx.Response(200, content=b"x" * 2_000_001)
    )
    with httpx.Client() as http, pytest.raises(TupaseError) as info:
        reservations.fetch_qr_image(http, "https://qr.example/big.png")
    assert info.value.safe_for_user is False
