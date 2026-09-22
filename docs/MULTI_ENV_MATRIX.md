# 知识问答机器人服务 多环境差异矩阵（MULTI_ENV_MATRIX）

> 服务：`sm-knowledge-bot` ｜ 端口 8023 ｜ 数据库 `sm_knowledge_bot`

| 维度 | dev | staging | prod |
| --- | --- | --- | --- |
| namespace | sm-dev | sm-staging | sm-prod |
| 副本数 | 1 | 2 | 3 |
| HPA（min/max） | 1 / 3 | 2 / 5 | 3 / 10 |
| requests(cpu/mem) | 50m / 64Mi | 100m / 128Mi | 200m / 256Mi |
| limits(cpu/mem) | 200m / 128Mi | 500m / 256Mi | 1 / 512Mi |
| 数据库 | sm_knowledge_bot（dev 实例） | sm_knowledge_bot（staging 实例） | sm_knowledge_bot（生产主库） |
| 镜像 tag | dev | staging | 语义版本（AppVersion） |
| 日志级别 | debug | info | warn |
| 域名 | sm-knowledge-bot.dev.sm.example.com | sm-knowledge-bot.staging.sm.example.com | sm-knowledge-bot.sm.example.com |
| TLS | 无 | sm-tls | sm-tls |
| 发布方式 | 自动 | 自动+测试门禁 | CAB 审批 |
