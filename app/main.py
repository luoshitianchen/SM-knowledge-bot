"""SM Knowledge Bot：具备持久化、检索、会话和 RBAC 的企业知识库 API。"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
import httpx
from pydantic import BaseModel, Field

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/knowledge_bot.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
ROLE_LEVEL = {"employee": 1, "manager": 2, "admin": 3}
Role = Literal["employee", "manager", "admin"]

app = FastAPI(title="SM Knowledge Bot", version="1.0.0", description="企业内部知识库问答服务")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def now() -> str:
    return datetime.now(UTC).isoformat()


def initialize_database() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
          department TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, department TEXT NOT NULL,
          min_role TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL, position INTEGER NOT NULL,
          content TEXT NOT NULL, terms TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(id)
        );
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, action TEXT NOT NULL, resource_id TEXT, detail TEXT, created_at TEXT NOT NULL
        );
        """)
        conn.execute("""INSERT OR IGNORE INTO users (id,name,role,department,created_at)
                     VALUES ('admin','系统管理员','admin','all',?)""", (now(),))


@app.on_event("startup")
def startup() -> None:
    initialize_database()


class CurrentUser(BaseModel):
    id: str
    name: str
    role: Role
    department: str


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> CurrentUser:
    if not x_user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请提供 X-User-Id 请求头")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (x_user_id,)).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已被停用")
    return CurrentUser(**dict(row))


User = Annotated[CurrentUser, Depends(current_user)]


def require_admin(user: User) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def audit(conn: sqlite3.Connection, user_id: str, action: str, resource_id: str | None = None, detail: str = "") -> None:
    conn.execute("INSERT INTO audit_logs VALUES (?,?,?,?,?,?)", (str(uuid4()), user_id, action, resource_id, detail, now()))


def normalized_terms(text: str) -> set[str]:
    # 同时保留英文词和中文单字/双字 gram，适合不依赖外部服务的中英文基础检索。
    latin = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    grams = list(chinese) + [chinese[i:i + 2] for i in range(max(0, len(chinese) - 1))]
    return set(latin + grams)


def split_content(content: str, size: int = 500, overlap: int = 80) -> list[str]:
    content = re.sub(r"\s+", " ", content).strip()
    if len(content) <= size:
        return [content]
    parts, start = [], 0
    while start < len(content):
        end = min(start + size, len(content))
        if end < len(content):
            boundary = max(content.rfind("。", start, end), content.rfind("\n", start, end), content.rfind(" ", start, end))
            if boundary > start + size // 2:
                end = boundary + 1
        parts.append(content[start:end].strip())
        start = end - overlap
    return [part for part in parts if part]


class UserInput(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,64}$")
    name: str = Field(min_length=1, max_length=80)
    role: Role = "employee"
    department: str = Field(min_length=1, max_length=80)


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=100_000)
    department: str = Field(default="all", min_length=1, max_length=80)
    min_role: Role = "employee"


class ChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class GitHubImportInput(BaseModel):
    repository_url: str = Field(description="GitHub 仓库地址，例如 https://github.com/org/repository")
    branch: str | None = Field(default=None, max_length=120)
    department: str = Field(default="all", min_length=1, max_length=80)
    min_role: Role = "employee"
    max_files: int = Field(default=50, ge=1, le=200)


def github_repository(repository_url: str) -> tuple[str, str]:
    """解析标准 GitHub HTTPS/SSH 仓库地址。"""
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?", repository_url.strip())
    if not match:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "repository_url 必须是 GitHub 仓库地址")
    return match.group(1), match.group(2)


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SM-Knowledge-Bot"}
    # 私有仓库在服务端设置 GITHUB_TOKEN；Token 不经 API 请求传递或持久化。
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def import_github_repository(payload: GitHubImportInput, user: CurrentUser) -> dict[str, object]:
    owner, repository = github_repository(payload.repository_url)
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    try:
        with httpx.Client(timeout=20, headers=github_headers(), follow_redirects=True) as client:
            repo_response = client.get(api_url)
            repo_response.raise_for_status()
            default_branch = payload.branch or repo_response.json()["default_branch"]
            tree_response = client.get(f"{api_url}/git/trees/{default_branch}?recursive=1")
            tree_response.raise_for_status()
            tree = tree_response.json().get("tree", [])
            paths = [item["path"] for item in tree if item.get("type") == "blob" and item["path"].lower().endswith((".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".json", ".yml", ".yaml"))][:payload.max_files]
            files: list[tuple[str, str]] = []
            for path in paths:
                content_response = client.get(f"https://raw.githubusercontent.com/{owner}/{repository}/{default_branch}/{path}")
                if content_response.is_success and content_response.text.strip():
                    files.append((path, content_response.text[:100_000]))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403, 404}:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub 仓库不可访问；私有仓库请在服务端配置 GITHUB_TOKEN") from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub API 请求失败") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "连接 GitHub 失败") from exc

    source_prefix = f"github:{owner}/{repository}:{default_branch}:"
    inserted_chunks = 0
    with db() as conn:
        # 同一分支再次同步时，先删除旧索引，避免检索重复。
        old_documents = conn.execute("SELECT id FROM documents WHERE title LIKE ?", (source_prefix + "%",)).fetchall()
        for old in old_documents:
            conn.execute("DELETE FROM chunks WHERE document_id=?", (old["id"],))
            conn.execute("DELETE FROM documents WHERE id=?", (old["id"],))
        for path, content in files:
            document_id = str(uuid4())
            title = source_prefix + path
            conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (document_id, title, payload.department, payload.min_role, user.id, now()))
            chunks = split_content(content)
            conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", [(str(uuid4()), document_id, position, chunk, " ".join(sorted(normalized_terms(chunk)))) for position, chunk in enumerate(chunks)])
            inserted_chunks += len(chunks)
        audit(conn, user.id, "github.imported", f"{owner}/{repository}", f"branch={default_branch} files={len(files)} chunks={inserted_chunks}")
    return {"repository": f"{owner}/{repository}", "branch": default_branch, "files": len(files), "chunks": inserted_chunks, "message": "GitHub 仓库已同步到知识库"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserInput, user: User) -> dict[str, str]:
    require_admin(user)
    with db() as conn:
        try:
            conn.execute("INSERT INTO users (id,name,role,department,created_at) VALUES (?,?,?,?,?)", (*payload.model_dump().values(), now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "用户 ID 已存在") from exc
        audit(conn, user.id, "user.created", payload.id)
    return {"id": payload.id, "message": "用户已创建"}


@app.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentInput, user: User) -> dict[str, object]:
    if user.role == "employee":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经理或管理员可录入文档")
    if ROLE_LEVEL[payload.min_role] > ROLE_LEVEL[user.role]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "不可创建高于自身角色的权限文档")
    if user.role != "admin" and payload.department not in {"all", user.department}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅可管理本部门文档")
    document_id = str(uuid4())
    chunks = split_content(payload.content)
    with db() as conn:
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (document_id, payload.title, payload.department, payload.min_role, user.id, now()))
        conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", [(str(uuid4()), document_id, index, part, " ".join(sorted(normalized_terms(part)))) for index, part in enumerate(chunks)])
        audit(conn, user.id, "document.created", document_id, payload.title)
    return {"id": document_id, "chunks": len(chunks), "message": "文档已写入并完成分块索引"}


@app.post("/documents/import/github", status_code=status.HTTP_201_CREATED)
def import_documents_from_github(payload: GitHubImportInput, user: User) -> dict[str, object]:
    if user.role == "employee":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅经理或管理员可同步 GitHub 仓库")
    if ROLE_LEVEL[payload.min_role] > ROLE_LEVEL[user.role]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "不可创建高于自身角色的权限文档")
    if user.role != "admin" and payload.department not in {"all", user.department}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅可同步到本部门知识库")
    return import_github_repository(payload, user)


def retrieve(question: str, user: CurrentUser, limit: int = 4) -> list[dict[str, object]]:
    query = normalized_terms(question)
    with db() as conn:
        rows = conn.execute("""SELECT c.id chunk_id,c.content,d.id document_id,d.title,d.department,d.min_role
                             FROM chunks c JOIN documents d ON c.document_id=d.id
                             WHERE (?='admin' OR d.min_role != 'admin')
                             AND (d.department='all' OR d.department=? OR ?='admin')""", (user.role, user.department, user.role)).fetchall()
    scored = []
    for row in rows:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[row["min_role"]]:
            continue
        document_terms = set(row["content"].lower().split()) | normalized_terms(row["content"])
        overlap = len(query & document_terms)
        if overlap:
            scored.append((overlap / (len(document_terms) ** 0.5), dict(row)))
    return [item for _, item in sorted(scored, key=lambda result: result[0], reverse=True)[:limit]]


@app.post("/chat")
def chat(payload: ChatInput, user: User) -> dict[str, object]:
    conversation_id = payload.conversation_id or str(uuid4())
    sources = retrieve(payload.question, user)
    with db() as conn:
        conversation = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if conversation and conversation["user_id"] != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该会话")
        if not conversation:
            conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (conversation_id, user.id, payload.question[:50], now(), now()))
        history = conn.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 6", (conversation_id,)).fetchall()
        if sources:
            evidence = "\n\n".join(f"[{index + 1}] 《{source['title']}》\n{source['content']}" for index, source in enumerate(sources))
            answer = f"根据当前权限范围内检索到的资料：\n\n{evidence}\n\n以上内容仅基于已检索文档。"
        else:
            answer = "当前权限范围内没有检索到可以支撑该问题的知识库内容。"
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)", (str(uuid4()), conversation_id, "user", payload.question, now()))
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)", (str(uuid4()), conversation_id, "assistant", answer, now()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
        audit(conn, user.id, "chat.answered", conversation_id, f"sources={len(sources)} history={len(history)}")
    return {"conversation_id": conversation_id, "answer": answer, "sources": [{"document_id": s["document_id"], "title": s["title"], "chunk_id": s["chunk_id"]} for s in sources]}


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User) -> dict[str, object]:
    with db() as conn:
        conversation = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conversation:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
        if conversation["user_id"] != user.id and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该会话")
        messages = conn.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,)).fetchall()
    return {"conversation": dict(conversation), "messages": [dict(row) for row in messages]}


@app.get("/audit-logs")
def list_audit_logs(user: User, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, str]]:
    require_admin(user)
    with db() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]
