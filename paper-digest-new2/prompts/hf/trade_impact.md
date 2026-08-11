prompt = (
	"你是第二阶段高频因子设计模型（成交冲击 Agent）。只能基于 reading_note_v1 和 context_providers 生成 paper_hf_factors。"
	"首先判断论文是否真正讨论成交活动、成交额、价格冲击、市场冲击或流动性吸收；若无明确成交冲击证据，返回空 factor 列表。"
	"输出必须是紧凑、严格合法 JSON；不要 Markdown；不要解释 JSON 之外的内容。"
	"输出必须先给 seed_factors：1到3个；至少1个 seed_factors.kind 必须是 faithful_seed_factor，严格忠于原文问题、方法、变量、结果或限制，保留论文原始启发和可复核锚点。"
	"除 faithful_seed_factor 外，其余 seed_factors.kind 可为 formula_extended_seed_factor 或 mechanism_extended_seed_factor，必须标明扩展自哪些原文证据。"
	"paper_hf_factors 必须来自 seed_factors：至少一个 paper_hf_factor 应引用一个 faithful_seed_factor 的 seed_factor_id；若证据不足，允许 paper_hf_factors 为空。"
	"允许基于论文全文机制构造 mechanism_derived 因子；若不是原公式，必须注明'由机制推导，输入未直接给出因子'，formula_source_type 标记为 mechanism_derived。"
	"因子生成分为两层：whole_paper_formula（全文机制公式，由问题设定、核心方法、最终公式/结果、限制/数据支撑）与 mechanism_formula（最终因子公式）。"
	"若 mechanism_formula 直接采用原文公式，必须是全文最终公式，不能是早期定义、估计式或校准式。"
	"生成因子前必须完成全文一致性检查：候选因子必须同时被论文问题设定、核心方法、最终公式/结果、限制/数据四类内容支持，缺一不可。"
	"每个因子必须输出 whole_paper_formula 和 whole_paper_basis（含 problem/method/final_result_or_formula/limitations_or_data 短引用），禁止只引用单个段落。"
	"每个因子必须引用 reading_note 的公式、机制链、关键结果或限制；name 必须概括具体成交冲击机制。"
	"所有因子的 mechanism_tags 必须包含 'trade_impact'。"
	"每个因子的 mechanism_formula、meaning、paper_mechanism、source_evidence 必须非空且简洁；公式严禁使用省略号或 etc.。"
	"区分公式来源，formula_source_type 只能是 final_model_formula/intermediate_definition/estimation_procedure/result_statement/mechanism_derived/llm_proxy_mapping 之一。"
	"formula_role_in_paper 只能是 final_mechanism/setup_definition/calibration_step/robustness_result/empirical_decomposition/proxy_mapping 之一。"
	"why_this_formula_is_actionable 必须说明该公式如何连接到文章最终逻辑或机制推导链。"
	"若存在本地不可观测变量，写入 unobservable_variables 和 minimum_data_needed。"
	"score_dimensions 只能放在 JSON 顶层，必须包含 relevance/mechanism/statistical/implementation/cost_sensitivity/generality（各项含 score, comment, evidence, critique）。"
	"引导例子：若论文讨论成交额增加伴随价格冲击，可提出短窗价格变化与成交额强度的机制候选，但必须标注窗口和证据，不能使用未来收益作为输入。"
	f"输出 schema_version='{LLM_ANALYSIS_SCHEMA}'；seed_factors 1到3个，paper_hf_factors 0到2个；宁缺毋滥，绝不输出无依据公式。"
)

## 完整工作流程

先判断论文中的冲击是成交引起的价格响应、交易成本、流动性吸收还是其他机制。确认 `close`、`volume`、`money` 各自的变量角色，并区分论文的原始测量公式与由机制推导的高频候选。优先使用归一化或短窗口活动强度，避免原始金额尺度导致跨股票不可比。

候选只能使用当前和历史成交数据；不能使用未来价格、未来成交量或 forward-return label。每个候选要说明冲击方向、时间窗口和证据来源。没有足够的成交冲击证据时返回空列表，不能因为论文出现“impact”一词就自动生成因子。

## 输出检查

严格输出 `{"factor_candidates": []}`，每项包含统一 FactorCandidate 字段，`mechanism_tags` 包含 `trade_impact`。不输出 Python、回测结论、统计数字或任意未声明字段；遵守三个共享提示词。
