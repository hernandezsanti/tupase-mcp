from datetime import timedelta

import pytest

from tupase_mcp import search
from tupase_mcp.errors import InputError
from tupase_mcp.timeutil import parse_local

DESDE = parse_local("2026-10-12T00:00:00")
HASTA = parse_local("2026-10-12T23:59:59")


class FakeClient:
    """`responses` es una lista (se consume en orden) o un callable(body) -> dict."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post(self, path, *, json=None):
        self.calls.append((path, json))
        if callable(self.responses):
            return self.responses(json)
        return self.responses.pop(0)


def element(i, start="2026-10-12T21:00:00", **overrides):
    base = {
        "activityId": f"a{i}",
        "entityId": f"e{i % 5}",
        "entityName": f"Lugar {i % 5}",
        "disciplineName": "Yoga",
        "disciplineGroup": "Yoga",
        "startDateTime": start,
        "endDateTime": "2026-10-12T22:00:00",
        "location": {
            "address": "Calle 1",
            "city": "Montevideo",
            "neighbourhood": "Pocitos",
            "lat": -34.91,
            "lon": -56.15,
        },
        "maxQuotas": 10,
        "online": False,
    }
    base.update(overrides)
    return base


def no_sleep(_seconds):
    pass


def run(client, **kwargs):
    kwargs.setdefault("sleep", no_sleep)
    return search.search_activities(client, DESDE, HASTA, **kwargs)


def test_normalize_converts_utc_to_local_and_renames_fields():
    item = search.normalize_activity(element(1, start="2026-10-13T01:30:00"))
    assert item["inicio"] == "2026-10-12T22:30:00-03:00"
    assert item["fin"] == "2026-10-12T19:00:00-03:00"
    assert item["lugar"] == "Lugar 1" and item["entity_id"] == "e1"
    assert item["disciplina"] == "Yoga" and item["grupo_disciplina"] == "Yoga"
    assert item["barrio"] == "Pocitos" and item["cupos"] == 10


def test_request_body_uses_utc_window():
    client = FakeClient([{"elements": []}])
    run(client)
    path, body = client.calls[0]
    assert path == "search/activities/search-by-location"
    assert body["startDateTimeFrom"] == "2026-10-12T03:00:00"
    assert body["startDateTimeTo"] == "2026-10-13T02:59:59"


def test_late_evening_class_keeps_its_local_day():
    client = FakeClient([{"elements": [element(1, start="2026-10-13T01:30:00")]}])
    result = run(client)
    assert result["resultados"][0]["inicio"].startswith("2026-10-12T22:30")


def test_splits_window_when_truncated_and_dedupes():
    first = {"elements": [element(i) for i in range(499)]}
    left = {"elements": [element(i) for i in range(10)]}
    right = {"elements": [element(i) for i in range(490, 499)]}
    client = FakeClient([first, left, right])
    result = run(client)
    assert len(client.calls) == 3
    assert result["total"] == 499 and not result["incompleto"]
    assert result["mostrando"] == 50


def test_budget_exhausted_is_reported():
    counter = iter(range(10_000))
    client = FakeClient(lambda body: {"elements": [element(next(counter)) for _ in range(499)]})
    result = run(client, max_requests=2)
    assert len(client.calls) == 2 and result["incompleto"]
    assert any("puede faltar" in aviso for aviso in result["avisos"])


MINIMAL = timedelta(minutes=20)


def run_minimal(client, **kwargs):
    return search.search_activities(client, DESDE, DESDE + MINIMAL, sleep=no_sleep, **kwargs)


def test_full_page_in_minimal_window_with_group_filter_is_reported_not_silent():
    client = FakeClient([{"elements": [element(i) for i in range(499)]}])
    result = run_minimal(client, disciplinas=["padel"])
    assert len(client.calls) == 1 and result["incompleto"]


def by_group(sizes=None, unknown=None):
    """Respuesta: llena sin filtro de grupo; con filtro, `sizes.get(grupo, 3)` elementos únicos."""
    sizes = sizes or {}
    counter = iter(range(100_000))

    def respond(body):
        groups = body.get("disciplineGroups")
        if not groups:
            first = [element(next(counter), disciplineGroup=unknown)] if unknown else []
            return {"elements": first + [element(next(counter)) for _ in range(499 - len(first))]}
        n = sizes.get(groups[0], 3)
        return {"elements": [element(next(counter), disciplineGroup=groups[0]) for _ in range(n)]}

    return respond


def test_full_minimal_window_fans_out_by_group_and_unions_results():
    client = FakeClient(by_group())
    result = run_minimal(client)
    assert len(client.calls) == 1 + len(search.KNOWN_GROUPS)
    fan_out = [body for _path, body in client.calls[1:]]
    assert all(len(body["disciplineGroups"]) == 1 for body in fan_out)
    assert [body["disciplineGroups"][0] for body in fan_out] == search.KNOWN_GROUPS
    assert not result["incompleto"]
    assert result["total"] == 499 + 3 * len(search.KNOWN_GROUPS)


def test_group_unknown_to_the_list_is_also_queried():
    client = FakeClient(by_group(unknown="Calistenia"))
    run_minimal(client)
    queried = [body["disciplineGroups"][0] for _path, body in client.calls[1:]]
    assert queried == [*search.KNOWN_GROUPS, "Calistenia"]


def test_group_window_still_full_is_incomplete():
    client = FakeClient(by_group(sizes={"Yoga": 499}))
    result = run_minimal(client)
    assert result["incompleto"]
    assert len(client.calls) == 1 + len(search.KNOWN_GROUPS)


def test_budget_exhausted_mid_fan_out_is_incomplete():
    client = FakeClient(by_group())
    result = run_minimal(client, max_requests=5)
    assert len(client.calls) == 5 < 1 + len(search.KNOWN_GROUPS)
    assert result["incompleto"]


def test_default_budget_covers_a_full_peak_hour():
    assert search.MAX_REQUESTS >= 2 + 2 * len(search.KNOWN_GROUPS) + 2


def test_pauses_between_requests():
    pauses = []
    first = {"elements": [element(i) for i in range(499)]}
    client = FakeClient([first, {"elements": []}, {"elements": []}])
    search.search_activities(client, DESDE, HASTA, sleep=pauses.append)
    assert pauses == [0.2, 0.2]


def test_known_group_goes_to_api_unknown_stays_client_side():
    client = FakeClient([{"elements": []}])
    run(client, disciplinas=["padel"])
    assert client.calls[0][1]["disciplineGroups"] == ["Pádel"]

    client = FakeClient(
        [
            {
                "elements": [
                    element(1, disciplineName="Pilates Reformer", disciplineGroup="Pilates"),
                    element(2),
                ]
            }
        ]
    )
    result = run(client, disciplinas=["pilates reformer"])
    assert "disciplineGroups" not in client.calls[0][1]
    assert [a["activity_id"] for a in result["resultados"]] == ["a1"]


def test_barrios_filter_ignores_accents_and_case():
    loc = {"neighbourhood": "Cordón", "lat": None, "lon": None}
    client = FakeClient([{"elements": [element(1, location=loc), element(2)]}])
    result = run(client, barrios=["cordon"])
    assert [a["activity_id"] for a in result["resultados"]] == ["a1"]


def test_lugares_go_to_api_and_filter_client_side():
    client = FakeClient([{"elements": [element(1), element(2)]}])
    result = run(client, lugares=["e1"])
    assert client.calls[0][1]["entityIds"] == ["e1"]
    assert [a["entity_id"] for a in result["resultados"]] == ["e1"]


def test_solo_entidades_empty_makes_no_request():
    client = FakeClient([])
    result = run(client, solo_entidades=set())
    assert client.calls == [] and result["total"] == 0


def test_solo_entidades_intersects_with_lugares():
    client = FakeClient([{"elements": [element(1), element(2)]}])
    result = run(client, lugares=["e1", "e2"], solo_entidades={"e2"})
    assert client.calls[0][1]["entityIds"] == ["e2"]
    assert [a["entity_id"] for a in result["resultados"]] == ["e2"]


def test_sorted_by_start_and_capped_with_warning():
    elements = [element(i, start=f"2026-10-12T{20 - i // 10:02d}:00:00") for i in range(60)]
    client = FakeClient([{"elements": elements}])
    result = run(client, limit=50)
    assert result["total"] == 60 and result["mostrando"] == 50
    starts = [a["inicio"] for a in result["resultados"]]
    assert starts == sorted(starts)
    assert any("Afina" in aviso for aviso in result["avisos"])


def test_distance_filters_sorts_and_drops_missing_coordinates():
    near = element(1, location={"neighbourhood": "A", "lat": -34.9011, "lon": -56.1645})
    far = element(2, location={"neighbourhood": "B", "lat": -34.9475, "lon": -54.9333})
    none = element(3, location={"neighbourhood": "C", "lat": None, "lon": None})
    client = FakeClient([{"elements": [far, none, near]}])
    result = run(client, lat=-34.9011, lon=-56.1645)
    assert [a["activity_id"] for a in result["resultados"]] == ["a1", "a2"]
    assert result["resultados"][0]["distancia_km"] == 0

    client = FakeClient([{"elements": [far, near]}])
    result = run(client, lat=-34.9011, lon=-56.1645, distancia_km=5)
    assert [a["activity_id"] for a in result["resultados"]] == ["a1"]


def test_haversine_one_degree_of_latitude():
    assert search.haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.1)


@pytest.mark.parametrize(
    "kwargs",
    [{"lat": 1.0}, {"distancia_km": 3}, {"lat": 1.0, "lon": 1.0, "distancia_km": -1}],
)
def test_inconsistent_location_args_are_rejected(kwargs):
    with pytest.raises(ValueError):
        run(FakeClient([]), **kwargs)


def test_range_validation():
    with pytest.raises(InputError, match="7 días"):
        search.search_activities(FakeClient([]), DESDE, DESDE + timedelta(days=8))
    with pytest.raises(InputError, match="posterior"):
        search.search_activities(FakeClient([]), HASTA, DESDE)


def test_canonical_group():
    assert search.canonical_group("PADEL") == "Pádel"
    assert search.canonical_group("inventado") is None
