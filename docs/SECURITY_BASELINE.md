# 知识问答机器人服务 安全基线（SECURITY_BASELINE）

> 适用服务：`sm-knowledge-bot`（容器端口 8023，数据库 `sm_knowledge_bot`）
> 版本：v1.0　｜　维护团队：SM 平台组

## 1. 安全基线概述

本服务属于存储治理域微服务，基于企业知识库的 RAG 问答服务，检索向量库与文档，向一线与运维提供智能问答与操作指引。。安全基线以"默认拒绝、最小权限、零信任、可审计"为原则，覆盖镜像构建、运行时、网络、密钥、数据与审计全链路。容器以非 root（UID 1000）运行、只读根文件系统、丢弃全部 Linux capabilities、关闭 ServiceAccount 自动挂载，网络通过 NetworkPolicy 默认拒绝入站。

## 2. 等保 2.0 三级控制映射表

| 控制点 | 实现方式 | 证据 |
| --- | --- | --- |
| 身份鉴别 | 内部 API 密钥 + JWT，经 IAM 统一签发 | ConfigMap/Secret、ExternalSecret 从 Vault 注入 |
| 访问控制 | RBAC 角色-资源-操作矩阵，默认拒绝 | 本文第 5 节、NetworkPolicy |
| 安全审计 | 结构化日志 + Loki 采集，保留 ≥180 天 | deploy/promtail/promtail-config.yaml |
| 入侵防范 | NetworkPolicy 限制东西向流量 | helm templates/networkpolicy.yaml |
| 恶意代码防范 | 镜像 Trivy 扫描、SBOM 锁定 | sbom.json、.trivyignore |
| 数据保密性 | SM4 字段级加密、TLS 终结 | secret.SM_SM4_KEY_HEX、Ingress TLS |
| 数据完整性 | 备份校验和 + 异地副本校验 | DR_RUNBOOK.md |

## 3. ISO 27001 控制映射表（关键控制）

| 控制项 | 实现 |
| --- | --- |
| A.5 访问控制 | 最小权限 ServiceAccount + RBAC |
| A.8 资产管理 | CMDB 登记，配置项可追溯 |
| A.10 加密 | SM4 字段加密、传输 TLS、密钥托管 Vault |
| A.12 运营安全 | 变更窗口、发布门禁、日志审计 |
| A.13 通信安全 | NetworkPolicy 微分段 |
| A.16 事件管理 | INCIDENT_RESPONSE.md + on-call 升级 |
| A.17 业务连续性 | DR_RUNBOOK.md 备份恢复与容灾切换 |
| A.18 合规 | 等保三级自评估、SBOM 供应链合规 |

## 4. 数据分类分级表

| 级别 | 示例字段 | 处理要求 |
| --- | --- | --- |
| 公开 | 服务元信息、文档链接 | 明文可查 |
| 内部 | 配置项、拓扑、发布记录 | 仅内网访问 |
| 机密 | 业务数据、主数据记录 | SM4 加密存储、审计访问 |
| 绝密 | 数据库连接串、API 密钥、SM4 密钥 | 仅 Vault，禁止入库/日志 |

## 5. RBAC 权限矩阵

| 角色 | 资源 | 操作 | 权限 |
| --- | --- | --- | --- |
| 匿名用户 | 全部 | 全部 | 拒绝 |
| 内部服务 | /api/v1/* | 读 | 允许（经 API 网关鉴权） |
| 业务运维 | /api/v1/* | 读 | 允许 |
| 值班 SRE | /api/v1/* | 读写 | 允许（变更窗口内） |
| 管理员 | 全部 | 读写/审批 | 允许（双人复核） |

## 6. 认证与授权机制

- 入站流量先经 API 网关校验 JWT，网关注入内部身份头后转发至本服务。
- 服务间调用使用 `SM_INTERNAL_API_KEY`（Vault 注入）双向校验。
- 所有授权决策基于上述 RBAC 矩阵，默认拒绝未显式放行的操作。

## 7. 审计日志要求

- 日志为 JSON 结构化，含 `level/msg/timestamp/trace_id`。
- 所有写操作与敏感读操作必须记录操作者、目标资源、结果。
- 日志由 promtail 采集至 Loki，保留 ≥180 天，禁止记录明文密钥/密码。

## 8. 漏洞管理流程

1. 每次提交触发 Trivy 镜像与依赖扫描、gitleaks 密钥扫描。
2. 高危（CVSS ≥7.0）漏洞 7 天内修复，中危 30 天，低危排期。
3. SBOM（sbom.json）随发布物归档，依赖版本锁定（requirements.lock）。
4. 外部披露漏洞按 INCIDENT_RESPONSE.md 启动应急响应。
