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
