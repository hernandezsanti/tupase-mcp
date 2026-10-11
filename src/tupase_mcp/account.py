"""Cuenta de Tupase: perfil, estado, medios de pago y edición del perfil."""

from .errors import InputError, TupaseError

USER_FIELDS = (
    "activationCode",
    "birthDate",
    "countryId",
    "deviceIdentifier",
    "email",
    "firstName",
    "lastName",
    "phone",
    "userDocument",
    "userLogicalId",
)
CHANGE_FIELDS = {
    "nombre": "firstName",
    "apellido": "lastName",
    "telefono": "phone",
    "fecha_nacimiento": "birthDate",
    "pais_id": "countryId",
    "documento": "userDocument",
}
_SHOWN_FIELDS = (
    "firstName",
    "lastName",
    "phone",
    "birthDate",
    "countryId",
    "userDocument",
    "email",
)


def _require_dict(body, action):
    if not isinstance(body, dict):
        raise TupaseError(f"{action} falló: respuesta inesperada", payload=body)
    return body


def get_profile(client, user_id):
    return _require_dict(client.get(f"users/user-account/{user_id}"), "perfil")


def get_status(client, user_id):
    return _require_dict(client.get(f"users/user-account/status/{user_id}"), "estado de la cuenta")


def get_payment_preferences(client, user_id):
    return _require_dict(client.get(f"payment-preferences/user/{user_id}"), "medios de pago")


def list_countries(client):
    body = client.get("countries")
    if not isinstance(body, list):
        raise TupaseError("listar países falló: respuesta inesperada", payload=body)
    return body


def update_profile(client, user_id, changes):
    changes = {key: value for key, value in changes.items() if value is not None}
    unknown = set(changes) - set(CHANGE_FIELDS)
    if unknown:
        raise InputError(f"No se puede editar: {', '.join(sorted(unknown))}.")
    if not changes:
        raise InputError("Indica al menos un campo para actualizar.")
    if "pais_id" in changes:
        known = {c.get("id") for c in list_countries(client) if isinstance(c, dict)}
        if changes["pais_id"] not in known:
            raise InputError("`pais_id` no es válido; los países disponibles salen de Tupase.")

    current = get_profile(client, user_id)
    body = {field: current.get(field) for field in USER_FIELDS}
    body["userLogicalId"] = user_id
    for key, value in changes.items():
        body[CHANGE_FIELDS[key]] = value
    result = client.put("users/user-account", json=body)
    if result is not True:
        raise TupaseError("Tupase no confirmó el cambio del perfil.", payload=result)
    return {field: body[field] for field in _SHOWN_FIELDS}
