"""Reservas de Tupase: listado con estado real, alta, baja y QR."""

import logging
import re
from datetime import datetime

import httpx

from . import timeutil
from .errors import TupaseError

log = logging.getLogger(__name__)

MAX_QR_BYTES = 2_000_000
_CUPO_DATETIME_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2})")


def list_reservations(client, user_id, page=0, page_size=9999):
    body = client.get(
        f"users/reservations/user/{user_id}", params={"page": page, "pageSize": page_size}
    )
    if not isinstance(body, list):
        raise TupaseError("listar reservas falló: la respuesta no es un array", payload=body)
    return body


def list_notifications(client, page=0, limit=50):
    body = client.get("users/notifications", params={"page": page, "limit": limit})
    items = body.get("items", []) if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise TupaseError("listar notificaciones falló: 'items' no es un array", payload=body)
    return items


def match_cupo_asignado(reservation: dict, notifications: list) -> bool:
    """True si hay EXACTAMENTE una notificación de "cupo asignado" que coincide con
    la reserva por lugar y fecha/hora. Con cero o más de un match devuelve False:
    nunca se inventa una confirmación."""
    info = reservation.get("activityInfo") or {}
    entity_name = info.get("entityName")
    start_utc = info.get("startDateTime")
    if not entity_name or not start_utc:
        return False
    expected_title = f"Se te ha asignado un cupo para {entity_name}"
    matches = 0
    for notification in notifications:
        if not isinstance(notification, dict) or notification.get("title") != expected_title:
            continue
        text = notification.get("subtitle") or notification.get("text") or ""
        found = _CUPO_DATETIME_RE.search(text)
        if not found:
            continue
        day, month, year, hour, minute = (int(g) for g in found.groups())
        try:
            local = datetime(year, month, day, hour, minute, tzinfo=timeutil.MONTEVIDEO)
        except ValueError:
            continue
        if timeutil.to_api_utc(local) == start_utc:
            matches += 1
    return matches == 1


def normalize_reservation(raw) -> dict:
    """Nunca lanza: una respuesta rara da campos en None (la usan tools que ya escribieron)."""
    if not isinstance(raw, dict):
        raw = {}
    info = raw.get("activityInfo")
    if not isinstance(info, dict):
        info = {}
    start = info.get("startDateTime")
    try:
        inicio = timeutil.local_iso(timeutil.from_api_utc(start)) if start else None
    except (ValueError, TypeError):
        inicio = None
    return {
        "codigo": raw.get("reservationIdentityCode"),
        "estado": raw.get("status"),
        "estado_texto": raw.get("statusStr"),
        "lugar": info.get("entityName"),
        "disciplina": info.get("disciplineName"),
        "inicio": inicio,
        "tiene_qr": bool(raw.get("qrUri")),
    }


def get_reservations(client, user_id, page=0, page_size=20):
    raw = list_reservations(client, user_id, page, page_size)
    pending = [r for r in raw if isinstance(r, dict) and r.get("status") == "PENDING_CONFIRMATION"]
    if pending:
        try:
            notifications = list_notifications(client)
        except TupaseError as exc:
            log.warning("cruce de notificaciones falló: %s", exc)
        else:
            for reservation in pending:
                if match_cupo_asignado(reservation, notifications):
                    reservation["status"] = "CONFIRMED"
                    reservation["statusStr"] = "Confirmada"
    return [normalize_reservation(r) for r in raw if isinstance(r, dict)]


def find_reservation(client, user_id, codigo):
    for reservation in list_reservations(client, user_id):
        if isinstance(reservation, dict) and reservation.get("reservationIdentityCode") == codigo:
            return reservation
    return None


def create_reservation(
    client, user_id, entity_id, activity_id, discipline_name, start_utc, timestamp
):
    return client.post(
        "users/reservations",
        json={
            "timeStamp": timestamp,
            "entityId": entity_id,
            "userLogicalId": user_id,
            "activityDate": start_utc,
            "activityId": activity_id,
            "activityName": discipline_name,
        },
    )


def cancel_reservation(client, codigo, start_utc):
    return client.post(
        "users/reservations/cancel",
        json={"activityDateStr": start_utc[:10], "reservationIdentityId": codigo},
    )


def fetch_qr_image(http: httpx.Client, qr_uri: str) -> bytes:
    if not qr_uri.startswith("https://"):
        raise TupaseError("El enlace del QR no es https; no lo descargo.")
    try:
        response = http.get(qr_uri)
    except httpx.HTTPError as exc:
        raise TupaseError(
            f"descargar el QR falló: error de red ({exc.__class__.__name__})"
        ) from exc
    if response.status_code != 200:
        raise TupaseError(f"descargar el QR falló: {response.status_code}")
    if len(response.content) > MAX_QR_BYTES:
        raise TupaseError("descargar el QR falló: la imagen es demasiado grande")
    return response.content
