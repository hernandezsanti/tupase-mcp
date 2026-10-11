"""Captura respuestas reales de Tupase (con la sesión ya iniciada) y guarda muestras anonimizadas.

Uso: uv run python scripts/capture_fixtures.py
Nunca imprime ni guarda valores sensibles: solo forma (claves) y muestras redactadas.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from tupase_mcp import account, auth, catalog, reservations, search, timeutil
from tupase_mcp.client import TupaseClient
from tupase_mcp.errors import TupaseError

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
MAX_ITEMS = 3
SENSITIVE = {
    "email",
    "firstName",
    "lastName",
    "phone",
    "userDocument",
    "birthDate",
    "userLogicalId",
    "sub",
    "qrUri",
    "reservationIdentityCode",
    "activationCode",
    "deviceIdentifier",
    "mpPaymentPreferenceId",
    "expirationDate",
    "text",
    "subtitle",
    "title",
    "uuid",
    "userFullName",
    "companyName",
    "creationTimeStamp",
    "infoCompleteTimeStamp",
    "extraData",
}
# Datos de la actividad de la persona (qué reservó, dónde y cuándo): se ocultan en las reservas.
HISTORY = {
    "entityName",
    "entityId",
    "activityId",
    "startDateTime",
    "endDateTime",
    "disciplineName",
    "disciplineAlias",
    "originalDisciplineName",
    "address",
    "addressCode",
    "lat",
    "lon",
    "mapUrl",
    "neighbourhood",
}


def redact(value, extra=frozenset()):
    hidden = SENSITIVE | extra
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key in hidden and item not in (None, "") else redact(item, extra)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, extra) for item in value[:MAX_ITEMS]]
    return value


def _shape(value, depth=0):
    if isinstance(value, dict):
        return (
            {key: _shape(item, depth + 1) for key, item in sorted(value.items())}
            if depth < 3
            else "{...}"
        )
    if isinstance(value, list):
        return [_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=15.0) as http:
        tokens = auth.TokenProvider(http)
        client = TupaseClient(http, tokens)
        user_id = tokens.user_logical_id()
        now = datetime.now(timeutil.MONTEVIDEO)
        end = now + timedelta(days=7)
        soon = client.post(
            search.SEARCH_PATH,
            json={
                "startDateTimeFrom": timeutil.to_api_utc(now),
                "startDateTimeTo": timeutil.to_api_utc(now + timedelta(hours=6)),
                "distance": search.DISTANCE,
            },
        )
        calls = {
            "activities": lambda: soon.get("elements", []) if isinstance(soon, dict) else soon,
            "disciplines": lambda: catalog.list_disciplines(client, now, end),
            "neighbourhoods": lambda: catalog.list_neighbourhoods(client, now, end),
            "profile": lambda: account.get_profile(client, user_id),
            "status": lambda: account.get_status(client, user_id),
            "countries": lambda: account.list_countries(client),
            "payment_preferences": lambda: account.get_payment_preferences(client, user_id),
            "notifications": lambda: reservations.list_notifications(client),
            "reservations": lambda: reservations.list_reservations(client, user_id, 0, 20),
        }
        for name, call in calls.items():
            try:
                data = call()
            except TupaseError as exc:
                print(f"== {name}: ERROR {exc}")
                continue
            extra = HISTORY if name == "reservations" else frozenset()
            (OUT / f"{name}.json").write_text(
                json.dumps(redact(data, extra), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"== {name}: {json.dumps(_shape(data), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
