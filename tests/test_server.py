import asyncio
import time

import httpx
import pytest
import respx
from mcp.server.fastmcp import Image
from mcp.server.fastmcp.exceptions import ToolError

from tupase_mcp import server
from tupase_mcp.errors import InputError, NoSessionError, TupaseError
from tupase_mcp.favorites import FavoritesStore
from tupase_mcp.timeutil import parse_local

NOW = parse_local("2026-10-12T12:00:00")  # lunes
SEARCH = ("POST", "search/activities/search-by-location")
RESERVATIONS = ("GET", "users/reservations/user/u1")
CREATE = ("POST", "users/reservations")
CANCEL = ("POST", "users/reservations/cancel")


class FakeTokens:
    def user_logical_id(self):
        return "u1"


class FakeClient:
    def __init__(self):
        self.routes = {}
        self.calls = []

    def _go(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        handler = self.routes[(method, path)]
        return handler(**kwargs) if callable(handler) else handler

    def get(self, path, *, params=None):
        return self._go("GET", path, params=params)

    def post(self, path, *, json=None):
        return self._go("POST", path, json=json)

    def put(self, path, *, json=None):
        return self._go("PUT", path, json=json)

    def posted(self, route):
        return [c for c in self.calls if (c[0], c[1]) == route]


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture
def app(client, tmp_path):
    with httpx.Client() as http:
        application = server.App(
            http=http,
            tokens=FakeTokens(),
            client=client,
            favorites=FavoritesStore(tmp_path / "favorites.json"),
            now=lambda: NOW,
        )
        server.set_app(application)
        yield application
    server.set_app(None)


def activity(i=1, start="2026-10-14T21:00:00", lugar="Estudio Sol", disciplina="Yoga"):
    return {
        "activityId": f"a{i}",
        "entityId": f"e{i}",
        "entityName": lugar,
        "disciplineName": disciplina,
        "disciplineGroup": disciplina,
        "startDateTime": start,
        "endDateTime": start,
        "location": {"neighbourhood": "Pocitos", "lat": -34.9, "lon": -56.15},
        "maxQuotas": 10,
        "online": False,
    }


def reservation(
    code="ABC", start="2026-10-14T21:00:00", status="CONFIRMED", qr="https://qr.example/a.png"
):
    return {
        "reservationIdentityCode": code,
        "status": status,
        "statusStr": status,
        "qrUri": qr,
        "activityInfo": {
            "entityName": "Estudio Sol",
            "disciplineName": "Yoga",
            "startDateTime": start,
        },
    }


def test_tool_inventory_and_annotations():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert set(tools) == {
        "buscar_actividades",
        "listar_disciplinas",
        "listar_barrios",
        "ver_lugar",
        "mis_reservas",
        "reservar",
        "cancelar_reserva",
        "ver_qr_reserva",
        "mi_rutina",
        "agregar_favorito",
        "quitar_favorito",
        "mis_favoritos",
        "quien_soy",
        "editar_perfil",
        "mis_notificaciones",
        "mis_medios_de_pago",
    }
    destructive = {n for n, t in tools.items() if t.annotations.destructiveHint}
    assert destructive == {"reservar", "cancelar_reserva", "editar_perfil"}
    local_writes = {"agregar_favorito", "quitar_favorito"}
    for name, tool in tools.items():
        if name not in destructive | local_writes:
            assert tool.annotations.readOnlyHint is True, name
    for name in ("reservar", "cancelar_reserva", "editar_perfil"):
        assert "confirmar" in tools[name].inputSchema["properties"], name
    assert "activity_id" not in tools["cancelar_reserva"].inputSchema["properties"]


def test_buscar_actividades_date_only_hasta_is_end_of_day(app, client):
    client.routes[SEARCH] = {"elements": [activity()]}
    result = server.buscar_actividades(desde="2026-10-14", hasta="2026-10-14")
    body = client.posted(SEARCH)[0][2]["json"]
    assert body["startDateTimeFrom"] == "2026-10-14T03:00:00"
    assert body["startDateTimeTo"] == "2026-10-15T02:59:59"
    assert result["total"] == 1 and result["resultados"][0]["inicio"] == "2026-10-14T18:00:00-03:00"


def test_buscar_actividades_bad_input_is_a_tool_error(app, client):
    with pytest.raises(ToolError, match="ISO 8601"):
        server.buscar_actividades(desde="mañana")
    with pytest.raises(ToolError, match="7 días"):
        server.buscar_actividades(desde="2026-10-01", hasta="2026-10-20")
    assert client.calls == []


def test_solo_favoritos(app, client):
    client.routes[SEARCH] = {"elements": [activity(1), activity(2)]}
    assert server.buscar_actividades(solo_favoritos=True)["total"] == 0
    assert client.calls == []
    app.favorites.add("e2", "Estudio Sol")
    result = server.buscar_actividades(solo_favoritos=True)
    assert [a["entity_id"] for a in result["resultados"]] == ["e2"]


def test_reservar_builds_the_body_itself(app, client):
    client.routes[SEARCH] = {"elements": [activity()]}
    client.routes[CREATE] = {"reservationIdentityCode": "N1", "status": "CONFIRMED"}
    before = int(time.time())
    out = server.reservar(activity_id="a1", inicio="2026-10-14T18:00:00", confirmar=True)
    body = client.posted(CREATE)[0][2]["json"]
    assert (
        body["entityId"] == "e1" and body["activityId"] == "a1" and body["activityName"] == "Yoga"
    )
    assert body["activityDate"] == "2026-10-14T21:00:00" and body["userLogicalId"] == "u1"
    assert before <= body["timeStamp"] <= before + 5
    assert out["reserva"]["codigo"] == "N1"


def test_reservar_never_posts_with_invented_data(app, client):
    client.routes[SEARCH] = {"elements": [activity(2)]}
    with pytest.raises(ToolError, match="No encontré"):
        server.reservar(activity_id="a1", inicio="2026-10-14T18:00:00", confirmar=True)
    with pytest.raises(ToolError, match="ya pasó"):
        server.reservar(activity_id="a1", inicio="2026-10-12T11:00:00", confirmar=True)
    assert client.posted(CREATE) == []


def test_reservar_finds_target_beyond_the_default_result_cap(app, client):
    elements = [activity(i, lugar=f"Lugar {i:03d}") for i in range(1, 61)]
    client.routes[SEARCH] = {"elements": elements}
    client.routes[CREATE] = {"reservationIdentityCode": "N55", "status": "CONFIRMED"}
    out = server.reservar(activity_id="a55", inicio="2026-10-14T18:00:00", confirmar=True)
    assert client.posted(CREATE)[0][2]["json"]["activityId"] == "a55"
    assert out["reserva"]["codigo"] == "N55"


def test_reservar_truncated_search_has_its_own_error(app, client, monkeypatch):
    monkeypatch.setattr(
        server.search,
        "search_activities",
        lambda *a, **k: {"resultados": [], "incompleto": True, "total": 0, "avisos": []},
    )
    with pytest.raises(ToolError, match="truncada") as info:
        server.reservar(activity_id="a1", inicio="2026-10-14T18:00:00", confirmar=True)
    assert "No encontré" not in str(info.value)
    assert client.posted(CREATE) == []


def test_cancelar_by_code_resolves_the_date(app, client):
    client.routes[RESERVATIONS] = [
        reservation("ABC"),
        reservation("XYZ", start="2026-10-16T21:00:00"),
    ]
    client.routes[CANCEL] = {"status": "CANCELLED"}
    out = server.cancelar_reserva(codigo_reserva="XYZ", confirmar=True)
    assert client.posted(CANCEL)[0][2]["json"] == {
        "activityDateStr": "2026-10-16",
        "reservationIdentityId": "XYZ",
    }
    assert out["cancelada"] is True
    assert out["reserva"]["estado"] == "CANCELLED"
    assert out["reserva"]["estado_texto"] == "Cancelada"  # no el texto de la reserva vieja


def test_cancelar_unknown_code_or_bad_args_never_posts(app, client):
    client.routes[RESERVATIONS] = [reservation("ABC")]
    with pytest.raises(ToolError, match="No encontré"):
        server.cancelar_reserva(codigo_reserva="NOPE", confirmar=True)
    with pytest.raises(ToolError):
        server.cancelar_reserva()
    assert client.posted(CANCEL) == []


def test_destructive_tools_only_preview_without_confirmation(app, client):
    client.routes[SEARCH] = {"elements": [activity()]}
    client.routes[RESERVATIONS] = [reservation("ABC")]
    reserved = server.reservar(activity_id="a1", inicio="2026-10-14T18:00:00")
    assert reserved["requiere_confirmacion"] is True
    assert reserved["actividad"]["activity_id"] == "a1"
    cancelled = server.cancelar_reserva(codigo_reserva="ABC")
    assert cancelled["requiere_confirmacion"] is True and cancelled["reserva"]["codigo"] == "ABC"
    edited = server.editar_perfil(telefono="098000111")
    assert edited["requiere_confirmacion"] is True
    assert edited["cambios"] == {"telefono": "098000111"}
    assert client.posted(CREATE) == [] and client.posted(CANCEL) == []
    assert all(call[0] == "GET" or call[:2] == SEARCH for call in client.calls)


def test_mis_reservas_pagination(app, client):
    client.routes[RESERVATIONS] = [reservation()]
    out = server.mis_reservas(pagina=1, por_pagina=5)
    assert client.calls[0][2]["params"] == {"page": 1, "pageSize": 5}
    assert out["reservas"][0]["codigo"] == "ABC"


@respx.mock
def test_ver_qr_returns_code_and_image(app, client):
    client.routes[RESERVATIONS] = [reservation("ABC")]
    respx.get("https://qr.example/a.png").mock(
        return_value=httpx.Response(200, content=b"\x89PNG\r\n\x1a\nrest")
    )
    out = server.ver_qr_reserva(codigo_reserva="ABC")
    assert "ABC" in out[0] and isinstance(out[1], Image) and out[1].data.startswith(b"\x89PNG")


@respx.mock
def test_ver_qr_unknown_format_falls_back_to_link(app, client):
    client.routes[RESERVATIONS] = [reservation("ABC")]
    respx.get("https://qr.example/a.png").mock(
        return_value=httpx.Response(200, content=b"<svg></svg>")
    )
    out = server.ver_qr_reserva(codigo_reserva="ABC")
    assert isinstance(out, str) and "https://qr.example/a.png" in out


def test_ver_qr_reservation_without_qr(app, client):
    client.routes[RESERVATIONS] = [reservation("ABC", qr=None)]
    with pytest.raises(ToolError, match="QR"):
        server.ver_qr_reserva(codigo_reserva="ABC")


def test_mi_rutina_lists_next_dates(app, client):
    history = [
        reservation("A", start="2026-10-01T21:00:00"),
        reservation("B", start="2026-10-08T21:00:00"),
    ]
    client.routes[RESERVATIONS] = history
    client.routes[SEARCH] = {
        "elements": [activity(1, start="2026-10-15T21:00:00"), activity(2, lugar="Otro")]
    }
    out = server.mi_rutina()
    searches = client.posted(SEARCH)
    assert len(searches) == 1
    body = searches[0][2]["json"]
    assert body["startDateTimeFrom"] == "2026-10-15T20:59:00"
    assert body["startDateTimeTo"] == "2026-10-15T21:01:00"
    routine = out["rutinas"][0]
    assert routine["veces"] == 2 and routine["dia_semana"] == "jueves"
    assert [d["activity_id"] for d in routine["proximas"]] == ["a1"]
    assert routine["sin_fechas"] is False


def test_mi_rutina_without_routines(app, client):
    client.routes[RESERVATIONS] = [reservation("A")]
    out = server.mi_rutina()
    assert out["rutinas"] == [] and "al menos 2" in out["aviso"]


def test_favorites_tools_roundtrip(app):
    assert server.agregar_favorito(entity_id="e1", lugar="Estudio Sol")["agregado"] is True
    assert server.agregar_favorito(entity_id="e1", lugar="Estudio Sol")["agregado"] is False
    assert server.mis_favoritos()["favoritos"] == [{"entity_id": "e1", "lugar": "Estudio Sol"}]
    assert server.quitar_favorito(entity_id="e1")["quitado"] is True
    assert server.mis_favoritos()["favoritos"] == []


def test_catalog_and_account_tools(app, client):
    client.routes[("POST", "search/disciplines/search-by-location")] = {
        "elements": [{"name": "Yoga"}]
    }
    client.routes[("POST", "search/neighbourhoods/search-by-location")] = {"elements": [{"id": 1}]}
    client.routes[("GET", "users/user-account/u1")] = {"firstName": "Ana", "userLogicalId": "u1"}
    client.routes[("GET", "users/user-account/status/u1")] = {"status": "ACTIVE"}
    client.routes[("GET", "payment-preferences/user/u1")] = {"mpPaymentPreferenceId": "p"}
    client.routes[("GET", "users/notifications")] = {"items": [{"title": "hola"}]}
    assert server.listar_disciplinas()["disciplinas"] == [{"name": "Yoga"}]
    assert server.listar_barrios()["barrios"] == [{"id": 1}]
    me = server.quien_soy()
    assert me["perfil"]["firstName"] == "Ana" and me["estado_cuenta"]["status"] == "ACTIVE"
    assert server.mis_medios_de_pago()["medios_de_pago"]["mpPaymentPreferenceId"] == "p"
    assert server.mis_notificaciones()["notificaciones"] == [{"title": "hola"}]


def test_editar_perfil_requires_a_field(app):
    with pytest.raises(ToolError):
        server.editar_perfil()


def test_ver_lugar_searches_that_entity(app, client):
    client.routes[SEARCH] = {"elements": [activity(1), activity(2)]}
    out = server.ver_lugar(entity_id="e1")
    assert client.posted(SEARCH)[0][2]["json"]["entityIds"] == ["e1"]
    assert [a["entity_id"] for a in out["resultados"]] == ["e1"]


def test_error_mapping(app, client):
    def safe(**kwargs):
        raise TupaseError("Cupo completo", safe_for_user=True)

    def unsafe(**kwargs):
        raise TupaseError("NullPointerException en com.tupase.Foo", payload={"trace": "x"})

    def no_session(**kwargs):
        raise NoSessionError()

    client.routes[RESERVATIONS] = safe
    with pytest.raises(ToolError, match="Cupo completo"):
        server.mis_reservas()
    client.routes[RESERVATIONS] = unsafe
    with pytest.raises(ToolError) as info:
        server.mis_reservas()
    assert "NullPointer" not in str(info.value) and "Inténtalo de nuevo" in str(info.value)
    client.routes[RESERVATIONS] = no_session
    with pytest.raises(ToolError, match="uvx tupase-mcp login"):
        server.mis_reservas()


@pytest.mark.parametrize(
    "response",
    [True, [], {"reservationIdentityCode": "N1"}, {"activityInfo": {"startDateTime": "basura"}}],
)
def test_reservar_never_errors_after_a_successful_write(app, client, response):
    client.routes[SEARCH] = {"elements": [activity()]}
    client.routes[CREATE] = response
    out = server.reservar(activity_id="a1", inicio="2026-10-14T18:00:00", confirmar=True)
    assert out["reservada"] is True and isinstance(out["reserva"], dict)
    assert out["actividad"]["activity_id"] == "a1"
    assert len(client.posted(CREATE)) == 1


@pytest.mark.parametrize(
    "response", [True, [], {"status": "CANCELLED"}, {"activityInfo": {"startDateTime": "basura"}}]
)
def test_cancelar_never_errors_after_a_successful_write(app, client, response):
    client.routes[RESERVATIONS] = [reservation("ABC")]
    client.routes[CANCEL] = response
    out = server.cancelar_reserva(codigo_reserva="ABC", confirmar=True)
    assert out["cancelada"] is True and out["reserva"]["codigo"] == "ABC"


def test_guard_branches(app, client, caplog):
    def boom(exc):
        def handler(**kwargs):
            raise exc

        return handler

    client.routes[RESERVATIONS] = boom(InputError("Dato inválido"))
    with pytest.raises(ToolError, match="Dato inválido"):
        server.mis_reservas()

    # un ValueError de una librería no es un error de entrada: va al catch-all genérico
    client.routes[RESERVATIONS] = boom(ValueError("detalle interno de la librería"))
    with pytest.raises(ToolError) as info:
        server.mis_reservas()
    assert str(info.value) == server.GENERIC_ERROR

    client.routes[RESERVATIONS] = boom(KeyError("secret"))
    with caplog.at_level("ERROR", logger="tupase_mcp"):
        with pytest.raises(ToolError) as info:
            server.mis_reservas()
    assert "secret" not in str(info.value) and str(info.value) == server.GENERIC_ERROR
    assert "error inesperado" in caplog.text


def test_guard_does_not_log_the_raw_payload(app, client, caplog):
    def unsafe(**kwargs):
        raise TupaseError("falló", payload={"token": "s3cr3t-value"})

    client.routes[RESERVATIONS] = unsafe
    with caplog.at_level("WARNING", logger="tupase_mcp"):
        with pytest.raises(ToolError):
            server.mis_reservas()
    assert "s3cr3t-value" not in caplog.text
    assert "dict" in caplog.text and "token" in caplog.text


def test_input_errors_from_the_server_are_input_errors(app):
    with pytest.raises(ToolError, match="ISO 8601"):
        server.reservar(activity_id="a1", inicio="mañana")
    with pytest.raises(ToolError, match="al menos un campo"):
        server.editar_perfil()
