"""SM Knowledge Bot：具备持久化、检索、会话和 RBAC 的企业知识库 API。"""
from __future__ import annotations

import os
import re
import sqlite3
import secrets
import hashlib
import json
import logging
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
import httpx
from pydantic import BaseModel, Field

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/knowledge_bot.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
ROLE_LEVEL = {"employee": 1, "manager": 2, "admin": 3}
Role = Literal["employee", "manager", "admin"]
SESSION_COOKIE = "sm_kb_session"
SESSION_TTL_SECONDS = int(os.getenv("KB_SESSION_TTL_SECONDS", "28800"))
LOGIN_RATE_WINDOW_SECONDS = int(os.getenv("KB_LOGIN_RATE_WINDOW_SECONDS", "60"))
LOGIN_RATE_MAX_REQUESTS = int(os.getenv("KB_LOGIN_RATE_MAX_REQUESTS", "20"))
login_rate_window: dict[str, tuple[int, int]] = {}
request_id_context: ContextVar[str] = ContextVar("request_id", default="system")

docs_enabled = os.getenv("KB_ENABLE_DOCS", "false").lower() == "true"
app = FastAPI(title="SM Knowledge Bot", version="1.2.0", description="企业内部知识库问答服务", docs_url="/docs" if docs_enabled else None, redoc_url=None, openapi_url="/openapi.json" if docs_enabled else None)
allowed_hosts = [host.strip() for host in os.getenv("KB_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("sm_knowledge_bot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def db():
    # WAL 允许读取与写入并行，busy_timeout 避免并发短暂写锁直接导致请求失败。
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
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
        CREATE TABLE IF NOT EXISTS knowledge_sources (
          id TEXT PRIMARY KEY, source_type TEXT NOT NULL, repository TEXT NOT NULL UNIQUE,
          branch TEXT NOT NULL, department TEXT NOT NULL, min_role TEXT NOT NULL,
          created_by TEXT NOT NULL, last_synced_at TEXT, last_file_count INTEGER NOT NULL DEFAULT 0,
          last_chunk_count INTEGER NOT NULL DEFAULT 0, last_status TEXT NOT NULL DEFAULT 'pending', last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS source_sync_runs (
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, file_count INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0, error TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
          department TEXT NOT NULL, max_role TEXT NOT NULL, system_prompt TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_active ON users(id, active);
        CREATE INDEX IF NOT EXISTS idx_documents_visibility ON documents(department, min_role);
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source_runs_source_started ON source_sync_runs(source_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agents_active_department ON agents(active, department);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(auth_sessions)").fetchall()}
        if "csrf_hash" not in columns:
            conn.execute("ALTER TABLE auth_sessions ADD COLUMN csrf_hash TEXT")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("""INSERT OR IGNORE INTO users (id,name,role,department,created_at)
                     VALUES ('admin','系统管理员','admin','all',?)""", (now(),))
        conn.execute("""INSERT OR IGNORE INTO agents VALUES
                     ('agent-general','知识助手','面向全员的企业知识问答助手','all','employee','请基于授权知识库内容回答，内容不足时明确说明。',1,'admin',?),
                     ('agent-engineering','研发助手','聚焦研发规范、代码协作和技术资料','engineering','manager','请优先引用研发资料，以清晰的步骤形式回答。',1,'admin',?)""", (now(), now()))


def seed_demo_data() -> None:
    """创建仅用于本地体验的示例用户和文档，可重复执行。"""
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (id,name,role,department,created_at) VALUES ('demo-manager','演示平台主管','manager','engineering',?)", (now(),))
        exists = conn.execute("SELECT 1 FROM documents WHERE title='示例：研发协作规范'").fetchone()
        if exists:
            return
        document_id = str(uuid4())
        content = "研发团队的代码评审需要至少一位同事批准。重要变更需附带测试结果，并在合并前更新变更说明。"
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (document_id, '示例：研发协作规范', 'engineering', 'employee', 'admin', now()))
        conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (str(uuid4()), document_id, 0, content, " ".join(sorted(normalized_terms(content)))))


@app.on_event("startup")
def startup() -> None:
    if os.getenv("KB_ENV", "development") == "production":
        if not os.getenv("ERP_AUTH_URL") or not os.getenv("ERP_INTEGRATION_KEY") or os.getenv("ERP_INTEGRATION_KEY", "").startswith("REPLACE_"):
            raise RuntimeError("生产环境必须配置 ERP_AUTH_URL 和 ERP_INTEGRATION_KEY")
        if any(host in {"*", "0.0.0.0"} for host in allowed_hosts):
            raise RuntimeError("生产环境 KB_ALLOWED_HOSTS 不可包含通配主机")
    initialize_database()
    if os.getenv("SEED_DEMO_DATA", "true").lower() == "true":
        seed_demo_data()


@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    """为控制台和监控提供轻量级请求耗时指标。"""
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    request.state.request_id = request_id
    context_token = request_id_context.set(request_id)
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.url.path != "/auth/login":
        token, csrf_token = request.cookies.get(SESSION_COOKIE), request.headers.get("X-CSRF-Token")
        if not token or not csrf_token:
            request_id_context.reset(context_token)
            return Response(status_code=status.HTTP_403_FORBIDDEN, content="CSRF validation failed", headers={"X-Request-Id": request_id})
        with db() as conn:
            row = conn.execute("SELECT csrf_hash,expires_at FROM auth_sessions WHERE token_hash=?", (session_hash(token),)).fetchone()
        if not row or row["expires_at"] <= timestamp() or not secrets.compare_digest(row["csrf_hash"] or "", session_hash(csrf_token)):
            request_id_context.reset(context_token)
            return Response(status_code=status.HTTP_403_FORBIDDEN, content="CSRF validation failed", headers={"X-Request-Id": request_id})
    started = datetime.now(UTC)
    response = await call_next(request)
    request_id_context.reset(context_token)
    elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    response.headers["X-Request-Id"] = request_id
    logger.info(json.dumps({"request_id": request_id, "method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round(elapsed_ms, 2)}, ensure_ascii=False))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'self'; frame-ancestors 'none'"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/", "/auth/", "/sources", "/agents", "/chat")) else "no-cache"
    if os.getenv("KB_ENV", "development") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class CurrentUser(BaseModel):
    id: str
    name: str
    role: Role
    department: str


def timestamp() -> int:
    return int(datetime.now(UTC).timestamp())


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> CurrentUser:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录会话已失效")
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at<?", (timestamp(),))
        row = conn.execute("""SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id
                            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (session_hash(session_token), timestamp())).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已被停用")
    return CurrentUser(**dict(row))


User = Annotated[CurrentUser, Depends(current_user)]


def require_admin(user: User) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def audit(conn: sqlite3.Connection, user_id: str, action: str, resource_id: str | None = None, detail: str = "") -> None:
    enriched = f"request_id={request_id_context.get()} {detail}".strip()
    conn.execute("INSERT INTO audit_logs VALUES (?,?,?,?,?,?)", (str(uuid4()), user_id, action, resource_id, enriched, now()))


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


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=100_000)
    department: str = Field(default="all", min_length=1, max_length=80)
    min_role: Role = "employee"


class ChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    agent_id: str | None = None


class AgentInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=240)
    department: str = Field(default="all", min_length=1, max_length=80)
    max_role: Role = "employee"
    system_prompt: str = Field(min_length=2, max_length=1000)


class GitHubImportInput(BaseModel):
    repository_url: str = Field(description="GitHub 仓库地址，例如 https://github.com/org/repository")
    branch: str | None = Field(default=None, max_length=120)
    department: str = Field(default="all", min_length=1, max_length=80)
    min_role: Role = "employee"
    max_files: int = Field(default=50, ge=1, le=200)


class SourceSyncInput(BaseModel):
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
    source_key = f"github.com/{owner}/{repository}"
    sync_started = now()
    try:
        with httpx.Client(timeout=httpx.Timeout(10, connect=5), headers=github_headers(), follow_redirects=True) as client:
            repo_response = client.get(api_url)
            repo_response.raise_for_status()
            default_branch = payload.branch or repo_response.json()["default_branch"]
            tree_response = client.get(f"{api_url}/git/trees/{default_branch}?recursive=1")
            tree_response.raise_for_status()
            tree = tree_response.json().get("tree", [])
            paths = [item["path"] for item in tree if item.get("type") == "blob" and item["path"].lower().endswith((".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".json", ".yml", ".yaml"))][:payload.max_files]
            files: list[tuple[str, str]] = []
            for path in paths:
                try:
                    content_response = client.get(f"https://raw.githubusercontent.com/{owner}/{repository}/{default_branch}/{path}")
                    if content_response.is_success and content_response.text.strip():
                        files.append((path, content_response.text[:100_000]))
                except httpx.HTTPError:
                    # 单一文件失败不应阻断整个仓库的索引过程。
                    continue
    except httpx.HTTPStatusError as exc:
        with db() as conn:
            conn.execute("""UPDATE knowledge_sources SET last_synced_at=?,last_status='failed',last_error=? WHERE repository=?""", (now(), f"GitHub HTTP {exc.response.status_code}", source_key))
        if exc.response.status_code in {401, 403, 404}:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub 仓库不可访问；私有仓库请在服务端配置 GITHUB_TOKEN") from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "GitHub API 请求失败") from exc
    except httpx.HTTPError as exc:
        with db() as conn:
            conn.execute("""UPDATE knowledge_sources SET last_synced_at=?,last_status='failed',last_error='network error' WHERE repository=?""", (now(), source_key))
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
        source = conn.execute("SELECT id FROM knowledge_sources WHERE repository=?", (source_key,)).fetchone()
        source_id = source["id"] if source else str(uuid4())
        if source:
            conn.execute("""UPDATE knowledge_sources SET branch=?,department=?,min_role=?,last_synced_at=?,last_file_count=?,last_chunk_count=?,last_status='success',last_error=NULL WHERE id=?""", (default_branch, payload.department, payload.min_role, now(), len(files), inserted_chunks, source_id))
        else:
            conn.execute("""INSERT INTO knowledge_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (source_id, "github", source_key, default_branch, payload.department, payload.min_role, user.id, now(), len(files), inserted_chunks, "success", None))
        conn.execute("INSERT INTO source_sync_runs VALUES (?,?,?,?,?,?,?,?)", (str(uuid4()), source_id, sync_started, now(), "success", len(files), inserted_chunks, None))
        audit(conn, user.id, "github.imported", source_id, f"repository={source_key} branch={default_branch} files={len(files)} chunks={inserted_chunks}")
    return {"source_id": source_id, "repository": f"{owner}/{repository}", "branch": default_branch, "files": len(files), "chunks": inserted_chunks, "message": "GitHub 仓库已同步到知识库"}


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "数据库不可用") from exc
    return {"status": "ok", "version": app.version, "database": "ok"}


@app.get("/readyz")
def ready() -> dict[str, str]:
    """编排平台就绪探针：确认数据库与 ERP 集成配置有效。"""
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    if os.getenv("KB_ENV", "development") == "production" and (not os.getenv("ERP_AUTH_URL") or not os.getenv("ERP_INTEGRATION_KEY")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ERP 集成配置不可用")
    return {"status": "ready"}


@app.post("/auth/login")
def login(payload: LoginInput, response: Response, request: Request) -> dict[str, object]:
    """经 ERP 集成接口认证后签发本项目专用 HttpOnly 会话。"""
    erp_url = os.getenv("ERP_AUTH_URL")
    integration_key = os.getenv("ERP_INTEGRATION_KEY")
    if not erp_url or not integration_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ERP 集成认证尚未配置")
    client_ip = request.client.host if request.client else "unknown"
    window_started, count = login_rate_window.get(client_ip, (timestamp(), 0))
    if timestamp() - window_started >= LOGIN_RATE_WINDOW_SECONDS:
        window_started, count = timestamp(), 0
    if count >= LOGIN_RATE_MAX_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "登录请求过于频繁，请稍后重试")
    login_rate_window[client_ip] = (window_started, count + 1)
    try:
        erp_response = httpx.post(
            erp_url,
            headers={"Accept": "application/json", "X-Integration-Key": integration_key},
            json={"username": payload.username, "password": payload.password},
            timeout=httpx.Timeout(10, connect=5),
            verify=os.getenv("ERP_VERIFY_TLS", "true").lower() == "true",
        )
        erp_response.raise_for_status()
        profile = erp_response.json()
        user_id, name = str(profile["id"]), str(profile["name"])
        department, role = str(profile["department"]), str(profile["role"]).lower()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ERP 账号或密码错误") from exc
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ERP 身份服务暂时不可用") from exc
    if role not in ROLE_LEVEL:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ERP 返回了不受支持的角色")
    token, csrf_token = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("""INSERT INTO users (id,name,role,department,active,created_at) VALUES (?,?,?,?,1,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,department=excluded.department,active=1""", (user_id, name, role, department, now()))
        conn.execute("INSERT INTO auth_sessions (token_hash,user_id,expires_at,created_at,csrf_hash) VALUES (?,?,?,?,?)", (session_hash(token), user_id, timestamp() + SESSION_TTL_SECONDS, now(), session_hash(csrf_token)))
        audit(conn, user_id, "erp.login", detail=f"department={department} role={role}")
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, httponly=True, secure=os.getenv("KB_ENV", "development") == "production", samesite="strict", path="/")
    return {"message": "登录成功", "user": CurrentUser(id=user_id, name=name, role=role, department=department).model_dump(), "csrf_token": csrf_token}


@app.post("/auth/logout")
def logout(response: Response, session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, str]:
    if session_token:
        with db() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (session_hash(session_token),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"message": "已退出登录"}


@app.get("/api/summary")
def summary(user: User) -> dict[str, object]:
    with db() as conn:
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conversation_count = conn.execute("SELECT COUNT(*) FROM conversations WHERE user_id=?", (user.id,)).fetchone()[0]
        agent_count = conn.execute("SELECT COUNT(*) FROM agents WHERE active=1").fetchone()[0]
    return {
        "user": user.model_dump(),
        "documents": document_count,
        "chunks": chunk_count,
        "conversations": conversation_count,
        "agents": agent_count,
    }


@app.get("/", include_in_schema=False)
def web_console() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


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


@app.get("/agents")
def list_agents(user: User) -> list[dict[str, object]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM agents WHERE active=1 ORDER BY created_at").fetchall()
    return [dict(row) for row in rows if (row["department"] in {"all", user.department} or user.role == "admin") and ROLE_LEVEL[user.role] >= ROLE_LEVEL[row["max_role"]]]


@app.post("/agents", status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentInput, user: User) -> dict[str, str]:
    require_admin(user)
    agent_id = str(uuid4())
    with db() as conn:
        conn.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)", (agent_id, payload.name, payload.description, payload.department, payload.max_role, payload.system_prompt, 1, user.id, now()))
        audit(conn, user.id, "agent.created", agent_id, payload.name)
    return {"id": agent_id, "message": "AI Agent 已创建"}


@app.delete("/agents/{agent_id}")
def archive_agent(agent_id: str, user: User) -> dict[str, str]:
    require_admin(user)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "AI Agent 不存在")
        conn.execute("UPDATE agents SET active=0 WHERE id=?", (agent_id,))
        audit(conn, user.id, "agent.archived", agent_id)
    return {"message": "AI Agent 已停用"}


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


@app.get("/sources")
def list_sources(user: User) -> list[dict[str, object]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM knowledge_sources ORDER BY last_synced_at DESC").fetchall()
    sources = []
    for row in rows:
        source = dict(row)
        if user.role == "admin" or source["department"] in {"all", user.department}:
            sources.append(source)
    return sources


@app.post("/sources/{source_id}/sync")
def sync_source(source_id: str, payload: SourceSyncInput, user: User) -> dict[str, object]:
    with db() as conn:
        row = conn.execute("SELECT * FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识来源不存在")
    source = dict(row)
    if user.role == "employee" or (user.role != "admin" and source["department"] not in {"all", user.department}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权同步该知识来源")
    repository_url = "https://" + source["repository"]
    return import_github_repository(GitHubImportInput(repository_url=repository_url, branch=source["branch"], department=source["department"], min_role=source["min_role"], max_files=payload.max_files), user)


@app.get("/sources/{source_id}/runs")
def list_source_runs(source_id: str, user: User, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, object]]:
    with db() as conn:
        source = conn.execute("SELECT department FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
        if not source:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识来源不存在")
        if user.role != "admin" and source["department"] not in {"all", user.department}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看该知识来源")
        rows = conn.execute("SELECT * FROM source_sync_runs WHERE source_id=? ORDER BY started_at DESC LIMIT ?", (source_id, limit)).fetchall()
    return [dict(row) for row in rows]


@app.delete("/sources/{source_id}")
def delete_source(source_id: str, user: User) -> dict[str, str]:
    with db() as conn:
        source = conn.execute("SELECT * FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
        if not source:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识来源不存在")
        if user.role != "admin" and source["department"] not in {"all", user.department}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权删除该知识来源")
        prefix = f"github:{source['repository'].removeprefix('github.com/')}:{source['branch']}:"
        documents = conn.execute("SELECT id FROM documents WHERE title LIKE ?", (prefix + "%",)).fetchall()
        for document in documents:
            conn.execute("DELETE FROM chunks WHERE document_id=?", (document["id"],))
            conn.execute("DELETE FROM documents WHERE id=?", (document["id"],))
        conn.execute("DELETE FROM knowledge_sources WHERE id=?", (source_id,))
        audit(conn, user.id, "source.deleted", source_id, source["repository"])
    return {"message": "知识来源及其索引已删除"}


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
    agent = None
    effective_user = user
    if payload.agent_id:
        with db() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id=? AND active=1", (payload.agent_id,)).fetchone()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "AI Agent 不存在或已停用")
        agent = dict(row)
        if agent["department"] not in {"all", user.department} and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权使用该 AI Agent")
        # Agent 仅可收缩权限：调用用户权限与 Agent 上限取较低值。
        effective_role = min(ROLE_LEVEL[user.role], ROLE_LEVEL[agent["max_role"]])
        effective_department = user.department if agent["department"] == "all" else agent["department"]
        effective_user = CurrentUser(id=user.id, name=user.name, role=next(role for role, level in ROLE_LEVEL.items() if level == effective_role), department=effective_department)
    sources = retrieve(payload.question, effective_user)
    with db() as conn:
        conversation = conn.execute("SELECT user_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if conversation and conversation["user_id"] != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该会话")
        if not conversation:
            conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (conversation_id, user.id, payload.question[:50], now(), now()))
        history = conn.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 6", (conversation_id,)).fetchall()
        if sources:
            evidence = "\n\n".join(f"[{index + 1}] 《{source['title']}》\n{source['content']}" for index, source in enumerate(sources))
            prefix = f"{agent['name']}：\n" if agent else ""
            answer = f"{prefix}根据当前权限范围内检索到的资料：\n\n{evidence}\n\n以上内容仅基于已检索文档。"
        else:
            answer = "当前权限范围内没有检索到可以支撑该问题的知识库内容。"
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)", (str(uuid4()), conversation_id, "user", payload.question, now()))
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)", (str(uuid4()), conversation_id, "assistant", answer, now()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
        audit(conn, user.id, "chat.answered", conversation_id, f"agent={agent['id'] if agent else 'default'} sources={len(sources)} history={len(history)}")
    return {"conversation_id": conversation_id, "agent": {"id": agent["id"], "name": agent["name"]} if agent else None, "answer": answer, "sources": [{"document_id": s["document_id"], "title": s["title"], "chunk_id": s["chunk_id"]} for s in sources]}


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
