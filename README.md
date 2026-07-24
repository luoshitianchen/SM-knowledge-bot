# SM Knowledge Bot

企业内部知识库问答 Bot（FastAPI），提供**文档分块检索、多轮对话、部门与角色权限控制、审计日志**。

## 已实现能力

- SQLite 持久化：用户、文档、知识块、会话、消息和审计日志；
- GitHub 仓库同步：通过 GitHub API 拉取 README、文档与常见代码文件并建立索引；
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

### 一键启动与浏览器演示

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
.\start.ps1
```

然后打开 http://127.0.0.1:8000/ 。项目启动时会自动写入一份“研发协作规范”演示数据；可在页面中同步 GitHub 仓库并立即提问。

## 快速流程

1. 用 `POST /users` 创建用户（管理员）。
2. 用 `POST /documents` 录入文档（经理/管理员）。
3. 用 `POST /chat` 提问；带上实际用户的 `X-User-Id`。
4. 将返回的 `conversation_id` 传回 `/chat` 保持多轮会话。

## 从 GitHub 导入知识

经理或管理员调用 `POST /documents/import/github` 即可直接拉取 GitHub 仓库内容。系统会读取默认分支（或指定 `branch`）中的 `.md`、`.txt`、`.rst`、`.py`、`.js`、`.ts`、`.json`、`.yml` 等文件；重复同步同一仓库分支会自动替换旧索引。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/documents/import/github -Method Post -Headers @{ 'X-User-Id' = 'admin' } -ContentType 'application/json' -Body '{"repository_url":"https://github.com/luoshitianchen/SM-knowledge-bot","department":"engineering","min_role":"employee"}'
```

私有仓库请在服务端环境变量中设置访问 Token：

```powershell
$env:GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN'
py -3.11 -m uvicorn app.main:app --reload
```

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

## Java（Spring Boot）运行版本

仓库同时提供独立的 Java 21 + Spring Boot 版本，位于 `java` 目录；功能包括 GitHub 导入、RBAC、SQLite 持久化与知识问答 API。

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
git pull origin main
cd .\java
.\start-java.ps1
```

需要 JDK 21 和 Maven。启动后接口地址为 http://127.0.0.1:8080/health；所有接口沿用 Python 版本的地址与 `X-User-Id` 请求头（默认管理员为 `admin`）。例如：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/documents/import/github -Method Post -Headers @{ 'X-User-Id' = 'admin' } -ContentType 'application/json' -Body '{"repository_url":"https://github.com/luoshitianchen/SM-knowledge-bot","department":"engineering"}'
```

## 生产接入建议

将 `current_user` 替换为企业 SSO/JWT 验证，并以其中的用户 ID、部门及角色作为唯一可信身份来源；将 SQLite 迁移至 PostgreSQL + pgvector/Qdrant；在 `chat` 中将检索出的来源片段传给企业批准的 LLM，并保留现有权限过滤和审计记录。
