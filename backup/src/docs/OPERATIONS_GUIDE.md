# 运维指南

## 环境与启动

生产环境应使用受支持的 Python、PostgreSQL 和独立 PaddleOCR 环境。配置文件和密钥不得
提交到仓库；必须设置持久且随机的 `APP_SECRET`，并保持 `ALLOW_ACTOR_HEADER=false`。

```powershell
python -m pip install -e ".[dev]"
python -m alembic current
python -m alembic upgrade head
python -m app
python -m app.worker
```

API 与 Worker 应由服务管理器分别托管，设置失败重启、日志轮转和最小权限账户。上线前检查
`GET /api/v1/health` 与 `GET /api/v1/health/ocr`，确认数据库和 OCR 均为 `ready`。

## 迁移

1. 记录当前应用版本、Alembic revision、数据库大小和存储目录。
2. 创建可恢复备份并在隔离环境验证。
3. 阅读待执行 revision；禁止对未检查的已有库直接重放初始建表脚本。
4. 停止写入或进入维护窗口，执行 `python -m alembic upgrade head`。
5. 检查 revision、健康接口、Worker 和一条非破坏性业务流程。
6. 失败时停止写入，按已审批的恢复方案处理，不要临时删除生产表。

## 备份与恢复

```powershell
python scripts/backup.py --output backups/manual
python scripts/restore.py backups/manual
```

- 数据库导出、存储文件、manifest 与校验值应作为同一个恢复点保管。
- 备份目录应加密、限制访问并配置异地副本和保留周期。
- 恢复只能先在独立数据库和存储目录演练；有意覆盖已初始化目标时才使用 `--replace`。
- 每次演练记录时间、恢复点、校验结果、RPO/RTO、执行人和审批人。

## 监控与故障处理

至少监控 API 健康、错误率、延迟、数据库连接、磁盘空间、Worker 心跳、积压任务、失败重试、
OCR 状态、外部翻译限流和备份结果。告警中不得包含访问令牌、数据库密码或文献正文。

故障处理顺序：

1. 记录时间、影响范围、版本和关联任务 ID。
2. 阻止影响扩大；不要直接修改业务表绕过状态机。
3. 检查 API、Worker、数据库、存储、OCR 和外部服务日志。
4. 按已验证 runbook 恢复，随后核对任务状态和证据文件。
5. 记录根因、修复、数据影响和后续行动。

## 验收与金标准工具

```powershell
python -m scripts.gold_standard_manifest verify path\manifest.json
python -m scripts.gold_standard_import --manifest path\manifest.json --expected path\expected.json --actual path\actual.json --output path\bundle.json
python -m scripts.gold_standard_evaluate --expected path\expected.json --actual path\actual.json --json-output path\report.json --markdown-output path\issues.md
```

只有 manifest 与所有输入文件校验通过后才能评估。报告应与输入 manifest 一起归档。合成
fixture 只用于开发预检，正式准确率必须来自客户签字确认的盲测集。

## 发布、回退与权限

- 发布需记录制品 SHA-256、配置差异、迁移版本、检查结果和审批人。
- 回退应用前确认数据库 revision 是否兼容；数据库恢复属于受控灾难恢复操作。
- 定期复核组织管理员、项目所有者和平台管理员，离职账户应及时移除。
- 定期轮换密钥并验证旧密钥失效；不得通过聊天、工单正文或日志传递密钥。
