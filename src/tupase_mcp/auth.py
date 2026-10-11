"""Login y refresh contra Auth0; el refresh token vive en el llavero del sistema."""

import json
import threading
from dataclasses import asdict, dataclass, replace

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from . import config
from .errors import AuthError, NoSessionError

SERVICE = "tupase-mcp"
ACCOUNT = "session"
GRANT_TYPE = "http://auth0.com/oauth/grant-type/password-realm"
REALM = "Username-Password-Authentication"
LOGIN_SCOPE = "openid profile email read:current_user update:current_user_metadata offline_access"


@dataclass(frozen=True)
class Session:
    refresh_token: str
    sub: str
    email: str


KEYRING_MESSAGE = (
    "No se pudo usar el llavero del sistema. En Linux sin escritorio instala un backend de "
    "Secret Service (por ejemplo gnome-keyring) o `keyrings.alt`."
)


def _keyring_error() -> AuthError:
    error = AuthError(KEYRING_MESSAGE)
    error.safe_for_user = True
    return error


def save_session(session: Session) -> None:
    try:
        keyring.set_password(SERVICE, ACCOUNT, json.dumps(asdict(session)))
    except (KeyringError, RuntimeError) as exc:
        raise _keyring_error() from exc


def load_session() -> Session | None:
    try:
        raw = keyring.get_password(SERVICE, ACCOUNT)
    except (KeyringError, RuntimeError) as exc:
        raise _keyring_error() from exc
    if not raw:
        return None
    try:
        return Session(**json.loads(raw))
    except (ValueError, TypeError):
        return None


def clear_session() -> None:
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except PasswordDeleteError:
        pass
    except (KeyringError, RuntimeError) as exc:
        raise _keyring_error() from exc


def _safe_body(response):
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def _post_token(http, body, action):
    try:
        response = http.post(f"https://{config.AUTH0_DOMAIN}/oauth/token", json=body)
    except httpx.HTTPError as exc:
        raise AuthError(f"{action} falló: error de red ({exc.__class__.__name__})") from exc
    if response.status_code != 200:
        raise AuthError(
            f"{action} falló: {response.status_code}",
            status_code=response.status_code,
            body=_safe_body(response),
        )
    data = _safe_body(response)
    if not isinstance(data, dict) or "access_token" not in data:
        raise AuthError(f"{action} falló: respuesta 200 sin access_token")
    return data


def _userinfo(http, access_token):
    try:
        response = http.get(
            f"https://{config.AUTH0_DOMAIN}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as exc:
        raise AuthError(f"userinfo falló: error de red ({exc.__class__.__name__})") from exc
    data = _safe_body(response)
    if (
        response.status_code != 200
        or not isinstance(data, dict)
        or not isinstance(data.get("sub"), str)
    ):
        raise AuthError("userinfo falló", status_code=response.status_code)
    return data


def login(email: str, password: str, http: httpx.Client) -> Session:
    tokens = _post_token(
        http,
        {
            "grant_type": GRANT_TYPE,
            "realm": REALM,
            "audience": f"https://{config.AUTH0_DOMAIN}/api/v2/",
            "client_id": config.AUTH0_CLIENT_ID,
            "username": email,
            "password": password,
            "scope": LOGIN_SCOPE,
        },
        "login",
    )
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise AuthError("login falló: Auth0 no devolvió refresh token")
    info = _userinfo(http, tokens["access_token"])
    session = Session(refresh_token, info["sub"], info.get("email") or email)
    save_session(session)
    return session


class TokenProvider:
    """Entrega access tokens. Refresca bajo un lock: si dos llamadas pegan 401 a la
    vez, la segunda reutiliza el token ya refrescado en vez de redimir de nuevo el
    mismo refresh token (con rotación, eso puede revocar toda la sesión)."""

    def __init__(self, http: httpx.Client):
        self._http = http
        self._lock = threading.Lock()
        self._access_token: str | None = None

    def _session(self) -> Session:
        session = load_session()
        if session is None:
            raise NoSessionError()
        return session

    def user_logical_id(self) -> str:
        sub = self._session().sub
        return sub.split("|", 1)[1] if "|" in sub else sub

    def email(self) -> str:
        return self._session().email

    def access_token(self) -> str:
        with self._lock:
            if self._access_token is None:
                self._refresh_locked()
            return self._access_token

    def force_refresh(self, stale_token: str | None) -> str:
        with self._lock:
            if self._access_token is not None and self._access_token != stale_token:
                return self._access_token
            self._refresh_locked()
            return self._access_token

    def _refresh_locked(self) -> None:
        session = self._session()
        try:
            tokens = _post_token(
                self._http,
                {
                    "grant_type": "refresh_token",
                    "client_id": config.AUTH0_CLIENT_ID,
                    "refresh_token": session.refresh_token,
                },
                "refresh",
            )
        except AuthError as exc:
            if exc.status_code in (400, 401, 403):
                raise NoSessionError() from exc
            raise
        self._access_token = tokens["access_token"]
        rotated = tokens.get("refresh_token")
        if rotated and rotated != session.refresh_token:
            save_session(replace(session, refresh_token=rotated))
