"""知识库业务深化测试：知识库/文档/问答交互全生命周期。"""
from __future__ import annotations

H = {"X-Internal-Token": "test-internal-key-12345"}


async def _mk_base(client, name="运维知识库", **extra):
    return await client.post("/api/kb/bases", json={"name": name, **extra}, headers=H)


# ═══════════════════════════════════════════════════════════
# 知识库
# ═══════════════════════════════════════════════════════════

class TestKnowledgeBase:
    async def test_create_base_success(self, client):
        resp = await _mk_base(client, "oncall-kb", description="值班手册")
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "oncall-kb"
        assert data["status"] == "active"
        assert data["visibility"] == "internal"

    async def test_create_base_requires_token(self, client):
        resp = await client.post("/api/kb/bases", json={"name": "noauth-kb"})
        assert resp.status_code in (401, 403)

    async def test_create_base_duplicate_name(self, client):
        await _mk_base(client, "dup-kb")
        resp = await _mk_base(client, "dup-kb")
        assert resp.status_code == 409

    async def test_list_bases(self, client):
        await _mk_base(client, "list-kb")
        resp = await client.get("/api/kb/bases", headers=H)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_list_bases_keyword(self, client):
        await _mk_base(client, "kw-unique-kb")
        resp = await client.get("/api/kb/bases?keyword=kw-unique", headers=H)
        assert resp.status_code == 200
        names = [b["name"] for b in resp.json()["items"]]
        assert "kw-unique-kb" in names

    async def test_get_base(self, client):
        create = await _mk_base(client, "get-kb")
        bid = create.json()["id"]
        resp = await client.get(f"/api/kb/bases/{bid}", headers=H)
        assert resp.status_code == 200
        assert resp.json()["id"] == bid

    async def test_get_base_not_found(self, client):
        resp = await client.get("/api/kb/bases/nope", headers=H)
        assert resp.status_code == 404

    async def test_update_base(self, client):
        create = await _mk_base(client, "upd-kb")
        bid = create.json()["id"]
        resp = await client.patch(f"/api/kb/bases/{bid}", json={
            "description": "新描述", "visibility": "private",
        }, headers=H)
        assert resp.status_code == 200
        assert resp.json()["description"] == "新描述"
        assert resp.json()["visibility"] == "private"

    async def test_archive_and_reactivate(self, client):
        create = await _mk_base(client, "arch-kb")
        bid = create.json()["id"]
        resp = await client.patch(f"/api/kb/bases/{bid}/status",
                                  json={"status": "archived"}, headers=H)
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"
        resp2 = await client.patch(f"/api/kb/bases/{bid}/status",
                                   json={"status": "active"}, headers=H)
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "active"

    async def test_delete_empty_base(self, client):
        create = await _mk_base(client, "del-kb")
        bid = create.json()["id"]
        resp = await client.delete(f"/api/kb/bases/{bid}", headers=H)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# ═══════════════════════════════════════════════════════════
# 知识文档
# ═══════════════════════════════════════════════════════════

class TestKnowledgeDocument:
    async def _base_id(self, client, name="doc-base"):
        return (await _mk_base(client, name)).json()["id"]

    async def test_create_document_success(self, client):
        bid = await self._base_id(client, "doc-ok-base")
        resp = await client.post("/api/kb/documents", json={
            "base_id": bid, "title": "故障排查指南", "content": "# 指南",
            "doc_type": "markdown",
        }, headers=H)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "故障排查指南"
        assert data["status"] == "parsing"

    async def test_create_document_requires_token(self, client):
        bid = await self._base_id(client, "doc-notoken-base")
        resp = await client.post("/api/kb/documents", json={
            "base_id": bid, "title": "x",
        })
        assert resp.status_code in (401, 403)

    async def test_create_document_nonexistent_base(self, client):
        resp = await client.post("/api/kb/documents", json={
            "base_id": "missing", "title": "x",
        }, headers=H)
        assert resp.status_code == 404

    async def test_create_document_duplicate_title(self, client):
        bid = await self._base_id(client, "doc-dup-base")
        body = {"base_id": bid, "title": "重名文档"}
        await client.post("/api/kb/documents", json=body, headers=H)
        resp = await client.post("/api/kb/documents", json=body, headers=H)
        assert resp.status_code == 409

    async def test_list_documents_filter_base(self, client):
        bid = await self._base_id(client, "doc-list-base")
        await client.post("/api/kb/documents", json={"base_id": bid, "title": "列出项"},
                          headers=H)
        resp = await client.get(f"/api/kb/documents?base_id={bid}", headers=H)
        assert resp.status_code == 200
        assert all(d["base_id"] == bid for d in resp.json()["items"])

    async def test_document_parse_state_machine(self, client):
        bid = await self._base_id(client, "doc-sm-base")
        create = await client.post("/api/kb/documents", json={"base_id": bid, "title": "状态机"},
                                   headers=H)
        did = create.json()["id"]
        # parsing -> ready
        resp = await client.patch(f"/api/kb/documents/{did}/status",
                                  json={"status": "ready"}, headers=H)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        # ready -> parsing (重新解析)
        resp2 = await client.patch(f"/api/kb/documents/{did}/status",
                                  json={"status": "parsing"}, headers=H)
        assert resp2.status_code == 200

    async def test_document_invalid_transition(self, client):
        bid = await self._base_id(client, "doc-badsm-base")
        create = await client.post("/api/kb/documents", json={"base_id": bid, "title": "非法"},
                                   headers=H)
        did = create.json()["id"]
        # parsing -> failed 合法；failed -> ready 非法
        await client.patch(f"/api/kb/documents/{did}/status",
                           json={"status": "failed"}, headers=H)
        resp = await client.patch(f"/api/kb/documents/{did}/status",
                                  json={"status": "ready"}, headers=H)
        assert resp.status_code == 409

    async def test_update_document(self, client):
        bid = await self._base_id(client, "doc-upd-base")
        create = await client.post("/api/kb/documents", json={"base_id": bid, "title": "待改"},
                                   headers=H)
        did = create.json()["id"]
        # 先 ready 才允许编辑
        await client.patch(f"/api/kb/documents/{did}/status",
                           json={"status": "ready"}, headers=H)
        resp = await client.patch(f"/api/kb/documents/{did}",
                                  json={"content": "新内容", "chunk_count": 5}, headers=H)
        assert resp.status_code == 200
        assert resp.json()["content"] == "新内容"
        assert resp.json()["chunk_count"] == 5

    async def test_delete_document(self, client):
        bid = await self._base_id(client, "doc-del-base")
        create = await client.post("/api/kb/documents", json={"base_id": bid, "title": "删除项"},
                                   headers=H)
        did = create.json()["id"]
        resp = await client.delete(f"/api/kb/documents/{did}", headers=H)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    async def test_delete_base_blocked_by_doc(self, client):
        bid = await self._base_id(client, "doc-block-base")
        await client.post("/api/kb/documents", json={"base_id": bid, "title": "挡路"},
                           headers=H)
        resp = await client.delete(f"/api/kb/bases/{bid}", headers=H)
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# 问答交互
# ═══════════════════════════════════════════════════════════

class TestQAInteraction:
    async def _base_id(self, client, name="qa-base"):
        return (await _mk_base(client, name)).json()["id"]

    async def test_record_qa_success(self, client):
        bid = await self._base_id(client, "qa-ok-base")
        resp = await client.post("/api/kb/qa", json={
            "base_id": bid, "question": "如何重启服务？", "answer": "执行 systemctl restart",
            "source_doc_ids": ["doc-1"], "asker": "zhangsan", "latency_ms": 120,
        }, headers=H)
        assert resp.status_code == 201
        data = resp.json()
        assert data["question"] == "如何重启服务？"
        assert data["status"] == "answered"
        assert "doc-1" in data["source_doc_ids"]

    async def test_record_qa_requires_token(self, client):
        bid = await self._base_id(client, "qa-notoken-base")
        resp = await client.post("/api/kb/qa", json={"base_id": bid, "question": "x"})
        assert resp.status_code in (401, 403)

    async def test_record_qa_nonexistent_base(self, client):
        resp = await client.post("/api/kb/qa", json={"base_id": "missing", "question": "x"},
                                 headers=H)
        assert resp.status_code == 404

    async def test_record_qa_empty_answer_marked_failed(self, client):
        bid = await self._base_id(client, "qa-fail-base")
        resp = await client.post("/api/kb/qa", json={
            "base_id": bid, "question": "无答案问题", "answer": "",
        }, headers=H)
        assert resp.status_code == 201
        assert resp.json()["status"] == "failed"

    async def test_list_qa_keyword(self, client):
        bid = await self._base_id(client, "qa-list-base")
        await client.post("/api/kb/qa", json={
            "base_id": bid, "question": "关键词检索问题ABC", "answer": "ok",
        }, headers=H)
        resp = await client.get("/api/kb/qa?keyword=关键词", headers=H)
        assert resp.status_code == 200
        questions = [q["question"] for q in resp.json()["items"]]
        assert any("关键词" in q for q in questions)

    async def test_submit_feedback(self, client):
        bid = await self._base_id(client, "qa-fb-base")
        create = await client.post("/api/kb/qa", json={
            "base_id": bid, "question": "反馈问题", "answer": "答案",
        }, headers=H)
        iid = create.json()["id"]
        resp = await client.post(f"/api/kb/qa/{iid}/feedback",
                                 json={"feedback": "up"}, headers=H)
        assert resp.status_code == 200
        assert resp.json()["feedback"] == "up"

    async def test_get_interaction_not_found(self, client):
        resp = await client.get("/api/kb/qa/nope", headers=H)
        assert resp.status_code == 404
