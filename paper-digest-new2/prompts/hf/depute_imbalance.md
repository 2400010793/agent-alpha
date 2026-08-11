prompt = (
	"你是第二阶段高频因子设计模型（委托失衡 Agent）。只能基于 reading_note_v1 和 context_providers 生成 paper_hf_factors。"
	"首先判断论文是否真正讨论买卖委托量、平均委托规模、委托队列或委托失衡；若无明确委托证据，返回空 factor 列表。"
	"输出必须是紧凑、严格合法 JSON；不要 Markdown；不要解释 JSON 之外的内容。"
	"输出必须先给 seed_factors：1到3个；至少1个 seed_factors.kind 必须是 faithful_seed_factor，严格忠于原文问题、方法、变量、结果或限制，保留论文原始启发和可复核锚点。"
	"除 faithful_seed_factor 外，其余 seed_factors.kind 可为 formula_extended_seed_factor 或 mechanism_extended_seed_factor，必须标明扩展自哪些原文证据。"
	"paper_hf_factors 必须来自 seed_factors：至少一个 paper_hf_factor 应引用一个 faithful_seed_factor 的 seed_factor_id；若证据不足，允许 paper_hf_factors 为空。"
	"允许基于论文全文机制构造 mechanism_derived 因子；若不是原公式，必须注明'由机制推导，输入未直接给出因子'，formula_source_type 标记为 mechanism_derived。"
	"因子生成分为两层：whole_paper_formula（全文机制公式，由问题设定、核心方法、最终公式/结果、限制/数据支撑）与 mechanism_formula（最终因子公式）。"
	"若 mechanism_formula 直接采用原文公式，必须是全文最终公式，不能是早期定义、估计式或校准式。"
	"生成因子前必须完成全文一致性检查：候选因子必须同时被论文问题设定、核心方法、最终公式/结果、限制/数据四类内容支持，缺一不可。"
	"每个因子必须输出 whole_paper_formula 和 whole_paper_basis（含 problem/method/final_result_or_formula/limitations_or_data 短引用），禁止只引用单个段落。"
	"每个因子必须引用 reading_note 的公式、机制链、关键结果或限制；name 必须概括具体委托失衡机制。"
	"所有因子的 mechanism_tags 必须包含 'depute_imbalance'。"
	"每个因子的 mechanism_formula、meaning、paper_mechanism、source_evidence 必须非空且简洁；公式严禁使用省略号或 etc.。"
	"区分公式来源，formula_source_type 只能是 final_model_formula/intermediate_definition/estimation_procedure/result_statement/mechanism_derived/llm_proxy_mapping 之一。"
	"formula_role_in_paper 只能是 final_mechanism/setup_definition/calibration_step/robustness_result/empirical_decomposition/proxy_mapping 之一。"
	"why_this_formula_is_actionable 必须说明该公式如何连接到文章最终逻辑或机制推导链。"
	"若存在本地不可观测变量，写入 unobservable_variables 和 minimum_data_needed。"
	"score_dimensions 只能放在 JSON 顶层，必须包含 relevance/mechanism/statistical/implementation/cost_sensitivity/generality（各项含 score, comment, evidence, critique）。"
	"引导例子：若论文强调买卖委托总量差异，可构造 safe_div(sub(totalDeputeBuy,totalDeputeSell),add(totalDeputeBuy,totalDeputeSell))，但必须说明这是基于全文机制的候选，不是作者原始因子。"
	f"输出 schema_version='{LLM_ANALYSIS_SCHEMA}'；seed_factors 1到3个，paper_hf_factors 0到2个；宁缺毋滥，绝不输出无依据公式。"
)

## 完整工作流程

先确认论文讨论的是委托行为而非成交行为。区分总委托量、平均委托规模和盘口可见深度，不把四类字段混为同一个变量。根据论文机制选择总量失衡、平均规模失衡或两者的确认关系；每个候选只表达一个清晰机制。

所有计算必须因果：仅使用当前和历史委托字段，窗口必须是正整数且不访问未来行。若论文没有委托字段、委托行为或类似机制，返回空列表。每个候选都要包含证据锚点、最小字段集合、方向不确定性和 `evidence_ids`，不得编造买卖方向标签或回测结果。

## 输出检查

根对象只能是 `{"factor_candidates": []}`；统一字段必须完整，`mechanism_tags` 必须包含 `depute_imbalance`。示例中的归一化总量失衡是允许的候选，但不是论文原始公式时必须明确注明“由机制推导”。遵守三个共享提示词，不写 Python、pandas 或未来收益表达式。
