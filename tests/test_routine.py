from tupase_mcp import routine
from tupase_mcp.timeutil import parse_local

NOW = parse_local("2026-10-12T12:00:00")  # lunes


def res(entity="Estudio Sol", disc="Yoga", start="2026-10-01T21:00:00", status="CONFIRMED"):
    return {
        "reservationIdentityCode": "X",
        "status": status,
        "activityInfo": {"entityName": entity, "disciplineName": disc, "startDateTime": start},
    }


THURSDAYS = ["2026-10-01T21:00:00", "2026-10-08T21:00:00"]  # jueves 18:00 locales


def test_two_same_slot_reservations_make_a_routine():
    found = routine.detect_routines([res(start=s) for s in THURSDAYS], NOW)
    assert found == [
        {
            "lugar": "Estudio Sol",
            "disciplina": "Yoga",
            "dia_semana": "jueves",
            "hora": "18:00",
            "veces": 2,
            "ultima": "2026-10-08T18:00:00-03:00",
        }
    ]


def test_single_occurrence_is_not_a_routine():
    assert routine.detect_routines([res()], NOW) == []


def test_cancelled_and_future_reservations_do_not_count():
    reservations = [res(start=THURSDAYS[0]), res(start=THURSDAYS[1], status="CANCELLED")]
    assert routine.detect_routines(reservations, NOW) == []
    reservations = [res(start=THURSDAYS[0]), res(start="2026-10-15T21:00:00")]
    assert routine.detect_routines(reservations, NOW) == []


def test_different_local_time_is_a_different_slot():
    reservations = [res(start="2026-10-01T21:00:00"), res(start="2026-10-08T22:00:00")]
    assert routine.detect_routines(reservations, NOW) == []


def test_weekday_uses_local_time_not_utc():
    # jueves 22:00 locales = viernes 01:00 UTC
    reservations = [res(start="2026-10-02T01:00:00"), res(start="2026-10-09T01:00:00")]
    found = routine.detect_routines(reservations, NOW)
    assert found[0]["dia_semana"] == "jueves" and found[0]["hora"] == "22:00"


def test_ranked_by_repetitions_and_capped_at_three():
    reservations = []
    for index, repetitions in enumerate([5, 4, 3, 2]):
        for week in range(repetitions):
            reservations.append(
                res(entity=f"L{index}", start=f"2026-09-{1 + week * 7:02d}T21:00:00")
            )
    found = routine.detect_routines(reservations, NOW)
    assert [r["veces"] for r in found] == [5, 4, 3]


def test_malformed_reservations_are_ignored():
    junk = [None, "x", {}, {"activityInfo": {"entityName": "A"}}, res(start="no-fecha")]
    assert routine.detect_routines(junk, NOW) == []


def _routine():
    return routine.detect_routines([res(start=s) for s in THURSDAYS], NOW)[0]


def act(inicio="2026-10-15T18:00:00-03:00", lugar="Estudio Sol", disciplina="Yoga", i=1):
    return {"activity_id": f"a{i}", "lugar": lugar, "disciplina": disciplina, "inicio": inicio}


def test_upcoming_dates_matches_slot_and_skips_booked():
    activities = [
        act(i=1),
        act(inicio="2026-10-16T18:00:00-03:00", i=2),  # viernes
        act(lugar="Otro", i=3),
        act(disciplina="Pilates", i=4),
        act(inicio="2026-10-15T19:00:00-03:00", i=5),
        act(inicio="2026-10-22T18:00:00-03:00", lugar="ESTUDIO SOL", i=6),
    ]
    booked = [
        {
            "lugar": "Estudio Sol",
            "disciplina": "Yoga",
            "inicio": "2026-10-22T18:00:00-03:00",
            "estado": "CONFIRMED",
        }
    ]
    assert [a["activity_id"] for a in routine.upcoming_dates(_routine(), activities, booked)] == [
        "a1"
    ]


def test_cancelled_booking_does_not_hide_the_date():
    booked = [
        {
            "lugar": "Estudio Sol",
            "disciplina": "Yoga",
            "inicio": "2026-10-15T18:00:00-03:00",
            "estado": "CANCELLED",
        }
    ]
    assert len(routine.upcoming_dates(_routine(), [act()], booked)) == 1


def _thursday_routine():
    return {"dia_semana": "jueves", "hora": "18:00"}


def test_next_occurrence_from_monday_is_that_thursday():
    assert routine.next_occurrence(_thursday_routine(), NOW) == parse_local("2026-10-15T18:00:00")


def test_next_occurrence_today_if_still_ahead():
    now = parse_local("2026-10-15T17:00:00")
    assert routine.next_occurrence(_thursday_routine(), now) == parse_local("2026-10-15T18:00:00")


def test_next_occurrence_next_week_if_already_passed():
    now = parse_local("2026-10-15T19:00:00")
    assert routine.next_occurrence(_thursday_routine(), now) == parse_local("2026-10-22T18:00:00")
