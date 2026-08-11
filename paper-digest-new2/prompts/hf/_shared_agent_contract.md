## 通用输入上下文

调用方会注入一段原始文本：

{{INPUT_TEXT}}

只使用这段文本作为研究依据；不要要求固定 JSON 字段，不要把文本外信息当作事实。

## 机制与因果边界

只有输入文本支持当前机制时才生成候选。候选只能使用当前或历史观测；rolling、zscore、rank、变化率和 lag 不得读取未来。`ret10s`、`ret30s`、`ret60s`、`ret120s` 及任何 forward return 只能作为评估目标，不能出现在 `fields`、`expression` 或 `prefix_expression`。文本证据不足时返回空列表。

## 因子设计要求

每个候选只表达一个主机制，优先简单、归一化、可解释和可复现的 ASL 表达式。如果表达式是基于文本机制推导而非原文直接给出，必须在 `economic_rationale` 中说明。

## 严格输出协议

只输出严格 JSON，不要 Markdown、代码围栏、Python、pandas 或 numpy。根对象必须是 `{"factor_candidates": []}`。每项必须包含 `factor_id`、`name`、`prefix_expression`、`expression`、`fields`、`windows`、`direction`、`source_signal_id`、`source_reading_note_id`、`mechanism_tags`、`economic_rationale`、`evidence_ids`。`prefix_expression` 只能使用已声明 ASL 算子，候选数量为 0 至 3。

## 输出前检查

检查机制标签、窗口正整数、未来标签泄漏、文本证据、evidence_ids 和方向解释。任意关键检查失败就删除候选。专用提示词中的例子仅用于说明格式和边界，不能直接当作当前文本的证据。
