# SM Knowledge Bot

企业内部知识库问答 Bot（FastAPI），提供**文档分块检索、多轮对话、部门与角色权限控制、审计日志**。

## 已实现能力

- SQLite 持久化：用户、文档、知识块、会话、消息和审计日志；
- RAG 基础检索：中文双字 gram 与英文关键词评分，文档自动分块；
- 多轮会话：会话归属校验和完整历史查询；
- RBAC：`employee`、`manager`、`admin`，且检索同时受部门与最低角色限制；
- 管理员可创建用户、查看审计日志；经理/管理员可写入本部门知识；
- Docker 部署配置和 API 自动化测试。

## 本地运行

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

访问 http://127.0.0.1:8000/docs 使用 Swagger 文档。首次启动自动创建管理员 `admin`；本地开发通过请求头 `X-User-Id: admin` 调用管理员接口。

## 快速流程

1. 用 `POST /users` 创建用户（管理员）。
2. 用 `POST /documents` 录入文档（经理/管理员）。
3. 用 `POST /chat` 提问；带上实际用户的 `X-User-Id`。
4. 将返回的 `conversation_id` 传回 `/chat` 保持多轮会话。

```powershell
$admin = @{ 'X-User-Id' = 'admin' }
Invoke-RestMethod http://127.0.0.1:8000/users -Method Post -Headers $admin -ContentType 'application/json' -Body '{"id":"finance-manager","name":"财务经理","role":"manager","department":"finance"}'

Invoke-RestMethod http://127.0.0.1:8000/documents -Method Post -Headers @{ 'X-User-Id' = 'finance-manager' } -ContentType 'application/json' -Body '{"title":"报销制度","content":"员工须于每月十日前提交报销单。","department":"finance"}'

Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -Headers @{ 'X-User-Id' = 'finance-manager' } -ContentType 'application/json' -Body '{"question":"报销单何时提交？"}'
```

## Docker

```powershell
docker compose up --build
```

## 生产接入建议

将 `current_user` 替换为企业 SSO/JWT 验证，并以其中的用户 ID、部门及角色作为唯一可信身份来源；将 SQLite 迁移至 PostgreSQL + pgvector/Qdrant；在 `chat` 中将检索出的来源片段传给企业批准的 LLM，并保留现有权限过滤和审计记录。
