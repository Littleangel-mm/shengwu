# 通用科研文献智能解析与机器学习平台

本仓库当前包含 FastAPI 后端、PostgreSQL 数据库结构、迁移脚本、自动化测试和验收文档。

后端工程位于 [`backup/src`](backup/src)，运行与部署说明见
[`backup/src/README.md`](backup/src/README.md)。数据库初始结构同时保存在
[`sql/001_initial_schema.sql`](sql/001_initial_schema.sql) 和后端 Alembic 迁移目录中。

客户原始文献、需求材料、环境变量、服务器配置、数据库凭据、运行数据、日志、备份、
本地 OCR 模型及虚拟环境不会提交到仓库。
