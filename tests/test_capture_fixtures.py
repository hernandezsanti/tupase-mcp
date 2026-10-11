import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "capture_fixtures", Path(__file__).parent.parent / "scripts" / "capture_fixtures.py"
)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def test_redact_hides_personal_values_recursively():
    data = {
        "email": "a@b.com",
        "firstName": "Ana",
        "nested": {"userDocument": "1234567", "keep": "Yoga"},
        "items": [{"phone": "099"}, {"phone": "098"}, {"phone": "097"}, {"phone": "096"}],
        "empty": None,
    }
    out = capture.redact(data)
    assert out["email"] == "<redacted>" and out["firstName"] == "<redacted>"
    assert out["nested"] == {"userDocument": "<redacted>", "keep": "Yoga"}
    assert len(out["items"]) == 3 and out["items"][0] == {"phone": "<redacted>"}
    assert out["empty"] is None


def test_redact_leaves_no_known_sensitive_key_untouched():
    for key in capture.SENSITIVE:
        assert capture.redact({key: "valor real"})[key] == "<redacted>"


def test_redact_hides_activity_history_only_when_asked():
    data = {
        "activityInfo": {"entityName": "Estudio Sol", "disciplineName": "Yoga", "online": False}
    }
    assert capture.redact(data)["activityInfo"]["entityName"] == "Estudio Sol"
    hidden = capture.redact(data, capture.HISTORY)["activityInfo"]
    assert hidden["entityName"] == "<redacted>" and hidden["disciplineName"] == "<redacted>"
    assert hidden["online"] is False


def test_redact_hides_full_name_and_employer():
    out = capture.redact({"userFullName": "Ana Pérez", "companyName": "ACME", "status": "ACTIVE"})
    assert out == {"userFullName": "<redacted>", "companyName": "<redacted>", "status": "ACTIVE"}
