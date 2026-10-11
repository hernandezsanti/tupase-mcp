"""Rutinas: clases que la persona repite en el mismo lugar, día y hora."""

from collections import defaultdict
from datetime import datetime, timedelta

from . import timeutil
from .textutil import fold

MIN_REPETITIONS = 2
MAX_ROUTINES = 3
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _slot(local: datetime) -> tuple[int, str]:
    return local.weekday(), local.strftime("%H:%M")


def detect_routines(reservations: list, now: datetime) -> list[dict]:
    groups = defaultdict(list)
    for raw in reservations:
        if not isinstance(raw, dict):
            continue
        if "CANCEL" in str(raw.get("status") or "").upper():
            continue
        info = raw.get("activityInfo") or {}
        lugar, disciplina, start = (
            info.get("entityName"),
            info.get("disciplineName"),
            info.get("startDateTime"),
        )
        if not (lugar and disciplina and start):
            continue
        try:
            local = timeutil.from_api_utc(start)
        except ValueError:
            continue
        if local >= now:
            continue
        groups[(fold(lugar), fold(disciplina), *_slot(local))].append((local, lugar, disciplina))

    routines = []
    for (_, _, weekday, hour), occurrences in groups.items():
        if len(occurrences) < MIN_REPETITIONS:
            continue
        last, lugar, disciplina = max(occurrences, key=lambda o: o[0])
        routines.append(
            {
                "lugar": lugar,
                "disciplina": disciplina,
                "dia_semana": WEEKDAYS_ES[weekday],
                "hora": hour,
                "veces": len(occurrences),
                "ultima": timeutil.local_iso(last),
            }
        )
    routines.sort(key=lambda r: r["ultima"], reverse=True)  # empate: la más reciente primero
    routines.sort(key=lambda r: -r["veces"])  # sort estable: más repeticiones primero
    return routines[:MAX_ROUTINES]


def upcoming_dates(routine: dict, activities: list[dict], booked: list[dict]) -> list[dict]:
    weekday = WEEKDAYS_ES.index(routine["dia_semana"])
    taken = {
        (fold(b["lugar"] or ""), fold(b["disciplina"] or ""), b["inicio"])
        for b in booked
        if "CANCEL" not in str(b.get("estado") or "").upper()
    }
    matches = []
    for activity in activities:
        if not activity.get("inicio"):
            continue
        local = timeutil.parse_local(activity["inicio"])
        if (
            fold(activity["lugar"] or "") == fold(routine["lugar"])
            and fold(activity["disciplina"] or "") == fold(routine["disciplina"])
            and _slot(local) == (weekday, routine["hora"])
            and (
                fold(activity["lugar"] or ""),
                fold(activity["disciplina"] or ""),
                activity["inicio"],
            )
            not in taken
        ):
            matches.append(activity)
    return sorted(matches, key=lambda a: a["inicio"])


def next_occurrence(routine: dict, now: datetime) -> datetime:
    """Primera ocurrencia (>= now) del día y la hora de la rutina, en hora de Montevideo."""
    local_now = now.astimezone(timeutil.MONTEVIDEO)
    weekday = WEEKDAYS_ES.index(routine["dia_semana"])
    hour, minute = (int(part) for part in routine["hora"].split(":"))
    day = local_now.date() + timedelta(days=(weekday - local_now.weekday()) % 7)
    candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timeutil.MONTEVIDEO)
    if candidate < local_now:
        day += timedelta(days=7)
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timeutil.MONTEVIDEO)
    return candidate
