"""HTTP contra la API de Tupase: errores seguros y un reintento tras 401."""

import httpx

from . import config
from .errors import NoSessionError, TupaseError


def _safe_body(response):
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def _raise_for_error_body(body, fallback, status_code):
    """Un mensaje legible en el body de un 4xx (o de un 200 con `errors`) es un
    rechazo de negocio y se puede mostrar. Un 5xx nunca: es el body de error por
    defecto de un backend Spring, no un "no" real de Tupase."""
    is_server_error = status_code >= 500
    if not is_server_error and isinstance(body, dict):
        for key in ("message", "showMessage"):
            message = body.get(key)
            if isinstance(message, str) and message.strip():
                raise TupaseError(message, safe_for_user=True, payload=body)
    raise TupaseError(fallback, payload=body)


class TupaseClient:
    def __init__(self, http: httpx.Client, tokens, base_url: str | None = None):
        self._http = http
        self._tokens = tokens
        self._base = (base_url or config.TUPASE_API_BASE).rstrip("/")

    def get(self, path, *, params=None):
        return self._call("GET", path, params=params)

    def post(self, path, *, json=None):
        return self._call("POST", path, json=json)

    def put(self, path, *, json=None):
        return self._call("PUT", path, json=json)

    def _call(self, method, path, *, params=None, json=None):
        token = self._tokens.access_token()
        response = self._send(method, path, token, params, json)
        if response.status_code == 401:
            token = self._tokens.force_refresh(token)
            response = self._send(method, path, token, params, json)
            if response.status_code == 401:
                raise NoSessionError()
        return self._parse(response, path)

    def _send(self, method, path, token, params, json):
        try:
            return self._http.request(
                method,
                f"{self._base}/{path.lstrip('/')}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise TupaseError(
                f"{method} {path} falló: error de red ({exc.__class__.__name__})"
            ) from exc

    def _parse(self, response, path):
        if response.is_success and not response.content.strip():
            return True
        body = _safe_body(response)
        if not response.is_success:
            _raise_for_error_body(
                body, f"tupase respondió {response.status_code}", response.status_code
            )
        if not isinstance(body, dict | list | bool):
            raise TupaseError(
                f"{path} falló: la respuesta no es un objeto, una lista ni un booleano",
                payload=body,
            )
        if isinstance(body, dict) and body.get("errors"):
            _raise_for_error_body(body, "la operación falló", response.status_code)
        return body
