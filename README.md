# SM Knowledge Bot

企业内部知识库问答 Bot 的可运行 MVP，包含：

- RAG 检索：按问题检索已录入文档；
- 多轮对话：通过 `conversation_id` 保留会话历史；
- 权限控制：按用户角色与部门过滤检索结果。

## 启动

```powershell
cd C:\Users\Admin\Desktop\github项目\SM-knowledge-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 可直接测试 API。

## 使用示例

先创建一份文档：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/documents -ContentType 'application/json' -Body '{"title":"报销制度","content":"员工报销需在每月 10 日前提交发票。","department":"finance","min_role":"employee"}'
```

再发起提问：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/chat -ContentType 'application/json' -Body '{"question":"报销何时提交？","user_id":"u-001","role":"employee","department":"finance"}'
```

## 后续接入

生产环境建议将内存文档库替换为向量数据库（如 pgvector 或 Qdrant），将 `chat` 中的答案组织逻辑接入 LLM，并通过公司 SSO/JWT 可信地提供用户角色与部门。
