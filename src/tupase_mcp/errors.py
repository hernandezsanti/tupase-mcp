class InputError(ValueError):
    """Dato de entrada inválido de la persona/modelo: el mensaje se puede mostrar tal cual."""


class TupaseError(Exception):
    """Error al hablar con Tupase o Auth0. `safe_for_user` marca un mensaje de
    negocio real (ej. "Cupo completo") que se puede mostrar tal cual; un
    diagnóstico interno (red, respuesta rara) nunca debe llegar al usuario."""

    def __init__(self, message, *, safe_for_user=False, payload=None):
        super().__init__(message)
        self.safe_for_user = safe_for_user
        self.payload = payload


class NoSessionError(TupaseError):
    def __init__(self):
        super().__init__(
            "No hay sesión. Corre `uvx tupase-mcp login` en la terminal.",
            safe_for_user=True,
        )


class UnauthorizedError(TupaseError):
    """Tupase rechazó el access token (401)."""

    def __init__(self):
        super().__init__("unauthorized")


class AuthError(TupaseError):
    def __init__(self, message, *, status_code=None, body=None):
        super().__init__(message, payload=body)
        self.status_code = status_code
