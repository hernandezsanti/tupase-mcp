"""Servidor MCP de Tupase: tools delgadas que delegan en los módulos de negocio."""

import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import account, auth, catalog, reservations, routine, search, timeutil
from .client import TupaseClient
from .errors import InputError, TupaseError
from .favorites import FavoritesStore

log = logging.getLogger("tupase_mcp")
GENERIC_ERROR = "No se pudo completar la operación con Tupase. Inténtalo de nuevo."
CONFIRM_MESSAGE = (
    "No se hizo ningún cambio. Muéstrale estos datos a la persona y, solo si lo confirma de forma "
    "explícita, vuelve a llamar a esta tool con confirmar=true."
)
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(destructiveHint=True, idempotentHint=False, openWorldHint=True)
LOCAL_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
WEEK = timedelta(days=7)

mcp = FastMCP(
    "tupase-mcp",
    instructions=(
        "Cliente no oficial de Tupase (actividades físicas en Uruguay). Las fechas van en ISO 8601 y "
        "se interpretan en hora de Montevideo. Para reservar, primero busca la actividad con "
        "buscar_actividades y usa su `activity_id` e `inicio` tal cual. Si una tool dice que no "
        "hay sesión, pídele a la persona que corra `uvx tupase-mcp login` en su terminal."
    ),
)


class App:
    def __init__(self, http=None, tokens=None, client=None, favorites=None, now=None):
        self.http = http or httpx.Client(timeout=10.0)
        self.tokens = tokens or auth.TokenProvider(self.http)
        self.client = client or TupaseClient(self.http, self.tokens)
        self.favorites = favorites or FavoritesStore()
        self.now = now or (lambda: datetime.now(timeutil.MONTEVIDEO))


_app: App | None = None


def get_app() -> App:
    global _app
    if _app is None:
        _app = App()
    return _app


def set_app(app: App | None) -> None:
    global _app
    _app = app


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except InputError as exc:
            raise ToolError(str(exc)) from exc
        except TupaseError as exc:
            if exc.safe_for_user:
                raise ToolError(str(exc)) from exc
            payload = exc.payload
            shape = type(payload).__name__
            if isinstance(payload, dict):
                shape += f" keys={sorted(str(k) for k in payload)}"
            log.warning("tupase falló: %s payload=%s", exc, shape)
            raise ToolError(GENERIC_ERROR) from exc
        except Exception as exc:
            log.exception("error inesperado en la tool")
            raise ToolError(GENERIC_ERROR) from exc

    return wrapper


def _parse(value: str, name: str) -> datetime:
    try:
        return timeutil.parse_local(value)
    except (ValueError, TypeError) as exc:
        raise InputError(
            f"`{name}` no es una fecha ISO 8601 válida (ej. 2026-10-12T18:00): {value!r}"
        ) from exc


def _merge(primary: dict, fallback: dict) -> dict:
    """Completa con `fallback` los campos que `primary` no trae."""
    return {
        key: fallback.get(key) if value is None else value for key, value in primary.items()
    } | {key: value for key, value in fallback.items() if key not in primary}


def _range(desde: str | None, hasta: str | None, now: datetime):
    start = _parse(desde, "desde") if desde else now
    if hasta:
        end = _parse(hasta, "hasta")
        if len(hasta.strip()) == 10:  # solo fecha: hasta el final de ese día
            end = end.replace(hour=23, minute=59, second=59)
    else:
        end = start + WEEK
    return start, end


@mcp.tool(annotations=READ)
@_guard
def buscar_actividades(
    desde: str | None = None,
    hasta: str | None = None,
    disciplinas: list[str] | None = None,
    barrios: list[str] | None = None,
    lugares: list[str] | None = None,
    lat: float | None = None,
    lon: float | None = None,
    distancia_km: float | None = None,
    solo_favoritos: bool = False,
) -> dict[str, Any]:
    """Busca actividades. `desde`/`hasta` en ISO 8601 (hora de Montevideo; por defecto, ahora y los
    próximos 7 días; máximo 7 días; si `hasta` es solo una fecha, incluye ese día completo).
    `disciplinas` y `barrios` por nombre, `lugares` por `entity_id`. Con `lat`/`lon` ordena por
    cercanía y `distancia_km` limita el radio. Devuelve hasta 50 resultados con `total` y `avisos`."""
    app = get_app()
    start, end = _range(desde, hasta, app.now())
    return search.search_activities(
        app.client,
        start,
        end,
        disciplinas=disciplinas,
        barrios=barrios,
        lugares=lugares,
        solo_entidades=app.favorites.ids() if solo_favoritos else None,
        lat=lat,
        lon=lon,
        distancia_km=distancia_km,
    )


@mcp.tool(annotations=READ)
@_guard
def listar_disciplinas(desde: str | None = None, hasta: str | None = None) -> dict[str, Any]:
    """Disciplinas disponibles en un rango de fechas (por defecto, los próximos 7 días)."""
    app = get_app()
    start, end = _range(desde, hasta, app.now())
    return {"disciplinas": catalog.list_disciplines(app.client, start, end)}


@mcp.tool(annotations=READ)
@_guard
def listar_barrios(desde: str | None = None, hasta: str | None = None) -> dict[str, Any]:
    """Barrios con actividad en un rango de fechas (por defecto, los próximos 7 días)."""
    app = get_app()
    start, end = _range(desde, hasta, app.now())
    return {"barrios": catalog.list_neighbourhoods(app.client, start, end)}


@mcp.tool(annotations=READ)
@_guard
def ver_lugar(entity_id: str) -> dict[str, Any]:
    """Todas las actividades de un lugar (por su `entity_id`) en los próximos 7 días."""
    app = get_app()
    now = app.now()
    return search.search_activities(app.client, now, now + WEEK, lugares=[entity_id])


@mcp.tool(annotations=READ)
@_guard
def mis_reservas(pagina: int = 0, por_pagina: int = 20) -> dict[str, Any]:
    """Tus reservas con el estado real (una reserva pendiente se confirma si hay una notificación
    de cupo asignado que coincide)."""
    app = get_app()
    user_id = app.tokens.user_logical_id()
    return {"reservas": reservations.get_reservations(app.client, user_id, pagina, por_pagina)}


@mcp.tool(annotations=WRITE)
@_guard
def reservar(activity_id: str, inicio: str, confirmar: bool = False) -> dict[str, Any]:
    """Reserva una actividad. Usa el `activity_id` y el `inicio` que devolvió buscar_actividades.
    Sin `confirmar=true` solo devuelve una vista previa; muéstrasela a la persona y pide su
    confirmación explícita antes de volver a llamar con `confirmar=true`."""
    app = get_app()
    start = _parse(inicio, "inicio")
    if start <= app.now():
        raise InputError("Esa actividad ya pasó.")
    window = search.search_activities(
        app.client,
        start - timedelta(minutes=1),
        start + timedelta(minutes=1),
        limit=100_000,
    )
    match = next((a for a in window["resultados"] if a["activity_id"] == activity_id), None)
    if match is None and window["incompleto"]:
        raise ToolError(
            "La búsqueda de Tupase vino truncada para esa hora; intenta de nuevo o acota la búsqueda."
        )
    if match is None:
        raise ToolError(
            "No encontré esa actividad en Tupase a esa hora. Búscala de nuevo con buscar_actividades."
        )
    if not confirmar:
        return {"requiere_confirmacion": True, "actividad": match, "mensaje": CONFIRM_MESSAGE}
    created = reservations.create_reservation(
        app.client,
        app.tokens.user_logical_id(),
        match["entity_id"],
        match["activity_id"],
        match["disciplina"],
        timeutil.to_api_utc(timeutil.parse_local(match["inicio"])),
        int(time.time()),
    )
    # La escritura ya ocurrió: de acá en adelante nada puede lanzar (un error haría reintentar).
    fallback = {
        "lugar": match.get("lugar"),
        "disciplina": match.get("disciplina"),
        "inicio": match.get("inicio"),
    }
    return {
        "reservada": True,
        "reserva": _merge(reservations.normalize_reservation(created), fallback),
        "actividad": match,
    }


@mcp.tool(annotations=WRITE)
@_guard
def cancelar_reserva(codigo_reserva: str, confirmar: bool = False) -> dict[str, Any]:
    """Cancela una reserva por su `codigo` (el que devuelve mis_reservas).
    Sin `confirmar=true` solo devuelve una vista previa; pide confirmación explícita a la persona."""
    app = get_app()
    user_id = app.tokens.user_logical_id()
    found = reservations.find_reservation(app.client, user_id, codigo_reserva)
    start = ((found or {}).get("activityInfo") or {}).get("startDateTime")
    if not found or not start:
        raise ToolError("No encontré una reserva con ese código.")
    if not confirmar:
        return {
            "requiere_confirmacion": True,
            "reserva": reservations.normalize_reservation(found),
            "mensaje": CONFIRM_MESSAGE,
        }
    result = reservations.cancel_reservation(app.client, codigo_reserva, start)
    # La escritura ya ocurrió: de acá en adelante nada puede lanzar (un error haría reintentar).
    reserva = _merge(
        reservations.normalize_reservation(result), reservations.normalize_reservation(found)
    )
    if reserva.get("estado") == "CANCELLED":
        # Tupase responde la baja sin texto de estado; el de la reserva vieja sería engañoso.
        reserva["estado_texto"] = "Cancelada"
    return {"cancelada": True, "reserva": reserva}


_IMAGE_SIGNATURES = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg"}


def _image_format(data: bytes) -> str | None:
    return next((fmt for sig, fmt in _IMAGE_SIGNATURES.items() if data.startswith(sig)), None)


@mcp.tool(annotations=READ)
@_guard
def ver_qr_reserva(codigo_reserva: str):
    """Devuelve el código de una reserva y su QR como imagen."""
    app = get_app()
    found = reservations.find_reservation(app.client, app.tokens.user_logical_id(), codigo_reserva)
    if not found:
        raise ToolError("No encontré una reserva con ese código.")
    qr_uri = found.get("qrUri")
    if not qr_uri:
        raise ToolError("Esa reserva no tiene QR.")
    text = f"Código de reserva: {codigo_reserva}"
    data = reservations.fetch_qr_image(app.http, qr_uri)
    fmt = _image_format(data)
    if fmt is None:
        return f"{text}\nQR: {qr_uri}"
    return [text, Image(data=data, format=fmt)]


@mcp.tool(annotations=READ)
@_guard
def mi_rutina() -> dict[str, Any]:
    """Detecta tus clases habituales (mismo lugar, disciplina, día y hora, al menos 2 veces) y lista
    las próximas fechas reservables de cada una en los próximos 7 días."""
    app = get_app()
    now = app.now()
    raw = reservations.list_reservations(app.client, app.tokens.user_logical_id())
    routines = routine.detect_routines(raw, now)
    if not routines:
        return {"rutinas": [], "aviso": "No encontré clases que hayas repetido al menos 2 veces."}
    booked = [reservations.normalize_reservation(r) for r in raw if isinstance(r, dict)]
    out = []
    for item in routines:
        occurrence = routine.next_occurrence(item, now)
        found = search.search_activities(
            app.client,
            occurrence - timedelta(minutes=1),
            occurrence + timedelta(minutes=1),
            limit=100_000,
        )
        dates = routine.upcoming_dates(item, found["resultados"], booked)
        out.append(
            {**item, "proximas": dates, "sin_fechas": not dates, "incompleto": found["incompleto"]}
        )
    return {"rutinas": out}


@mcp.tool(annotations=LOCAL_WRITE)
@_guard
def agregar_favorito(entity_id: str, lugar: str) -> dict[str, Any]:
    """Guarda un lugar como favorito (solo en tu computadora)."""
    store = get_app().favorites
    return {"agregado": store.add(entity_id, lugar), "total": len(store.list())}


@mcp.tool(annotations=LOCAL_WRITE)
@_guard
def quitar_favorito(entity_id: str) -> dict[str, Any]:
    """Quita un lugar de tus favoritos."""
    store = get_app().favorites
    return {"quitado": store.remove(entity_id), "total": len(store.list())}


@mcp.tool(annotations=READ)
@_guard
def mis_favoritos() -> dict[str, Any]:
    """Tus lugares favoritos."""
    return {"favoritos": get_app().favorites.list()}


@mcp.tool(annotations=READ)
@_guard
def quien_soy() -> dict[str, Any]:
    """Tu perfil y el estado de la cuenta; sirve para comprobar que el login funciona."""
    app = get_app()
    user_id = app.tokens.user_logical_id()
    return {
        "perfil": account.get_profile(app.client, user_id),
        "estado_cuenta": account.get_status(app.client, user_id),
    }


@mcp.tool(annotations=WRITE)
@_guard
def editar_perfil(
    nombre: str | None = None,
    apellido: str | None = None,
    telefono: str | None = None,
    fecha_nacimiento: str | None = None,
    pais_id: str | None = None,
    documento: str | None = None,
    confirmar: bool = False,
) -> dict[str, Any]:
    """Actualiza los datos de tu perfil de Tupase. Indica solo los campos que quieres cambiar.
    Sin `confirmar=true` solo devuelve una vista previa; pide confirmación explícita a la persona."""
    app = get_app()
    changes = {
        "nombre": nombre,
        "apellido": apellido,
        "telefono": telefono,
        "fecha_nacimiento": fecha_nacimiento,
        "pais_id": pais_id,
        "documento": documento,
    }
    provided = {key: value for key, value in changes.items() if value is not None}
    if not provided:
        raise InputError("Indica al menos un campo para actualizar.")
    if not confirmar:
        return {"requiere_confirmacion": True, "cambios": provided, "mensaje": CONFIRM_MESSAGE}
    return {"perfil": account.update_profile(app.client, app.tokens.user_logical_id(), changes)}


@mcp.tool(annotations=READ)
@_guard
def mis_notificaciones(pagina: int = 0, limite: int = 20) -> dict[str, Any]:
    """Tus notificaciones de Tupase."""
    return {"notificaciones": reservations.list_notifications(get_app().client, pagina, limite)}


@mcp.tool(annotations=READ)
@_guard
def mis_medios_de_pago() -> dict[str, Any]:
    """Tu medio de pago registrado en Tupase (solo lectura)."""
    app = get_app()
    return {
        "medios_de_pago": account.get_payment_preferences(app.client, app.tokens.user_logical_id())
    }
