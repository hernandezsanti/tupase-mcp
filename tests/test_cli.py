import logging

import httpx
import keyring
import pytest
import respx

from tupase_mcp import auth, cli, config

TOKEN_URL = f"https://{config.AUTH0_DOMAIN}/oauth/token"
USERINFO_URL = f"https://{config.AUTH0_DOMAIN}/userinfo"


def _inputs(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "a@b.com")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secreto")


@respx.mock
def test_login_saves_session_and_never_prints_the_password(monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "refresh_token": "rt"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=httpx.Response(200, json={"sub": "auth0|1", "email": "a@b.com"})
    )
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 0
    output = capsys.readouterr()
    assert "a@b.com" in output.out and "secreto" not in output.out + output.err
    assert auth.load_session().refresh_token == "rt"


@respx.mock
def test_login_with_wrong_password_fails_cleanly(monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(403, json={"error": "access_denied"}))
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 1
    assert "Credenciales" in capsys.readouterr().err
    assert auth.load_session() is None


def test_logout_clears_session(capsys):
    auth.save_session(auth.Session("rt", "auth0|1", "a@b.com"))
    assert cli.main(["logout"]) == 0
    assert auth.load_session() is None


def test_no_subcommand_serves(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_serve", lambda: calls.append(1))
    assert cli.main([]) == 0 and calls == [1]
    assert cli.main(["serve"]) == 0 and calls == [1, 1]


@respx.mock
def test_login_other_auth0_errors_are_not_reported_as_bad_credentials(monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(403, json={"error": "too_many_attempts"})
    )
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 1
    err = capsys.readouterr().err
    assert "Credenciales" not in err and "too_many_attempts" in err and "secreto" not in err


@respx.mock
def test_login_invalid_grant_is_bad_credentials(monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(403, json={"error": "invalid_grant"}))
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 1
    assert "Credenciales" in capsys.readouterr().err


@respx.mock
def test_login_server_error_shows_the_status(monkeypatch, capsys):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(500, text="boom"))
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 1
    err = capsys.readouterr().err
    assert "500" in err and "Credenciales" not in err


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_login_cancelled_prints_cancelado(monkeypatch, capsys, exc):
    def raiser(prompt=""):
        raise exc

    monkeypatch.setattr("builtins.input", raiser)
    assert cli.main(["login"]) == 1
    assert "Cancelado." in capsys.readouterr().err


def test_login_and_logout_survive_a_broken_keyring(monkeypatch, capsys):
    from tests.test_auth import BrokenKeyring

    keyring.set_keyring(BrokenKeyring(RuntimeError("no backend")))
    assert cli.main(["logout"]) == 1
    assert "llavero" in capsys.readouterr().err


def test_unsafe_tupase_error_prints_a_generic_message(monkeypatch, capsys):
    from tupase_mcp.errors import TupaseError

    def boom(email, password, http):
        raise TupaseError("detalle interno", payload={"x": 1})

    monkeypatch.setattr(cli.auth, "login", boom)
    _inputs(monkeypatch)
    assert cli.main(["login"]) == 1
    err = capsys.readouterr().err
    assert "detalle interno" not in err and "Traceback" not in err


def test_httpx_request_logs_are_silenced(monkeypatch):
    monkeypatch.setattr(cli, "_serve", lambda: None)
    cli.main([])
    assert logging.getLogger("httpx").level == logging.WARNING
