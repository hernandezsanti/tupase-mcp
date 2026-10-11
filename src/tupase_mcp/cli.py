"""Línea de comandos: `login`, `logout` y `serve` (el servidor MCP por stdio)."""

import argparse
import getpass
import logging
import sys

import httpx

from . import auth
from .errors import TupaseError

LOG = logging.getLogger("tupase_mcp")
BAD_CREDENTIALS_CODES = ("invalid_grant", "access_denied")


def _report(exc: TupaseError) -> None:
    """Imprime el error en stderr sin filtrar diagnósticos internos."""
    LOG.warning("falló: %s", exc)
    if exc.safe_for_user:
        print(str(exc), file=sys.stderr)
        return
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    code = payload.get("error")
    if code in BAD_CREDENTIALS_CODES:
        print("Credenciales inválidas.", file=sys.stderr)
        return
    detail = code or getattr(exc, "status_code", None) or "error"
    print(
        f"No se pudo iniciar sesión ({detail}). Inténtalo de nuevo o revisa tu cuenta.",
        file=sys.stderr,
    )


def _login() -> int:
    try:
        email = input("Correo de Tupase: ").strip()
        password = getpass.getpass("Contraseña (no se guarda): ")
    except (EOFError, KeyboardInterrupt):
        print("Cancelado.", file=sys.stderr)
        return 1
    try:
        with httpx.Client(timeout=15.0) as http:
            session = auth.login(email, password, http)
    except TupaseError as exc:
        _report(exc)
        return 1
    except KeyboardInterrupt:
        print("Cancelado.", file=sys.stderr)
        return 1
    print(f"Sesión iniciada como {session.email}.")
    return 0


def _logout() -> int:
    try:
        auth.clear_session()
    except TupaseError as exc:
        _report(exc)
        return 1
    print("Sesión cerrada.")
    return 0


def _serve() -> None:
    from .server import mcp

    mcp.run(transport="stdio")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tupase-mcp", description="Servidor MCP no oficial para Tupase."
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("login", help="Inicia sesión con tu cuenta de Tupase (una sola vez)")
    sub.add_parser("logout", help="Borra la sesión guardada")
    sub.add_parser("serve", help="Levanta el servidor MCP por stdio (es el comando por defecto)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    # httpx registra cada pedido (URL incluida) a nivel INFO: ruido y datos de más en el log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "login":
        return _login()
    if args.command == "logout":
        return _logout()
    _serve()
    return 0
