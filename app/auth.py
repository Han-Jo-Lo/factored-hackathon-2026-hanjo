"""
Sesion de prueba de confianza y politica de acceso por rol.

TEST_SESSIONS es un IdP de juguete (rol + user). El thread_id del dict
no se usa en el chat: cada navegador manda un visitor_id y el servidor
arma session_key:visitor_id. El modelo no elige rol ni hilo.
"""

from typing import Any, Optional, TypedDict
import re


class SessionClaims(TypedDict):
    user_id: str
    role: str
    thread_id: str


class RolePolicy(TypedDict):
    allowed_tools: frozenset[str]
    allowed_metrics: frozenset[str] | None
    max_limite: int


TEST_SESSIONS: dict[str, SessionClaims] = {
    "analyst": {
        "user_id": "analyst",
        "role": "marketing_analyst",
        "thread_id": "sess_analyst_1",
    },
    "viewer": {
        "user_id": "viewer",
        "role": "marketing_viewer",
        "thread_id": "sess_viewer_1",
    },
}

ROLE_POLICIES: dict[str, RolePolicy] = {
    "marketing_analyst": {
        "allowed_tools": frozenset({"consultar_desempeno_campanas"}),
        "allowed_metrics": None,
        "max_limite": 50,
    },
    "marketing_viewer": {
        "allowed_tools": frozenset({"consultar_desempeno_campanas"}),
        "allowed_metrics": frozenset(
            {"roi", "pct_cobertura_costo", "conversiones_reales"}
        ),
        "max_limite": 10,
    },
}

_ORDEN_REQUIERE_METRICA = {
    "roi_desc": "roi",
    "roi_asc": "roi",
    "valor_desc": "valor_creditado_usd",
    "conversiones_desc": "conversiones_reales",
}

_VISITOR_ID = re.compile(r"^[0-9a-fA-F-]{8,36}$")


def resolve_test_session(session_key: str) -> Optional[SessionClaims]:
    """Devuelve claims solo si la clave esta en el IdP de prueba."""
    return TEST_SESSIONS.get(session_key)


def bind_visitor_thread(
    session: SessionClaims, visitor_id: str | None
) -> SessionClaims | None:
    """Hilo por navegador. visitor_id invalido -> None (no hay chat)."""
    if not visitor_id or not _VISITOR_ID.fullmatch(visitor_id):
        return None
    bound = dict(session)
    bound["thread_id"] = f"{session['user_id']}:{visitor_id}"
    return bound


def resolve_test_session(session_key: str) -> Optional[SessionClaims]:
    """Devuelve claims solo si la clave esta en el IdP de prueba."""
    return TEST_SESSIONS.get(session_key)


def get_role_policy(role: str | None) -> RolePolicy | None:
    if not role:
        return None
    return ROLE_POLICIES.get(role)


def tool_is_allowed(role: str | None, tool_name: str) -> bool:
    policy = get_role_policy(role)
    if policy is None:
        return False
    return tool_name in policy["allowed_tools"]


def apply_role_ceiling_to_args(role: str, args: dict[str, Any]) -> dict[str, Any]:
    """Recorta args del LLM segun el rol. No lee identidad de los args."""
    policy = get_role_policy(role)
    if policy is None:
        return dict(args)

    capped = dict(args)
    limite = capped.get("limite", 20)
    try:
        limite = int(limite)
    except (TypeError, ValueError):
        limite = 20
    capped["limite"] = min(limite, policy["max_limite"])

    allowed = policy["allowed_metrics"]
    if allowed is not None:
        metricas = capped.get("metricas")
        if metricas:
            filtered = [m for m in metricas if m in allowed]
            capped["metricas"] = filtered or sorted(allowed)
        orden = capped.get("orden")
        requerida = _ORDEN_REQUIERE_METRICA.get(orden)
        if requerida and requerida not in allowed:
            capped["orden"] = "sin_orden"
    return capped
