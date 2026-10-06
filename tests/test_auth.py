from app.auth import apply_role_ceiling_to_args, resolve_test_session, tool_is_allowed, bind_visitor_thread


def test_resolve_known_session_returns_trusted_claims():
    session = resolve_test_session("analyst")
    assert session is not None
    assert session["user_id"] == "analyst"
    assert session["role"] == "marketing_analyst"


def test_bind_visitor_thread_is_per_browser_not_shared_role():
    base = resolve_test_session("analyst")
    a = bind_visitor_thread(base, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    b = bind_visitor_thread(base, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    other_role = bind_visitor_thread(
        resolve_test_session("viewer"),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    assert a["thread_id"] != b["thread_id"]
    assert a["role"] == "marketing_analyst"
    assert b["role"] == "marketing_analyst"
    assert other_role["thread_id"] != a["thread_id"]
    assert bind_visitor_thread(base, "") is None
    assert bind_visitor_thread(base, "not a uuid!") is None


def test_resolve_unknown_session_is_rejected():
    assert resolve_test_session("admin") is None
    assert resolve_test_session("") is None


def test_viewer_session_uses_restricted_role():
    session = resolve_test_session("viewer")
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
