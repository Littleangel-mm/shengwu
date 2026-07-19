# 通用科研文献智能解析与机器学习平台

本仓库包含 React 前端、FastAPI 后端、PostgreSQL 数据库结构、迁移脚本、
自动化测试和验收文档。

后端工程位于 [`backup/src`](backup/src)，运行与部署说明见
[`backup/src/README.md`](backup/src/README.md)。数据库初始结构同时保存在
[`sql/001_initial_schema.sql`](sql/001_initial_schema.sql) 和后端 Alembic 迁移目录中。

客户原始文献、需求材料、环境变量、服务器配置、数据库凭据、运行数据、日志、备份、
本地 OCR 模型及虚拟环境不会提交到仓库。

## Windows 一键启动

在仓库根目录双击 `start.bat`，或在 PowerShell 中执行：

```powershell
.\start.bat
```

脚本会检查主后端和 PaddleOCR 依赖。缺少依赖时会依次尝试豆瓣、清华和阿里云（淘宝）
PyPI 镜像，完成后启动 FastAPI 与后台 Worker。首次运行会生成已被 Git 忽略的本地
`.env` 配置模板，具体配置由后端读取。

仅检查或安装依赖、不启动服务：

```powershell
.\start.bat --check
```

## 前端开发

后端启动后，在另一个终端执行：

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。开发服务器会将 `/api` 请求代理到本地 8000 端口。
