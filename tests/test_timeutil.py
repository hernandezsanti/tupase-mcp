from datetime import datetime

from tupase_mcp.timeutil import MONTEVIDEO, from_api_utc, local_iso, parse_local, to_api_utc


def test_parse_local_naive_is_montevideo():
    dt = parse_local("2026-10-12T18:00:00")
    assert dt.tzinfo == MONTEVIDEO
    assert dt.utcoffset().total_seconds() == -3 * 3600


def test_parse_local_respects_explicit_offset():
    dt = parse_local("2026-10-12T18:00:00+00:00")
    assert to_api_utc(dt) == "2026-10-12T18:00:00"


def test_to_api_utc_converts_local_to_utc():
    assert to_api_utc(parse_local("2026-10-12T22:00:00")) == "2026-10-13T01:00:00"


def test_from_api_utc_crosses_midnight_to_previous_local_day():
    dt = from_api_utc("2026-10-13T01:30:00")
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 10, 12, 22)


def test_local_iso_has_offset():
    assert local_iso(from_api_utc("2026-10-13T01:30:00")) == "2026-10-12T22:30:00-03:00"


def test_parse_local_rejects_garbage():
    import pytest

    with pytest.raises(ValueError):
        parse_local("mañana")
    assert isinstance(parse_local("2026-10-12"), datetime)
