"""Catálogos de Tupase: disciplinas y barrios con actividad en un rango."""

from datetime import datetime

from . import timeutil
from .errors import TupaseError

DISTANCE = 2


def _elements(response, action):
    elements = response.get("elements") if isinstance(response, dict) else None
    if not isinstance(elements, list):
        raise TupaseError(f"{action} falló: respuesta inesperada", payload=response)
    return elements


def _window(desde: datetime, hasta: datetime) -> dict:
    return {
        "startDateTimeFrom": timeutil.to_api_utc(desde),
        "startDateTimeTo": timeutil.to_api_utc(hasta),
    }


def list_disciplines(client, desde, hasta):
    body = {**_window(desde, hasta), "distance": DISTANCE}
    return _elements(
        client.post("search/disciplines/search-by-location", json=body), "listar disciplinas"
    )


def list_neighbourhoods(client, desde, hasta):
    return _elements(
        client.post("search/neighbourhoods/search-by-location", json=_window(desde, hasta)),
        "listar barrios",
    )
