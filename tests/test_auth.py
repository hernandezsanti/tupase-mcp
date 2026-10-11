import json

import httpx
import keyring
import pytest
import respx

from tupase_mcp import auth, config
from tupase_mcp.errors import AuthError, NoSessionError

TOKEN_URL = f"https://{config.AUTH0_DOMAIN}/oauth/token"
USERINFO_URL = f"https://{config.AUTH0_DOMAIN}/userinfo"


@pytest.fixture
def http():
    with httpx.Client() as client:
        yield client


def _store(refresh_token="rt1", sub="auth0|abc123", email="a@b.com"):
    auth.save_session(auth.Session(refresh_token, sub, email))


@respx.mock
def test_login_saves_session_without_password(http):
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "refresh_token": "rt1"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=httpx.Response(200, json={"sub": "auth0|abc123", "email": "a@b.com"})
    )
    session = auth.login("a@b.com", "contraseña-ñ|1", http)
    assert session == auth.Session("rt1", "auth0|abc123", "a@b.com")
    sent = json.loads(token_route.calls[0].request.content)
    assert sent["password"] == "contraseña-ñ|1"
    stored = keyring.get_password(auth.SERVICE, auth.ACCOUNT)
    assert "contraseña" not in stored and "password" not in stored
    assert auth.load_session() == session


@respx.mock
def test_login_wrong_password_raises_auth_error(http):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(403, json={"error": "access_denied"}))
    with pytest.raises(AuthError) as info:
        auth.login("a@b.com", "mala", http)
    assert info.value.status_code == 403
    assert auth.load_session() is None


@respx.mock
def test_login_without_refresh_token_fails(http):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "at"}))
    with pytest.raises(AuthError):
        auth.login("a@b.com", "x", http)


def test_no_session_raises_no_session_error(http):
    with pytest.raises(NoSessionError):
        auth.TokenProvider(http).access_token()


@respx.mock
def test_access_token_refreshes_once_and_caches(http):
    _store()
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a1"})
    )
    tokens = auth.TokenProvider(http)
    assert tokens.access_token() == "a1"
    assert tokens.access_token() == "a1"
    assert route.call_count == 1
    sent = json.loads(route.calls[0].request.content)
    assert sent["grant_type"] == "refresh_token" and sent["refresh_token"] == "rt1"


@respx.mock
def test_rotated_refresh_token_is_saved(http):
    _store()
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a1", "refresh_token": "rt2"})
    )
    auth.TokenProvider(http).access_token()
    assert auth.load_session().refresh_token == "rt2"


@respx.mock
def test_refresh_rejected_means_no_session(http):
    _store()
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(403, json={"error": "invalid_grant"}))
    with pytest.raises(NoSessionError):
        auth.TokenProvider(http).access_token()


@respx.mock
def test_refresh_server_error_is_not_no_session(http):
    _store()
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(AuthError):
        auth.TokenProvider(http).access_token()


@respx.mock
def test_stale_force_refresh_does_not_refresh_twice(http):
    _store()
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "a1"}),
            httpx.Response(200, json={"access_token": "a2"}),
        ]
    )
    tokens = auth.TokenProvider(http)
    assert tokens.access_token() == "a1"
    assert tokens.force_refresh("a1") == "a2"
    assert tokens.force_refresh("a1") == "a2"  # otro request con el token viejo
    assert route.call_count == 2


@pytest.mark.parametrize(
    "sub,expected",
    [
        ("auth0|abc123", "abc123"),
        ("google-oauth2|99", "99"),
        ("sinbarra", "sinbarra"),
        ("a|b|c", "b|c"),
    ],
)
def test_user_logical_id_from_sub(http, sub, expected):
    _store(sub=sub)
    assert auth.TokenProvider(http).user_logical_id() == expected


def test_clear_session_is_idempotent():
    _store()
    auth.clear_session()
    auth.clear_session()
    assert auth.load_session() is None


class BrokenKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self, error):
        super().__init__()
        self.error = error

    def set_password(self, service, username, password):
        raise self.error

    def get_password(self, service, username):
        raise self.error

    def delete_password(self, service, username):
        raise self.error


@pytest.mark.parametrize("error", [keyring.errors.KeyringError("boom"), RuntimeError("no backend")])
def test_keyring_failures_become_a_safe_auth_error(error):
    keyring.set_keyring(BrokenKeyring(error))
    for call in (
        lambda: auth.save_session(auth.Session("rt", "auth0|1", "a@b.com")),
        auth.load_session,
        auth.clear_session,
    ):
        with pytest.raises(AuthError, match="llavero del sistema") as info:
            call()
        assert info.value.safe_for_user is True
        assert info.value.__cause__ is error


def test_clear_session_stays_idempotent_when_nothing_is_stored():
    keyring.set_keyring(BrokenKeyring(keyring.errors.PasswordDeleteError("no existe")))
    auth.clear_session()
