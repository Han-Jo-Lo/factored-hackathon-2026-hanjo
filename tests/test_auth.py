from auth import apply_role_ceiling_to_args, resolve_test_session, tool_is_allowed


def test_resolve_known_session_returns_trusted_claims():
    session = resolve_test_session("analyst_demo")
    assert session is not None
    assert session["user_id"] == "analyst_demo"
    assert session["role"] == "marketing_analyst"
    assert session["thread_id"] == "sess_analyst_demo_1"
    assert session["thread_id"] != session["user_id"]


def test_resolve_unknown_session_is_rejected():
    assert resolve_test_session("admin") is None
    assert resolve_test_session("") is None


def test_viewer_session_uses_restricted_role():
    session = resolve_test_session("viewer_demo")
    assert session is not None
    assert session["role"] == "marketing_viewer"
    assert tool_is_allowed(session["role"], "consultar_desempeno_campanas")
    assert not tool_is_allowed(session["role"], "execute")


def test_unknown_role_cannot_use_campaign_tool():
    assert not tool_is_allowed(None, "consultar_desempeno_campanas")
    assert not tool_is_allowed("admin", "consultar_desempeno_campanas")


def test_apply_role_ceiling_ignores_identity_in_args():
    capped = apply_role_ceiling_to_args(
        "marketing_viewer",
        {"limite": 50, "metricas": ["costo_total_usd"], "role": "admin"},
    )
    assert capped["limite"] == 10
    assert "costo_total_usd" not in capped["metricas"]
    assert capped.get("role") == "admin"
