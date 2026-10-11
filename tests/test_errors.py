from tupase_mcp.errors import AuthError, NoSessionError, TupaseError, UnauthorizedError


def test_no_session_is_safe_and_mentions_login():
    err = NoSessionError()
    assert err.safe_for_user
    assert "uvx tupase-mcp login" in str(err)


def test_tupase_error_defaults_to_unsafe():
    err = TupaseError("boom", payload={"x": 1})
    assert not err.safe_for_user
    assert err.payload == {"x": 1}


def test_unauthorized_and_auth_error_are_tupase_errors():
    assert isinstance(UnauthorizedError(), TupaseError)
    err = AuthError("falló", status_code=403, body={"error": "x"})
    assert err.status_code == 403
    assert err.payload == {"error": "x"}
