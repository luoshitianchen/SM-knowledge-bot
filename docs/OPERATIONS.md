# 知识问答机器人服务 运维手册（OPERATIONS）

> 服务：`sm-knowledge-bot` ｜ 端口 8023 ｜ 数据库 `sm_knowledge_bot`

## 1. 服务概述与依赖

基于企业知识库的 RAG 问答服务，检索向量库与文档，向一线与运维提供智能问答与操作指引。

运行依赖：PostgreSQL（sm_knowledge_bot）、Vault（密钥）、Loki（日志）、ArgoCD（发布）、API 网关（鉴权）。对象存储类服务另依赖 S3 后端与 PVC 持久卷。

## 2. SLO 定义

| 指标 | 目标 |
| --- | --- |
| 可用性 | ≥ 99.9%（月度） |
| P99 延迟 | < 1000ms |
| 错误率（5xx） | < 0.1% |

## 3. 错误预算公式与消耗跟踪

- 月度错误预算 = 30 天 × 99.9% 不可用时间 ≈ 43.2 分钟。
- 消耗跟踪：以 Loki/Prometheus 计算月度不可用时长，超过 50% 预算即冻结非必要变更，优先稳定性工作。

## 4. 变更管理流程（CAB）

- 变更须在变更窗口（工作日 10:00–16:00）内执行，P0/P1 紧急变更可走加急通道并事后补审。
- 所有变更需填写变更单，关联工单、回滚方案与验证步骤。

## 5. 发布审批流程（门禁）

dev（自动）→ staging（自动化测试通过）→ prod（CAB/值班负责人审批）。三级环境 values 分离，ArgoCD 按环境 Application 同步。

## 6. 回滚流程

1. `helm rollback sm-knowledge-bot <上一版本>` 或在 ArgoCD 点击 Rollback。
2. 等待 Deployment 滚动完成，检查 readiness。
3. 冒烟 `/health` 与 `/readyz`，验证核心接口。
4. RTO 目标 ≤ 10 分钟。

## 7. 值班与告警响应

- on-call 7×24，告警分级 P0–P3。
- 升级路径：值班工程师 → 值班负责人 → 平台组负责人 → 部门负责人（P0 30 分钟未恢复升级）。

## 8. 日常运维操作手册

- 查日志：`kubectl -n sm-prod logs -l app.kubernetes.io/name=sm-knowledge-bot -f`
- 扩缩容：由 HPA 自动完成，紧急时 `kubectl -n sm-prod scale deploy/sm-knowledge-bot --replicas=N`
- 查配置：`kubectl -n sm-prod get cm,secret -l app.kubernetes.io/name=sm-knowledge-bot`
- 发布：合并 main 后由 ArgoCD 自动同步 prod，或 `helm upgrade sm-knowledge-bot helm/sm-knowledge-bot -f values-prod.yaml`。
