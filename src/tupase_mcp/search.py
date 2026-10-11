"""Búsqueda de actividades: ventana partida por el tope de la API, normalización y filtros."""

import math
import time
from datetime import datetime, timedelta

from . import timeutil
from .errors import InputError
from .textutil import fold

SEARCH_PATH = "search/activities/search-by-location"
TRUNCATION_THRESHOLD = 499  # tope real observado de la API (no pagina)
MIN_WINDOW_MINUTES = 30
MAX_REQUESTS = 60
PAUSE_SECONDS = 0.2
MAX_RESULTS = 50
MAX_DAYS = 7
DISTANCE = 2  # la ubicación real se filtra en el cliente

KNOWN_GROUPS = [
    "Sala de musculación",
    "Funcional",
    "Crossfit",
    "Fitness",
    "Pádel",
    "Pilates",
    "Boxeo",
    "Danza",
    "Spinning",
    "Artes Marciales",
    "Running",
    "Piscina",
    "Yoga",
    "Cycling",
    "Deportes Colectivos",
    "Zumba",
    "Remo",
    "Tenis",
    "Patinaje",
    "Esgrima",
    "Deportes",
]


_GROUPS_BY_FOLD = {fold(g): g for g in KNOWN_GROUPS}


def canonical_group(name: str) -> str | None:
    return _GROUPS_BY_FOLD.get(fold(name))


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def _local(value):
    return timeutil.local_iso(timeutil.from_api_utc(value)) if value else None


def normalize_activity(raw: dict) -> dict:
    loc = raw.get("location") or {}
    return {
        "activity_id": raw.get("activityId"),
        "entity_id": raw.get("entityId"),
        "lugar": raw.get("entityName"),
        "disciplina": raw.get("disciplineName"),
        "grupo_disciplina": raw.get("disciplineGroup"),
        "inicio": _local(raw.get("startDateTime")),
        "fin": _local(raw.get("endDateTime")),
        "barrio": loc.get("neighbourhood"),
        "direccion": loc.get("address"),
        "ciudad": loc.get("city"),
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "cupos": raw.get("maxQuotas"),  # cupo máximo de la clase, no los lugares libres
        "online": raw.get("online"),
    }


class _Budget:
    def __init__(self, max_requests):
        self.max = max_requests
        self.used = 0
        self.incomplete = False


def _fetch_window(client, start, end, extra, budget, out, sleep):
    if budget.used >= budget.max:
        budget.incomplete = True
        return
    if budget.used:
        sleep(PAUSE_SECONDS)
    budget.used += 1
    body = {
        "startDateTimeFrom": timeutil.to_api_utc(start),
        "startDateTimeTo": timeutil.to_api_utc(end),
        "distance": DISTANCE,
        **extra,
    }
    response = client.post(SEARCH_PATH, json=body)
    elements = response.get("elements", []) if isinstance(response, dict) else []
    for element in elements:
        if element.get("activityId"):
            out[element["activityId"]] = element
    if len(elements) < TRUNCATION_THRESHOLD:
        return
    if (end - start).total_seconds() / 60 <= MIN_WINDOW_MINUTES:
        if "disciplineGroups" in extra:
            budget.incomplete = True
            return
        # Hora pico: la ventana mínima sigue llena, se parte por grupo de disciplina.
        groups = list(dict.fromkeys(KNOWN_GROUPS))
        for element in elements:
            group = element.get("disciplineGroup")
            if group and group not in groups:
                groups.append(group)
        for group in groups:
            group_extra = {**extra, "disciplineGroups": [group]}
            _fetch_window(client, start, end, group_extra, budget, out, sleep)
        return
    middle = start + (end - start) / 2
    _fetch_window(client, start, middle, extra, budget, out, sleep)
    _fetch_window(client, middle, end, extra, budget, out, sleep)


def _validate(desde, hasta, lat, lon, distancia_km):
    if hasta <= desde:
        raise InputError("`hasta` debe ser posterior a `desde`.")
    if hasta - desde > timedelta(days=MAX_DAYS):
        raise InputError(f"El rango máximo es de {MAX_DAYS} días.")
    if (lat is None) != (lon is None):
        raise InputError("`lat` y `lon` van juntas.")
    if distancia_km is not None and (lat is None or distancia_km < 0):
        raise InputError("`distancia_km` necesita `lat` y `lon`, y no puede ser negativa.")


def _entity_scope(lugares, solo_entidades):
    scopes = []
    if lugares:
        scopes.append(set(lugares))
    if solo_entidades is not None:
        scopes.append(set(solo_entidades))
    return set.intersection(*scopes) if scopes else None


def _matches_discipline(activity, folded_terms):
    haystack = fold(f"{activity['disciplina'] or ''} {activity['grupo_disciplina'] or ''}")
    return any(term in haystack for term in folded_terms)


def _result(items, limit, incomplete):
    avisos = []
    if len(items) > limit:
        avisos.append(
            f"Hay {len(items)} resultados y muestro los primeros {limit}. "
            "Afina con disciplinas, barrios o un rango más corto."
        )
    if incomplete:
        avisos.append(
            "La API de Tupase devolvió su máximo de resultados en una ventana y puede faltar "
            "alguna actividad; acota el rango o los filtros."
        )
    page = items[:limit]
    return {
        "total": len(items),
        "mostrando": len(page),
        "resultados": page,
        "incompleto": incomplete,
        "avisos": avisos,
    }


def search_activities(
    client,
    desde: datetime,
    hasta: datetime,
    *,
    disciplinas=None,
    barrios=None,
    lugares=None,
    solo_entidades=None,
    lat=None,
    lon=None,
    distancia_km=None,
    limit=MAX_RESULTS,
    max_requests=MAX_REQUESTS,
    sleep=time.sleep,
) -> dict:
    _validate(desde, hasta, lat, lon, distancia_km)
    entities = _entity_scope(lugares, solo_entidades)
    if entities is not None and not entities:
        return _result([], limit, False)

    extra = {}
    if disciplinas:
        groups = [canonical_group(d) for d in disciplinas]
        if all(groups):
            extra["disciplineGroups"] = groups
    if entities:
        extra["entityIds"] = sorted(entities)

    budget = _Budget(max_requests)
    collected = {}
    _fetch_window(client, desde, hasta, extra, budget, collected, sleep)

    items = [normalize_activity(raw) for raw in collected.values()]
    if entities:
        items = [a for a in items if a["entity_id"] in entities]
    if disciplinas:
        terms = [fold(d) for d in disciplinas]
        items = [a for a in items if _matches_discipline(a, terms)]
    if barrios:
        terms = [fold(b) for b in barrios]
        items = [a for a in items if any(t in fold(a["barrio"] or "") for t in terms)]

    if lat is not None:
        located = []
        for activity in items:
            if activity["lat"] is None or activity["lon"] is None:
                continue
            km = haversine_km(lat, lon, activity["lat"], activity["lon"])
            if distancia_km is None or km <= distancia_km:
                located.append({**activity, "distancia_km": round(km, 2)})
        items = sorted(located, key=lambda a: (a["distancia_km"], a["inicio"] or ""))
    else:
        items.sort(key=lambda a: (a["inicio"] or "", a["lugar"] or ""))

    return _result(items, limit, budget.incomplete)
