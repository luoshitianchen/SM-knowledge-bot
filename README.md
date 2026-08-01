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
- SQLite 并发优化：WAL 模式、15 秒繁忙重试、查询索引和 `X-Process-Time-Ms` 请求耗时响应头。

## 本地运行

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

访问 http://127.0.0.1:8000/docs 使用 Swagger 文档。Python 服务通过 ERP 集成认证建立 `HttpOnly` 会话 Cookie；业务接口不接受客户端传入的用户 ID。

## ERP 登录联动

企业部署时在 `.env` 配置 ERP 集成认证端点和共享集成密钥：

```text
ERP_AUTH_URL=https://ERP_HOST/api/integrations/knowledge-bot/auth
ERP_INTEGRATION_KEY=RANDOM_SHARED_INTEGRATION_KEY
```

系统会以 `username` 和 `password` 调用 ERP 受保护集成接口，不保存密码。ERP 返回 `id`、`name`、`department`、`role` 后，知识库签发独立的 `HttpOnly`、`SameSite=Strict` 会话 Cookie。支持的角色为 `employee`、`manager`、`admin`。

### 一键启动与浏览器演示

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
.\start.ps1
```

然后打开 http://127.0.0.1:8000/ 。项目启动时会自动写入一份“研发协作规范”演示数据；可在页面中同步 GitHub 仓库并立即提问。

### Docker 部署

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
Copy-Item .env.example .env
.\deploy.ps1
```

部署完成后访问 http://127.0.0.1:8010/。容器包含健康检查，SQLite 数据保存在本机 `data/` 目录；若端口冲突，可在 `.env` 修改 `APP_PORT`。私有 GitHub 仓库在 `.env` 中设置 `GITHUB_TOKEN` 后再执行部署。

生产部署使用 `KB_ENV=production`。应用会校验 ERP 集成端点和集成密钥，容器以非 root 用户运行，且所有响应附带基础安全响应头与登录速率限制。生产环境应在反向代理层启用 HTTPS、IP 限流、访问日志与集中式监控。

## 网络暴露控制

Docker 默认仅监听 `127.0.0.1:8010`，不直接暴露到公网。应通过企业 VPN、零信任网关或反向代理提供访问，并配置 TLS、IP 白名单和身份认证。生产环境保持 `KB_ENABLE_DOCS=false`，把实际内部域名写入 `KB_ALLOWED_HOSTS`。

仓库提供 [内网 Nginx + mTLS 示例](deploy/nginx/internal.conf.example)：它同样只监听回环地址，并要求企业 CA 签发的客户端证书。替换示例域名和证书路径后，先通过 `nginx -t` 校验，再由企业网络团队将 VPN/零信任入口转发至该监听地址；不要直接开放应用容器端口或 Nginx 监听端口到公网。

## 备份与恢复

执行 `./backup.ps1` 可在 `backup/` 目录生成 SQLite 一致性备份。备份目录不纳入 Git；应将备份转存到加密、受访问控制的企业备份存储，并定期进行恢复演练。

## 快速流程

管理员审计查询支持分页和筛选：`GET /audit-logs?limit=50&offset=0&action=chat.answered&since=2026-01-01T00:00:00Z`。接口只返回管理员可见的审计记录，单页最多 100 条。

1. 用 `POST /users` 创建用户（管理员）。
2. 用 `POST /documents` 录入文档（经理/管理员）。
3. 登录成功后，用 `POST /chat` 提问；浏览器自动携带会话 Cookie。
4. 将返回的 `conversation_id` 传回 `/chat` 保持多轮会话。

## 从 GitHub 导入知识

经理或管理员调用 `POST /documents/import/github` 即可直接拉取 GitHub 仓库内容。系统会读取默认分支（或指定 `branch`）中的 `.md`、`.txt`、`.rst`、`.py`、`.js`、`.ts`、`.json`、`.yml` 等文件；重复同步同一仓库分支会自动替换旧索引。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/documents/import/github -Method Post -WebSession $session -ContentType 'application/json' -Body '{"repository_url":"https://github.com/luoshitianchen/SM-knowledge-bot","department":"engineering","min_role":"employee"}'
```

私有仓库请在服务端环境变量中设置访问 Token：

```powershell
$env:GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN'
py -3.11 -m uvicorn app.main:app --reload
```

同步完成后，在首页“网络知识来源”区域可查看文件/知识块数量、再次同步或删除来源。网络请求使用超时与单文件失败跳过策略；若 GitHub API 返回错误，会在来源状态中记录失败原因。

每次成功同步都会写入来源同步历史（时间、状态、文件数和知识块数），可在控制台点击“同步历史”查看。

```powershell
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod http://127.0.0.1:8000/auth/login -Method Post -WebSession $session -ContentType 'application/json' -Body '{"username":"ERP账号","password":"ERP密码"}'
Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -WebSession $session -ContentType 'application/json' -Body '{"question":"报销单何时提交？"}'
```

## Docker

```powershell
docker compose up --build
```

## Java（Spring Boot）运行版本

`java` 目录保留为历史演示实现，不包含当前 ERP 集成会话与安全加固能力。生产环境必须部署根目录 Python 服务，并通过 `SM-ERP` 的集成认证接口登录。

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
git pull origin main
cd .\java
.\start-java.ps1
```

需要 JDK 21 和 Maven。启动后打开 http://127.0.0.1:8080/ 使用内置 Web 控制台；接口健康检查地址为 http://127.0.0.1:8080/health。所有接口使用 `X-User-Id` 请求头（默认管理员为 `admin`）。例如：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/documents/import/github -Method Post -Headers @{ 'X-User-Id' = 'admin' } -ContentType 'application/json' -Body '{"repository_url":"https://github.com/luoshitianchen/SM-knowledge-bot","department":"engineering"}'
```

Java 服务启动会自动写入并更新 `java/demo/操作指南-模拟知识文件.md`。该模拟文件提供 `npx skills add` 安装全部/单个 Skill 以及 `git clone` 项目拉取示例；启动后可提问“如何安装全部 Skill？”验证知识检索。

运行 Java 测试：

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot\java
mvn test
```

## 生产接入建议

将 `current_user` 替换为企业 SSO/JWT 验证，并以其中的用户 ID、部门及角色作为唯一可信身份来源；将 SQLite 迁移至 PostgreSQL + pgvector/Qdrant；在 `chat` 中将检索出的来源片段传给企业批准的 LLM，并保留现有权限过滤和审计记录。
