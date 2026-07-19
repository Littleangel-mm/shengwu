# 溯研前端

React + TypeScript + Vite 前端。开发服务器将 `/api` 代理到
`http://127.0.0.1:8000`，无需在浏览器中保存数据库或外部服务凭据。

## 开发

```bash
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。运行前请确保 FastAPI 后端位于 8000 端口。

## 质量检查

```bash
npm run lint
npm test
npm run build
```

生产部署时可通过 `VITE_API_PREFIX` 修改 API 前缀；默认使用 `/api/v1`。
## 功能入口

- 「模型实验」支持冻结数据集选字段、算法对比、解释、预测和候选方案优化。
- 「研究报告」支持组合数据集、模型和优化运行生成 Word，并查看后台日志。
- 「成员权限」支持组织/项目成员邀请和角色维护；viewer 自动进入只读界面。
