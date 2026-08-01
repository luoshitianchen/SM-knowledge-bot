import os
from pathlib import Path

os.environ["DATABASE_PATH"] = str(Path(__file__).parent / "test.db")
os.environ["ERP_AUTH_URL"] = "https://erp.example.test/api/integrations/knowledge-bot/auth"
os.environ["ERP_INTEGRATION_KEY"] = "test-integration-key"

from fastapi.testclient import TestClient
from app.main import app, db, now, session_hash, timestamp


def authenticate(client: TestClient, user_id: str, name: str, role: str, department: str) -> None:
    token = f"test-{user_id}"
    csrf = f"csrf-{user_id}"
    with db() as conn:
        conn.execute("""INSERT INTO users (id,name,role,department,active,created_at) VALUES (?,?,?,?,1,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,department=excluded.department,active=1""", (user_id, name, role, department, now()))
        conn.execute("INSERT OR REPLACE INTO auth_sessions (token_hash,user_id,expires_at,created_at,csrf_hash) VALUES (?,?,?,?,?)", (session_hash(token), user_id, timestamp() + 3600, now(), session_hash(csrf)))
    client.cookies.set("sm_kb_session", token)
    client.headers.update({"X-CSRF-Token": csrf})


def test_rbac_retrieval_and_conversation():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        authenticate(client, "admin", "系统管理员", "admin", "all")
        assert client.post("/users", json={"id": "fin-manager", "name": "财务经理", "role": "manager", "department": "finance"}).status_code == 201
        assert client.post("/users", json={"id": "dev", "name": "研发同事", "role": "employee", "department": "engineering"}).status_code == 201
        authenticate(client, "fin-manager", "财务经理", "manager", "finance")
        created = client.post("/documents", json={"title": "报销制度", "content": "报销单需要在每月十日前提交给财务。", "department": "finance", "min_role": "employee"})
        assert created.status_code == 201
        authenticate(client, "dev", "研发同事", "employee", "engineering")
        blocked = client.post("/chat", json={"question": "报销何时提交"})
        assert not blocked.json()["sources"]
        authenticate(client, "fin-manager", "财务经理", "manager", "finance")
        allowed = client.post("/chat", json={"question": "报销何时提交"})
        assert allowed.json()["sources"]
        conversation_id = allowed.json()["conversation_id"]
        assert client.get(f"/conversations/{conversation_id}").status_code == 200


def test_sources_are_scoped_to_department():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        authenticate(client, "admin", "系统管理员", "admin", "all")
        client.post("/users", json={"id": "eng-manager", "name": "研发经理", "role": "manager", "department": "engineering"})
        with db() as conn:
            conn.execute("INSERT INTO knowledge_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("source-1", "github", "github.com/acme/engineering", "main", "engineering", "employee", "admin", now(), 1, 2, "success", None))
        assert len(client.get("/sources").json()) == 1
        authenticate(client, "eng-manager", "研发经理", "manager", "engineering")
        assert len(client.get("/sources").json()) == 1


def test_agents_can_be_created_and_used_with_restricted_scope():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        authenticate(client, "admin", "系统管理员", "admin", "all")
        response = client.post("/agents", json={
            "name": "测试 Agent", "description": "测试受控问答", "department": "all",
            "max_role": "employee", "system_prompt": "只引用授权知识。",
        })
        assert response.status_code == 201
        agent_id = response.json()["id"]
        assert any(agent["id"] == agent_id for agent in client.get("/agents").json())
        result = client.post("/chat", json={"question": "研发协作规范", "agent_id": agent_id})
        assert result.status_code == 200
        assert result.json()["agent"]["id"] == agent_id


def test_local_login_returns_active_user():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        assert client.get("/api/summary", headers={"X-User-Id": "admin"}).status_code == 401
        authenticate(client, "admin", "系统管理员", "admin", "all")
        client.headers.pop("X-CSRF-Token")
        assert client.post("/agents", json={"name": "被拒绝", "description": "缺少 CSRF", "department": "all", "max_role": "employee", "system_prompt": "test"}).status_code == 403


def test_security_headers_and_request_id():
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-Id": "kb-trace-1"})
        assert response.status_code == 200
        assert response.headers["X-Request-Id"] == "kb-trace-1"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert float(response.headers["X-Process-Time-Ms"]) >= 0
        assert response.headers["Server-Timing"].startswith("app;dur=")


def test_rejects_oversized_request_body(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 8)
    with TestClient(app) as client:
        response = client.post("/auth/login", content="x" * 9, headers={"content-type": "application/json"})
        assert response.status_code == 413
        assert response.headers["X-Request-Id"]


def test_rejects_malformed_content_length():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Content-Length": "not-a-number"})
        assert response.status_code == 400


def test_replaces_unsafe_request_id():
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-Id": "x" * 65})
        assert response.status_code == 200
        assert response.headers["X-Request-Id"] != "x" * 65


def test_production_refuses_demo_data(monkeypatch):
    from app import main
    monkeypatch.setenv("KB_ENV", "production")
    monkeypatch.setenv("SEED_DEMO_DATA", "true")
    monkeypatch.setattr(main, "allowed_hosts", ["kb.internal.test"])
    try:
        main.startup()
    except RuntimeError as exc:
        assert "SEED_DEMO_DATA" in str(exc)
    else:
        raise AssertionError("production demo data must be refused")


def test_summary_only_counts_visible_resources():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        authenticate(client, "admin", "系统管理员", "admin", "all")
        assert client.post("/users", json={"id": "finance-user", "name": "财务同事", "role": "employee", "department": "finance"}).status_code == 201
        assert client.post("/documents", json={"title": "研发机密", "content": "engineering confidential", "department": "engineering", "min_role": "employee"}).status_code == 201
        assert client.post("/documents", json={"title": "财务制度", "content": "finance policy", "department": "finance", "min_role": "employee"}).status_code == 201
        authenticate(client, "finance-user", "财务同事", "employee", "finance")
        summary = client.get("/api/summary")
        assert summary.status_code == 200
        assert summary.json()["documents"] == 1


def test_github_import_is_serialized():
    from app import main
    assert main.github_import_lock.acquire(blocking=False)
    try:
        with TestClient(app) as client:
            authenticate(client, "admin", "系统管理员", "admin", "all")
            response = client.post("/documents/import/github", json={"repository_url": "https://github.com/acme/repo"})
            assert response.status_code == 429
    finally:
        main.github_import_lock.release()


def test_admin_audit_logs_are_paginated_and_filterable():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        authenticate(client, "admin", "系统管理员", "admin", "all")
        assert client.post("/users", json={"id": "audit-user", "name": "审计用户", "role": "employee", "department": "engineering"}).status_code == 201
        response = client.get("/audit-logs?action=user.created&limit=1&offset=0")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["action"] == "user.created"


def test_session_pruning_keeps_latest_sessions(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_SESSIONS_PER_USER", 2)
    with main.db() as conn:
        for index in range(4):
            conn.execute("INSERT OR REPLACE INTO auth_sessions (token_hash,user_id,expires_at,created_at,csrf_hash) VALUES (?,?,?,?,?)", (f"session-{index}", "admin", main.timestamp() + 3600, f"2026-01-01T00:00:0{index}+00:00", "csrf"))
        main.prune_user_sessions(conn, "admin")
        assert conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id='admin'").fetchone()[0] == 2
