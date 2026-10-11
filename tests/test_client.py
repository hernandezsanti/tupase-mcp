import httpx
import pytest
import respx

from tupase_mcp.client import TupaseClient
from tupase_mcp.errors import NoSessionError, TupaseError

BASE = "https://api.test"


class FakeTokens:
    def __init__(self):
        self.token = "t1"
        self.refreshes = 0
        self.stale = None

    def access_token(self):
        return self.token

    def force_refresh(self, stale):
        self.stale = stale
        self.refreshes += 1
        self.token = f"t{self.refreshes + 1}"
        return self.token


@pytest.fixture
def tokens():
    return FakeTokens()


@pytest.fixture
def client(tokens):
    with httpx.Client() as http:
        yield TupaseClient(http, tokens, base_url=BASE)


@respx.mock
def test_get_sends_bearer_and_params(client):
    route = respx.get(f"{BASE}/users/notifications").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    assert client.get("users/notifications", params={"page": 0}) == {"items": []}
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer t1"
    assert request.url.params["page"] == "0"


@respx.mock
def test_401_refreshes_once_and_retries(client, tokens):
    route = respx.post(f"{BASE}/x").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
    )
    assert client.post("x", json={"a": 1}) == {"ok": True}
    assert tokens.refreshes == 1
    assert tokens.stale == "t1"
    assert route.calls[1].request.headers["authorization"] == "Bearer t2"
    assert route.calls[0].request.content == route.calls[1].request.content


@respx.mock
def test_second_401_means_no_session(client):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401))
    with pytest.raises(NoSessionError):
        client.get("x")


@respx.mock
def test_business_error_message_is_safe(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(400, json={"message": "Cupo completo"})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert info.value.safe_for_user and str(info.value) == "Cupo completo"


@respx.mock
def test_server_error_message_is_never_safe(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(500, json={"message": "NullPointerException at ..."})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert not info.value.safe_for_user


@respx.mock
def test_200_with_errors_list_is_an_error(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(200, json={"errors": ["e"], "message": "Ya tienes una reserva"})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert info.value.safe_for_user and "Ya tienes una reserva" in str(info.value)


@respx.mock
def test_200_with_empty_errors_is_fine(client):
    respx.post(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"errors": [], "a": 1}))
    assert client.post("x", json={})["a"] == 1


@respx.mock
def test_200_not_json_is_unsafe_error(client):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(TupaseError) as info:
        client.get("x")
    assert not info.value.safe_for_user


@respx.mock
def test_boolean_body_is_accepted(client):
    respx.put(f"{BASE}/users/user-account").mock(return_value=httpx.Response(200, json=True))
    assert client.put("users/user-account", json={}) is True


@respx.mock
def test_network_error_is_unsafe_and_hides_url(client):
    respx.get(f"{BASE}/x").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(TupaseError) as info:
        client.get("x")
    assert not info.value.safe_for_user and "ConnectError" in str(info.value)


@respx.mock
def test_show_message_is_used_on_4xx(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(400, json={"showMessage": "Horario no disponible"})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert info.value.safe_for_user and str(info.value) == "Horario no disponible"


@respx.mock
def test_non_str_message_falls_back_to_show_message(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(400, json={"message": {"a": 1}, "showMessage": "Ok visible"})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert info.value.safe_for_user and str(info.value) == "Ok visible"


@respx.mock
def test_non_str_message_is_unsafe_and_not_echoed(client):
    respx.post(f"{BASE}/x").mock(
        return_value=httpx.Response(400, json={"message": {"secret": "boom"}})
    )
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert not info.value.safe_for_user
    assert "secret" not in str(info.value) and "{" not in str(info.value)


@respx.mock
@pytest.mark.parametrize("body", [["a"], "texto"])
def test_4xx_list_or_string_body_is_unsafe(client, body):
    respx.post(f"{BASE}/x").mock(return_value=httpx.Response(400, json=body))
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert not info.value.safe_for_user and "400" in str(info.value)


@respx.mock
def test_4xx_empty_body_uses_generic_fallback(client):
    respx.post(f"{BASE}/x").mock(return_value=httpx.Response(404))
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert not info.value.safe_for_user and "404" in str(info.value)


@respx.mock
def test_200_errors_without_message_is_unsafe(client):
    respx.post(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"errors": ["e"]}))
    with pytest.raises(TupaseError) as info:
        client.post("x", json={})
    assert not info.value.safe_for_user


@respx.mock
def test_204_empty_body_returns_true(client):
    respx.put(f"{BASE}/x").mock(return_value=httpx.Response(204))
    assert client.put("x", json={}) is True


@respx.mock
def test_201_json_body_is_returned(client):
    respx.post(f"{BASE}/x").mock(return_value=httpx.Response(201, json={"id": 7}))
    assert client.post("x", json={}) == {"id": 7}


@respx.mock
def test_json_scalar_body_is_unsafe_with_accurate_wording(client):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json="hola"))
    with pytest.raises(TupaseError) as info:
        client.get("x")
    assert not info.value.safe_for_user and "objeto, una lista ni un booleano" in str(info.value)
