# 知识问答机器人服务 上线部署检查清单（DEPLOYMENT_CHECKLIST）

> 服务：`sm-knowledge-bot` ｜ 端口 8023 ｜ 数据库 `sm_knowledge_bot`

## 1. 上线前检查

- [ ] 代码评审已通过（至少 1 名 reviewer approve）
- [ ] 单元/集成测试通过，覆盖率达标
- [ ] Trivy 镜像与依赖扫描无高危漏洞
- [ ] gitleaks 无密钥泄露
- [ ] 性能基准达到 SLO（P99 < 1s）
- [ ] SBOM 已生成并归档（sbom.json）

## 2. 配置检查

- [ ] ConfigMap 环境变量正确（SM_ENV / SM_DATABASE_NAME=sm_knowledge_bot）
- [ ] ExternalSecret 已在 Vault 配置全部密钥
- [ ] 数据库迁移（alembic upgrade）已在目标环境验证
- [ ] Ingress 域名与 TLS 证书就绪

## 3. 部署步骤

1. `helm lint helm/sm-knowledge-bot`
2. `helm upgrade --install sm-knowledge-bot helm/sm-knowledge-bot -n sm-prod -f helm/sm-knowledge-bot/values-prod.yaml`
3. 等待 rollout：`kubectl -n sm-prod rollout status deploy/sm-knowledge-bot`
4. 确认 ArgoCD Application 健康、同步正常
5. 按灰度策略逐步放量

## 4. 验证步骤

- [ ] `/health`、`/readyz` 返回 200
- [ ] 核心接口冒烟通过
- [ ] Prometheus 指标正常上报
- [ ] Loki 可检索到本服务日志
- [ ] 业务方确认功能正常

## 5. 回滚触发条件与步骤

- 触发：错误率 > 1%、P99 严重劣化、核心功能不可用。
- 步骤：见 OPERATIONS.md 第 6 节，`helm rollback`，目标 RTO ≤ 10 分钟。

## 6. SBOM 与供应链策略

- 依赖版本经 requirements.lock 锁定。
- 镜像基于固定基础镜像摘要构建，启用 cosign 签名验证。
- 每次发布产物附 SBOM（SPDX），漏洞变更可追溯。
