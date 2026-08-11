## 输入

只基于 merge 阶段传入的完整阅读文本。不要要求额外文档，不要把输入之外的信息当作论文事实。

## 语言

除 JSON 字段名、类别 ID、`schema_version`、数值、公式、变量名和证据原文外，所有自然语言内容必须使用简体中文。论文标题可保留原文，并可在中文中括号保留英文术语。

## 任务边界

当前 agent 只负责一个已经选定的十类 idea 角度。先判断输入是否支持该角度；证据不足时输出空的 `article_opinions`，不要补造结论。HF 机制线和本 opinion/idea 线并行，不能混用输出。这里生成的是可供后续研究的想法，不是已经实现或验证的因子。必须区分作者明确主张、输入支持的保守判断、分析者评价、待验证假设和输入未披露。

## 证据规则

每条 idea 必须给出 `supporting_evidence` 和 `evidence_anchor`，尽量引用原文段落、chunk_id、公式、结果或限制，并说明 `idea_category`。不得编造样本量、t 值、Sharpe、IC、回测、交易成本、样本外、容量或统计显著性。

## 严格输出

只输出严格 JSON，不要 Markdown、解释文字、代码或 JSON 之外的内容。根对象必须包含：`schema_version`、`article_opinions`、`supporting_evidence`、`review_anchors`。每条 idea 必须包含：`opinion_id`、`type`（固定为 `idea`）、`idea_category`、`claim`、`assessment`、`supporting_evidence`、`evidence_anchor`、`confidence`、`limitations`。`confidence` 只能是 `high`、`medium`、`low`、`undisclosed`。

## 质量检查

输出前检查：观点是否属于当前角度；作者主张和分析者评价是否分开；证据是否能复查；是否误把相关性说成因果或预测；是否忽略 limitations/not_disclosed。没有充分证据时宁可返回空列表。
