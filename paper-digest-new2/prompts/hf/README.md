# new2 高频因子 Agent

这些提示词是 new2 自己的 agent 定义，参考了 `agent_alpha` 的机制划分，但不运行外部 agent。

流程：

`reading_note_v1 -> 融合 AI 分类 -> 选择一个或多个 new2 agent 提示词 -> FactorCandidate JSON`

分类不是单独的 AI 调用。融合 AI 在生成论文观点的同一次调用中完成分类，并根据证据选择 agent。

每个 agent 只能输出高频因子候选，不写 Python。因子必须引用 `source_reading_note_id` 或 evidence anchor，并遵守 30 秒至 30 分钟、只使用当前和历史数据的约束。
