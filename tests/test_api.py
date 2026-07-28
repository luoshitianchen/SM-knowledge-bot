import os
from pathlib import Path

os.environ["DATABASE_PATH"] = str(Path(__file__).parent / "test.db")

from fastapi.testclient import TestClient
from app.main import app


def test_rbac_retrieval_and_conversation():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        admin = {"X-User-Id": "admin"}
        assert client.post("/users", headers=admin, json={"id": "fin-manager", "name": "财务经理", "role": "manager", "department": "finance"}).status_code == 201
        assert client.post("/users", headers=admin, json={"id": "dev", "name": "研发同事", "role": "employee", "department": "engineering"}).status_code == 201
        created = client.post("/documents", headers={"X-User-Id": "fin-manager"}, json={"title": "报销制度", "content": "报销单需要在每月十日前提交给财务。", "department": "finance", "min_role": "employee"})
        assert created.status_code == 201
        blocked = client.post("/chat", headers={"X-User-Id": "dev"}, json={"question": "报销何时提交"})
        assert not blocked.json()["sources"]
        allowed = client.post("/chat", headers={"X-User-Id": "fin-manager"}, json={"question": "报销何时提交"})
        assert allowed.json()["sources"]
        conversation_id = allowed.json()["conversation_id"]
        assert client.get(f"/conversations/{conversation_id}", headers={"X-User-Id": "fin-manager"}).status_code == 200


def test_sources_are_scoped_to_department():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        admin = {"X-User-Id": "admin"}
        client.post("/users", headers=admin, json={"id": "eng-manager", "name": "研发经理", "role": "manager", "department": "engineering"})
        from app.main import db, now
        with db() as conn:
            conn.execute("INSERT INTO knowledge_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("source-1", "github", "github.com/acme/engineering", "main", "engineering", "employee", "admin", now(), 1, 2, "success", None))
        assert len(client.get("/sources", headers=admin).json()) == 1
        assert len(client.get("/sources", headers={"X-User-Id": "eng-manager"}).json()) == 1


def test_agents_can_be_created_and_used_with_restricted_scope():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        admin = {"X-User-Id": "admin"}
        response = client.post("/agents", headers=admin, json={
            "name": "测试 Agent", "description": "测试受控问答", "department": "all",
            "max_role": "employee", "system_prompt": "只引用授权知识。",
        })
        assert response.status_code == 201
        agent_id = response.json()["id"]
        assert any(agent["id"] == agent_id for agent in client.get("/agents", headers=admin).json())
        result = client.post("/chat", headers=admin, json={"question": "研发协作规范", "agent_id": agent_id})
        assert result.status_code == 200
        assert result.json()["agent"]["id"] == agent_id


def test_local_login_returns_active_user():
    Path(os.environ["DATABASE_PATH"]).unlink(missing_ok=True)
    with TestClient(app) as client:
        login = client.post("/auth/login", json={"username": "admin"})
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "admin"
        assert client.post("/auth/login", json={"username": "unknown"}).status_code == 401
