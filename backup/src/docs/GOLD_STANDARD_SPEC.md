# 客户金标准数据规范

## 目的

客户金标准用于验证文献解析、术语检索、数值抽取、表格与图片识别、翻译和模型预测的真实业务准确率。代码覆盖率与合成测试不能替代客户金标准。

## 样本要求

- 由客户提供并确认可用于验收的代表性 PDF、DOCX、XLSX、图片型 PDF 和 ZIP 文献包。
- 样本应覆盖普通正文、扫描页、多级表头、合并单元格、脚注、图例、坐标轴、直接标数图表及同名文献版本。
- 每类版式建议不少于 20 份；总样本量和业务分布由客户在验收前签字确认。
- 训练集、调参集与最终盲测集必须按文献隔离，盲测集在系统定版前不得用于开发调参。

## 标注字段

每条期望结果至少包含：

| 字段 | 说明 |
| --- | --- |
| `document_name` | 原始文献名 |
| `document_sha256` | 原文件 SHA-256，防止样本被替换 |
| `page_or_sheet` | 页码或工作表 |
| `evidence_text` | 原始证据文本或图表标数 |
| `evidence_bbox` | 可用时填写坐标 `[x0,y0,x1,y1]` |
| `field_name` | 目标字段 |
| `expected_value` | 期望标准值 |
| `expected_unit` | 标准单位 |
| `treatment_group` | 处理组 |
| `timepoint` | 时间点 |
| `condition` | 实验条件 |
| `tolerance` | 数值允许误差 |
| `reviewer` | 标注人 |
| `review_status` | `draft/reviewed/approved` |

## 评分规则

- 文档解析完整率：成功解析且证据可定位的文档数 / 总文档数。
- 字段准确率：完全匹配字段数 / 应抽取字段数。
- 数值准确率：单位归一化后落入客户容差的数值数 / 应抽取数值数。
- 关联准确率：处理组、时间点、实验条件三者关联均正确的记录数 / 应关联记录数。
- 表格结构准确率：多级表头、合并关系、脚注与数据单元格均匹配的表格数 / 应验收表格数。
- 图表准确率只评价图内直接印刷数值；趋势线未印刷值不纳入当前版本承诺。
- 翻译质量由客户指定双语审阅人盲评；执行前必须配置有效的 `DEEPSEEK_API_KEY`。
- 指标阈值、样本权重、严重缺陷定义和一票否决项必须由客户在测试前确认，测试后不得追溯修改。

## 评估 JSON 与完整性清单

开发预检工具读取 UTF-8 JSON。`expected.json` 与 `actual.json` 顶层可包含以下数组，
每条记录都必须有唯一字符串 `id`：

- `documents`：actual 记录以 `parsed=true` 且 `evidence_locatable=true` 计为完整。
- `fields`：双方使用 `value`，忽略大小写和连续空白后比较。
- `numbers`：expected 使用 `value`、`unit`、可选绝对 `tolerance` 与
  `relative_tolerance`；允许误差取两种容差中的较大值，单位必须一致。
- `associations`：比较 `treatment_group`、`timepoint` 和 `condition`，三项全对才计分。
- `tables`：严格比较 `headers`、`merged_cells`、`footnotes` 和 `cells` 的 JSON 结构。
- `translations`：expected 使用客户批准的 `reference` 和开发预检 `min_score`，
  actual 使用 `translation`。工具报告标准化文本的相似度；正式翻译质量仍由客户指定的
  双语审阅人盲评。

先使用 `gold_standard_manifest.py create` 为 expected、actual 和原始样本生成清单。
清单包含自身规范化内容的 `manifest_sha256`，以及每个文件的相对路径、大小和 SHA-256。
导入或评分前必须执行 `verify`；文件缺失、路径越界、大小或摘要不匹配均应终止测试。

JSON 与 Markdown 输出必须连同 manifest、工具版本、执行时间、阈值确认单一起归档。
仓库中的合成 fixture 仅验证工具行为，不得作为客户真实准确率、客户 UAT 或正式签字证据。

## 签字确认

| 项目 | 客户填写 |
| --- | --- |
| 样本总数与版本 | 待确认 |
| 盲测集 SHA-256 清单 | 待确认 |
| 指标阈值 | 待确认 |
| 容差规则 | 待确认 |
| 客户负责人 | 待签字 |
| 确认日期 | 待填写 |
