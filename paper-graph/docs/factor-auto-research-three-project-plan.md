# Paper Graph × Paper Digest New2 × Agent Alpha：因子 Auto-Research 整体计划

状态：设计基线（implementation blueprint）  
最后核对：2026-08-11  
适用工作区：`quant-research-loop.code-workspace`

研究资产范围：市场机制、经验效应、计算特征、机器学习/建模方法、标签与评价协议，以及最终因子；允许相互隔离的 A 股日内高频与日频横截面研究轨道，不把“论文”默认等同于“因子论文”。

## 1. 结论和核心设计判断

三个项目共同建设的不是通用“AI Scientist”，也不是从论文标题直接生成公式的因子工厂，而是一套可审计、可证伪、可恢复的量化因子研究系统：

```text
Paper Graph 发现研究机会和证据关系
    -> Paper Digest New2 获取全文并提取可信机制证据
    -> Agent Alpha 判断数据可实现性
    -> 建立可证伪 FactorHypothesis
    -> 生成受约束的因子族
    -> 预注册、分阶段回测、稳健性和否证
    -> 保存正结果、负结果、谱系和验证过的记忆
    -> 将结果反馈给 Paper Graph 和 Digest
```

核心调度单位应从笼统的 `GraphResearchRun` 进一步收敛为：

> **一个带 Paper Graph/Digest 证据上下文、目标市场数据契约和固定实验预算的 `FactorResearchRun`。**

Graph 是研究机会和关系上下文，不是因子公式的权威来源。单篇论文也可以启动 `FactorResearchRun`；当 graph 证据成熟后，再用局部 graph 提供支持、冲突、复现和跨论文组合。

`FactorResearchRun` 的直接研究产物不必总是 FactorCandidate。它可以先产出市场机制、计算特征、状态估计量、模型方法、标签定义或评价协议；其中通过验证的新特征再进入相关因子的嵌套增量实验。学术论文直接给出可交易因子的情况应视为少数，而不是默认。

本计划回答三个关键问题：

1. **Graph 发现的因子思想是否新颖？**可能更有机会新颖，但不能因为来自 graph 就宣称新颖。新颖性必须拆成结构、机制、公式、经验增量和全球既有研究等层级分别验证。
2. **因子变异是不是 Auto-Research 的一部分？**是，但只有受证据、预算、预注册和数据隔离约束的科学变异才是 Auto-Research；编译修复只是工程 retry，改变机制则必须创建新 hypothesis。
3. **记忆如何保存？**以不可变事件和实验 artifact 为事实源，分为 run-local、project-scoped 和 verified-global 三层；未经独立复验的单次结果不得晋升成全局经验。

## 2. 目标、非目标和成功定义

### 2.1 目标

- 从真实论文证据中提取可以用本地市场数据检验的经济/微观结构机制；
- 系统生成少量有对照组、可证伪的因子候选，而不是无限公式枚举；
- 用时间隔离、跨股票聚合、成本、稳健性和多重检验控制评价因子；
- 将每个指标回链到论文、evidence、hypothesis、因子定义、数据版本和实验配置；
- 保存失败和否证，避免不同 graph、不同 agent 重复走同一条失败路线；
- 将实验反馈用于下一轮论文检索、证据补全和因子研究优先级。

### 2.2 非目标

- 不让 Paper Graph 直接生成可执行因子；
- 不让 Digest 执行生产回测或维护 Alpha Library；
- 不让 Agent Alpha 重复生产爬虫和全文解析；
- 不以 LLM 新颖性评分代替文献检索、定义去重和经验增量验证；
- 不追求一次运行自动产生“可部署 Alpha”；
- 不允许根据锁定测试集继续 mutation；
- 不将单个股票、单个日期或单个 graph 的结果写成全局定律；
- 不以单一绝对 RankIC 作为全部搜索目标。

### 2.3 成功定义

一条研究链只有同时满足以下条件才算闭环：

1. 论文身份和 graph snapshot 可复现；
2. 使用的每个事实有稳定 evidence ID 和源位置；
3. 论文变量到本地字段的映射有保真度说明；
4. hypothesis 明确可被什么结果否证；
5. 实验在看指标前完成预注册；
6. 指标按预注册规则跨股票、日期和分段聚合；
7. mutation 没有看到锁定测试集；
8. 最终结论通过稳健性、成本、消融和重复性门控；
9. 正负结果、失败、预算和 lineage 全部保存；
10. 结果能反馈上游，并可由另一个进程从 artifact 独立重放。

## 3. 当前事实基线与必须修复的问题

### 3.1 Paper Graph 当前状态

- Paper Graph 已具备 canonical identity、OpenAlex 召回/审核、citation/similarity graph 和 graph/Digest seed 选择能力；
- 当前 OpenAlex Gate 2 仍是代表样本审核，不是完整生产语料；
- 当前关系的可靠核心是 `CITES`、bibliographic coupling 和 co-citation；
- `SUPPORTS`、`CONTRADICTS`、`REPLICATES` 等只能在 Digest 提供双方 claim-level evidence 后成立；
- 当前 Gate 2 AI 复核报告可用于小型候选排序，不能充当人工 Gate 验收或全球 prior-art 完整性证明。

因此第一版 Factor Auto-Research 应允许“单篇主证据 + graph 邻域作为检索先验”，不能强制每次都从成熟 claim graph 开始。

### 3.2 Paper Digest New2 当前状态

- 已具备 TeX/PDF/HTML 解析、section-aware evidence、公式、变量、方法、数据、结果、限制和成本/OOS evidence marker；
- 已有 `ResearchArtifactEnvelopeV1` exporter，但尚未接入生产主链；
- 正式 three-AI pipeline 已停止本地 HF factor generation，转向 article opinion，这是正确的职责收敛；
- 旧 `proxy_registry.yaml` 中 `direct | derived | weak_proxy | future_pipeline | unsupported` 的本体和保真度信息仍有价值；
- 当前 evidence 中部分引用只有 chunk/文本锚点，需要补文档版本、内容哈希和更稳定的源位置。

### 3.3 Agent Alpha 当前状态

可保留的成熟能力：

- reading gate、`AlphaSignal`、`FactorCandidate`；
- 字段/算子白名单和 ASL prefix expression；
- deterministic renderer、`py_compile` 和 fac-eval adapter；
- implementation/statistical/risk/economic evaluator；
- candidate pool、mutation、crossover、lineage；
- evaluation/feedback/function/transfer/specialist memory；
- factor definition/instance identity、alpha library 和 run manifest；
- 已实现的 graph research 领域模型、资格 gate、状态机、预算、事件链、checkpoint、preregistration、attempt/review ports。

当前 graph research control plane 仍是独立内核，尚未与 Digest 生产 artifact、真实 Slurm fac-eval 和因子专用统计门控完整接通。

### 3.4 日频数据的当前事实基线

日频因子研究已被纳入正式范围，但不能把日频和日内实验混进同一个 run。按当前决定，日频轨道**只允许读取** `/home/gaozh/ret.parquet`，此前盘点的 `universe.parq`、日频 OHLCV、公告、波动率和日频特征切片均不进入日频 Auto-Research 的数据依赖。

`ret.parquet` 的已核验契约：

| 属性 | 值 |
|---|---|
| artifact role | `daily-wide-store` / `base` |
| field | `ret` |
| 布局 | 宽表；行索引为 `datetime`，每个股票 ticker 为一列 |
| 日期 | 2010-01-04 至 2026-08-03，共 4,026 个不重复交易日 |
| 股票列 | 5,470，所有列至少有一个非空值 |
| 有效单元 | 14,256,274，整体覆盖率约 64.74% |
| 每日覆盖 | 最少 1,670、median 3,503.5、最多 5,208 只股票 |
| content fingerprint | `sha256:2b3eedfadbaee7230478878c7e006a52e074b3c9279a0547433f219b5008e8e2` |

哈希校正记录：2026-08-11 由执行器对物理文件重新运行 SHA-256，确认当前 123,452,994-byte 文件的真实哈希为上述 `2b3e...e8e2`；此前计划中记录的 `8c7f...f7e2` 未通过物理文件校验，已作废且不得用于 resume。Parquet metadata 仍为 4,026 rows、5,471 physical columns（5,470 ticker fields + `datetime`）。

它是**收益矩阵，不是完整日频行情或基本面面板**。因此日频 run 的输入只能由截至时点 `t` 的历史 `ret` 派生，允许的首批研究族包括：

- 多周期动量、短期/长期反转和趋势持续；
- realized volatility、downside volatility、波动率变化和风险尺度；
- 偏度、峰度、尾部损失、最大/最小收益、回撤和恢复；
- 自相关、状态切换和仅用历史收益定义的 regime；
- 横截面相对强弱、市场/同群残差和 breadth；
- 滚动相关、lead-lag、网络连通性和邻居聚合；
- 只以历史收益窗口为输入的统计或机器学习表示。

以下论文变量在 `ret.parquet`-only 轨道中为 `NEEDS_DATA` 或 `OUT_OF_SCOPE`：估值、财务报表、行业、市值、成交量、换手、流动性、盘口、订单流、公告文本、期权/期货和交易成本。不能从收益序列伪造这些字段。

数据质量约束同样必须进入 contract：有效值中约 5.35% 为零，可能同时包含真实零收益与停牌；有 726 个单元绝对收益大于 1，最大值约 19.43，主要疑似 IPO、重新上市、公司行动或数据异常。由于唯一数据源不含交易状态，系统必须：

1. 根据每列首次有效日期，只用历史信息屏蔽上市初期的预注册天数；
2. 在生成输入特征前执行固定的异常值策略，并保存原值、mask 和规则版本；
3. 不能利用 `t+1` 是否为零或异常来决定 `t` 的可交易 universe；
4. 用 `ret.shift(-h)` 或向前复合收益构造标签，确保所有 feature 严格只读到 `t`；
5. 将结果限定为研究级 IC/RankIC 和收益矩阵组合试验；没有价格、成交量和交易状态时，不宣称完成真实成交、容量或执行验证。

### 3.5 P0 正确性阻塞项

在启动自动 mutation 前必须解决：

1. **指标覆盖错误**：当前主 experiment runner 以 `factor_id` 读取 `stock_level.parquet`，多只股票的行会互相覆盖；必须先形成明确定义的跨股票/日期 aggregate。
2. **缺少冻结的数据切分**：当前默认 fac-eval config 没有固定 dates/codes 和 train/validation/test；不能区分探索、选择和最终确认。
3. **入库过早**：当前 evaluator `accept` 后可直接写 Alpha Library；候选筛选通过不等于稳健性通过，更不等于可部署。
4. **lifecycle 语义冲突**：library policy 与 runner 的直接入库路径不一致，需要单一权威 admission gate。
5. **实例去重错误风险**：相同公式可以共享 definition，但不同 research run 的 instance/evaluation/lineage 不能被 candidate pool 静默折叠。
6. **执行边界**：生产 fac-eval 必须使用 Slurm adapter；sandbox 或调度不可用时不能降级到登录节点大规模 subprocess。
7. **指标目标过窄**：不能只使用绝对 RankIC；必须包含方向、置信度、覆盖率、稳定性、成本、换手、复杂度和相对现有因子的增量。
8. **缺少日频专用执行器**：当前 fac-eval 是日内 tick 因子评估器；必须为 `ret.parquet` 新增只读 wide-store adapter、return-only 算子白名单、横截面 daily evaluator 和独立 admission policy，不能把日收益广播到 tick evaluator 后冒充日频验证。

## 4. 三项目责任边界

| 能力 | Paper Graph | Paper Digest New2 | Agent Alpha |
|---|---|---|---|
| canonical paper identity | 主责 | 消费 | 消费 |
| OpenAlex/citation 检索 | 主责 | 不重复 | 不重复 |
| graph snapshot 和关系 provenance | 主责 | 消费 | 消费 |
| 全文获取与解析 | 不重复 | 主责 | 不重复生产 |
| claim/evidence/公式/变量 | 引用 | 主责 | 消费与校验 |
| 变量到本地字段映射 | 提供主题先验 | 提供语义候选 | 主责并最终裁决 |
| FactorHypothesis | 提供 graph context | 提供 evidence | 主责 |
| 因子生成/变异 | 不负责 | 不负责 | 主责 |
| fac-eval/统计/稳健性 | 不负责 | 不负责 | 主责 |
| prior-art/graph novelty 检索 | 主责 | 提供全文语义 | 提供公式/Library 对比 |
| Alpha Library | 仅消费反馈 | 不负责 | 主责 |
| evidence-gap queue | 接收并排优先级 | 主责处理 | 产生 |
| 研究反馈 | 消费 | 消费 | 产生 |

三个项目不共享可变数据库，不复制大型数据目录。连接只通过版本化 artifact、稳定 ID、内容哈希和显式 adapter。

### 4.1 当前 Paper Graph 论文语料的实证分类基线

这里必须区分三个维度：

1. **论文主题类别**回答“论文研究什么”，应从 Paper Graph 当前论文和 topic graph 归纳；
2. **贡献形态**回答“论文给出了什么新东西”，例如机制、特征、模型、评价方法；
3. **因子研究用途**回答“Agent Alpha 应如何使用它”，例如直接信号、状态过滤、风险尺度、成本约束或模型组件。

此前只用“市场机制”和“机器学习/新特征”概括论文，会把三个维度混在一起。新的正式分类使用：

```text
paper
  -> topic labels                 # 研究对象，可多标签
  -> contribution records         # 论文贡献，可一篇多个
  -> factor-research roles         # 对具体研究机会逐项路由
```

当前实证底稿来自：

- `docs/generated/digest-topic-graphs/taxonomy.json`：12 个一级主题、54 个二级主题；
- `docs/generated/digest-topic-graphs/papers_classified.jsonl`：691 篇论文，640 篇至少命中一个主题；
- `docs/generated/digest-topic-graphs/summary.json`：各二级主题候选论文数量；
- `data/processed/openalex_quant_gate2_ai_review_v1/report.md`：20 篇 strict Gate 2 自动 accepted 的独立 AI 复核，其中 18 篇确认相关。

重要限制：Digest topic graph 当前是**关键词宽召回、多标签分类**。一级数量是至少命中其任一子主题的去重论文数，二级数量也是独立多标签计数，因此不能相加；弱关键词还会产生误标。它适合作为当前语料的主题地图和检索入口，不是最终 claim-level 真值。正式进入 Auto-Research 前，Digest 必须用正文 evidence 重新确认主题和贡献。

OpenAlex 20 篇复核样本虽然很小，但已覆盖强化学习组合、multi-level OFI、最优执行、动量/均值回复、已实现波动率分解和跳跃波动率模型，说明“可用于因子研究”的论文确实远多于两类。

### 4.2 基于当前论文的 12 个一级类别和 54 个二级类别

#### 4.2.1 市场微观结构（245 篇候选）

二级主题：限价订单簿（154）、价格发现（30）、做市机制（101）、信息不对称（7）。

这类论文研究报价、队列、成交和信息如何形成短期价格。它至少可再分为：

- **订单簿状态与形状**：多档深度、斜率、凸性、缺口、队列集中度和盘口恢复；
- **价格形成与价格发现**：mid/microprice、领先市场、信息进入价格的速度；
- **做市与库存行为**：报价偏移、库存压力、补单和流动性供给行为；
- **知情交易与信息不对称**：毒性订单流、逆向选择、成交后的不对称响应。

对因子研究的主要价值不是只有“发现一个直接 IC 因子”，还包括机制假设、盘口计算特征、流动性状态、可交易性过滤和执行风险。当前语料代表例子包括 `Second-Order Approximation of Limit Order Books in a Single-Scale Regime`（arXiv:2308.00805）和 `Forecasting High Frequency Order Flow Imbalance`（arXiv:2408.03594）。

#### 4.2.2 订单流与交易事件（149 篇候选）

二级主题：订单流不平衡（115）、委托不平衡（3）、交易方向识别（5）、订单到达与 Hawkes（36）、撤单与订单补充（2）。

应进一步区分：

- **成交型订单流**：signed trade、主动买卖量、成交方向和大单序列；
- **委托型订单流**：新增、撤销、修改、补单和多档 OFI；
- **事件强度与时间结构**：到达率、自激/互激、burst、等待时间和事件 surprise；
- **持续性与耗竭**：同向订单流持续、反转、补给不足和流动性耗竭。

这是当前高频因子最直接的来源之一，可产生方向信号、强度特征、持续性/反转条件和事件时钟。Gate 2 中的 `Multi-level order-flow imbalance in a limit order book` 也属于这一核心类别。

#### 4.2.3 流动性与交易执行（222 篇候选）

二级主题：买卖价差（11）、市场深度（4）、流动性供需（31）、最优执行（24）、交易成本与滑点（168）、逆向选择（20）。

内部需要拆成：

- **静态流动性测量**：spread、depth、quoted/realized liquidity；
- **动态流动性供需**：补单速度、韧性、稀薄化、供给/需求失衡；
- **交易成本模型**：冲击前成本、滑点、成交概率和机会成本；
- **执行与控制**：下单节奏、拆单、限价/市价选择和执行策略；
- **逆向选择**：成交后价格漂移、fill toxicity 和 maker/taker 风险。

这类论文不应被强制转成收益因子。其主要产物可为流动性状态、成本预测、候选过滤、容量约束、净收益评价或执行 policy；部分动态流动性变量也可以成为收益预测条件。代表论文包括 `Optimal Execution under Liquidity Uncertainty`（arXiv:2506.11813）。

#### 4.2.4 市场冲击（24 篇候选）

二级主题：Metaorder 与大额交易（14）、平方根冲击（4）、永久价格冲击（3）、临时价格冲击（9）。

应区分冲击的**来源、形状、时间衰减和可恢复部分**：

- 大单/metaorder 识别和隐含拆单；
- 冲击随成交量、波动率和参与率的尺度关系；
- 临时冲击、永久冲击和冲击后的回补；
- 冲击饱和、非线性以及买卖方向不对称。

它可产生订单压力持续性、冲击残差、预期回补、异常冲击和容量/成本特征。代表论文包括 `The Subtle Interplay between Square-root Impact, Order Imbalance & Volatility: A Unifying Framework`（arXiv:2506.07711）。

#### 4.2.5 波动率与相关性（31 篇候选）

二级主题：已实现波动率（16）、波动率预测（11）、波动率跳跃与冲击（1）、粗糙波动率（8）、高频相关性与 Epps 效应（2）。

内部至少包含：

- **波动率测量**：realized variance、range、kernel、噪声修正和连续/跳跃分解；
- **波动率动态**：持续性、期限结构、粗糙性和预测；
- **跳跃与极端状态**：jump intensity、jump variation 和冲击恢复；
- **高频协方差**：异步交易、Epps effect、相关性和 beta 的稳健估计。

这类论文常提供新“计算字段”，而不是直接给方向 IC。其正确用途包括风险尺度、状态过滤、分母归一化、动态窗口、波动目标/标签、横截面风险暴露和组合约束。代表论文包括 `State Space Model of Realized Volatility under the Existence of Dependent Market Microstructure Noise`（arXiv:2408.17187）；Gate 2 也包含已实现波动率连续/跳跃分解预测。

#### 4.2.6 收益预测与资产定价（153 篇候选）

二级主题：股票收益预测（34）、资产定价因子（104）、风险溢价（11）、异常收益（15）、横截面预测（42）。

它应拆成：

- **时序收益预测**：单资产未来收益、方向或分位数；
- **横截面选股**：同一时点的相对排序和截面收益差；
- **风险因子与风险溢价**：共同暴露和定价补偿；
- **异常与错误定价**：行为、约束或信息摩擦产生的异常收益；
- **factor discovery/combination**：新因子生成、残差因子和多因子组合。

这是最接近传统“论文因子”的类别，可产生直接复现、baseline 因子、组合候选和 prior-art 对照。但仍必须区分 paper 的市场、频率、持有期和数据可用性。代表论文包括 `NeuralFactors: A Novel Factor Learning Approach to Generative Modeling of Equities`（arXiv:2408.01499）和 `A Deep Learning Approach for Trading Factor Residuals`（arXiv:2412.11432）。

#### 4.2.7 价量关系与交易策略（63 篇候选）

二级主题：短期动量（34）、短期反转（1）、均值回复（10）、价量关系（4）、高频交易信号（20）。

内部需要区分：

- **趋势/动量**与不同形成期、持有期；
- **反转/均值回复**及其冲击回补或流动性补偿解释；
- **量价确认与背离**；
- **日内季节性、开收盘效应和事件时点信号**；
- **规则型交易策略**和可拆解的最小信号组件。

这也是直接 alpha 的核心来源，但应避免把整套交易策略不加拆解地当成一个因子。Gate 2 的 `Slow Momentum with Fast Reversion` 展示了同一论文可能同时贡献信号、状态检测和模型方法。

#### 4.2.8 衍生品与金融合约（156 篇候选）

二级主题：期权定价与隐含波动率（73）、期货与永续合约（51）、预测市场（21）、衍生品策略（37）。

应区分：

- **期权与隐含分布**：IV surface、skew、term structure、Greeks 和风险中性分布；
- **期现关系**：basis、carry、期限结构和价格发现；
- **永续合约机制**：funding、清算、杠杆和跨市场传导；
- **预测市场概率**及其信息聚合；
- **对冲、套利和衍生品执行策略**。

对 A 股 30 秒至 30 分钟 L2 因子而言，这类论文是否可用取决于本地期权、期货或跨市场数据。数据齐全时可产生领先指标、隐含风险/情绪、basis、跨市场价差和 regime；数据缺失时应进入 `NEEDS_DATA`，不能用股票盘口字段伪造。代表论文包括 `Whack-a-mole Online Learning: Physics-Informed Neural Network for Intraday Implied Volatility Surface`（arXiv:2411.02375）。

#### 4.2.9 组合优化与风险管理（136 篇候选）

二级主题：组合优化（52）、组合构建（27）、风险管理（45）、尾部与系统性风险（41）。

可进一步分为：

- **权重求解与约束**：mean-variance、risk parity、稀疏性、换手和容量；
- **信号到组合的转换**：标准化、中性化、组合和动态权重；
- **风险模型**：协方差、因子暴露、VaR/ES 和情景风险；
- **尾部与系统性风险**：极端依赖、压力传播和崩盘状态。

它通常不产生原始 alpha，而是决定多个候选如何转成净值、是否保留增量、怎样控制暴露和尾部风险。应在“单因子评价”和“组合增量评价”之间保留清晰边界。代表论文包括 `A Cholesky decomposition-based asset selection heuristic for sparse tangent portfolio optimization`（arXiv:2502.11701）。

#### 4.2.10 金融机器学习（283 篇候选）

二级主题：深度学习金融应用（87）、Transformer 与时序模型（66）、强化学习交易（63）、大语言模型与智能体（114）、机器学习预测（68）。

这不是一个单一“因子类别”，而是横跨其他主题的方法层：

- **监督学习预测**：特征到收益、方向、波动率或流动性目标；
- **深度时序/盘口表征**：CNN/RNN/Transformer、multi-scale encoder；
- **自监督和表示学习**：embedding、latent state、预训练；
- **强化学习**：执行、做市、组合和交易控制；
- **LLM/Agent**：文本信息、工具编排、假设生成或决策系统。

必须抽取论文究竟改进了输入表征、模型结构、损失、标签还是决策 policy。只有可独立定义的 latent/measurement 才进入 Feature Registry；模型整体进入公平 benchmark，而不是被包装成 ASL 因子。代表论文包括 `TLOB: A Novel Transformer Model with Dual Attention for Price Trend Prediction with Limit Order Book Data`（arXiv:2502.15757）。

#### 4.2.11 连续时间与随机过程（93 篇候选）

二级主题：随机过程（18）、连续时间模型（5）、机制切换与隐状态（38）、高阶矩与渐近（48）。

内部包括：

- 点过程、扩散、跳跃过程和随机控制；
- 连续时间价格/波动率/订单流模型；
- HMM、change point、regime switching 和 latent state；
- 高阶矩、重尾、渐近理论和估计误差。

这类论文常贡献估计器、状态概率、机制解释、模拟器或统计检验。Agent Alpha 应提取可观测 proxy 或可复现 estimator，而不是直接把理论参数当作现成因子。代表论文包括 `Convergence of Heavy-Tailed Hawkes Processes and the Microstructure of Rough Volatility`（arXiv:2312.08784）。

#### 4.2.12 网络、溢出与市场系统（151 篇候选）

二级主题：网络连通性（103）、信息溢出（14）、市场模拟（45）。

应拆成：

- **资产/行业/市场网络**：相关、partial correlation、transfer entropy 和动态连通性；
- **领先—滞后与信息溢出**：跨资产、跨市场和跨投资者类型传播；
- **系统性风险传播**：中心性、脆弱节点和压力传染；
- **市场模拟**：agent-based、LOB simulator、反事实市场和合成数据。

它可产生关系型因子、邻居聚合、lead-lag 信号、系统状态和压力测试环境。它高度依赖时间对齐、多资产 universe 和防止同刻信息泄漏。代表论文包括 `Information Propagation Across Investor Types: Transfer Entropy Networks in the Korean Equity Market`（arXiv:2603.20271）。

### 4.3 12 类论文对因子研究的用途不是同一种

下表首先给出 Agent Alpha 日内轨道（A 股 L2、约 30 秒至 30 分钟）的默认路由。`直接 alpha` 只是其中一种用途。

| 论文主题 | 直接信号 | 新计算特征 | 状态/条件 | 标签/评价 | 成本/执行 | 模型/组合 | 当前本地优先级 |
|---|---:|---:|---:|---:|---:|---:|---|
| 市场微观结构 | 高 | 高 | 高 | 中 | 高 | 中 | P0 |
| 订单流与交易事件 | 高 | 高 | 高 | 中 | 中 | 中 | P0 |
| 流动性与交易执行 | 中 | 高 | 高 | 中 | 高 | 中 | P0 |
| 市场冲击 | 中 | 高 | 高 | 中 | 高 | 中 | P0/P1 |
| 波动率与相关性 | 低/中 | 高 | 高 | 高 | 中 | 高 | P0/P1 |
| 收益预测与资产定价 | 高 | 中 | 中 | 中 | 低 | 高 | P0 |
| 价量关系与交易策略 | 高 | 高 | 高 | 中 | 中 | 中 | P0 |
| 衍生品与金融合约 | 中 | 高 | 高 | 中 | 中 | 中 | P2，取决于数据 |
| 组合优化与风险管理 | 低 | 中 | 高 | 高 | 高 | 高 | P1 |
| 金融机器学习 | 取决于目标 | 高 | 高 | 中 | 中 | 高 | P1，先建公平 baseline |
| 连续时间与随机过程 | 低 | 高 | 高 | 高 | 中 | 中 | P1 |
| 网络、溢出与市场系统 | 中 | 高 | 高 | 中 | 低 | 高 | P1/P2，取决于多资产数据 |

日频轨道使用同一套论文主题，但只接受能由历史收益矩阵实现的 contribution。收益动量/反转、收益分布、波动率、尾部风险、相关网络和 return-only ML 为 P0/P1；基本面资产定价、行业/市值暴露、价量、微观结构、订单流、流动性和冲击论文在当前日频数据契约下进入 `NEEDS_DATA`，不能因为属于资产定价论文就自动进入实验。日频论文不再因为无法迁移到 ret60s 而被判无用，但只能进入独立的 `daily_cross_sectional` run。

由此得到八种独立的 factor-research role：

1. `DIRECT_ALPHA`：变量直接预测未来收益或横截面排序；
2. `MECHANISM_PROXY`：用本地可观测量代理价格形成机制；
3. `MEASUREMENT_FEATURE`：更好地测量波动率、盘口、流动性、冲击等对象；
4. `REGIME_OR_CONDITIONER`：作为门控、交互、置信度或动态参数；
5. `LABEL_OR_ESTIMAND`：形成新目标、分解量或检验对象；
6. `COST_RISK_CONSTRAINT`：用于滑点、容量、风险和可交易性约束；
7. `MODEL_OR_REPRESENTATION`：改进编码、预测、控制或 latent state；
8. `PORTFOLIO_OR_POLICY`：将信号转换为权重、订单和执行动作。

同一论文可以横跨多个主题，也可以贡献多个 role。例如 multi-level OFI 同时是订单流主题下的测量特征、机制 proxy 和直接 alpha 候选；realized volatility decomposition 可以是测量特征、regime、label 和风险尺度，但不要求自身具有方向 IC。

### 4.4 贡献形态是第二层标签，而不是论文主题分类

在上述 12 类主题之下，Paper Graph 和 Digest 还要记录论文“贡献了什么”。每篇论文可以同时有多个 contribution record：

| contribution type | 论文主要贡献 | Agent Alpha 的正确产物 | 是否要求自身有 IC |
|---|---|---|---|
| `MARKET_MECHANISM` | 价格发现、订单流、流动性、冲击、信息不对称等机制 | `MechanismHypothesis`，再生成/约束因子 | 最终机制代理需要检验，但论文不必直接报告 IC |
| `EMPIRICAL_EFFECT` | 某变量、事件或状态与未来结果存在经验关系 | replication/FactorHypothesis | 通常需要方向性预测检验 |
| `MEASUREMENT_FEATURE` | 新波动率、盘口形状、订单流、噪声、状态量计算方法 | `FeatureCandidate` | 不要求；先检验测量有效性和增量用途 |
| `ML_REPRESENTATION` | 新表征、embedding、latent state、特征学习方法 | `ModelFeatureCandidate` | 不要求单输出直接有 IC；检验 OOS 下游增量 |
| `PREDICTION_MODEL` | 新架构、损失、训练或集成方法 | `ModelMethodCandidate` | 模型整体需与同输入 baseline 公平比较 |
| `LABEL_OR_TARGET` | 新预测目标、事件标签、波动率/冲击/流动性目标 | `LabelCandidate` / evaluation extension | 不适用；必须先验证时序和经济含义 |
| `EXECUTION_OR_CONTROL` | 最优执行、做市、仓位、风险控制、组合优化 | policy/optimizer experiment | 不以单因子 IC 为主指标 |
| `EVALUATION_METHOD` | 新统计检验、稳健性、估计或回测协议 | evaluator/preregistration extension | 不适用；验证校准和错误率 |
| `DATA_OR_MARKET_DESIGN` | 新数据源、市场规则、撮合/事件定义 | data/feasibility/evidence request | 不适用；可能暂停到 needs-data |
| `NEGATIVE_OR_BOUNDARY` | 失败、反例、适用边界、非稳健结果 | falsification/negative memory | 不要求正 IC，是重要约束证据 |

不能根据论文标题一次性决定 contribution。Digest 应基于正文 evidence 为每个贡献输出 `topic_ids + contribution_type + factor_research_roles + evidence_ids + confidence + not_disclosed`；Agent Alpha 再根据本地数据契约决定研究路径。

### 4.5 四种主要研究路径

#### 路径 A：机制到因子

```text
MARKET_MECHANISM / EMPIRICAL_EFFECT
  -> 可证伪 MechanismHypothesis
  -> observable event/state/response
  -> FactorCandidate family
  -> baseline/validation/locked test
```

这是原计划覆盖的主要路径，但不应代表全部论文。

#### 路径 B：论文计算量到新特征

```text
MEASUREMENT_FEATURE
  -> FeatureCandidate
  -> calculator/temporal/measurement validation
  -> Feature Registry candidate
  -> 加入预先选择的相关父因子
  -> nested ablation: parent vs parent + feature
  -> Feature Augmentation Outcome
```

新特征可能是 realized volatility estimator、multi-level order-flow imbalance、book slope/convexity、replenishment/depletion、microstructure noise、state probability 等。它本身可以没有稳定方向 IC；它的价值可能是：

- 为已有因子提供状态过滤；
- 作为强度、置信度或风险尺度；
- 替换低保真 proxy；
- 降低噪声或改善跨股票可比性；
- 提供非线性交互或条件效应；
- 改善成本、换手或尾部风险，而不是提高裸 RankIC。

#### 路径 C：机器学习/建模方法到模型特征或方法

```text
ML_REPRESENTATION / PREDICTION_MODEL
  -> 判断可复现层级
  -> deterministic estimator | trained feature | model method
  -> 固定输入、训练集、seed、预算和 baseline
  -> OOS representation/downstream ablation
```

优先提取论文中可独立验证的最小贡献：

1. 若创新是确定性估计量，进入 `FeatureCandidate`；
2. 若创新是训练得到的 latent state/embedding，进入 `ModelFeatureCandidate`，必须保存 fit/predict 边界；
3. 若创新是模型架构或损失，进入 `ModelMethodCandidate`，与相同输入和训练预算的 baseline 比较；
4. 若无法获得训练细节、代码、数据或合理替代，不强行转成 ASL 因子，状态为 `NEEDS_MODEL_EVIDENCE` 或 `UNREPRODUCIBLE`。

#### 路径 D：研究方法改进

```text
LABEL_OR_TARGET / EVALUATION_METHOD / EXECUTION_OR_CONTROL
  -> protocol candidate
  -> calibration/reproducibility test
  -> 新 experiment/evaluator version
```

这类论文改进研究 harness，而不是直接提供 alpha。它们必须通过独立方法学 gate，不能在看到当前候选结果后临时修改 label 或评价规则。

### 4.6 Graph 最有价值的跨主题、跨贡献组合

Graph 的重要作用不只是组合两个“因子论文”，而是连接不同贡献类型：

```text
市场机制论文
  + 测量/特征论文
  -> 用更忠实的新特征实现机制

市场机制论文
  + 状态/表示学习论文
  -> 用 latent state 条件化原因子

因子/经验效应论文
  + 统计/评价论文
  -> 更严格地复现或否证效应

盘口机制论文
  + 波动率/流动性估计论文
  -> 检验风险尺度或流动性状态是否改善父因子

失败/边界论文
  + 原始正结果论文
  -> 生成 regime condition、placebo 或 falsification
```

这种组合产生的是一个新的、可证伪的 `AugmentationHypothesis`，而不是自动声称出现新 alpha。

### 4.7 论文 contribution routing 决策

每个 contribution 进入以下终态之一：

```text
ROUTE_TO_MECHANISM_RESEARCH
ROUTE_TO_DIRECT_EFFECT_REPLICATION
ROUTE_TO_FEATURE_RESEARCH
ROUTE_TO_MODEL_FEATURE_RESEARCH
ROUTE_TO_MODEL_METHOD_BENCHMARK
ROUTE_TO_LABEL_OR_EVALUATOR_REVIEW
ROUTE_TO_EXECUTION_POLICY_RESEARCH
ROUTE_TO_NEGATIVE_OR_BOUNDARY_TEST
NEEDS_EVIDENCE
NEEDS_DATA
UNREPRODUCIBLE
OUT_OF_SCOPE
```

一篇论文可以产生多个 contribution records，但每个 record 只能沿一个明确路径进入实验，避免同一段证据被重复包装成多个“独立发现”。

### 4.8 完整分类的目标：不是给论文贴一个标签，而是生成可执行路由

完整分类必须同时回答六个互不替代的问题：

| 分类轴 | 回答的问题 | 主要生产者 | 是否可多选 |
|---|---|---|---:|
| `relevance_class` | 是否属于当前量化研究范围 | Paper Graph 初筛，Digest 复核 | 否 |
| `topic_ids` | 论文研究什么对象 | Paper Graph 候选，Digest 证据确认 | 是；另设一个 primary |
| `contribution_type` | 这一项贡献究竟给出了什么 | Digest | 每条 contribution 单选 |
| `required_observables` | 复现它必须有哪些数据 | Digest 提取，Agent Alpha 标准化 | 是 |
| `factor_research_roles` | 它在因子研究中扮演什么角色 | Digest 建议，Agent Alpha 裁决 | 是 |
| `track_decision` | 当前哪条数据线路真正可以执行 | Agent Alpha | 每个 route instance 单选 |

分类单位采用两级结构：

```text
PaperClassificationV1
  -> 一篇论文一个记录：相关性、primary topic、secondary topics
  -> 一篇论文允许多个主题，不直接决定是否可执行

ResearchContributionV1
  -> 一项独立 claim/方法/测量/负结果一个记录
  -> 每条记录有自己的 evidence、数据需求、研究角色和路由
  -> 同一论文可拆成多个 contribution records
```

必须遵守以下原则：

1. 不把整篇论文强制塞进一个互斥主题；`primary_topic_id` 只服务于检索排序和统计，`secondary_topic_ids[]` 保留交叉学科内容。
2. 不根据标题或关键词直接生成研究任务；关键词只负责召回，最终分类必须回链正文 claim/evidence。
3. 主题只说明语义相关性，不能绕过数据契约。`data feasibility` 对实验资格拥有否决权。
4. 一篇论文同时适合两条线路时，生成两个独立 route instance、两个 hypothesis 和两套实验，不允许在同一个 run 中混合数据。
5. 一项 contribution 在 v1 中只能有一个当前终态；若两个用途都值得研究，应拆成两个贡献或两个 route instance，而不是写含糊的组合路由。
6. 无法执行不等于论文无用。它可能进入方法改造、未来数据队列、边界条件或 prior-art memory。

`relevance_class` 使用四级枚举：

```text
CORE_QUANT_RESEARCH       # 直接研究金融市场变量、预测、定价、风险、执行或组合
ADJACENT_METHOD           # 通用统计/ML/优化方法，对明确的量化问题有可迁移贡献
CONTEXT_ONLY              # 只提供制度、背景或综述，不生成当前实验
OUT_OF_RESEARCH_SCOPE     # 与当前金融量化研究无实质关系
```

### 4.9 数据需求本体与两条线路的硬隔离

Digest 不直接写本地列名，而是先把论文输入归一化为 `required_observables[]`：

| observable class | 含义 | 日频 `ret.parquet` | 日内 L2 |
|---|---|---:|---:|
| `RETURN_HISTORY` | 历史单资产/横截面收益 | 允许 | 仅用日内线自己的收益定义 |
| `PRICE_LEVEL_OHLC` | 价格水平、开高低收、复权价格 | 不允许 | 取决于 L2 registry |
| `VOLUME_TURNOVER` | 成交量、成交额、换手率 | 不允许 | 取决于 L2 registry |
| `L2_BOOK_SNAPSHOT` | 多档报价、深度、队列状态 | 不允许 | 取决于 L2 registry |
| `ORDER_EVENT_STREAM` | 新增、撤销、修改和事件时间 | 不允许 | 取决于是否有逐笔委托事件 |
| `TRADE_PRINTS_SIGN` | 逐笔成交和买卖方向 | 不允许 | 取决于成交字段及 signing 规则 |
| `FUNDAMENTAL_PIT` | point-in-time 财务/估值数据 | 不允许 | 不允许 |
| `MARKET_CAP_SHARES` | 市值、股本、规模暴露 | 不允许 | 默认不允许 |
| `INDUSTRY_CLASSIFICATION` | 行业分类和行业中性化 | 不允许 | 默认不允许 |
| `DERIVATIVES_CHAIN` | 期权链、IV、Greeks、期货/永续 | 不允许 | 不允许 |
| `CROSS_MARKET_DATA` | 跨市场、指数、外汇、利率或基准 | 不允许 | 默认不允许 |
| `TEXT_EVENT` | 新闻、公告、研报、社媒和事件文本 | 不允许 | 不允许 |
| `MACRO_ALTERNATIVE` | 宏观和另类数据 | 不允许 | 不允许 |
| `EXECUTION_FILL_COST` | 成交回报、手续费、冲击和 fill | 不允许 | 取决于执行数据契约 |
| `TRAINED_MODEL_ARTIFACT` | 需训练权重、代码、超参或预训练模型 | 条件允许 | 条件允许 |
| `SIMULATOR` | 可校准仿真器或强化学习环境 | 条件允许，单独方法 gate | 条件允许，单独方法 gate |

当前只有两条实证线路：

```text
daily_cross_sectional
  dataset_contract_id: daily_ret_wide_v1
  physical_source: /home/gaozh/ret.parquet
  allowed_observables: [RETURN_HISTORY]

intraday_hf
  dataset_contract_id: intraday_hf_v1
  physical_source: 由 Agent Alpha 的冻结 L2 snapshot 指定
  allowed_observables: 只能来自该线路 field registry
```

隔离规则：

1. 日频 run 只允许读取 `daily_ret_wide_v1` 中登记的精确路径和内容哈希，任何其他日频文件、基本面、成交量、行业或价格表访问都立即失败。
2. 日内 run 不得读取 `/home/gaozh/ret.parquet`；所有收益、标签和 universe 都由冻结的日内数据契约生成。
3. 两条线路分别拥有 field/operator registry、split、evaluator、admission policy、Alpha Library 和 negative memory scope。
4. 共享内容只限于 paper ID、claim/evidence、抽象机制和 hypothesis lineage；不得共享数值特征、阈值、回测结果或拟合状态。
5. v1 不做跨频 join。需要日频状态加日内盘口、或期货加股票的论文进入 `NEEDS_DATA`/未来 multi-source track。
6. `TRAINED_MODEL_ARTIFACT` 和 `SIMULATOR` 不是普通字段；必须另外通过可复现性、训练时序、seed、预算和数据泄漏 gate。

### 4.10 54 个二级主题的完整默认路由矩阵

矩阵只给出**路由先验**，不自动接受具体论文。符号含义如下：

- `A`：存在与当前数据契约直接兼容的常见贡献，可在 evidence 和时序检查后自动候选化；
- `C`：条件兼容，必须先检查精确输入、市场、频率、定义或 proxy fidelity；
- `M`：主要进入方法、评价、模拟器或 policy review，不默认生成因子；
- `N`：当前数据缺失，进入 `NEEDS_DATA`；
- `—`：与该线路语义不匹配。

#### 市场微观结构、订单流、流动性和冲击

| 二级主题 | 典型数据需求/贡献 | `intraday_hf` | `daily_cross_sectional` | 默认处置 |
|---|---|---:|---:|---|
| `limit_order_book` | 多档报价、深度、形状和恢复 | A | N | 日内特征/机制；日频缺数据 |
| `price_discovery` | 报价/成交或跨资产领先关系 | C | C | 日频只接受 return-only lead-lag；其余需数据 |
| `market_making` | 报价、库存、fill 和供给行为 | C | N | 日内视库存/fill 可用性；否则 needs-data |
| `information_asymmetry` | signed flow、毒性、成交后响应 | C | N | 只接受有定义和证据的本地 proxy |
| `order_flow_imbalance` | 多档 book/trade OFI | A | N | 日内 P0 |
| `order_imbalance` | queue/quote imbalance | A | N | 日内 P0 |
| `trade_signing` | 逐笔成交、方向识别 | C | N | 无逐笔成交或 signing 规则则 needs-data |
| `order_arrival_hawkes` | 订单事件流和事件时间 | C | N | snapshot 不能冒充 event stream |
| `order_cancellation` | 撤单、补单、修改事件 | C | N | 必须核验逐笔委托字段 |
| `bid_ask_spread` | bid/ask 和有效/实现价差 | A | N | 日内测量、状态或成本 |
| `market_depth` | 多档深度 | A | N | 日内测量/状态 |
| `liquidity_supply_demand` | 补单、耗竭、供需变化 | C | N | 由 snapshot/event 可用性决定 |
| `optimal_execution` | 订单、fill、成本和控制环境 | C/M | N | 方法或 policy；不以 IC 作为唯一指标 |
| `transaction_cost` | spread、fill、fee、impact | C | N | 缺真实 fill 时只能做受限 cost proxy |
| `adverse_selection` | 成交方向和成交后漂移 | C | N | 无 trade/fill 则 needs-data |
| `metaorder` | 大单序列、参与率和隐含拆单 | C | N | 需事件/成交序列 |
| `square_root_impact` | 成交量、波动率、冲击 | C | N | 缺 volume/impact 定义则 needs-data |
| `permanent_impact` | 长短期响应分解 | C | N | 需事件锚点和足够响应期 |
| `temporary_impact` | 冲击衰减和恢复 | C | N | 日内机制/回补假设 |

#### 波动率、收益、资产定价和价量策略

| 二级主题 | 典型数据需求/贡献 | `intraday_hf` | `daily_cross_sectional` | 默认处置 |
|---|---|---:|---:|---|
| `realized_volatility` | 收益路径、噪声修正、RV estimator | C | A | 日频只能用历史日收益 estimator |
| `volatility_forecasting` | 历史收益/波动及预测模型 | C | A | 分线路独立标签和 horizon |
| `volatility_jumps` | 跳跃/连续分解和冲击状态 | C | C | 日频只能实现 return-only 近似并标 approximation |
| `rough_volatility` | 多尺度收益和粗糙度估计 | C | C | 采样频率不足时拒绝强结论 |
| `high_frequency_correlation` | 异步高频协方差/Epps | A | N | 普通日频相关应改标 network/correlation，不冒充高频估计 |
| `return_prediction` | 历史输入到未来收益 | C | A | 日频仅限 return-history 输入 |
| `asset_pricing_factors` | 风险/特征暴露和横截面收益 | C | C | 按 4.11 六类资产定价分支路由 |
| `risk_premia` | beta、协方差、共同因子和风险补偿 | C/M | C | 缺无风险利率/市场基准时限制结论 |
| `return_anomalies` | 异常收益和排序特征 | C | C | 日频仅复现 return-derived anomaly |
| `cross_sectional_prediction` | 同日 universe 排序和未来收益 | C | A | 日频 P0，严格 point-in-time universe |
| `short_term_momentum` | 滚动累计收益/趋势 | A | A | 两线路分别研究，不共享窗口结论 |
| `short_term_reversal` | 滞后收益反转 | A | A | 两线路分别研究 |
| `mean_reversion` | 偏离、残差和回归速度 | A | A | 日频偏离必须由收益历史可重建 |
| `price_volume` | 价格与成交量/换手交互 | A | N | 日频 `ret.parquet` 无 volume，禁止实现 |
| `intraday_signals` | 日内季节性、盘口或事件信号 | A | — | 只进入日内线 |

#### 衍生品、组合、机器学习、随机过程和网络

| 二级主题 | 典型数据需求/贡献 | `intraday_hf` | `daily_cross_sectional` | 默认处置 |
|---|---|---:|---:|---|
| `options_implied_volatility` | 期权链、IV surface、Greeks | N | N | 当前统一 `NEEDS_DATA`；方法贡献可进 M |
| `futures_perpetuals` | 期货/永续、basis、funding | N | N | 当前统一 `NEEDS_DATA` |
| `prediction_markets` | 合约概率和交易数据 | N | N | 当前统一 `NEEDS_DATA` |
| `derivatives_strategies` | 多合约价格、对冲和成本 | N/M | N/M | 仅保留通用方法；不执行实证策略 |
| `portfolio_optimization` | 预期收益、协方差和约束 | C/M | A/C | 日频可做 return-only 研究级组合，不宣称真实成本 |
| `portfolio_construction` | 排序、标准化、组合和权重 | C/M | A/C | 保持信号评价与组合评价分离 |
| `risk_management` | 风险估计、VaR/ES、状态 | C | C | 日频仅做收益历史可识别的风险 |
| `tail_systemic_risk` | 重尾、极端相关和系统状态 | C | A | 日频 return-only P1 |
| `deep_learning_finance` | 模型架构和金融输入表征 | C | C | 输入必须全部来自对应线路 registry |
| `transformer_finance` | 时序/截面注意力表征 | C | C | 同输入、同预算 baseline；不能只比论文分数 |
| `reinforcement_learning` | 环境、reward、执行/组合 policy | C/M | C/M | 必须有可审计 simulator；研究级结果不等于部署 |
| `llm_finance` | 文本、agent 或研究编排 | M | M | 文本信号当前不进两条实证线；可改进 research harness |
| `machine_learning_prediction` | 特征到目标的预测方法 | C | C | 日频只允许 return-only 输入，强制 OOS benchmark |
| `stochastic_process` | 扩散、跳跃、点过程和 estimator | C | C | 提取可观测 estimator；纯理论进入 M |
| `continuous_time` | 连续时间模型和参数估计 | C | C/M | 日频若离散采样无法识别则仅方法研究 |
| `regime_switching` | HMM、change point、latent state | A/C | A | fit 只能使用训练期，状态输出必须 causal |
| `high_order_tail` | 高阶矩、重尾和渐近估计 | C | A | 日频 return-only P1，保留小样本不确定性 |
| `network_connectedness` | 相关/偏相关/动态网络 | C | A | 日频可用历史收益矩阵，严禁同刻未来边 |
| `spillover` | lead-lag、传导和邻居聚合 | C | A | 日频可做 return-only 多资产传播 |
| `market_simulation` | ABM、LOB 或 return simulator | C/M | C/M | 先校准和方法 gate，不直接进入 Alpha Library |

### 4.11 资产定价论文的专门细分与日频可行性

“资产定价论文”不能整体判断为有用或无用。必须按真正使用的可观测量拆成六类：

| 子类 | 典型内容 | `ret.parquet` 当前可行性 | 当前路由 |
|---|---|---:|---|
| `AP_RETURN_DERIVED` | 动量、反转、趋势、收益分布、残差、季节性 | 高 | `daily_cross_sectional` |
| `AP_STATISTICAL_RISK` | beta、协方差、波动、尾部、latent return factor | 中/高 | 可做；缺外部市场/无风险基准时限制 claim |
| `AP_FUNDAMENTAL_CHARACTERISTIC` | 价值、盈利、投资、成长、质量、应计 | 无 | `NEEDS_DATA:FUNDAMENTAL_PIT` |
| `AP_SIZE_INDUSTRY` | 市值、小盘、行业暴露/中性化 | 无 | `NEEDS_DATA:MARKET_CAP_SHARES/INDUSTRY_CLASSIFICATION` |
| `AP_MARKET_FRICTION` | 流动性、换手、交易成本、卖空限制、机构持仓 | 无（日频）/部分日内 | 日频 needs-data；可评估是否转日内机制贡献 |
| `AP_TESTING_METHOD` | factor zoo、多重检验、模型比较、组合/定价检验 | 方法可用 | `ROUTE_TO_LABEL_OR_EVALUATOR_REVIEW` |

因此，当前日频数据**可以研究资产定价的一部分**，包括：

- 历史收益构造的横截面排序因子；
- 收益协方差、beta proxy、PCA/latent factor、残差动量；
- 波动率、偏度、峰度、尾部风险、最大/最小收益和 drawdown；
- return-only 的 anomaly combination、network、regime 和 ML；
- 用收益矩阵完成的研究级排序和组合增量。

当前**不能完整研究**价值、规模、盈利、投资、质量、行业、成交量、换手、流动性和机构行为等经典资产定价因子。缺少市值时也不能把等权股票平均收益无条件称为“市场因子”；缺少无风险利率时只能使用明确命名的 raw-return proxy。所有结果必须写清楚 estimand，避免把“return-only 横截面预测”夸大为完整资产定价检验。

### 4.12 contribution 分类和路由算法

每篇论文按以下确定顺序处理：

```text
1. canonical identity / version / retraction 检查
2. quant relevance 四级分类
3. 12/54 topic 宽召回，多标签保留
4. Digest 从正文拆分独立 contribution records
5. 为每项 contribution 绑定 claim/evidence/formula/variable
6. 提取 market / asset / frequency / horizon / label / estimator
7. 将论文输入归一化为 required_observables[]
8. 分别与 daily_ret_wide_v1 和 intraday_hf_v1 做精确匹配
9. 评估 direct / derived / weak_proxy / unavailable
10. 分配 factor_research_roles[] 和一个 research route
11. 生成 route instance 或进入人工复核/needs-data/方法队列
12. 冻结 classification version、evidence hash 和决策理由
```

路由优先级不是“日内优先”或“日频优先”，而是：

```text
exact observable + exact temporal semantics
  > validated derived observable
  > explicit weak-proxy hypothesis
  > method-only reuse
  > needs evidence/data
  > out of scope
```

若一项 contribution 在两条线路均精确可行，例如 momentum 或 volatility forecasting：

```text
contribution_id = C
  -> route_instance_id = C:intraday_hf
  -> route_instance_id = C:daily_cross_sectional
```

两个实例必须拥有不同 `research_run_id`、数据哈希、窗口、标签、preregistration、评价阈值和结论；论文证据可以相同，但实验结论不能合并。

### 4.13 自动分类、人工复核和状态机

仅在以下条件全部满足时允许 `AUTO_ROUTED`：

1. 有正文 evidence，而不是只有标题/摘要关键词；
2. contribution 边界、输入、输出、频率和预测 horizon 清楚；
3. 所需 observable 与某一线路精确匹配，或是已批准的 deterministic derived field；
4. causal availability 明确，无 label leakage、survivorship 或事后 universe 依赖；
5. 只有一个明确的当前路由，且不需要创造新 proxy、训练协议或 evaluator。

出现以下任一情况进入 `HUMAN_REVIEW`：

- primary topic 或 contribution type 低置信；
- 同一 claim 同时落入两个贡献类型，无法可靠拆分；
- 两条线路都可行，需要决定研究预算和优先级；
- 论文变量只能映射为 `weak_proxy`；
- 输入数据、采样方式、训练细节或时间可用性没有披露；
- 涉及 fitted representation、RL、simulator、LLM、跨市场或衍生品；
- evidence 相互矛盾、论文有版本冲突、撤稿/更正或异常结果；
- contribution 会修改 label、评估协议、admission gate 或 locked-test 规则。

正式分类状态：

```text
UNCLASSIFIED
KEYWORD_RECALLED
EVIDENCE_CLASSIFIED
AUTO_ROUTED
HUMAN_REVIEW
NEEDS_EVIDENCE
NEEDS_DATA
METHOD_ONLY
UNREPRODUCIBLE
OUT_OF_SCOPE
SUPERSEDED
```

人工复核只能修改带版本的 classification record，并保存旧状态、理由、reviewer 和 source evidence；不能原地覆盖历史分类。

### 4.14 分类文件、项目所有权和精确记录内容

#### Paper Graph 输出

```text
data/processed/paper_classification/<snapshot_id>/
  classification_manifest.json
  paper_relevance.jsonl
  paper_topics.jsonl
  topic_counts.json
  review_queue.jsonl
```

`PaperClassificationV1` 至少包含：

```text
schema_version
paper_classification_id
paper_id / work_id / version_id
title
relevance_class
primary_topic_id
secondary_topic_ids[]
candidate_topic_scores{}
classification_evidence_refs[]
classification_basis          # keyword | abstract | full_text
classifier_version / taxonomy_version
confidence
review_status / review_reason_codes[]
created_at / supersedes_id
```

Paper Graph 只负责论文级检索分类和 snapshot；没有全文证据时不得声称贡献已确认。

#### Paper Digest New2 输出

```text
data/runtime/research_classification/<artifact_id>/
  research_contributions.jsonl
  data_requirements.jsonl
  classification_evidence.jsonl
  digest_classification_manifest.json
  evidence_gap_queue.jsonl
```

每条 contribution 必须记录 claim、evidence、贡献类型、主题、研究角色建议、所需数据和未披露项；同一变量的同义词归并到 canonical observable，但保留原文名称和 evidence span。

#### Agent Alpha 输出

```text
outputs/research_routing/batch_id=<batch_id>/
  routing_manifest.json
  routing_decisions.jsonl
  feasibility_assessments.jsonl
  route_instances.jsonl
  human_review_queue.jsonl
  needs_data_queue.jsonl
  audit/data_access_allowlist.json

configs/data_contracts/intraday_hf_v1.yaml
configs/data_contracts/daily_ret_wide_v1.yaml
configs/field_registry_intraday_hf.yaml
configs/operator_registry_daily_return_only.yaml
```

`RoutingDecisionV1` 至少包含：

```text
routing_decision_id / route_instance_id
contribution_id / paper_id / evidence_ids[]
primary_topic_id / secondary_topic_ids[]
contribution_type / factor_research_roles[]
required_observables[]
target_track
dataset_contract_id / dataset_content_hash
field_registry_version / operator_registry_version
observable_mappings[]
proxy_strength / approximation_loss
temporal_compatibility / leakage_risks[]
track_eligibility{}             # 每条线路的 eligible/conditional/ineligible + reasons
routing_decision / route_reason_codes[]
classification_version / confidence
review_status / reviewer / supersedes_id
```

### 4.15 稳定 reason codes

为了统计分类错误和积压原因，不允许只写自然语言理由。至少实现：

```text
EXACT_RETURN_ONLY_MATCH
EXACT_INTRADAY_FIELD_MATCH
DERIVED_FIELD_APPROVED
WEAK_PROXY_REVIEW_REQUIRED
MISSING_FULL_TEXT_EVIDENCE
MISSING_INPUT_DISCLOSURE
MISSING_FUNDAMENTAL_DATA
MISSING_MARKET_CAP_DATA
MISSING_INDUSTRY_DATA
MISSING_VOLUME_DATA
MISSING_L2_DATA
MISSING_ORDER_EVENT_DATA
MISSING_TRADE_OR_FILL_DATA
MISSING_DERIVATIVES_DATA
MISSING_CROSS_MARKET_DATA
MISSING_TEXT_OR_ALTERNATIVE_DATA
FREQUENCY_MISMATCH
HORIZON_MISMATCH
MARKET_TRANSFER_RISK
TEMPORAL_AVAILABILITY_UNCLEAR
LEAKAGE_RISK
MODEL_REPRODUCIBILITY_GAP
METHOD_CONTRIBUTION_ONLY
PURE_THEORY_NO_OBSERVABLE
OUTSIDE_CURRENT_MARKET_SCOPE
```

reason code 与详细说明、evidence refs 同时保存；未来新增 code 只能 additive，不能改变已有 code 语义。

### 4.16 分类质量评估和验收标准

分类系统本身也必须被评估，而不是只检查文件是否生成：

1. 54 个二级主题各有至少 2 个正例和 1 个 hard negative 的固定测试；语料不足时记录为 coverage gap，不能编造样本。
2. 抽取至少 100 篇分层人工金标，覆盖 12 个一级主题、跨主题论文、needs-data 和 method-only；论文级 topic micro-F1 与 contribution-level exact agreement 分开报告。
3. `primary_topic_id` 人工一致率目标不低于 90%；secondary topic 用 precision/recall，不以强制单标签 accuracy 评价。
4. 100% `EVIDENCE_CLASSIFIED` contribution 有 evidence ID；100% executable route 有 observable signature、唯一 target track、data contract ID/hash 和 reason code。
5. 100% `NEEDS_DATA` 记录指出缺失 observable，而不是笼统写“数据不足”。
6. 两条线路的测试运行中，跨契约数据读取次数必须为 0；违规必须 hard fail 并写 audit event。
7. 随机抽样复核 track eligibility、weak proxy 和资产定价细分；自动路由 precision 未达到 95% 前，不扩大自动执行预算。
8. taxonomy、classifier、evidence artifact 或数据契约发生变化时，只重算受影响记录，并通过 `supersedes_id` 保留旧版本。
9. 报告 classification confusion matrix、各 reason-code 数量、人工队列 aging、needs-data 分布和 route conversion rate。
10. 分类结果只证明“按当前证据和数据可进入哪种研究”，不证明论文结论正确、因子新颖或因子有效。

### 4.17 首版分类实施顺序

```text
P0-1  冻结 taxonomy_v1（12/54）、observable ontology 和 reason codes
P0-2  建立 100 篇人工金标及 54-topic test fixtures
P0-3  Paper Graph 产出 paper relevance/topics snapshot
P0-4  Digest 实现 evidence-backed contribution splitter/classifier
P0-5  Agent Alpha 实现两个 data contract 和 eligibility matcher
P0-6  实现数据路径 allowlist、hash 校验和跨线路 hard-fail 测试
P0-7  先路由 return-only 资产定价/收益论文和 L2/OFI 论文两个 pilot
P1-1  增加 feature/model/method contribution 的专用 review queue
P1-2  统计人工 disagreement，修正 taxonomy mapping 和 prompt/schema
P1-3  达到自动路由 precision 门槛后再接入批量 hypothesis generation
P2    等新增数据契约后再启用基本面、衍生品、跨市场和文本线路
```

首版 pilot 应刻意选择两组边界清楚但数据完全不同的论文：

- 日频组：`AP_RETURN_DERIVED`、`cross_sectional_prediction`、`realized_volatility`、`network_connectedness`，仅使用 `/home/gaozh/ret.parquet`；
- 日内组：`limit_order_book`、`order_flow_imbalance`、`bid_ask_spread`、`temporary_impact`，仅使用冻结 L2 snapshot。

先验证分类和数据隔离，再扩到需要弱 proxy、fitted model、执行 policy 或方法改造的论文。

### 4.18 taxonomy 扩展策略：稳定 12/54，候选扩展为 18/92

12/54 对市场微观结构、订单流、流动性、冲击、波动率、收益、组合和金融 ML 的覆盖较好，但当前未分类论文已经暴露出系统性缺口。不能直接修改旧主题含义或重用旧 ID；采用 additive overlay：

| 新一级主题 | 新二级主题数 | 主要缺口 | 当前两线路状态 |
|---|---:|---|---|
| `fundamental_corporate` | 7 | 估值、盈利/投资、财报事件、会计质量、公司行动、信用、持股 | 日频当前大多 `NEEDS_DATA` |
| `behavioral_information` | 6 | 关注、情绪、新闻文本、分析师、行为偏差、拥挤 | 当前大多 `NEEDS_DATA`；机制仍可保留 |
| `macro_cross_asset` | 7 | 宏观、利率债券、外汇、商品、跨资产、货币政策、通胀增长 | 当前大多 `NEEDS_DATA` |
| `research_methods_data` | 6 | 因果、计量检验、回测验证、多重检验、数据偏差、复现 | 进入 evaluator/protocol 路线 |
| `digital_assets_market_design` | 6 | 加密现货、DeFi/AMM、MEV、稳定币、链上网络、操纵/清算 | 当前市场不匹配；保留方法和 prior art |
| `market_institutions_regulation` | 6 | 集合竞价、tick/涨跌停、分割/延迟、卖空、熔断、监管规则 | A 股高度相关，需匹配具体制度和字段 |

版本策略：

```text
digest_quant_topics_v1_12_54
  status: stable
  historical IDs and snapshots remain immutable

quant_research_topics_v2_candidate_18_92
  mode: additive_only
  inherits: v1
  promotion: 每个新二级主题至少 2 个金标正例、1 个 hard negative、
             precision >= 0.90 且人工批准
```

18/92 仍然不是最终上限。后续新增主题必须来自可审计的 `taxonomy_gap_queue`：连续出现的未覆盖 contribution、无法解释的人工 disagreement、新数据契约或稳定的新研究域；不能因为单篇论文出现新名词就新增主题。资产类别、市场、频率、数据需求和 contribution type 继续使用独立 facet，不应全部塞进 topic hierarchy。

## 5. 研究对象、身份和作用域

### 5.1 主键链

```text
research_opportunity_id
  -> graph_id + graph_version                  # graph 可选，但版本必须明确
  -> evidence_bundle_id
  -> factor_research_run_id
  -> hypothesis_id
  -> factor_definition_id
  -> factor_instance_id
  -> experiment_id + experiment_version
  -> run_attempt_id
  -> metric_record_id
  -> review_id
  -> library_record_id / negative_result_id
```

### 5.2 因子身份必须分离

1. `factor_definition_id`：规范化 ASL、字段、窗口和方向的全局定义身份；
2. `factor_instance_id`：definition + research run + hypothesis + evidence/proxy context；
3. `experiment_id`：instance + 数据/标签/split/cost/metric preregistration；
4. `run_attempt_id`：同一实验的工程执行尝试；
5. `candidate_id`：搜索池中用于调度的记录。

同一公式在两个 graph 中可共享 `factor_definition_id`，但不能共享 evidence conclusion、evaluation 或 scientific status。

### 5.3 特征、模型和增强实验身份

新计算字段不能直接塞进 `derived_feature_fields` 后失去来源。必须分开：

1. `feature_definition_id`：规范计算图、原始输入、窗口、参数、单位和输出语义；
2. `feature_instance_id`：definition + data/registry version + fit state（若有）+ research evidence；
3. `model_method_id`：架构、损失、训练协议、输入输出契约的身份；
4. `trained_model_instance_id`：method + train split + seed + checkpoint hash；
5. `augmentation_hypothesis_id`：为什么该 feature 应改善哪些父因子、以何种方式改善；
6. `augmentation_experiment_id`：固定 parent、feature、composition operator、split 和 metric 的嵌套实验。

对应链路：

```text
paper contribution
  -> feature/model definition
  -> implementation + measurement validation
  -> augmentation hypothesis
  -> parent factor baseline
  -> parent factor + feature child
  -> paired augmentation outcome
```

Feature Registry admission 与 Candidate Alpha Library admission 完全分开：一个高质量 volatility estimator 可以进入 Feature Registry，即使它单独预测收益的 IC 为零；反之，一个偶然高 IC 但计算不稳定、含未来信息或无法解释的字段不能进入 Feature Registry。

### 5.4 研究作用域

每个 `FactorResearchRun` 固定：

- `as_of_date` 和 paper/graph snapshot；
- Digest document/evidence versions；
- market data snapshot；
- market、asset class、frequency 和目标 horizon；
- 可用字段/算子 registry 版本；
- train/exploration/validation/locked-test 切分；
- cost、turnover、capacity 假设；
- 搜索和计算预算；
- memory snapshot 和允许检索的 scope；
- LLM/prompt/config revisions。

任一关键输入变化都创建新 run 或新 experiment version，不覆盖旧记录。

当前允许两个互相隔离的 frequency track：

```text
intraday_hf
  data: A 股 L2 / tick-derived fields
  example labels: ret30s / ret60s / ret120s / ret1800s
  evaluator: fac-eval Slurm adapter

daily_cross_sectional
  data: /home/gaozh/ret.parquet only
  features: functions of returns observed through t only
  example labels: next_day / t+5 / t+20 compounded returns
  evaluator: dedicated daily cross-sectional evaluator
```

两个轨道不能共享 split、指标阈值或 Alpha Library admission 结论。一个因子可以建立跨频率 lineage，但日频验证通过不代表日内通过，反之亦然。

## 6. Graph 发现的思想是否新颖

### 6.1 Graph 能提高新颖性概率，但不能证明新颖性

Graph 的优势是发现单篇阅读不容易注意到的结构：

- 两个长期分离的论文社区使用相似变量解释不同现象；
- 一篇论文给出机制，另一篇给出本地可观测 proxy；
- 支持与反驳结果之间存在可检验的状态条件；
- 同一机制在不同频率、市场或 regime 中结论相反；
- 一个失败论文暴露的限制可被另一篇方法论文解决；
- 一个 paper path 形成“事件 -> 状态 -> 价格响应 -> 风险/成本”的完整链。

这些结构能够产生比“从单篇摘要改写一个公式”更好的研究问题，但仍可能已经存在于：

- graph 未覆盖的论文；
- 较新论文、工作论文、行业研究或代码仓库；
- Agent Alpha 已研究但未进入 Paper Graph 的因子；
- 不同表达式但经济含义相同的 Alpha Library 记录中。

因此禁止把 `graph_discovered=true` 翻译成“全球新颖”。

### 6.2 新颖性的五个层级

每个 hypothesis 保存一个向量，而不是单一分数：

1. **Graph structural novelty**  
   当前固定 graph 中是否跨社区、跨路径或首次连接两组 claims。只证明局部结构新颖。
2. **Mechanism novelty**  
   机制链的事件、状态条件、响应和边界条件是否不同于已检索的 hypothesis signature。
3. **Factor-definition novelty**  
   规范 ASL、字段、窗口、方向是否未出现在 Candidate/Negative/Alpha Library；同时检查近似表达式和语义等价。
4. **Empirical incremental novelty**  
   相对已有因子，在固定数据和成本下是否提供低相关、显著的增量解释或组合价值。
5. **Global prior-art novelty**  
   截至 `as_of_date` 是否没有公开文献或实现。局部系统通常只能给出 `not_found_in_searched_prior_art`，不能给出绝对证明。

推荐状态：

```text
known_duplicate
local_graph_recombination
mechanism_variant
definition_novel
empirically_incremental
not_found_in_searched_prior_art
global_novelty_unverified
```

### 6.3 新颖性检查流程

1. Paper Graph 对 canonical paper/claim 做去重，冻结检索截止日；
2. 以机制关键词、变量、目标、市场、频率和引用邻域检索 prior art；
3. Digest 对候选 prior art 提取具体 claims，而不是只比标题/摘要；
4. Agent Alpha 构建 `HypothesisSignature`：

```text
event
state_condition
observable_variables
expected_response
horizon
direction
market/frequency
mechanism_path
```

5. 对 `factor_definition_id` 做精确 dedupe；对 ASL 做交换律、常数折叠和窗口标准化后的近似 dedupe；
6. 对 Alpha Library 和 Negative Result Archive 做机制、字段、公式和 lineage 检索；
7. 用验证集/锁定测试集检查与现有 alpha 的相关性和增量价值；
8. 输出检索范围、未覆盖来源和不确定性，不输出无证据的“first ever”。

### 6.4 Graph 生成新思想的受控操作

允许的 graph-conditioned research operators：

- `CONDITION`：用反驳/限定论文中的 regime 条件约束原机制；
- `BRIDGE`：连接两个有证据的机制，但每个中间推断必须显式标记；
- `TRANSFER`：将机制迁移到新市场/频率，必须新建外推 hypothesis；
- `RESIDUALIZE`：从已有因子中移除已知共同机制，检验剩余信息；
- `REPLICATION`：在本地数据重现论文结果；
- `CONTRADICTION_TEST`：直接检验相反方向或边界条件；
- `PROXY_SUBSTITUTION`：使用本地可观测 proxy，明确 approximation loss；
- `COMPOSITION`：组合两个经过独立支持且时序兼容的机制。

禁止：

- 仅因为 graph 路径存在就声称因果关系；
- 强迫路径上的每个概念进入公式；
- 用 citation similarity 代替 claim entailment；
- 用 LLM 自评分替代 prior-art 检索；
- 为追求“新颖”而加入没有经济含义的算子或窗口。

### 6.5 宏观研究控制器：决定研究预算，不决定科学真值

系统需要一个跨 graph 的“宏观大脑”，正式名称为 `ResearchPortfolioController`。它是可审计的 portfolio scheduler，不是另一个自由推理 Agent：

```text
Paper Graph
  -> GraphValueFeaturesV1
     evidence readiness / graph coherence / novelty / relation information

Paper Digest New2
  -> claim evidence coverage / support-refute-replication relations / evidence gaps

Agent Alpha
  -> data feasibility / direct observability / downstream utility / estimated cost

ResearchPortfolioController
  -> GraphValueAssessmentV1
  -> budget + topic diversity + track capacity
  -> selected research graph portfolio
```

第一版评分维度和默认权重：

| 维度 | 权重 | 含义 |
|---|---:|---|
| evidence readiness | 0.18 | 可引用正文、claim 和 evidence 的覆盖 |
| data feasibility | 0.22 | 当前数据契约能否真正执行 |
| direct observability | 0.10 | direct/approved-derived 比例 |
| graph coherence | 0.10 | graph 是否形成明确问题而非关键词杂团 |
| novelty | 0.16 | 范围受限的机制/prior-art gap |
| relation information | 0.08 | 已核验支持、反驳、复现和限定关系的信息量 |
| downstream utility | 0.16 | 对 factor/feature/model/evaluator 的预期用途 |

另扣 redundancy 和 estimated cost。硬门槛优先于加权分数：证据不足进入 `BUILD_EVIDENCE`，数据完全不可行进入 `NEEDS_DATA`。存在同范围高可信分歧时，优先路由到 `RESOLVE_CONTRADICTION`，而不是把争议当作低质量噪声。控制器还必须限制每个一级主题的名额，避免热门 LOB/LLM 主题耗尽全部预算。

控制器只能决定 `BUILD_EVIDENCE / NEEDS_DATA / RESOLVE_CONTRADICTION / RUN_FACTOR_RESEARCH / RUN_FEATURE_OR_METHOD_RESEARCH / REVIEW_RESEARCH_OPPORTUNITY`；它无权写入“论文为真”“因子有效”或 Candidate Alpha Library admission。

### 6.6 按 SciNet 三层关系消费结构化结果，但不重复论文结构化

参考 `SciNet: Evaluating AI Agents in Relation-Aware Scientific Literature Retrieval`（arXiv:2601.03260v2），Paper Graph 将关系检索分成三层：

| SciNet 层级 | 本系统用途 | 当前负责模块 |
|---|---|---|
| Ego-centric | novelty/disruption、graph structure 和单 graph 研究价值 | `graph_value.py` + OpenAlex citation statistics |
| Pair-wise | 支持、反驳、复现、限定、方法继承 | `ClaimRelationV1` + verified-only projection |
| Path-wise | 从基础论文到新论文的显式引用演化路径 | `relation_aware_retrieval.py` |

论文 PDF 结构化、GROBID/TeX 解析、章节/claim/evidence/citation-context 抽取由独立 AI 模块负责，本计划不重复实现。下游只消费版本化 artifact：

```text
StructuredPaperArtifact
  paper_id / document_version / content_hash
  claims[] / evidence_spans[]
  citation_contexts[]
  contribution_records[]
  extraction_config / producer_revision
```

Pair-wise proposal 必须来自 citation context 或双方 claim evidence。正面/负面 citation sentiment 只能作为候选证据，不能直接映射为 `SUPPORTS`/`CONTRADICTS`。Path-wise 的拓扑候选只使用显式 `CITES` 边，embedding similarity 不得创建路径；候选路径仍需外部结构化模块或人工完成 logical-coherence review，才能成为 verified evolution path。

### 6.7 SciNet 复现的责任边界和产物

Paper Graph 负责复现 SciNet 的 relation-aware corpus/index/retrieval/evaluation 部分，并将其收窄到量化研究语料。它不解析 PDF/TeX，不从原文自行生成 claim，不判定因子有效，也不执行 Auto-Research。

输入仅有两类：

1. OpenAlex 快照提供的 paper metadata、topic、reference 和 citation topology；
2. 上游文章结构化 AI 输出的版本化 `StructuredPaperArtifact`。

输出是只追加、可复现的四类产物：

```text
CorpusSnapshotV1             # paper/version/identity/citation 基线
ScientificRelationGraphV1    # 多层 graph 及可查询投影
EvolutionPathArtifactV1      # 拓扑候选与已核验演化路径
FacetedClassificationGraphV1 # contribution-level 精细分类 graph
```

Auto-Research 只消费固定 snapshot/hash 的上述产物。它返回的因子表现不得修改 claim 真值、citation relation、taxonomy 或 SciNet 指标；最多只能生成新的 evidence-gap 或 revalidation request。

### 6.8 `StructuredPaperArtifactV1` 消费契约

本项目需镜像一份严格 JSON Schema，作为上游的交付门槛。最小契约为：

```text
artifact_id / schema_version / producer_revision / extraction_config_hash
paper_id / document_version / content_hash / source_uri / language
sections[]
evidence_spans[]
  evidence_id / section_id / page_or_tex_locator / char_offsets / quote_hash
claims[]
  claim_id / claim_type / normalized_statement / polarity / evidence_ids[] / scope
citation_contexts[]
  context_id / paragraph_id / cited_paper_ids[] / marker_offsets / sentiment / evidence_id
contribution_records[]
  contribution_id / contribution_type / mechanism / method / variables / datasets
  topic_candidates[] / evidence_ids[] / not_disclosed[]
quality / warnings / supersedes_artifact_id
```

`scope` 不能是一段自由文本，至少需分解为 market、asset、geography、frequency、sample period、dataset、population/universe、estimand/target、method 和 outcome。不披露必须显式写 `unknown/not_disclosed`，不得由下游猜测。

稳定 ID 规则：

- `document_version_id = hash(paper_id, content_hash)`；
- `evidence_id = hash(document_version_id, locator, quote_hash)`；
- `claim_id = hash(document_version_id, claim_type, normalized_statement, evidence_ids)`；
- `citation_context_id = hash(document_version_id, paragraph locator, cited_paper_ids, quote_hash)`；
- `contribution_id = hash(document_version_id, contribution_type, claim_ids, evidence_ids)`。

入库前依次执行 schema、hash、paper identity、引用目标解析、跨字段引用完整性和 version lineage 校验。失败产物进入 quarantine，不做容错补写。同一 paper 的新版本只能用 `supersedes` 追加，不覆盖旧 claim/evidence。

### 6.9 精细 graph：一个物理存储，四个严格投影

不把所有关系压成一张同质 paper graph。底层使用异质节点：

```text
Paper / DocumentVersion / Claim / EvidenceSpan / CitationContext / Contribution
Topic / Mechanism / Method / Dataset / Observable / ScopeValue
```

底层边分组保存：

| 边组 | 示例 | 真值来源 |
|---|---|---|
| document provenance | `PAPER_HAS_VERSION`, `CLAIM_HAS_EVIDENCE` | artifact + hash |
| citation topology | `CITES`, `CITED_IN_CONTEXT`, `CO_MENTIONED_IN_PARAGRAPH` | OpenAlex + citation context |
| epistemic | `SUPPORTS`, `CONTRADICTS`, `REPLICATES`, `REFINES` | 双侧 evidence + verifier |
| contribution/ontology | `MAKES_CONTRIBUTION`, `CLASSIFIED_AS`, `USES_METHOD`, `USES_DATA`, `MEASURES` | contribution evidence |
| soft retrieval | `EMBEDDING_SIMILAR_TO`, keyword/retrieval score | 候选召回，永不作真值 |

在此之上物化四个查询投影：

1. `citation_topology_view`：只含显式 `CITES`，服务 ego/path-wise；
2. `verified_epistemic_view`：只含双侧 evidence 且 `review_status=verified` 的 claim relation；
3. `evolution_view`：顺序路径 + hop-level citation/evidence/coherence；
4. `faceted_taxonomy_view`：contribution-topic-facet 分类，不把资产、频率、方法塞进单一 topic tree。

`PaperEdge` 可继续作为对外投影，但不能是底层真值模型。当前 `citation_edge()` 生成 `CITATION_SIMILAR_TO` 的历史接口不得用于 SciNet `CITES` 路径。

### 6.10 Ego-centric：复现指标，不与 graph value 混用

SciNet-compatible 基线需独立实现两类指标：

1. Uzzi novelty：对每篇论文的 reference pairs 计算相对 field/year null model 的 co-citation Z-score，取 `p10_z`，并保存 null-model snapshot/hash。
2. disruption：根据后续论文是否只引用 focal paper，或同时引用 focal 及其 predecessors，计算 SciNet 声明的 index variant。

每条指标记录 `metric_variant`、citation observation cutoff、window、field assignment、reference coverage 和 maturity。先保留与 SciNet 评测一致的 global percentile，再额外输出 field-year percentile 供量化语料生产排序；两者不可混为一列。

`GraphValueAssessmentV1` 仍只表示下游研究价值和成本。novelty/disruption 是可复算的 scientometric facts，不受 Auto-Research 结果或 LLM 喜好修改。

### 6.11 Pair-wise：从 citation context 到双侧 claim relation

候选对的召回顺序为：

1. 直接 citation context；
2. 同段 co-mention；
3. 同一细分 contribution/mechanism 中的双侧 claim；
4. embedding 近邻，仅用作低优先级补召回。

先保存 SciNet 原始层的 `citation_sentiment = positive/negative/neutral/mixed`、`co_mention_same_paragraph` 和定位证据。这些不等于 epistemic relation。之后才通过 claim type、polarity、method、estimand 和 scope vector 进行可比性校验，生成 `ClaimRelationV1` proposal。

自动进入 `verified` 必须同时满足：

- source/target 两侧都有稳定 evidence IDs 和 document versions；
- relation-specific 规则通过；
- `CONTRADICTS`/`FAILS_TO_REPLICATE` 的 scope 为 exact 或可解释的 partial；
- verifier version、rationale、confidence 和 calibration record 完整；
- 不存在未解决的 document-version 冲突。

否则只能停在 `proposed`。生产流程不要求逐条人工审核；但是 verifier 必须在 SciNet 公开 pair-wise tasks 和固定的本地 gold fixtures 上校准，且低置信度不得投影。

### 6.12 Path-wise：拓扑连通、影响力排序和逻辑连续分开

路径候选只在 `citation_topology_view` 上运行，`CITES` 按 citing -> cited 存储，对外演化序列按 foundation -> descendant 输出。每一 hop 必须存在真实 citation edge，并通过年份/版本单调性检查。

提供两个显式模式：

- `scinet_v2_baseline`：在可控子图上复现 BFS 连通候选和 maximum cumulative citation path；
- `production_robust_v1`：有界 best-first/k-best path，对 hop、topic drift、citation-age bias 和证据缺口加惩罚。

当前 `citation_evolution_paths()` 的早停 BFS 和 `log1p(citation)/path length` 是实用候选启发式，不是 SciNet exact baseline，因此需保留兼容模式而不冒充复现结果。

候选路径再消费 citation context、claim/contribution continuity 和 scope drift，为每个 hop 生成 coherence record。只有所有 hop 连通、端点正确、关键跳转有证据且整体主题连续时，才标为 `verified`。embedding 可用于主题漂移惩罚，不能补造断开的 hop。

评测保留 SciNet 三个维度：Consistency（与 ground-truth path 节点重合）、Connectivity（相邻论文显式引用连通）和 Rationality（证据化的逻辑连续性）。对所有 `verified` 路径，Connectivity 必须为 100%。

### 6.13 精细分类 graph：topic hierarchy + 独立 facets

12/54 稳定 taxonomy 和 18/92 candidate taxonomy 只回答“研究什么”。精细分类不应继续无限扩张一棵 topic tree，而应对每个 `Contribution`建立多 facet graph：

| facet | 例子 |
|---|---|
| topic | market microstructure / behavioral text / macro cross-asset |
| contribution type | mechanism / empirical effect / method / measurement / dataset / survey |
| mechanism | information diffusion / inventory risk / attention / risk premium |
| method | causal inference / forecasting / optimization / representation learning |
| asset & market | equity / futures / options / crypto；A-share / US / global |
| frequency & horizon | tick / intraday / daily / monthly |
| data & observable | LOB / trades / news / fundamentals / macro / on-chain |
| estimand/outcome | return / volatility / liquidity / execution / risk / allocation |
| evidence status | theoretical / in-sample / OOS / replication / contradiction / limitation |

分类单位是 contribution，不是整篇 paper。一篇 paper 可以有多个 contribution，每个 contribution 可多标签，但每条 `CLASSIFIED_AS` 都必须保存：

```text
classification_id / contribution_id / facet / label_id
taxonomy_or_ontology_version / classifier_version
evidence_ids[] / confidence / status / reason_codes[]
supersedes_id / artifact_hash
```

分类流程是：上游 evidence-backed candidates -> canonical label mapping -> 父子层级与跨 facet 约束 -> 置信度校准 -> accepted/proposed/gap。标题、摘要、关键词和 OpenAlex topic 只能提供召回 prior。正式分类必须指向 contribution evidence；缺失时进入 `taxonomy_gap_queue`，不得自动新建 label。

### 6.14 存储、索引和增量更新

采用分层存储，避免把数亿条引用边和少量正文 claim 强塞进单一图数据库：

```text
L0  OpenAlex metadata/citations: partitioned Parquet
L1  paper identity + adjacency + field/year statistics: DuckDB build + SQLite read index
L2  selected quant corpus StructuredPaperArtifact: versioned JSONL/Parquet
L3  claim/evidence/contribution/classification tables: Parquet
L4  verified projections + path artifacts + benchmark outputs: immutable snapshots
```

建议的核心表是 `papers`、`paper_versions`、`citations`、`claims`、`evidence_spans`、`citation_contexts`、`contributions`、`classifications`、`claim_relations`、`ego_metrics`、`evolution_paths`和 `graph_snapshots`。

每个 snapshot manifest 固定 OpenAlex release、artifact set hash、taxonomy/ontology version、verifier version、metric policy、path policy 和代码 revision。更新时根据 document/artifact hash 做受影响子图重算，不做全量原地覆盖。

### 6.15 SciNet 实施阶段、文件路线和验收门槛

#### S0：契约和可复现 fixture

- 新增 `schemas/structured_paper_artifact_v1.schema.json`、`src/paper_graph/structured_artifacts.py`和 quarantine report；
- 用合成文章构建 exact citation、co-mention、support、contradiction、replication 和 version-supersede fixtures；
- 锁定 SciNet 公开 Queries/Evaluation 的 commit hash 与本地评测 manifest。

**Gate**：100% 接收 artifact 通过 schema/hash/referential-integrity；坏 artifact 100% quarantine；不允许 silent repair。

#### S1：OpenAlex citation topology 基座

- 新增 `src/paper_graph/citation_index.py`和 `scripts/build_citation_index.py`；
- 建立 canonical paper ID -> dense integer ID mapping、双向 adjacency、year/topic/citation-count side tables；
- 从 `CITES` 中严格分离 co-citation、bibliographic coupling 和 embedding edges。

**Gate**：抽样边可回链 OpenAlex source record；路径索引中零 similarity-created hop；同 snapshot 重建 hash 一致。

#### S2：Ego-centric 指标

- 新增 `src/paper_graph/scinet_ego.py`和 `scripts/compute_scinet_ego_metrics.py`；
- 实现 novelty null model、disruption variant、global/field-year percentiles 和 maturity flags；
- 用小图手算 fixture 和 SciNet Task1 evaluator 做 parity test。

**Gate**：手算 fixture 误差为零；所有 score 可回溯 observation cutoff/null-model hash；与 graph value 字段物理分离。

#### S3：Pair-wise context/claim graph

- 新增 `src/paper_graph/citation_contexts.py`、`src/paper_graph/relation_verifier.py` 和 `scripts/build_pairwise_relations.py`；
- 先输出 SciNet-compatible sentiment/co-mention records，再输出 `ClaimRelationV1`；
- 将现有 `enrich_graph_claim_relations.py` 改为最后投影步骤，不负责猜测缺失 evidence。

**Gate**：100% 正式 epistemic edge 有双侧 evidence、双 document version、scope alignment 和 verifier；所有非 verified relation 投影数为零。

#### S4：Path-wise 候选和已核验演化路径

- 扩展 `relation_aware_retrieval.py`，拆分 exact baseline、production scorer 和 coherence verifier；
- 新增 `schemas/evolution_path_artifact_v1.schema.json`、`scripts/build_evolution_paths.py` 和 SciNet Task3 adapter；
- 对 classic/emerging endpoints 保存所有检索限制、裁剪理由和 hop evidence。

**Gate**：`verified` 路径 Connectivity=100%；任一断边、时间倒置或无证据关键跳转均不得晋级；SciNet 评测输出可复算。

#### S5：Faceted classification graph

- 新增 `configs/quant_research_facets_v1.json`、`schemas/contribution_classification_v1.schema.json` 和 `src/paper_graph/classification_graph.py`；
- 建立 18/92 topic 与 OpenAlex topics 的版本化 crosswalk，另建 contribution/method/asset/frequency/data/estimand/evidence facets；
- 新增 `scripts/build_classification_graph.py` 和 taxonomy-gap report。

**Gate**：100% accepted classification 绑定 contribution evidence和taxonomy/classifier version；层级冲突为零；无 evidence 的关键词命中只能停在 candidate。

#### S6：统一评测与下游交付

- 新增 `scripts/evaluate_scinet_reproduction.py` 统一输出 Task1/2/3 metrics、coverage、latency 和 failure taxonomy；
- 生成 `ScientificRelationGraphV1` 和 `FacetedClassificationGraphV1` immutable manifests；
- 只将已固定 snapshot 传给 graph value controller 和 Auto-Research。

**Gate**：官方 SciNet evaluator 的格式/指标 parity 测试通过；查询结果能回链到 paper -> document version -> claim/context -> evidence -> relation/path/classification；下游无法修改上游 snapshot。

#### S7：角色化 seed portfolio

- 新增 `schemas/seed_candidate_v1.schema.json`、`src/paper_graph/scientific_seed_selection.py` 和 `scripts/select_scientific_seeds.py`；
- 分开计算 authority、novelty/frontier、replication/critique 和 method/data bridge 角色；
- 按细分主题、年代、作者/机构/期刊去重和角色配额选择 seed portfolio；
- 为 path-wise 任务生成 `authoritative_classic -> novel_emerging` 端点对。

**Gate**：seed 分数可回链 citation snapshot/metric/artifact；权威与新颖两类均有覆盖；撤稿、无法解析身份或证据未就绪的论文不得成为正式 seed；同一作者群或期刊不得垄断一个 topic graph。

实施依赖为：S0 先行；S1 完成后 S2 与 S4-topology 可并行；S3 和 S5 的正式产物等待真实 `StructuredPaperArtifact`，但可先用 fixture 完成；S7 先用 S1/S2 产出结构 seed，再在 S3/S5 后增加证据和角色 seed；S6 最后收口。第一个可验收竖切片应限制在 200–500 篇量化论文、1个细分主题、至少1组 support/contradiction/replication 关系和5条 evolution paths，通过后再扩到全部候选语料。

### 6.16 Paper Digest New2 应输出什么

当前 `reading_note_v1` 以 `central_claim` 单字符串、自由文本 `method_logic`、整体评分和 chunk notes 为主，适合人阅读和旧下游，但不足以稳定构建 claim/context/contribution graph。新版不删除 `reading_note_v1`，而是把它降为从 `StructuredPaperArtifactV1` 派生的 compatibility summary。

#### 6.16.1 责任分解

| 输出内容 | 权威生产者 | LLM 是否可修改 |
|---|---|---|
| paper identity、document version、content hash | 解析/导出器 | 否 |
| section/page/TeX/offset locator、exact quote | 解析器 | 否 |
| citation marker -> bibliography target | 解析器 + identity resolver | 否，不确定时输出 unresolved |
| claim 归一化、claim type、scope | Digest LLM | 可，但必须引用 evidence IDs |
| citation intent/sentiment/relation proposal | Digest LLM | 可，但不能直接 verified |
| contribution 拆分与 facet candidates | Digest LLM | 可，但必须引用 claim/evidence |
| novelty/disruption/authority/PageRank | Paper Graph | 否，Digest 不得自评 |
| factor 是否有效/可部署 | Auto-Research/审批层 | Digest 不得输出为论文事实 |

#### 6.16.2 主产物的十个必要区块

1. **Artifact provenance**
   
   `artifact_id`、`schema_version`、`producer_revision`、`model_id`、`prompt_hash`、`extraction_config_hash`、`created_at`、`supersedes_artifact_id`。

2. **Document identity and quality**
   
   canonical paper/OpenAlex/arXiv/DOI IDs、document version、content hash、source type/language、parse coverage、OCR/TeX/GROBID warnings、missing sections、reference-resolution coverage。

3. **Section map**
   
   `section_id`、normalized type（abstract/introduction/method/data/results/discussion/limitations/appendix）、heading、ordinal、source locator。

4. **Stable evidence spans**
   
   `evidence_id`、section/page/TeX/character locator、exact quote、quote hash、evidence role（claim/method/data/result/limitation/citation context）。摘要和转述不能当 exact evidence。

5. **Typed claims**
   
   每条 claim 独立输出 `claim_id`、`claim_type`、`normalized_statement`、`subject/predicate/object`、`polarity`、`author_assertion_status`、`evidence_ids[]`、`scope`、`uncertainty`。`claim_type` 至少包含 research question、hypothesis、theory、method、data、empirical result、null result、robustness、limitation、external-validity boundary。

6. **Study design and result records**
   
   dataset、sample/universe、market/asset/geography、time range、frequency、split/OOS status、baseline、treatment/exposure、target/estimand、metric、effect direction/size/unit、standard error/interval/p-value（仅原文披露时）、robustness test 和 evidence IDs。作者结论与 Digest 的 critical assessment 必须分字段。

7. **Formula, method, variable and data entities**
   
   公式原文/归一化表达、变量原名与 canonical observable candidate、输入/输出、单位、滞后和可得时间、method/dataset/code identifiers、实现约束和 evidence IDs。

8. **Citation contexts**
   
   每个 context 输出 citing paper/version、paragraph/evidence ID、文中 marker、resolved/unresolved cited IDs、同段 co-mentioned IDs、citation intent（background/uses/compares/extends/replicates/criticizes）、sentiment（positive/negative/neutral/mixed/unclear）和 relation proposals。提案不得写 `verified`。

9. **Contribution records**
   
   一篇文章可拆为多个 contribution。每个 contribution 输出 `contribution_type`、claim/evidence IDs、mechanism、method、dataset/observable、scope、topic/facet candidates、novelty statement（仅“作者声称新颖”）、limitations 和 not-disclosed fields。

10. **Internal links and quality audit**
    
    `claim -> evidence`、`result -> method/dataset`、`contribution -> claims`、`citation context -> cited paper`、文内 claim 间 supports/qualifies/conflicts proposals，外加 coverage、faithfulness、referential-integrity、unresolved identity、unsupported inference 和 missing-evidence reports。

#### 6.16.3 推荐输出外壳

```json
{
  "schema_version": "structured_paper_artifact_v1",
  "provenance": {},
  "paper": {},
  "document": {"sections": [], "quality": {}},
  "evidence_spans": [],
  "claims": [],
  "study_designs": [],
  "results": [],
  "formulas": [],
  "entities": {"methods": [], "datasets": [], "variables": [], "observables": []},
  "citation_contexts": [],
  "contribution_records": [],
  "internal_relation_proposals": [],
  "quality_audit": {},
  "compatibility_views": {"reading_note_v1": {}}
}
```

Digest exporter 应该同时输出上述 artifact 和现有 `ResearchArtifactEnvelopeV1`，但 envelope 只是过渡包装。LLM prompt 必须允许空数组、`unknown`、`not_disclosed` 和 `unresolved`；不能为了 schema 完整而补写原文没有的数字、数据集、引用目标或结论。

#### 6.16.4 LLM 工作流采用两阶段通用版本，不再设置 LLM 忠实度审核

Paper Digest New2 的生产主链调整为：

```text
parser / external paper structurer
  -> stable sections + evidence spans + citation contexts
  -> LLM 1: evidence-grounded reading / factual extraction
  -> LLM 2: generic Graph and Auto-Research interpretation
  -> deterministic schema, reference and semantic-boundary validation
  -> artifact publisher + compatibility views
```

不再调用第三个 LLM 审核前两个 LLM 的忠实度。原因不是降低证据要求，而是避免让另一个生成模型充当最终真值裁判；生产门槛改由可复算的确定性检查承担，包括 schema、枚举、稳定 ID、claim/evidence 外键、quote hash、document version、relation `proposed` 状态、contribution evidence coverage，以及 `AUTHOR_REPORTED`、`DIGEST_NORMALIZED`、`DIGEST_DERIVED`、`DIGEST_PROPOSED`、`NOT_DISCLOSED` 之间的语义边界。

第二阶段首版只实现一个通用 prompt，适用于任意 graph 的 paper，并接受可选 `graph_context`：graph/snapshot ID、research question、seed role、topic candidates、neighbor paper IDs 和已有 relation context。未来可以按 graph 增加专门 prompt，但专门 prompt 必须是同一 schema 上的可选策略，不能改变 contribution type、observable ontology、证据要求或下游执行权限。首版明确输出 `specialized_prompt_used=false`。

第二阶段的权威输出是 `research_contributions[]`、`relation_candidates[]`、`research_ideas[]` 和 `graph_research_summary`。旧 `article_opinions` 仅作为页面兼容视图；所有 idea 固定为 `DIGEST_PROPOSED`，所有跨论文关系固定为 `proposed`。Paper Digest 不输出本地字段映射、数据路径、IC/Sharpe 结论、verified epistemic relation 或 Agent Alpha 执行许可。

### 6.17 权威论文、新颖论文与角色化 seed 选择

seed 不应是单一排名的 top-N。权威论文适合定义知识边界和发展起点，新颖论文适合定义前沿端点，复现/反驳/方法论文则提高 relation graph 的信息量。

#### 6.17.1 seed 角色

```text
AUTHORITATIVE_ANCHOR   # 领域权威锚点
SEMINAL_FOUNDATION     # 演化路径的经典起点
FRONTIER_NOVEL         # 新颖结构/机制的前沿论文
EMERGING_HIGH_POTENTIAL# 引用未成熟但增速/结构异常的新论文
REPLICATION_ANCHOR     # 复现或外部验证
CONTRADICTION_ANCHOR   # 反驳、失败复现或边界条件
METHOD_BRIDGE          # 跨主题方法桥
DATASET_BRIDGE         # 关键数据/测量桥
REVIEW_MAP             # 仅作导航，不作原始 claim 权威替代
```

同一 paper 可有多个角色，但每个角色都需独立的 metric/evidence reason。

#### 6.17.2 authority 评分

不直接使用 raw citation count。初版可配置为：

```text
0.25 field-year normalized citation percentile
0.20 citation-network PageRank/HITS authority
0.15 citation longevity/persistence
0.15 co-citation/betweenness centrality
0.15 verified relation + evidence readiness
0.10 reference/identity/document coverage
```

评分必须固定 citation cutoff 并保存 maturity。期刊声望、作者机构和 LLM 的“经典”判断不得作为必要条件。review 可作 `REVIEW_MAP`，但不得因高引用而取代原始研究锚点。

#### 6.17.3 novelty/frontier 评分

初版可配置为：

```text
0.30 Uzzi atypical-combination novelty percentile
0.25 disruption percentile（只对已成熟年龄）
0.15 cross-topic bridge score
0.15 field/year normalized recent citation acceleration
0.15 evidence-backed contribution/mechanism distinctiveness
```

对最近论文，disruption 和长期引用不成熟，必须输出 `provisional_frontier=true`，主要依赖 reference-combination novelty、cross-topic bridge、贡献与现有 claim graph 的距离和早期增速；不得把“发表时间新”等同于“科学新颖”。

#### 6.17.4 eligibility 和多样性约束

正式 seed 至少要求：

- canonical identity 已解析，不是 retracted/paratext；
- 量化金融分类为 accepted，或有已核验的跨域 bridge reason；
- 有标题、年份和最低引用结构覆盖；
- Digest 主张/关系 seed 需有可用 structured artifact；纯 topology seed 可先标 `structure_only`；
- 所有 score 固定 snapshot、policy version 和 reason codes。

每个细分主题的初始 portfolio 目标是 8 个：2个 authority/seminal、2个 frontier/emerging、1个 replication、1个 contradiction/boundary、1个 method/data bridge 和1个机动名额。稀疏主题允许缺位，不能用低质量论文强行填满。

多样性约束至少包括同一作者群最多2篇、同一期刊/会议最多2篇、同年代不得全部占据、至少覆盖一个方法或数据桥。embedding 可用于去重和多样性惩罚，不得生成 authority/novelty 真值。

#### 6.17.5 `SeedCandidateV1`

```text
seed_candidate_id / paper_id / snapshot_id
topic_ids[] / seed_roles[] / eligibility_status
authority_components / novelty_components / relation_components
evidence_readiness / maturity / provisional_frontier
metric_refs[] / structured_artifact_refs[]
selection_reasons[] / exclusion_reasons[]
policy_version / selected_portfolio_id / supersedes_id
```

authority 和 novelty 保留两个分数，不强行合成一个“好论文分数”。主题 graph 扩展时，authority seed 主要向 predecessors/descendants 扩展，frontier seed 主要向 prior art 和相邻新 contribution 扩展，replication/contradiction seed 主要走 verified epistemic edges。path-wise 优先配对 `SEMINAL_FOUNDATION/AUTHORITATIVE_ANCHOR` 与 `FRONTIER_NOVEL/EMERGING_HIGH_POTENTIAL`。

### 6.18 SciNet 与外部科学计量代码的复用边界

仓库已经存在 SciNet checkout，2026-08-11 核对时本地和远端 HEAD 均为 `ed5c76fb250a4face6224ea834a62e63b47ddabd`。另外引入 pySciSci 0.92 的固定源码包作为小样本公式基准；所有来源、hash、许可状态和允许用途记录在 `configs/scientometrics_references_v1.json`。

#### 6.18.1 审计结论

| 来源 | 可复用部分 | 不直接复用部分 | 决策 |
|---|---|---|---|
| SciNet | Queries、任务拆分、输入输出格式、评测行为 | 硬编码路径、API 调用、随机 path shuffle、依赖预计算 z-score 的 novelty、简化 disruption | 兼容 fixture 与 evaluator adapter；不作生产依赖 |
| pySciSci 0.92 | Uzzi novelty/conventionality、含 `Ni/Nj/Nk` 的 disruption、PageRank 等公式和小图实现 | 面向内存 DataFrame 的全量计算、未固定随机种子的默认调用 | MIT 源码保留归属；仅作 deterministic parity oracle 和算法参考 |
| Novelpy 1.4 | 多种 novelty 与 disruptiveness 变体、单元测试 | MongoDB/JSON 工作流；PyPI metadata 未给上游仓库 | 固定 sdist hash 的可选第二 oracle，不 vendor、不作生产依赖 |
| cdindex / fast-cdindex | disruption 行为和性能设计参考 | GPL 代码链接、复制或导入 | 当前不克隆、不依赖；未来使用前单独作许可决策 |

SciNet 的 novelty evaluator 只对外部 `z_score` Parquet 求论文参考组合的 p10，本身没有构建 null model；其 disruption evaluator 未计入只引用 focal references 的 `Nk`；path connectivity 还尝试反转和随机排列。因此“通过该脚本”只代表格式兼容，不能代表指标科学定义或生产路径验证已经正确。

#### 6.18.2 生产指标合同

生产实现必须独立于第三方运行时，并固定以下语义：

- `uzzi_journal_pair_p10_v1`：按 citing year 计算 cited-source pair；null model 保持论文参考数、来源频率和被引文年份分层，保存随机种子、样本数、null-model hash、有效 pair coverage，同时输出 p10 与 median；
- `disruption_funk_windowed_v1`：显式保存 `Ni`、`Nj`、`Nk`、citation/reference window、observation cutoff 和 maturity；SciNet 简化式仅作为 `scinet_compat_disruption` 另列，不可覆盖正式字段；
- `field_year_citation_percentile_v1`：按 taxonomy/OpenAlex field 与发表年归一化，保存 field mapping 与 citation cutoff；
- `citation_pagerank_v1`、`hits_authority_v1`、`citation_longevity_v1` 和 centrality 指标都必须保存图 snapshot、阻尼/窗口/收敛参数和 coverage；
- 任一指标无法满足最小引用覆盖或成熟期时，输出 `unavailable/provisional` 和 reason code，不用零分冒充真实低值。

全量计算采用分区 Parquet + DuckDB/批处理 sparse graph；pySciSci/Novelpy 只在合成图和 200–500 篇竖切片上运行。相同 fixture 要同时跑 production implementation、手算 expected value 和至少一个许可允许的 oracle，并将差异归因到明确的 metric variant，而不是为了追求数值相同而模糊定义。

#### 6.18.3 对实施阶段的补充

- S0 增加 external-reference manifest 校验、许可 gate 和 SciNet query manifest；任何未固定版本的外部结果不得进入测试基线；
- S2 先实现 `scinet_compat_*` adapter 复现公开 evaluator 行为，再实现上述正式 variant；两组字段和报告物理分离；
- S2 Gate 增加 pySciSci deterministic fixture parity、不同随机种子的稳定性区间、窗口/cutoff/maturity 回归测试；
- S4 connectivity 必须按返回顺序逐跳验证真实 `CITES`，不得继承 SciNet evaluator 的随机重排；兼容评测结果和严格结果同时报告；
- S7 authority/frontier 选择只消费正式 variant；兼容分数、LLM 判断、期刊/机构声望不能直接决定 seed。

这样既利用 SciNet 的公开任务和成熟科学计量包减少重复试错，又不把评测脚本的简化假设、第三方内存瓶颈或许可风险带入精细 graph。

## 7. 因子变异在 Auto-Research 中的位置

### 7.1 变异是研究的一部分，但不是无约束公式搜索

变异的目的应是回答科学问题：机制是否存在、在哪些状态成立、对 proxy/尺度是否稳健、为什么失败。它必须发生在 exploration/validation 阶段，并受搜索预算和 multiplicity ledger 约束。

### 7.2 变异分类和身份规则

| 类型 | 例子 | 是否新 experiment | 是否新 hypothesis | 是否计入科学搜索预算 |
|---|---|---:|---:|---:|
| implementation repair | 语法、类型、字段名、NaN 防护 | 否，新增 attempt | 否 | 否；计工程 retry |
| parameter refine | 窗口、clip、阈值 | 是 | 否 | 是 |
| representation refine | zscore、rank、差分、平滑 | 是 | 通常否 | 是 |
| state conditioning | 高波动/低流动性条件 | 是 | 条件未预注册时需 child hypothesis | 是 |
| horizon mutation | ret30s -> ret60s | 是 | 若机制时间尺度改变则是 | 是 |
| proxy substitution | direct -> derived/weak proxy | 是 | weak proxy 必须新建 proxy hypothesis | 是 |
| mechanism pivot | 从 order-flow pressure 改为 liquidity replenishment | 是 | 是 | 是 |
| evidence expansion | 增加支持/反驳论文 | 新 version | 可能 | 是 |
| crossover | 合并两个父机制 | 是 | 原则上是 | 是 |

### 7.3 mutation 输入

mutation agent 只能看到：

- hypothesis 和允许的 evidence refs；
- exploration/validation aggregate；
- implementation diagnostics；
- 因子覆盖率、稳定性、方向和成本诊断；
- run-local negative memory；
- 经过 scope 过滤的 verified transfer memory；
- 剩余预算和允许的 mutation 类型。

它不能看到：

- locked-test 结果；
- 其他 run 的未验证自由文本结论；
- 未来日期数据；
- 不可用字段或未授权算子；
- 没有 evidence provenance 的“最佳实践”。

### 7.4 mutation 决策

每次变异产生 `MutationDecisionV1`：

```text
mutation_id
research_run_id
parent_hypothesis_ids[]
parent_factor_instance_ids[]
mutation_class
changed_dimensions[]
kept_mechanism
new_mechanism_claim
evidence_ids[]
diagnostic_inputs[]
expected_improvement
invalidating_result
budget_charge
child_hypothesis_id / child_experiment_id
```

### 7.5 何时停止变异

满足任一条件即停止当前 lineage：

- hypothesis 被明确否证；
- 连续预注册轮次没有超过 baseline/parent 的最小改进；
- 只有通过 weak proxy 才能继续且未获批准；
- 覆盖率、成本或稳定性存在结构性失败；
- 与 Alpha Library 高度重复且无增量价值；
- 搜索/LLM/计算预算耗尽；
- 所有候选改善只来自单一股票、日期或 regime；
- 继续搜索需要查看 locked test；
- evidence critic 判定机制与公式已经脱离来源证据。

停止不等于删除。lineage 进入 `REFUTED`、`INCONCLUSIVE`、`DUPLICATE`、`DATA_UNAVAILABLE` 或 `BUDGET_EXHAUSTED`，并进入负结果档案。

## 8. 记忆设计

### 8.1 原则：artifact 是事实，memory 是索引和压缩

LLM 生成的 memory summary 不是事实源。事实源必须是不可变的：

- evidence artifact；
- preregistration；
- rendered factor 和 config；
- run attempt 和 Slurm log；
- raw/aggregate metrics；
- review decision；
- lineage/event journal；
- 内容哈希和 producer revision。

Memory 只用于检索、归纳和下一轮决策，任何 memory claim 必须能回链到上述 artifact。

### 8.2 三层记忆

#### A. Run-local memory

只在当前 `FactorResearchRun` 内可见：

- evidence retrieval trace；
- hypothesis proposal/review；
- 所有 candidate 和 mutation；
- implementation failure/repair；
- exploration/validation 诊断；
- lineage stop reason；
- 预算消耗；
- 尚未复验的临时经验。

Run-local memory 默认不能跨 run 自动复用。

#### B. Project-scoped memory

按市场、数据源、频率和字段 registry 限定：

- A 股 L2 字段语义；
- 特定 fac-eval operator 的已验证行为；
- 稳定的缺失值/覆盖率处理；
- 数据版本特有的陷阱；
- 重复出现的 implementation repair；
- 同一研究主题内经过多个 run 验证的 proxy 质量。

它不能自动迁移到不同市场、不同频率或不同数据供应商。

#### C. Verified global transfer memory

只保存经过 promotion gate 的可迁移经验：

- schema/编译/算子层的确定性规则；
- 跨多个独立 run 验证的机制边界；
- 稳定 mutation arm 的适用条件和失败条件；
- 严格定义的风险、泄漏和数据质量规则。

全局记忆保存适用范围和反例，不保存“某公式永远有效”之类绝对结论。

### 8.3 记忆记录类型

```text
EvidenceUseRecordV1
HypothesisDecisionRecordV1
ExperimentOutcomeRecordV1
MutationOutcomeRecordV1
ImplementationRepairRecordV1
NegativeResultRecordV1
VerifiedMechanismPatternV1
ProxyReliabilityRecordV1
DataQualityRuleV1
LibrarySimilarityRecordV1
```

每条至少包含：

```text
memory_id
memory_type
scope                         # run | project | global
market / asset / frequency
data_version / registry_version
source_artifact_ids[]
source_run_ids[]
hypothesis/factor/experiment refs
claim
supporting_conditions[]
counterexamples[]
confidence
promotion_status
created_at / last_validated_at
expires_or_revalidate_after
content_hash
```

### 8.4 promotion gate

不同记忆采用不同晋升标准：

- **确定性 implementation repair**：单元测试 + 至少一次真实受控执行可晋升 project scope；
- **字段/数据质量规则**：需要字段 schema 证据、统计诊断和数据版本约束；
- **proxy 可靠性**：需要至少两个独立研究 run 或一次专门 proxy validation；
- **mutation 策略**：需要多个独立 lineage，报告成功率、失败率和适用条件；
- **机制经验**：至少需要非重叠时间块、多个股票/子集、锁定测试和稳健性证据；跨市场前保持 project scope；
- **负结果**：一次严格预注册的否证可保存，但只在原 scope 内生效；重复否证后才能扩大 scope。

具体次数是可配置 gate，不是普适统计定律；每次晋升必须保存采用的 policy version。

### 8.5 防止记忆污染

- 候选生成阶段不能检索 locked-test outcome；
- 未验证 LLM 总结不得进入 global memory；
- run-local “BAD” 标签不得覆盖全局定义；
- 相同数据切分上的多次 mutation 不能被伪装成独立证据；
- memory retrieval 必须过滤 market/frequency/data/as-of scope；
- 过期或数据版本变化的经验标为 `stale`，不得静默继续使用；
- memory summary 重新生成时不能删除原始 records；
- 冲突记忆并存，并保存适用条件，不使用最后写入覆盖；
- Alpha Library 只保存通过 admission 的候选，所有研究历史另存 Research Archive。

### 8.6 三项目分别保存什么

**Paper Graph：**

- paper/claim/relation identity；
- prior-art 检索记录；
- research opportunity 和 graph selection trace；
- 论文/claim 对成功或失败 hypothesis 的贡献；
- 待扩展邻域、复现、反驳和 Digest 队列；
- 不复制大体量 fac-eval 输出，只保存稳定引用和摘要。

**Paper Digest New2：**

- 文档版本、解析 provenance、evidence spans；
- evidence faithfulness/audit；
- 变量、公式、机制和缺失证据；
- Agent Alpha 返回的 evidence useful/not-useful、proxy gap 和补证据请求；
- 不保存 Alpha admission 决策为自己的事实。

**Agent Alpha：**

- FactorResearchRun event log；
- hypothesis/experiment/candidate/attempt/metric/review；
- lineage、mutation outcome 和 negative results；
- factor identity、Research Archive、Candidate Alpha Library、Deployment Registry；
- run-local/project/global memory 及 promotion record。

### 8.7 Memory 不是一种文件：正式分类

实现时不要继续把所有信息统称为 `memory`。至少分成以下十三类，并明确哪些是事实、哪些是可重建视图：

| memory 类型 | 内容 | 事实/视图 | 默认 scope | 是否可直接进入 prompt |
|---|---|---|---|---|
| Evidence-use memory | 本次使用了哪些 paper/claim/evidence，如何使用 | 事实 | run | 只传必要引用 |
| Hypothesis-decision memory | proposal、gate、approve/reject/pivot 理由 | 事实 | run | 可传摘要 |
| Experiment-outcome memory | preregistration、aggregate、review、结论 | 事实引用 | run | 只传 exploration/validation 结果 |
| Negative-result memory | 严格失败、否证、重复、数据不可用 | 事实 | run/project | 可传 scope 内规则 |
| Implementation-repair memory | 编译、字段、NaN、执行失败和确定性修复 | 事实 | run/project | 可以，不能当科学结果 |
| Proxy-reliability memory | 论文变量到本地字段的映射及 approximation loss | 事实+审查 | project | 可以，必须带 scope |
| Mutation-outcome memory | parent -> operation -> child -> delta | 事实 | run | 可以，必须过滤 stage |
| Mutation-policy memory | 某类 mutation 在相似条件下的统计表现 | 可重建聚合 | project/global | 可以，需达到最小样本 |
| Function/operator memory | ASL/字段/窗口模式的失败、修复、适用条件 | 晋升后的规则 | project/global | 可以，必须有 provenance |
| Feature-definition memory | 新计算字段的定义、输入、单位、窗口和论文来源 | 事实 | project | 可以，需为 approved feature |
| Feature-validation memory | 计算一致性、时序、覆盖、测量有效性和稳定性 | 事实 | run/project | 可传验证摘要 |
| Feature-augmentation memory | feature 加入父因子后的 paired 增量、失败条件和 operator | 事实/聚合 | run/project | validation 可见，locked test 不可见 |
| Retrieval/summary memory | 为 prompt 构建的短上下文和 LLM summary | 可重建视图 | snapshot | 可以；不是事实源 |

另有三类库不应再叫普通 memory：

- `Research Archive`：完整研究历史；
- `Candidate Alpha Library`：通过科学 admission 的候选；
- `Deployment Registry`：通过独立运营审批的部署记录。

### 8.8 权威存储布局

#### 8.8.1 每个 run 的不可变事实

```text
outputs/factor_research/run_id=<research_run_id>/
  manifest.json
  events/
    checkpoint.json
    events.jsonl
  artifacts/
    hypotheses/<hypothesis_id>.json
    experiments/<experiment_id>/preregistration.json
    attempts/<run_attempt_id>/attempt.json
    attempts/<run_attempt_id>/stdout.log
    attempts/<run_attempt_id>/stderr.log
    metrics/<metric_artifact_id>/raw_ref.json
    metrics/<metric_artifact_id>/aggregate.json
    reviews/<review_id>.json
  memory/
    evidence_use.jsonl
    hypothesis_decisions.jsonl
    experiment_outcomes.jsonl
    negative_results.jsonl
    implementation_repairs.jsonl
    proxy_assessments.jsonl
    feature_definitions.jsonl
    feature_validations.jsonl
    feature_augmentation_outcomes.jsonl
    mutation_outcomes.jsonl
    retrieval_traces.jsonl
    promotion_proposals.jsonl
    views/
      prompt_memory.json
      function_memory.jsonl
      transfer_memory.jsonl
      specialist_agents/<agent>.jsonl
      mutation_arm_stats.json
    snapshots/
      <memory_snapshot_id>.json
```

原则：

- `artifacts/` 和 `events/` 是权威事实；
- `memory/*.jsonl` 是只追加、带 artifact refs 的结构化事实索引；
- `memory/views/` 可删除、可重建，不得反向成为科学结论；
- worker 不并发 append 同一个 JSONL；每个 worker 只写自己的 attempt 目录；
- orchestrator 在 attempt 完成后单写者 ingest，并更新 event checkpoint；
- 任何 summary 都必须保存 `source_record_ids[]` 和 `source_artifact_ids[]`。

#### 8.8.2 Project-scoped memory

```text
data/memory/project/
  scope=<scope_id>/
    records/
      <memory_id>.json
    index.jsonl
    promotion_events.jsonl
    retractions.jsonl
    snapshots/
      <snapshot_id>.json
```

`scope_id` 由以下字段的规范哈希生成：

```text
market
asset_class
data_provider
data_schema_version
frequency
field_registry_version
operator_registry_version
label_family
```

缺少 scope 字段的历史记录只能进入 `scope=legacy_unscoped`。

#### 8.8.3 Verified global memory

```text
data/memory/global/
  records/<memory_id>.json
  index.jsonl
  promotion_events.jsonl
  retractions.jsonl
  snapshots/<snapshot_id>.json
```

Global memory 主要保存确定性工程规则和经过多 scope 验证的条件性经验，不保存具体 alpha 公式的“永远有效”判断。

### 8.9 统一 memory record schema

在 Agent Alpha 新增 `MemoryRecordV1`。所有正式 memory 类型共享 envelope：

```text
schema_version: memory_record_v1
memory_id                         # 由 immutable identity payload 确定性生成
memory_type
scope_level                      # run | project | global
scope_id
research_run_id
source_record_ids[]
source_artifact_ids[]
source_event_ids[]
paper_ids[] / evidence_ids[]
hypothesis_ids[]
factor_definition_ids[]
factor_instance_ids[]
experiment_ids[] / run_attempt_ids[]
stage                            # implementation | exploration | validation | locked_test | robustness
claim
conditions[]
counterexamples[]
metrics_summary                  # 只保存 verified aggregate 的引用和小摘要
confidence
promotion_status                # local | proposed | approved | rejected | retracted | stale
policy_version
as_of_date
created_at / last_validated_at
revalidate_after
content_hash
```

子类型 payload 示例：

```text
MutationOutcomePayloadV1:
  parent_factor_instance_id
  child_factor_instance_id
  mutation_class
  changed_dimensions[]
  parent_metric_ref
  child_metric_ref
  paired_delta
  uncertainty
  success_definition
  multiplicity_family_id

ImplementationRepairPayloadV1:
  failure_class
  failure_fingerprint
  failing_artifact_id
  repair_operation
  validation_test_refs[]
  scientific_result_unchanged: true

ProxyReliabilityPayloadV1:
  paper_variable
  local_proxy
  proxy_strength
  approximation_loss
  temporal_compatibility
  validated_run_ids[]
  known_failure_conditions[]

FeatureValidationPayloadV1:
  feature_definition_id
  implementation_parity_refs[]
  temporal_validation
  finite_and_coverage_summary
  measurement_validity_refs[]
  stability_summary
  runtime_cost_summary

FeatureAugmentationOutcomePayloadV1:
  feature_definition_id
  parent_factor_definition_id
  child_factor_definition_id
  composition_operator
  parent_metric_ref
  child_metric_ref
  paired_incremental_metrics
  complexity_and_runtime_delta
  feature_ablation_result
  multiplicity_family_id
```

`memory_id` 不能继续使用随机 UUID 作为权威身份。随机 ID 可以用于临时消息，但正式 record ID 应由 `memory_type + scope + source refs + normalized claim/payload` 哈希生成，从而支持幂等 ingest。

### 8.10 Agent Alpha：现有文件如何改造

#### `src/agent_alpha/graph_research/events.py`

保留并扩展为 run 的权威事件链：

- 新增 `MEMORY_RECORD_CREATED`、`MEMORY_PROMOTION_PROPOSED`、`MEMORY_PROMOTED`、`MEMORY_RETRACTED`、`MEMORY_SNAPSHOT_FROZEN` 事件；
- event payload 只保存 record/artifact ID 和 hash，不嵌入大 metrics；
- 禁止绕过事件链直接改变 promotion status；
- 保持确定性 event ID 和 previous-event chain。

#### `src/agent_alpha/graph_research/checkpoint.py`

保留 atomic checkpoint：

- checkpoint 增加 memory head/snapshot ID；
- load 时校验引用的 memory record 是否存在且 hash 匹配；
- checkpoint 只负责恢复，不承担长期 memory 检索；
- 不能因为 view 丢失而判定 checkpoint 损坏，view 应可重建。

#### `src/agent_alpha/contracts/memory.py`（新增）

定义：

- `MemoryScopeV1`；
- `MemoryRecordV1`；
- 上述各 subtype payload；
- `PromotionProposalV1`；
- `PromotionDecisionV1`；
- `MemorySnapshotV1`；
- 确定性 identity/content hash；
- 严格枚举和 `from_mapping/to_dict`。

不要让各 store 自己发明字段和 schema version。

#### `src/agent_alpha/memory/record_store.py`（新增）

实现权威 store：

- 按 `memory_id` 写 content-addressed 单记录 JSON；
- 临时文件 + atomic rename；
- 同 ID 不同内容时 fail closed；
- 校验 schema、content hash、source refs；
- 构建/重建 `index.jsonl`；
- 不提供任意原地 update；状态改变写 promotion/retraction event；
- 支持 run/project/global 三种 root。

#### `src/agent_alpha/memory/jsonl_store.py`

保留给兼容 registry 和可重建 index，但需要：

- 增加可选 schema validator；
- 增加 deterministic ID factory；
- 明确 `append` 不是多进程安全；
- 不再用于多个 Slurm worker 共同写权威事实；
- 读取时验证 schema version，不能混合 V1/V2 后静默返回；
- 分页/limit 应明确 newest/oldest 顺序；
- filters 增加 scope/stage/as-of 的严格匹配测试。

#### `src/agent_alpha/memory/run_memory.py`（新增）

从 event/artifact 生成 run-local records：

- `record_evidence_use()`；
- `record_hypothesis_decision()`；
- `record_experiment_outcome()`；
- `record_negative_result()`；
- `record_implementation_repair()`；
- `record_proxy_assessment()`；
- `record_feature_definition()`；
- `record_feature_validation()`；
- `record_feature_augmentation_outcome()`；
- `record_mutation_outcome()`；
- 保证同一个 event 幂等投影；
- 只引用 verified aggregate，不复制 raw parquet。

#### `src/agent_alpha/memory/evaluation_store.py`

当前 `evaluation_record_v1` 继续作为兼容 reader。新路径应：

- 将 `factor_id/run_id/metrics` 扁平记录升级为带 `factor_instance_id/experiment_id/stage/metric_artifact_id` 的 outcome；
- 拒绝未聚合 stock row；
- 拒绝缺失 data/split/config hash 的科学结果；
- 旧记录迁移为 `legacy_unscoped`，不能用于 promotion 或 library admission；
- 最终可由 `run_memory.py` 统一写入，原模块仅保留 adapter。

#### `src/agent_alpha/memory/experiment_memory_writer.py`

当前 `GOOD/BAD/REVISE` 只能作为 UI/提示词摘要。需要：

- 输入 `FactorEvaluationAggregateV1` 和 review，而不是任意 metrics dict；
- implementation failure 与 scientific rejection 分开；
- `GOOD` 不能自动生成“worked”全局原则；
- 保存 scope、stage、source IDs、expected direction 和 uncertainty；
- `write_feedback_memory()` 改成生成 run-local view，不覆盖权威 records；
- locked-test feedback 标记 `prompt_visibility=forbidden`。

#### `src/agent_alpha/memory/feedback_memory.py`

降级为兼容/检索 view：

- 路径迁移到 run 的 `memory/views/feedback_memory.jsonl`；
- 默认只检索当前 run；
- 增加 scope/stage/promotion filters；
- 禁止把 `GOOD/BAD` 标签本身作为 admission 依据；
- 不再把所有历史 `data/feedback_memory/good_bad.jsonl` 自动注入生成 prompt。

#### `src/agent_alpha/memory/function_memory.py`

保留接口，但改变含义：

- run 内文件是 function observation view；
- project/global 文件只读取 `promotion_status=approved` 的正式规则；
- 每条必须包含 ASL pattern、适用 scope、source outcome refs、反例和验证日期；
- NEUTRAL proposal 不进入跨 run 检索；
- operator repair 与经济有效性分开保存。

#### `src/agent_alpha/memory/transfer_memory.py`

从“父子公式文本”升级为科学 mutation outcome view：

- 保存 parent/child `factor_instance_id`，不能只用易冲突的 `factor_id`；
- delta 使用同 stage、同 split、paired aggregation；
- 保存 uncertainty 和 multiplicity family；
- implementation retry 不写 transfer memory；
- validation mutation 可供同 run 检索；跨 run 使用必须经过 promotion。

#### `src/agent_alpha/memory/specialist_memory.py`

明确只保存 specialist 的提案历史和对应结果：

- proposal 与 outcome 分成两个 record type；
- 未评估提案保持 `PROPOSED`，不能当 NEUTRAL 经验；
- 每个 agent 文件只是 view，权威记录仍在 record store；
- 检索必须排除当前已失败 expression 和所有 ancestor definition；
- 不能仅因为 proposal 被多次生成就提高可信度。

#### `src/agent_alpha/memory/mutation_arm_memory.py`

现有 arm bandit 可保留，但必须重定义 reward：

- 使用 direction-adjusted、paired validation delta；
- 不同 horizon、universe、metric 不直接平均；
- 按 project scope + mechanism class + mutation class 聚合，而不是仅 `lineage_id:focus`；
- 保存 `n_trials`、有效独立 run 数、uncertainty、failure types；
- locked-test 不更新 arm；
- NEUTRAL/missing metrics 不算 success；
- 聚合文件是 view，event records 不原地压缩。

#### `src/agent_alpha/memory/memory_summary_agent.py`

重新定位为 view builder：

- 规则摘要和 LLM 摘要均不得直接写 global store；
- 摘要输出带 `source_record_ids[]`；
- 摘要不能丢掉反例、scope、stage 和 uncertainty；
- LLM 输出必须经过 schema/faithfulness validator；
- 原始 records 不足时返回空，不从 candidate rationale 推断“worked”；
- `abs(RankIC)` 改为读取已验证的 direction-adjusted metric；
- 生成 summary 后创建 promotion proposal，而不是自动 promotion。

#### `src/agent_alpha/memory/memory_consolidation.py`

当前原地重写 JSONL 的行为必须停止用于权威记录：

- 改名/重构为 `memory/view_builder.py`；
- 只读取 immutable records，写 `memory/views/*`；
- 相同 key 的正反结果不能用 first-non-empty merge 合并；
- 冲突结果生成 condition split 或 explicit conflict；
- `usage_count` 写独立 retrieval telemetry，不能改事实 record；
- 保留原 consolidation API 作为 legacy wrapper，但仅处理 run-local view。

#### `src/agent_alpha/memory/balanced_memory.py`

保留正例/警告/探索混合思想，新增硬过滤顺序：

1. `prompt_visibility`；
2. as-of/locked-test contamination；
3. scope compatibility；
4. schema/data/field registry compatibility；
5. promotion status；
6. source artifact 完整性；
7. 相关性、质量、反例覆盖和使用惩罚。

质量分不能继续把任意 `GOOD + abs(delta)` 当通用质量；必须读取 promotion policy 认可的 outcome。

#### `src/agent_alpha/memory/memory_retriever.py`

当前是空 stub，需要成为唯一正式检索入口：

```text
retrieve_memory(query, research_context, stage, allowed_types, limit)
  -> MemoryRetrievalResultV1
```

返回：

- 选中的 records；
- 被 scope/stage/promotion/as-of 拒绝的数量和 reason；
- memory snapshot ID；
- 排序 trace；
- 总字符/token budget；
- 是否包含 warning/counterexample；
- prompt context content hash。

所有 signal/factor/mutation prompt 必须通过这个入口，不能各自直接 search JSONL。

#### `src/agent_alpha/memory/promotion.py`（新增）

实现：

- `propose_promotion(record_ids, target_scope, policy_version)`；
- 验证独立 run/time/universe 数；
- 检查 locked-test 泄漏和 artifact 完整性；
- 检查 counterexamples 和 scope compatibility；
- 生成 approve/reject decision；
- promote 时创建新 scoped record，不修改 source record；
- 支持 `retract`、`mark_stale`、`revalidate`；
- 所有动作写 event/ledger。

#### `src/agent_alpha/memory/snapshot.py`（新增）

在 run 开始冻结可见 memory：

```text
memory_snapshot_id
as_of_date
run/project/global index hashes
included_memory_ids[]
excluded_scope_ids[]
policy_version
locked_test_visibility_policy
created_at
```

同一 run 的后续 generation 默认使用同一 snapshot；如需刷新，必须创建新 run/version，避免在线学习改变实验条件。

#### `src/agent_alpha/rag/alpha_memory_retriever.py`

当前会混合 factor registry、Alpha Library 和若干手工 output 文件。需要拆分来源：

- `research_archive`：用于查重复和负结果；
- `candidate_alpha_library`：用于计算相似性和增量；
- `deployment_registry`：只用于运营冲突检查；
- legacy/manual outputs：标记 `legacy_unscoped`，不得提供性能先验；
- 返回 canonical definition match、机制相似、字段相似、经验相关性四种不同结果；
- 不能用因子名去重代替 `factor_definition_id`。

#### `src/agent_alpha/library/research_archive.py`（新增）

保存每个完成或终止的 hypothesis/factor lineage 索引：

- 支持 accepted/rejected/inconclusive/duplicate/data-unavailable；
- 引用 run artifacts，不复制大 metrics；
- 支持按 mechanism signature、factor definition、paper/evidence 检索；
- 是 novelty/dedupe 的历史事实源；
- 任何失败都不得被 consolidation 删除。

#### `src/agent_alpha/library/alpha_library.py`

将当前 `accept + abs(rankic) + finite_ratio` admission 替换为：

- 必须引用 locked-test verified metric；
- 必须通过最低 robustness、cost、coverage、novelty/dedupe gate；
- 保存 `factor_definition_id` 和具体 `factor_instance_id`；
- 保存 data/split/config/evidence/lineage refs；
- 禁止使用 legacy/unscoped evaluation；
- admission event 与研究 review 分离。

#### `src/agent_alpha/library/deployment_registry.py`

- 要求 Candidate Alpha Library record ID；
- 要求人工/运营 approval、环境和版本；
- 记录回滚、停用和监控状态；
- Auto-Research 只能提出 deployment candidate，不能调用 `register_deployment()` 自动部署。

#### `src/agent_alpha/workflows/run_manifest.py`

扩充 `standard_run_paths()`：

- events/checkpoint；
- 全部版本化 run-local facts，包括 feature definition/validation/augmentation；
- views/snapshots/promotion proposals；
- Research Archive export；
- memory snapshot ID 和 index hashes；
- 所有输出 content hash。

#### `src/agent_alpha/search/iterative_enhancer.py`

- 移除对 function/transfer/specialist store 的直接检索；
- 只调用统一 `retrieve_memory()`；
- 显式传当前 stage，validation mutation 不能获得 locked-test memory；
- 保存本次 prompt memory context snapshot 和 selection trace；
- 生成 child 后先写 mutation proposal，评估完成再写 outcome。

#### `src/agent_alpha/search/experiment_runner.py`

- 先完成正确 metric aggregation；
- 每次 review 后写 immutable outcome，而不是立即形成 global GOOD/BAD；
- 停止直接 alpha admission；
- 把 implementation retry、scientific outcome、mutation outcome 分开；
- run 完成时调用 Research Archive writer；
- 只产生 promotion proposals，promotion 由单独 policy/reducer 处理。

### 8.11 Paper Graph：需要实现的 memory/feedback 文件

Paper Graph 不保存 Agent Alpha 的 prompt memory；它只保存研究历史对 graph discovery 有用的反馈。

#### `src/paper_graph/research_contracts.py`

- 保留 `ResearchArtifactEnvelopeV1` 和 `ResearchFeedbackV1` 兼容；
- 为 feedback 增加 additive factor-research extension，或新建 `ResearchFeedbackV2`；
- 加入 `research_run_id`、hypothesis outcomes、paper/claim contribution、novelty trace、evidence gap、scope 和 artifact refs；
- feedback ID 的 identity payload 必须包含 run/version，避免相同 accepted/rejected 列表覆盖不同实验。

#### `schemas/research_feedback_v2.schema.json`（新增）

- 严格声明上述字段；
- 区分 paper feedback、claim feedback、graph expansion request 和 Digest evidence-gap；
- 指标只允许 verified metric refs 和小摘要，禁止嵌入无版本 raw metrics；
- 支持 V1 adapter，但 V1 不得伪装成 V2 完整反馈。

#### `src/paper_graph/research_feedback_store.py`（新增）

- 验证并保存 Agent Alpha feedback artifact；
- 按 `feedback_id` content-addressed 写入；
- 建立 paper、claim、graph、hypothesis signature 索引；
- 同 ID 不同内容 fail closed；
- 不原地修改 canonical graph，只影响下一 snapshot 的优先级。

#### `src/paper_graph/research_memory.py`（新增）

生成 Paper Graph 自己的研究记忆投影：

```text
paper_claim_outcomes.jsonl
hypothesis_signatures.jsonl
graph_path_outcomes.jsonl
prior_art_queries.jsonl
digest_evidence_gap_queue.jsonl
next_opportunity_scores.parquet
```

每条只保存 Agent Alpha artifact refs、scope 和结果类别。不得把某个 factor 的 RankIC 直接解释为论文质量。

#### `src/paper_graph/novelty_index.py`（新增）

- 索引已研究 `HypothesisSignature`；
- 区分 local graph novelty、prior-art not-found 和 empirical incremental；
- 保存检索 as-of date、coverage 和 query trace；
- 支持 exact/near/semantic candidate，semantic 相似只能进入 review；
- 为下一次 opportunity 生成 duplicate/replication/contradiction 提示。

#### `scripts/ingest_agent_alpha_feedback.py`（新增）

- 只读 ingest 一个或一批 feedback；
- 支持 `--probe`、`--resume`、manifest/hash reconciliation；
- 生成新 feedback snapshot，不覆盖原 graph；
- 大批 ingest 通过 Slurm；
- 输出 accepted/rejected/quarantined 和原因统计。

#### Paper Graph tests（新增）

```text
tests/test_research_feedback_v2.py
tests/test_research_feedback_store.py
tests/test_research_memory.py
tests/test_novelty_index.py
tests/test_feedback_snapshot_reproducibility.py
```

必须覆盖 V1 migration、重复 ingest、hash conflict、title-only identity 拒绝、scope 隔离和 graph snapshot 不被原地修改。

### 8.12 Paper Digest New2：需要实现的 memory/feedback 文件

Digest 的“记忆”是可复核 evidence 历史，不是因子成败提示词。

#### `src/arxiv/evidence_identity.py`（新增）

- 由 canonical paper ID、document version、source hash、section/offset 和 quote hash 生成稳定 evidence ID；
- 解析版本变化时创建新 evidence version，并保留 supersedes link；
- 不能仅用数组顺序生成 `ev_0001` 作为跨 run 永久身份。

#### `src/llm/three_ai/factor_mechanism_brief.py`（新增）

- 从 evidence pack 生成 `FactorMechanismBriefV1`；
- 只提取 market/frequency/horizon/mechanism/variables/limitations；
- 每个字段绑定 evidence IDs；
- 明确 `not_disclosed` 和 `missing_observables`；
- 不输出可执行 FactorCandidate；
- LLM 结果通过确定性的 schema、evidence-reference、quote-hash 和语义边界校验；不使用额外 LLM 充当忠实度裁判。

#### `src/llm/three_ai/research_artifact_exporter.py`

- 接入稳定 evidence identity；
- 写 document/content/config/run hashes；
- 加入 factor mechanism extension；
- artifact content-addressed，重复导出幂等；
- 不允许空位置、重复 evidence ID 或无法验证的 reading note claim。

#### `src/llm/three_ai/research_feedback_ingester.py`（新增）

读取 `ResearchFeedbackV2`，只生成：

- evidence useful/not-useful 索引；
- missing evidence queue；
- parsing/faithfulness correction queue；
- unobservable variable/proxy gap；
- 需补全文/公式/成本/OOS 的任务。

不得把 `accepted factor` 反写成论文 claim 为真，也不得修改原始 evidence artifact。

#### Digest runtime 文件

```text
data/runtime/research_artifacts/<artifact_id>/artifact.json
data/runtime/research_feedback/<feedback_id>.json
data/runtime/evidence_memory/evidence_use.jsonl
data/runtime/evidence_memory/evidence_gaps.jsonl
data/runtime/evidence_memory/corrections.jsonl
data/runtime/evidence_memory/snapshots/<snapshot_id>.json
```

其中 artifact/feedback 为不可变事实；三个 JSONL 是可重建索引或 queue。

#### Digest scripts/tests（新增）

```text
scripts/export_research_artifact.py
scripts/ingest_research_feedback.py
tests/test_evidence_identity.py
tests/test_factor_mechanism_brief.py
tests/test_research_artifact_exporter.py
tests/test_research_feedback_ingester.py
tests/test_evidence_memory_snapshot.py
```

### 8.13 配置文件和 prompt 规则

#### `agent_alpha/configs/memory_policy.yaml`（新增）

```yaml
schema_version: memory_policy_v1
scope_fields:
  - market
  - asset_class
  - data_provider
  - data_schema_version
  - frequency
  - field_registry_version
  - operator_registry_version
  - label_family
prompt_visibility:
  implementation: [implementation_repair]
  exploration: [implementation_repair, proxy_reliability, feature_definition, feature_validation, function, negative_result]
  validation: [implementation_repair, proxy_reliability, feature_definition, feature_validation, feature_augmentation, function, mutation_outcome, negative_result]
  locked_test: []
promotion:
  implementation_repair:
    min_real_runs: 1
    require_regression_test: true
  proxy_reliability:
    min_independent_runs: 2
  mutation_policy:
    min_independent_runs: 3
  mechanism_pattern:
    require_locked_test: true
    require_robustness: true
retrieval:
  max_records: 12
  max_chars: 24000
  require_counterexample_when_available: true
legacy:
  scope: legacy_unscoped
  allow_auto_promotion: false
```

具体阈值后续用 pilot 校准，但 policy 必须版本化并进入 run hash。

#### `agent_alpha/prompts/thinking_evolution/memory_summary_v1_system.md`

需要增加硬约束：

- 不得把 proposal/NEUTRAL 说成经验；
- 不得丢弃 scope/stage/source refs/counterexamples；
- 不得根据绝对 RankIC 推导成功；
- 输出只形成 summary/proposal，不形成 approved memory；
- 若证据冲突，输出 conflict，不选择性总结。

#### mutation prompts

所有 mutation prompt 统一接收：

```text
memory_snapshot_id
allowed_memory_records[]
warning_records[]
counterexample_records[]
retrieval_trace_id
forbidden_stage_notice
```

Prompt 自身不得调用不同 store 绕过 retrieval policy。

### 8.14 Memory 测试文件清单

Agent Alpha 至少新增：

```text
tests/test_memory_contracts.py
tests/test_memory_record_store.py
tests/test_run_memory_projection.py
tests/test_memory_scope_filter.py
tests/test_memory_snapshot.py
tests/test_memory_promotion.py
tests/test_memory_retraction.py
tests/test_memory_retriever.py
tests/test_memory_prompt_contamination.py
tests/test_memory_view_rebuild.py
tests/test_mutation_outcome_memory.py
tests/test_mutation_arm_scoping.py
tests/test_negative_result_archive.py
tests/test_research_archive.py
tests/test_alpha_library_admission_v2.py
tests/test_legacy_memory_migration.py
```

关键性质测试：

- 删除全部 `memory/views/` 后可从事实 records 完全重建；
- 相同 record 重放幂等；同 ID 不同内容失败；
- 两个 worker 不能竞争写同一个权威文件；
- validation prompt 看不到 locked-test records；
- A 股 L2 memory 默认不能进入外汇日频 run；
- 同一 split 的十次 mutation 不被计作十次独立验证；
- 冲突结果不会被 consolidation 合并成单一 GOOD/BAD；
- legacy records 永不自动 promotion；
- retraction 后新 snapshot 不再返回该规则，旧 snapshot 仍可复现；
- Alpha Library 拒绝 run-local/legacy/未通过 robustness 的记录。

### 8.15 现有 memory 数据迁移

当前已有：

```text
data/memory/cog/function_memory.jsonl
data/memory/cog/transfer_memory.jsonl
data/memory/cog/mutation_arm_memory.jsonl
data/memory/cog/specialist_agents/*.jsonl
data/feedback_memory/good_bad.jsonl
data/evaluation_records/evaluations.jsonl
```

截至 2026-08-11 的只读抽查：`function_memory.jsonl` 约 264 行、`transfer_memory.jsonl` 约 264 行、`mutation_arm_memory.jsonl` 约 56 行，两个已有 specialist view 分别约 175 行和 109 行。抽查记录中存在大量重复 proposal、`NEUTRAL` 且没有 parent/child metric 的 transfer、可变 `usage_count`，并普遍缺少 research run、stage、data/split hash、evidence 和 scope。这些数量只是迁移基线，不是有效独立记忆数量。

迁移策略：

1. 原文件只读备份并记录 hash；
2. 逐行校验 schema，坏行进入 quarantine；
3. 能回链 run/candidate/review 的记录导入对应 run-local archive；
4. 缺 run/data/split/stage 的记录标记 `legacy_unscoped`；
5. `NEUTRAL` proposal 只导入 proposal history；
6. 旧 mutation reward 不具备同 split paired delta 时不导入 policy stats；
7. 旧 GOOD/BAD 不自动进入 project/global memory；
8. 生成 migration manifest、source line -> new record ID map 和统计报告；
9. 不删除或原地改写旧文件；
10. 新旧 reader 并存一个兼容周期后再停止 legacy prompt retrieval。

### 8.16 Memory 实现的主要难点

#### 权威事实与摘要混淆

目前同一个 JSONL 既像事实库又像 prompt summary；一旦 LLM summary 被再次总结，就会产生无法追踪的二手结论。解决关键是 record/view 分离和 source refs 强制校验。

#### 并发和原子性

多个 Slurm worker 并发 append JSONL 会产生交错、重复和部分写入。最可靠方案不是复杂文件锁，而是 worker 写独立 attempt artifact、单 orchestrator reducer ingest。

#### scope 定义

“订单簿不平衡”看似通用，但数据供应商字段、采样频率、市场规则和 label 完全不同。Scope 太宽会错误迁移，太窄又无法复用。需要以数据契约哈希为基础，再通过 promotion 明确扩大。

#### reward 可比性

不同股票池、日期、horizon、方向和 metric 的 RankIC 不能直接相减。Mutation reward 必须来自同一 preregistration 下的 paired aggregate，否则 arm memory 没有统计意义。

#### 自适应搜索污染

Memory 会让下一候选依赖过去结果，因此搜索不是独立试验。必须保存 memory snapshot、retrieval trace 和 multiplicity family，locked test 必须完全不可见。

#### 冲突和非平稳性

同一 mutation 在高波动时期有效、平稳时期无效，不能用最后写入或简单多数投票覆盖。Memory record 必须支持 conditions、counterexamples、stale 和 retraction。

#### Legacy 数据缺少 provenance

当前很多 records 只有 factor name、GOOD/BAD/NEUTRAL 或绝对 score，没有 run/data/split/evidence。强行补全会制造虚假 provenance，因此只能 quarantine 或 `legacy_unscoped`。

#### 压缩不能破坏证据

现有 consolidation 的 first-non-empty merge 可能把两个不同条件的记录合并。新系统只能压缩 view，且正反证据必须并存。

#### 检索质量和 prompt 预算

仅关键词搜索容易返回同名但不同机制的记录；只按高分又会形成利用偏见。检索要先做硬 scope/stage 过滤，再兼顾相关、警告、反例、新近和探索，同时保存为什么选中。

#### 跨项目反馈语义

一个因子失败可能来自 proxy、实现、市场迁移或统计功效不足，不能简单反馈“论文无效”。ResearchFeedback 必须把 evidence、proxy、implementation 和 empirical outcome 分开。

### 8.17 Memory 实施顺序

按以下顺序实施，不能先做更复杂的 RAG/embedding：

1. 定义 `MemoryRecordV1`、scope、stage、promotion 和 snapshot schema；
2. 实现 immutable `record_store.py` 和幂等/hash tests；
3. 修复 metric aggregation，产生可信 ExperimentOutcome；
4. 从 graph research events 投影 run-local memory；
5. 实现 snapshot 和统一 scope-aware retriever；
6. 将 iterative enhancer 改为只使用统一 retriever；
7. 将现有 specialist/function/transfer 文件降级为 views；
8. 实现 negative result 和 Research Archive；
9. 实现 promotion/retraction/staleness；
10. 改造 mutation arm reward；
11. 收紧 Alpha Library admission；
12. 接通 Paper Graph/Digest feedback stores；
13. 最后迁移 legacy memory，并运行 contamination/恢复测试。

第一版不要引入向量数据库。稳定 schema、scope、provenance、stage isolation 和 exact/mechanism-field 检索足以完成 pilot；只有 records 数量和检索评测证明关键词/结构检索不足后，才评估复用已有 embedding，且不能生成新的 embedding 任务。

## 9. 跨项目 artifact contract

### 9.1 `ResearchOpportunityV1` — Paper Graph 输出

```text
schema_version
research_opportunity_id
as_of_date
graph_id / graph_version / graph_content_hash
taxonomy_version / topic_ids[]
seed_paper_ids[]
neighbor_paper_ids[]
relation_refs[]
evolution_path_refs[]
structured_artifact_refs[]
contribution_type_mix[]
research_question
selection_reasons[]
target_tracks[]
required_observables[]
digest_ready_paper_ids[]
missing_evidence_paper_ids[]
prior_art_search_trace
graph_value_assessment_id / recommended_action / status
producer_revision / config_hash
```

当前实现采用以下硬门槛：seed 论文缺 claim/evidence 时进入 `EVIDENCE_QUEUE`；graph 无可行数据线路时进入 `NEEDS_DATA`；矛盾消解任务没有 verified `CONTRADICTS/FAILS_TO_REPLICATE` 边时也不能进入执行。只有 `status=READY` 可以继续生成 `FactorResearchPackageV1`。

### 9.2 `ResearchArtifactEnvelopeV1` — Digest 输出

继续兼容现有 V1，不立即破坏历史 reader。第一阶段通过 additive `factor_research` extension 增加：

```text
document_version
content_hash
claims[]
evidence_spans[]
formulas[]
variables[]
methods[]
data_sample
reported_results[]
limitations[]
cost_oos_capacity_markers
factor_research:
  market
  frequency
  horizon
  mechanism_chain[]
  observable_candidates[]
  missing_observables[]
```

若未来改为 V2，必须提供 V1 -> V2 adapter 和兼容测试。

### 9.3 `FactorResearchPackageV1` — Agent Alpha intake

```text
package_id
research_opportunity_id / research_opportunity_hash
graph_snapshot_ref
paper_artifact_refs[]
evidence_bundle_hash
target_track
data_contract_id / data_contract_hash
field_registry_version / operator_registry_version
memory_snapshot_id
research_budget
selection_trace
```

Package 是 Agent Alpha run 的不可变入口；修改 graph、evidence、data contract、registry、memory 或 budget 中任一身份字段都必须生成新的 `package_id`。

### 9.4 `ResearchContributionV1`

由 Digest 基于 evidence 输出，Agent Alpha 复核 routing：

```text
schema_version
contribution_id
paper_id
paper_classification_id
primary_topic_id
secondary_topic_ids[]
contribution_type
factor_research_roles[]
claim
evidence_ids[]
market / asset / frequency / horizon
original_inputs[] / canonical_inputs[] / outputs[]
required_observables[]
label_or_estimand
method_or_estimator
reported_validation
limitations[]
not_disclosed[]
classification_basis
classification_version
confidence
route_recommendations[]
```

Digest 的 `route_recommendations[]` 只是语义建议，不是最终执行许可。`ResearchContributionV1` 不绑定本地物理路径，也不自行宣布某个 weak proxy 可用；最终线路由 Agent Alpha 的 `RoutingDecisionV1` 裁决。

### 9.5 `FactorFeasibilityAssessmentV1`

对每个论文变量/机制映射：

```text
feasibility_assessment_id
contribution_id
target_track
dataset_contract_id / dataset_content_hash
paper_variable
evidence_ids[]
required_observable
local_field_or_expression
proxy_strength              # direct | derived | weak_proxy | unavailable
confidence
approximation_loss
temporal_compatibility
frequency_compatibility
cross_asset_requirement
model_requirement
data_leakage_risk
route_reason_codes[]
decision                    # automatic | proxy_hypothesis | needs_data | reject
```

只有 `direct` 和高可信 `derived` 默认允许自动候选生成。`weak_proxy` 创建单独 proxy hypothesis；`unavailable` 停止该分支。

### 9.5.1 `PaperClassificationV1` / `RoutingDecisionV1`

分类和路由不能藏在自由文本字段中。正式 contract 采用 4.14 的完整字段，并满足：

```text
PaperClassificationV1
  identity = paper_id + taxonomy_version + classifier_version + evidence_hash
  authority = Paper Graph snapshot，Digest 可追加 evidence review

RoutingDecisionV1
  identity = contribution_id + target_track + data_contract_id + classification_version
  authority = Agent Alpha
  immutable decision event + superseding event；不允许原地覆盖
```

`track_eligibility{}` 必须同时给出 `intraday_hf` 和 `daily_cross_sectional` 的结论，即使其中一条明显不兼容；这样才能区分“没有评估”与“已评估为不兼容”。

### 9.6 `FeatureDefinitionV1` / `ModelFeatureDefinitionV1`

```text
feature_definition_id
name
semantic_type                    # price | flow | liquidity | volatility | state | risk | representation
source_contribution_ids[]
evidence_ids[]
calculation_kind                 # asl | deterministic_kernel | fitted_model
input_fields[]
output_fields[]
calculation_graph / estimator_spec
parameters
window / warmup
units / expected_range
causal_availability
fit_required
fit_protocol_ref
missing_value_policy
normalization_policy
runtime_budget
approximation_loss
implementation_status            # proposed | implemented | calculator_validated | rejected | deprecated
measurement_status               # untested | validated | conditional | failed
downstream_utility_status         # untested | no_increment | conditional_increment | broad_increment
```

若是 fitted model，还必须保存 train-only fit、checkpoint hash、seed、依赖、模型大小和 inference latency。模型输出不能作为“已经观察到的 derived field”静默加入 registry。

### 9.7 `FeatureAugmentationHypothesisV1` / `FeatureAugmentationExperimentV1`

```text
augmentation_hypothesis_id
feature_definition_id
parent_factor_definition_ids[]
mechanism_relation
composition_operators[]          # gate | interact | confirm | scale | residualize | substitute
expected_improvement_dimensions[]
expected_non_improvements[]
falsification_criteria[]
parent_selection_rule
max_parent_factors
max_compositions

augmentation_experiment_id
parent_factor_instance_id
child_factor_instance_id
composition_operator
shared_data_split
shared_metric_definition
paired_comparison_method
complexity/runtime controls
multiplicity_family_id
```

`expected_improvement_dimensions` 可以是方向调整预测、稳定性、覆盖率、成本、换手、尾部风险或 Alpha Library 增量，不必只写 IC。

### 9.8 `FactorHypothesisV1`

```text
hypothesis_id
research_run_id
parent_hypothesis_ids[]
paper_ids[] / claim_ids[] / evidence_ids[]
mechanism
observable_event
state_condition
expected_response
target_horizons[]
expected_direction
allowed_fields[]
proxy_assumptions[]
baseline_family
falsification_tests[]
novelty_vector
scope_limitations[]
status
```

### 9.9 `FactorExperimentPreregistrationV1`

```text
experiment_id / version
hypothesis_id
factor_instance_ids[]
data_snapshot
universe
frequency
label / primary_horizon
train / exploration / validation / locked_test windows
purge / embargo
primary_metric / expected_direction
aggregation_method
uncertainty_method
secondary_metrics[]
cost / turnover / capacity assumptions
robustness / falsification checklist
multiplicity_family_id
budget
acceptance / rejection / inconclusive rules
content_hash
```

### 9.10 `FactorEvaluationAggregateV1`

保存 raw metrics 的引用和预注册聚合结果：

```text
factor_instance_id
experiment_id
stage
codes / dates / regimes / horizons
raw_metric_artifact
aggregation_method
direction_adjusted_rankic
mean / median / dispersion / confidence_interval
coverage / finite_ratio
qspread / turnover / cost_adjusted_metric
stability_metrics
library_correlation / incremental_metric
multiple_testing_adjustment
result_hash
```

### 9.11 `ResearchFeedbackV1` — Agent Alpha 返回

```text
research_run_id
accepted / rejected / inconclusive hypotheses
factor definitions / instances / lineage
verified metric refs
negative results
evidence contribution and faithfulness issues
unobservable variables / proxy failures
paper/claim prioritization feedback
requested replications / contradictions / neighbors
Digest evidence-gap requests
memory promotions
next research opportunities
```

### 9.12 新计算特征和模型研究的文件级实现

#### `src/agent_alpha/contracts/research_contribution.py`（新增）

- 实现 `ResearchContributionV1` 和 contribution/routing enums；
- 验证每个 contribution 有 evidence，且只选择一个主 routing；
- 保存论文原始贡献与 Agent Alpha 本地可行性判断，不能覆盖 Digest 判断；
- 支持一篇论文多个 contribution，但 evidence 重叠需要显式声明。

#### `src/agent_alpha/features/feature_schema.py`（新增）

- 实现 `FeatureDefinitionV1`、`FeatureInstanceV1`、`FeatureValidationResultV1`；
- 区分 raw field、deterministic derived feature 和 fitted model feature；
- 强制 input/output、单位、warmup、session reset、causal availability、missing policy；
- feature 不包含 expected RankIC direction，除非它同时被包装成 FactorHypothesis。

#### `src/agent_alpha/features/feature_identity.py`（新增）

- 规范化 calculation graph、参数、窗口、输入和输出；
- 生成 `feature_definition_id`；
- fitted model 的 definition 与 trained instance 分开；
- 支持 exact calculation dedupe 和语义/单位冲突 review；
- 同名不同计算必须拒绝，同计算不同 alias 共享 definition。

#### `src/agent_alpha/features/feature_registry.py`（新增）

维护 Feature Registry。不要用一个线性状态把计算正确、测量有效和因子增量混在一起，分别保存：

```text
implementation_status: proposed | implemented | calculator_validated | rejected | deprecated
measurement_status: untested | validated | conditional | failed
downstream_utility_status: untested | no_increment | conditional_increment | broad_increment
```

- 只有 calculator 和 measurement 均通过的 feature 默认暴露给因子研究；
- `calculator_validated` 但尚未完成测量验证的 feature 仅能在其 research run 中使用；
- `no_increment` 不否定 feature 的测量价值，但默认不推荐用于相同父因子/组合；
- `conditional_increment` 必须保存具体 parent、operator、market 和 regime，不能升级为普遍有用；
- 保存论文/evidence、calculator hash、验证 artifact、runtime 和已知限制；
- Feature Registry 记录不能保存“全局 GOOD”结论，只保存 scope 和 interaction outcomes refs。

#### `src/agent_alpha/features/feature_calculator.py`（新增）

作为所有 derived feature 的唯一计算源：

- 构建 feature dependency DAG；
- 拓扑排序并检测循环；
- 只读取允许的 raw/approved upstream features；
- 统一 EPS、rolling min periods、session reset、dtype、timestamp order 和 missing policy；
- 支持 deterministic ASL kernels；
- 复杂 estimator 使用已审计的专用 kernel adapter；
- 输出计算 provenance 和 runtime diagnostics。

#### `src/agent_alpha/features/feature_validator.py`（新增）

分四层验证：

1. schema/dependency/field validation；
2. temporal leakage、fit/predict 和 session boundary；
3. numerical parity、finite/coverage/range/units；
4. measurement validity、stability、runtime 和重复 feature 检查。

Measurement validity 可以是：

- 与论文公式/公开实现的合成样例一致；
- 在已知盘口构造下满足单调性/对称性；
- 与现有 estimator 的关系符合预期但不完全重复；
- 对波动率等测量量使用 forecast/realization calibration；
- 对 latent state 使用 OOS stability、separation 或 downstream usefulness。

#### `src/agent_alpha/features/feature_renderer.py`（新增）

- 从同一个 validated definition 生成 fac-eval-compatible feature builder；
- 禁止复制另一套手写公式；
- renderer 输出包含 feature definition/hash；
- 生成代码只调用白名单 kernel；
- 与 local calculator 做逐值 parity test。

#### `src/agent_alpha/features/augmentation.py`（新增）

- 实现 `FeatureAugmentationHypothesisV1` 和 nested experiment planner；
- 按 evidence/mechanism 选择有限 parent factors；
- 只允许预注册 composition operators；
- 构建 Parent/Child/Control 三元组；
- 生成 paired delta 和 feature ablation；
- 保存 complexity/runtime delta；
- 禁止对所有因子/feature 做组合爆炸搜索。

#### `src/agent_alpha/models/model_feature_contract.py`（新增）

- 定义 fit、transform/predict、checkpoint 和 inference availability；
- 训练只能读取 train split；
- validation/locked test 只 transform/predict；
- 保存 seed、环境、依赖、checkpoint hash 和 latency；
- 模型输出注册为版本化 feature instance，不成为无版本字段名。

#### `src/agent_alpha/factors/hf_feature_builder.py`

当前基础实现保留为兼容 facade，但内部改为调用中央 `FeatureCalculator`。不得继续与 renderer/calculator 各自维护一份 `_add_basic_hf_features`。

#### `src/agent_alpha/factors/factor_calculator.py`

- 删除/弃用本地重复 `_add_basic_hf_features`；
- 从固定 Feature Registry snapshot 构建所需 feature；
- FactorCandidate 记录使用的 `feature_definition_ids[]`；
- local calculation 与 renderer 使用完全相同的 dependency DAG。

#### `src/agent_alpha/factors/fac_eval_renderer.py`

- 删除生成文件中的重复 hard-coded feature builder；
- 注入/引用 validated feature kernel bundle；
- bundle hash 进入 factor definition/experiment manifest；
- fac-eval 缺 feature implementation 时 fail closed，不能只因字段在 whitelist 中就运行。

#### `configs/feature_registry.yaml`（新增）

成为 derived feature 的权威 registry。每个 entry 至少包含：

```yaml
feature_name:
  feature_definition_id: "..."
  status: approved
  semantic_type: volatility
  calculation_kind: deterministic_kernel
  inputs: [mid_price_l1]
  window: 60
  units: return_std
  causal_availability: current_tick_after_quote
  warmup: 60
  session_reset: true
  missing_policy: nan_until_min_obs
  kernel: realized_vol_mid
  evidence_ids: []
  validation_artifact_ids: []
  scope_id: "..."
```

#### `configs/field_registry.yaml`

- raw fields、label fields 和 blocked fields 仍由它管理；
- `derived_feature_fields` 改为从 approved Feature Registry 生成或做严格一致性检查；
- 当前大量“将来可计算”的词表移到 `proposed_feature_vocabulary`，不能继续被 validator 当已实现字段；
- 显式区分 `declared`、`implemented`、`approved`。

#### `src/agent_alpha/rag/field_registry.py` / `field_retriever.py`

- 读取 raw field registry + frozen Feature Registry snapshot；
- 只有 `implementation_status=calculator_validated` 且 measurement gate 允许的 feature 被视为 runtime-safe；
- 检索结果返回 feature status、definition ID、inputs、evidence 和 approximation loss；
- 移除手写 `RUNTIME_SAFE_DERIVED_FIELDS` 作为第二权威来源。

#### Digest 和 Paper Graph 对应改造

- Digest `factor_mechanism_brief.py` 增加 contribution classification，并为 feature/model 记录公式、输入、输出、fit protocol 和 reported validation；
- Paper Graph `ResearchOpportunityV1` 增加 contribution-type mix，使 graph 可以优先寻找“机制论文 + measurement/model 论文”的组合；
- Paper Graph novelty index 分开索引 mechanism signature、feature calculation signature 和 model method signature；
- Agent Alpha feedback 分开返回 feature implemented、validated、augmentation improved、no incremental value 和 model unreproducible。

#### Feature/model tests（新增）

```text
tests/test_research_contribution_routing.py
tests/test_feature_schema.py
tests/test_feature_identity.py
tests/test_feature_registry.py
tests/test_feature_dependency_dag.py
tests/test_feature_temporal_availability.py
tests/test_feature_calculator_renderer_parity.py
tests/test_feature_session_reset.py
tests/test_feature_measurement_validation.py
tests/test_feature_augmentation_ablation.py
tests/test_feature_parent_selection_budget.py
tests/test_model_feature_fit_predict_isolation.py
tests/test_field_feature_registry_consistency.py
```

## 10. 因子 Auto-Research 全流程

### Stage 0：冻结研究环境

输入：代码 revision、dirty-tree manifest、market data、field/operator registry、fac-eval、memory snapshot。  
动作：计算哈希，创建 run ID、预算和 event journal。  
输出：`FactorResearchRunManifestV1`。  
Gate：任一不可变输入无法确定则不启动研究。

### Stage 1：Paper Graph 发现研究机会

1. 从高可信 finance corpus 选择主题/seed；
2. 构建局部 citation/similarity graph；
3. 标记哪些关系是结构关系，哪些已有双方 claim evidence；
4. 寻找支持、反驳、复现、限定、跨社区桥接和 evidence gap；
5. 输出研究问题和 prior-art search trace；
6. 选择 Digest 队列。

Graph 排序目标应包括：

- finance 和目标市场/频率相关性；
- 精确身份和全文可获得性；
- 机制清晰度；
- 潜在本地可观测性；
- 支持/冲突/复现价值；
- 与已研究 graph/Alpha Library 的距离；
- 预期证据成本。

### Stage 2：Digest 构建可信 evidence

1. 按 exact arXiv/DOI/canonical ID 获取全文；
2. 固定 source version 和内容哈希；
3. 构建 section-aware chunks；
4. 提取 claim、公式、变量、方法、数据、结果、限制；
5. 明确交易成本、OOS、容量和统计证据是否存在；
6. 对 LLM reading 做确定性的 quote hash、source locator、evidence foreign-key 和 document-version 校验；
7. 为论文生成一个或多个带 evidence 的 `ResearchContributionV1`；
8. 区分 mechanism/effect、measurement feature、ML/model、label/evaluator、execution 和 negative/boundary；
9. 导出 envelope；
10. 缺证据时返回 `needs_evidence`，不让下游补写。

### Stage 3：贡献分类与研究可行性 Gate

Agent Alpha 先根据 4.4 的 routing decision 选择研究路径，再对每个 contribution 检查：

- 论文市场和本地市场是否可比；
- 论文频率/持有期与本地 label 是否兼容；
- 变量是否可直接观察；
- proxy 误差是否会改变经济含义；
- 是否需要跨证券、指数、新闻、订单事件或训练模型；
- 字段是否在当前 snapshot 中真实存在；
- 计算时序是否只使用当时可得数据；
- 最小覆盖率是否可达到；
- 成本和容量是否可评价。

对 `MEASUREMENT_FEATURE` 额外检查：

- 计算定义是否完整且能形成确定性 calculation graph；
- 输入字段是否真实可用；
- 单位、尺度、warmup、缺失值和 session reset 是否明确；
- 新字段在事件时间上何时可用；
- 是否需要订单事件数据而本地只有快照；
- 能否定义 measurement validity，而不是只用收益 IC；
- 计算和存储成本是否适合在 factor harness 中复用。

对 `ML_REPRESENTATION/PREDICTION_MODEL` 额外检查：

- fit/predict 时序能否严格分离；
- 训练目标是否包含未来 label，输出何时可用；
- 训练数据、seed、超参数和 checkpoint 是否可复现；
- 是否有相同输入、相同训练预算的 baseline；
- 模型能否在受控环境和预算内运行；
- 论文贡献能否降解成更小的 deterministic feature 先验证。

输出：

```text
ELIGIBLE_DIRECT
ELIGIBLE_DERIVED
ELIGIBLE_FEATURE
ELIGIBLE_MODEL_FEATURE
ELIGIBLE_MODEL_METHOD
PROXY_HYPOTHESIS_REQUIRED
NEEDS_DATA
NEEDS_MODEL_EVIDENCE
FREQUENCY_MISMATCH
UNFAITHFUL_MAPPING
UNREPRODUCIBLE
REJECTED
```

### Stage 4：生成分类型 Research Hypothesis forest

机制/经验效应路径生成 `FactorHypothesisV1`；计算特征路径生成 `FeatureValidationHypothesisV1` 和 `FeatureAugmentationHypothesisV1`；模型路径生成 `ModelBenchmarkHypothesisV1`。

所有 hypothesis 必须包含：

- 完整机制链；
- 本地可观测事件；
- 状态条件；
- 预期响应、方向和 horizon；
- baseline；
- 至少一个 invalidating result；
- evidence refs 和 proxy 假设；
- novelty vector 和 scope limitations。

Feature augmentation hypothesis 还必须说明：

- 为什么该 feature 与某类父因子的机制相关；
- 预期改善预测、稳定性、成本、换手、风险还是 proxy fidelity；
- 允许的 composition operator；
- 如果 feature 自身无 IC，为什么仍可能改善父因子；
- 什么结果说明 feature 只是增加复杂度或重复信息。

首个 pilot 每个 run 最多两个 hypothesis。证据不足时状态为 `PAUSED_EVIDENCE`，而不是让 LLM自由补全。

### Stage 5：新颖性和可证伪性 Gate

分别运行：

- graph/prior-art 检索；
- hypothesis signature 相似性；
- factor definition 和近似表达式 dedupe；
- feature calculation graph、单位/语义和近似 estimator dedupe；
- Alpha Library/Negative Archive 检索；
- Feature Registry 和 feature augmentation history 检索；
- 数据可实现性；
- 方向和 invalidating test 完整性；
- 证据忠实度审查。

决策：

```text
APPROVE_REPLICATION
APPROVE_MECHANISM_VARIANT
APPROVE_NOVEL_CANDIDATE
APPROVE_FEATURE_VALIDATION
APPROVE_FEATURE_AUGMENTATION
APPROVE_MODEL_BENCHMARK
NEEDS_PRIOR_ART
NEEDS_EVIDENCE
DUPLICATE
REJECT
```

### Stage 6：生成小型候选因子族

#### Stage 6A：直接因子/机制路径

每个 FactorHypothesis 默认：

- 1 个 null/simple baseline；
- 1–2 个 primary candidates；
- 1 个 placebo/negative control；
- 可选 1 个论文原式 replication（数据契约允许时）。

Candidate 只能使用允许字段和算子。所有候选保存公式含义、预期方向、父节点和 evidence，不允许只有匿名表达式。

#### Stage 6B：新计算特征路径

每个 measurement contribution 默认只生成：

- 1 个论文忠实版 feature；
- 可选 1 个保守简化版；
- 1 个现有相近 feature baseline；
- 最多 2 个机制相关的父因子；
- 每个父因子最多 2 个预注册 composition operators。

允许的组合语义：

```text
gate:        parent * state_gate(feature)
interact:    normalized(parent) * normalized(feature)
confirm:     parent * confirmation_weight(feature)
scale:       parent / risk_or_liquidity_scale(feature)
residualize: remove information already represented by feature
substitute:  replace an older low-fidelity proxy with the new feature
```

不允许 LLM 对所有 Feature Registry 字段和所有父因子做笛卡尔积搜索。父因子必须由机制/evidence、现有 lineage 或预注册规则选出。

#### Stage 6C：ML/model 路径

- deterministic component 优先走 6B；
- learned feature 生成固定 fit/predict contract；
- model method 使用相同输入、label、split、seed set 和 compute budget 的 baseline；
- 模型超参数搜索属于 multiplicity family；
- 不能把训练集内 representation quality 当 OOS 下游价值。

### Stage 7：实验预注册

在读取任何本轮结果前冻结：

- 探索、验证和锁定测试时间；
- 股票池和排除规则；
- 主 horizon；
- 方向调整的 primary metric；
- 聚合和置信区间方法；
- 最小覆盖率；
- 成本、换手、容量假设；
- baseline 和最小改进；
- robustness/falsification checklist；
- 候选、mutation、LLM 和 compute budget；
- 多重检验 family。

Feature augmentation 还需冻结：

- feature definition/version；
- 父因子选择规则；
- composition operators；
- parent/child paired comparison；
- 特征本身的 measurement/coverage/stability 指标；
- 复杂度、latency 和存储增量；
- “无 IC 但改善父因子”的允许判定规则。

变更上述内容必须新建 experiment version。

### Stage 8：实现和数据冒烟

1. ASL/schema/field/operator validation；
2. renderer 和 `py_compile`；
3. 小日期/小股票 calculator 对照；
4. 无未来字段检查；
5. finite、coverage、常数、极端值和符号 sanity；
6. 本地 calculator 与 fac-eval 输出一致性。

新 FeatureCandidate 还必须通过：

1. 单一中央 calculator、local calculator 和 fac-eval renderer 三方数值 parity；
2. session 边界、排序、重复时间戳和 warmup 测试；
3. 只使用当时可得输入的 temporal availability 测试；
4. 单位、范围、符号、单调性或已知极端样例测试；
5. 大样本 runtime/memory benchmark；
6. fitted feature 的 train-only fit 和 checkpoint reproducibility。

工程失败只产生新 `run_attempt_id`，不能成为因子弱或强的科学结论。

### Stage 9：探索集筛选

只用于低成本淘汰：

- 不可计算或覆盖率不足；
- 几乎常数/重复；
- 方向完全相反且无合理解释；
- 成本或换手明显不可接受；
- 与 baseline 无差异；
- 与已有因子几乎完全重复。

对 feature 的探索筛选不能只看其单变量 IC。应先检查：

- 计算覆盖率、稳定性和跨股票尺度；
- 是否测量了论文声称的 construct；
- 与现有 feature 的重复度；
- 是否在预注册 parent 上至少一个增量维度改善；
- 改善是否足以覆盖复杂度和运行成本。

探索集结果允许触发 parameter/representation refine，但不允许宣称最终有效。

### Stage 10：验证集搜索与变异

1. 按预注册规则跨股票、日期聚合；
2. 比较 baseline、primary、placebo；
3. 计算方向、稳定性、置信区间、成本和 Library 增量；
4. 结构化诊断失败原因；
5. 在预算内执行 REFINE/PIVOT/REJECT；
6. 所有 child 建立 lineage 和 multiplicity record；
7. 选出少量 finalist 后冻结定义。

Feature augmentation 必须使用嵌套 paired ablation：

```text
Parent:       F(x)
Child:        Compose(F(x), Z_new(x))
Control:      Compose(F(x), Z_old_or_placebo(x))
```

三者使用完全相同的数据、split、label、聚合和成本设置。评价 `Child - Parent` 以及 `Child - Control`，而不是只比较两个候选的绝对排行榜。若新 feature 只在某一个被挑选的 parent 上改善，结论限制在该 interaction，不晋升为普遍有效字段。

建议多目标选择，而不是单指标最大化：

```text
direction-adjusted predictive quality
+ cross-code/time stability
+ coverage and uncertainty quality
+ cost-adjusted qspread
+ incremental value vs Alpha Library
- turnover/capacity penalty
- complexity penalty
- duplicate correlation
- search multiplicity penalty
```

### Stage 11：锁定测试

- finalist 定义冻结后才能运行；
- 每个 multiplicity family 按预注册次数使用；
- 结果只用于 confirm/reject/inconclusive；
- 不能触发继续 mutation；
- 测试意外损坏只能由独立审计判定是否允许新 attempt；
- 测试失败后若要研究新想法，必须创建新 run 和新 locked test period。

### Stage 12：稳健性和否证

最终确认至少覆盖：

- 非重叠时间块；
- 股票/行业/universe 子集；
- ret30s/ret60s/ret120s 等 horizon curve，主 horizon 保持预注册；
- 高低波动、价差、成交活跃度 regime；
- 成本、滑点、换手和容量敏感性；
- 关键组件消融；
- placebo、延迟、反向和标签置换；
- 与相似 Alpha 的残差/组合增量；
- 输入字段泄漏和 survivorship 检查。

### Stage 13：科学评审和分层入库

评审分开评价：

1. implementation validity；
2. evidence faithfulness；
3. proxy fidelity；
4. statistical validity；
5. economic mechanism；
6. risk/cost/capacity；
7. novelty/duplication；
8. robustness/falsification；
9. reproducibility。

库分三层：

- **Research Archive**：所有测试过的 hypothesis/factor，包括失败和否证；
- **Feature Registry**：计算/时序/测量验证通过的 feature definition；记录是否有下游增量，但不要求自身有 IC；
- **Model Method Registry**：可复现的模型方法、训练协议和 benchmark 结果，不等同于 Alpha；
- **Candidate Alpha Library**：通过 locked test 和最小 robustness gate；
- **Deployment Registry**：另行人工/运营审批，Auto-Research 不直接部署。

### Stage 14：反馈上游

向 Paper Graph 返回：

- 哪些 paper/claim 真正贡献了可用机制；
- 哪些路径只是结构相关、没有 evidence；
- 需要检索的复现、反驳和邻域；
- 机制在何种市场/状态成立或失败；
- 与已研究 hypothesis 的重复度。

还应返回哪些论文贡献最终形成了：

- 直接因子；
- 新的 approved feature；
- 仅在特定父因子/组合 operator 上有效的 feature interaction；
- 可复现但没有增量的模型方法；
- 新的 label/evaluator 或负面边界。

向 Digest 返回：

- 缺失全文/公式/样本/成本/OOS 证据；
- 变量不可观察或 proxy 不忠实；
- 引用位置不稳定/quote 无法复核；
- 需要重新解析或人工确认的 evidence。

## 11. 状态机和决策语义

### 11.1 Run 状态

```text
CREATED
  -> ENVIRONMENT_FROZEN
  -> EVIDENCE_PENDING | EVIDENCE_READY
  -> FEASIBILITY_CHECKED
  -> HYPOTHESES_READY
  -> PREREGISTERED
  -> EXPLORING
  -> VALIDATING
  -> FINALISTS_FROZEN
  -> LOCKED_TESTING
  -> ROBUSTNESS_REVIEW
  -> COMPLETED
```

允许的暂停/终止：

```text
PAUSED_EVIDENCE
PAUSED_DATA
PAUSED_BUDGET
FAILED_RETRYABLE
FAILED_FINAL
CANCELLED_BY_USER
```

### 11.2 科学决策

```text
PROCEED
REFINE
PIVOT
REPLICATE
REJECT
DUPLICATE
INCONCLUSIVE
PAUSE_EVIDENCE
PAUSE_DATA
PAUSE_BUDGET
```

每次决策保存输入 artifact、指标、规则版本、理由、父 ID、预算和下一合法状态。预算耗尽不得强制 `PROCEED`。

## 12. 统计与评估规范

### 12.1 原始结果不能直接按 factor name 覆盖

`stock_level.parquet` 的自然粒度通常是：

```text
factor × code × horizon × segment × date/window
```

必须先校验唯一键，再生成：

- code-level；
- date-level；
- universe aggregate；
- horizon/regime aggregate。

任何缺失维度或重复键都应 fail closed。

### 12.2 主指标

主指标应是预期方向调整后的聚合预测质量，例如：

```text
signed_rankic = expected_direction_sign * rankic
```

`conditional` 方向必须在 hypothesis 中定义具体条件，不能直接取绝对值。绝对 RankIC 可以作为诊断，不作为唯一 acceptance 指标。

### 12.3 不确定性和稳定性

至少报告：

- 均值、中位数、标准差/稳健离散度；
- 按日期和股票的分布；
- 置信区间或 block bootstrap；
- 正方向占比；
- 最差时间块/股票子集；
- 有效观测和 finite ratio；
- 相对 baseline 的 paired difference。

### 12.4 多重检验

- 所有 candidate/mutation 属于明确 `multiplicity_family_id`；
- 搜索次数、停止规则和选择 trace 完整保存；
- 最终报告披露尝试总数，而不是只展示 winner；
- locked test 限定 finalist 数；
- 大规模筛选可使用 FDR、deflated Sharpe、现实检验或其他预注册方法，但方法必须与指标粒度匹配；
- 不能把同一数据上的多个窗口当成独立复验。

## 13. 执行、恢复和安全边界

- 长时间全文、LLM、graph、fac-eval 和模型任务通过 Slurm；
- 先做 schema、syntax、config 和小样本 probe；
- 每个 attempt 使用独立目录和 immutable input refs；
- 记录 Slurm job ID、资源、wall time、退出码和日志哈希；
- 不允许 sandbox/Slurm 不可用时自动回退到登录节点大任务；
- checkpoint 使用临时文件 + atomic rename；
- resume 前验证所有 parent hash；
- 重放 budget event 必须幂等；
- 不得自动 kill 现有任务；
- 不得动态安装实验依赖或修改固定数据；
- 生成代码仅通过 ASL/白名单 renderer，不允许自由 `exec()`。

## 14. 整个流程最困难的地方

### 14.1 论文机制到可交易因子的语义鸿沟

论文常研究理论变量、跨市场变量或模型输出，而本地只有 L2 快照字段。最危险的错误不是代码失败，而是生成了可计算但不再代表论文机制的 proxy。解决手段是独立的 feasibility/proxy gate、approximation loss 和 proxy falsification。

### 14.2 新颖性无法由局部 graph 证明

Graph 覆盖不完整，术语和公式存在同义表达，行业实现也可能不公开。系统只能给出范围受限的新颖性结论，必须保存检索截止日和 coverage。全球首创需要人工和更完整 prior-art 审核。

### 14.3 多重检验和自适应过拟合

Auto-Research 会自动产生大量候选、窗口和条件。即使每次回测都“合法”，持续看同一验证/测试数据也会过拟合。必须限制搜索预算、保存所有尝试、隔离 locked test，并将 mutation 数量纳入统计解释。

### 14.4 跨股票和跨日期的正确聚合

因子效果具有横截面和时间异质性。单行覆盖、简单平均、按观测量隐式加权都可能产生错误结论。聚合粒度、权重、置信区间和缺失处理必须预注册并测试。

### 14.5 时间尺度和市场迁移

日频 LSTM、外汇预测、美国股票跨证券同步不能直接变成 A 股 ret60s 单证券盘口因子；但与 A 股日频数据契约匹配的论文可以进入独立日频 run。任何跨市场或跨频率迁移仍是一个新 hypothesis，需要明确外推假设和本地证据。

### 14.6 Graph relation 与 claim evidence 不同

引用、共引和文本相似只说明研究关系，不说明支持或反驳。claim-level relation 需要双方全文证据，且要区分方法复用、结论一致和条件限定。

正式 claim relation 使用以下方向语义：`source_claim RELATION target_claim`。

```text
SUPPORTS
CONTRADICTS
REPLICATES
FAILS_TO_REPLICATE
REFINES
QUALIFIES
EXTENDS
USES_METHOD_FROM
BOUNDARY_CONDITION
```

每条关系必须绑定 source/target 两侧 evidence IDs、两份 document version、scope alignment、confidence、extraction method、review status 和 reviewer。只有 `verified` 关系可投影成 Paper Graph edge；`proposed` 只能进入审核队列。若市场、频率、样本、estimand 或方法不具有 exact/partial 可比性，不允许标为 `CONTRADICTS` 或 `FAILS_TO_REPLICATE`，应标为限定/边界或保持 `scope unclear`。

### 14.7 Evidence 的稳定性和可复核性

chunk ID、LLM quote 和缓存路径可能随解析版本变化。必须有 document version、内容哈希、section/page/TeX offsets；否则后续 hypothesis 无法审计。

### 14.8 记忆污染和错误迁移

单次运行的偶然规律最容易被 memory summary 放大。系统需要 scope、promotion、反例、过期和 revalidation；否则 Auto-Research 会反复强化自己的早期偏差。

### 14.9 非平稳性、成本和容量

统计预测不等于可交易 Alpha。市场状态、队列成交概率、交易成本、滑点、冲击和容量可能完全消除信号。Candidate Library 和 Deployment Registry 必须分开。

### 14.10 科学失败与工程失败的区分

编译错误、数据缺失、Slurm 超时不是 hypothesis 被否证；相反，一个运行成功但 proxy 不忠实也不是科学成功。attempt、experiment 和 hypothesis 必须使用不同状态机。

### 14.11 三项目版本一致性

Paper identity、Digest document、market data、field registry 和代码都在演化。任何隐式“读最新文件”都会破坏复现；所有 contract 必须固定版本和 hash。

### 14.12 新特征的测量有效性不等于收益预测

一个更准确的 volatility、book slope 或 liquidity state estimator 可能没有独立 IC，却能改善风险缩放、状态过滤或成本控制。如果只以 IC 筛选，会错误淘汰有价值的研究资产；如果完全不看下游，又可能积累大量无用字段。必须把 calculator validity、measurement validity 和 downstream incremental utility 分成三道 gate。

### 14.13 新字段与父因子的组合爆炸

如果每个 feature 与每个 factor、每种 operator、每个窗口组合，搜索量会指数增长且严重过拟合。父因子选择必须由 graph/evidence/机制相关性预注册，并限制 parent 和 composition 数量。

### 14.14 公平的嵌套消融

Parent 与 Parent+Feature 必须共享数据、split、参数预算和评价；否则改善可能来自额外调参、复杂度或不同缺失样本。还要加入旧 feature/placebo control，区分“任何额外字段都改善”与“这个新字段特有的改善”。

### 14.15 Feature Registry 的单一实现源

当前 derived feature 列表大于真实 runtime 实现，且基础特征在三个模块重复计算。若继续这样扩展，local、renderer 和 fac-eval 会产生同名不同值。必须先建立中央 dependency DAG/calculator，再允许论文特征进入 registry。

### 14.16 学习型特征的训练泄漏和版本爆炸

Latent state、embedding 和神经网络 feature 同时依赖训练窗口、seed、checkpoint 和超参数。它们不是普通字段。必须将 model method 与 trained feature instance 分离，并固定 fit/predict 边界、checkpoint hash、inference latency 和 retraining policy。

### 14.17 论文创新可能只改善方法而不是 Alpha

更好的 estimator、label 或统计协议可能使原有结果变弱甚至消失。这仍是成功的 Auto-Research 结果，因为它提高了测量或否证质量。Research review 不能只按“是否提高 IC”评价论文贡献。

## 15. 分阶段实施计划

### Phase F0：正确性基础

**Paper Graph**

- 保留 Gate 2 审核和 raw recall；
- 已实现稳定 12/54 + candidate 18/92 additive taxonomy loader；
- 已实现 `ClaimRelationV1`、verified-only graph projection 和 schema；
- 已实现 `GraphValueAssessmentV1`、`ResearchPortfolioController` 和预算/主题多样性门槛；
- 已实现显式引用驱动的 path-wise evolution candidate 检索；
- 已实现 `ResearchOpportunityV1`、`FactorResearchPackageV1` 和不可变 hash/ID；
- 已实现 graph -> opportunity -> Agent Alpha package 离线 intake CLI；
- 已实现 opportunity-level feedback -> evidence/relation/archive/priority update；
- 已为 graph snapshot、selection trace 和 evidence bundle 增加 hash；
- 将 Digest 的双侧 evidence extraction 接到 claim-relation proposal/review queue；
- 批量计算 graph value features，并保存 selection trace。

**Digest**

- 将现有 exporter 接入一个离线可测试入口；
- 稳定 evidence span 的 document version/location/hash；
- 输出 factor mechanism extension；
- 增加 V1 contract round-trip tests。

**Agent Alpha**

- 已实现 `FactorResearchPackageV1` -> 现有 graph-research orchestrator adapter；
- 已实现日频/日内 `DataContractV1` registry、observable/path allowlist 和 hash gate；
- 已实现独立 return-only 日频 feature/evaluator、逐日 RankIC artifact 和 aggregate；
- 已实现日频不可变 preregistration 与 locked-test 显式授权入口；
- 修复 fac-eval 多行聚合和唯一键校验；
- 冻结 dates/codes/splits；
- 拆分 exploration/validation/locked test；
- 统一 lifecycle/admission；
- 修复 definition/instance dedupe；
- 建立中央 Feature Registry、FeatureDefinition identity 和单一 FeatureCalculator；
- 让 field registry 只暴露真实 implemented/approved derived features；
- 消除 `hf_feature_builder`、`factor_calculator`、`fac_eval_renderer` 的重复 feature 计算；
- 把现有 control plane 与因子专用 contracts 对齐。

**Gate**：一个合成 factor 的多股票结果能按预注册规则聚合；同定义不同 run 的实例不串联；候选筛选不能直接进入 Candidate Alpha Library；同一 feature 在 local calculator、renderer 和 fac-eval 三处逐值一致，未实现的词表字段被拒绝。

### Phase F1：单篇论文、单 contribution 闭环

- 一个 exact-ID Digest artifact；
- 一个明确 contribution：mechanism/effect 或 measurement feature；
- 若是 feature，先完成 definition/calculator/measurement validation，再做 parent augmentation；
- 最多两个 hypothesis；
- 因子路径每个 hypothesis 使用 1 baseline + 2 primary + 1 placebo；
- 特征路径使用 1 feature + 可选简化版、最多 2 个 parents 和 Parent/Child/Control；
- 固定 20 codes、固定 dates 和 ret60s primary；
- 一轮 refine；
- fake/no-network contract test 后再 Slurm 实验；
- 输出完整 ResearchFeedback。

**Gate**：从 paper ID 到 contribution、evidence、hypothesis、feature/factor、aggregate、review 和反馈可全链追踪；feature 自身无 IC 时不会被错误判为无效。

### Phase F2：小型 Paper Graph 研究

- 一个主论文 + 1–2 个支持/反驳/复现论文；
- claim-level evidence bundle；
- 优先包含一次跨类型组合，例如 mechanism paper + measurement/model paper；
- 运行 CONDITION/REPLICATION/CONTRADICTION_TEST 中至少两种 operator；
- 比较 single-paper baseline 与 graph-conditioned hypothesis；
- 完成 novelty vector 和 prior-art trace。

**Gate**：Graph 带来的改动可以明确说明来自哪条 claim/evidence，而不是笼统声称“多论文更好”。

### Phase F3：受预算 mutation 和 memory

- 接入 `MutationDecisionV1`；
- 区分 retry/refine/proxy/pivot/crossover；
- multiplicity ledger；
- run-local negative memory；
- feature definition/validation/augmentation memory；
- project memory promotion；
- memory snapshot 和 contamination tests。

**Gate**：locked test 对 mutation 不可见；单 run 失败不会成为 global BAD；所有 child 都有父节点和预算记录。

### Phase F4：稳健性和候选库

- horizon/regime/universe/cost/ablation/placebo；
- Verified Metric Registry；
- Research Archive/Feature Registry/Model Method Registry/Candidate Library/Deployment Registry 分层；
- 增量 alpha 和重复性检查；
- evidence-grounded scientific review。

**Gate**：Candidate Library 的每条记录都通过 locked test 和最低稳健性门控；没有自动部署。

### Phase F5：规模化 benchmark

- 先 1 graph，再 3 graph，最后 30 graph；
- 比较 single-paper、graph-conditioned、无 memory、verified memory 四类配置；
- 固定 corpus/config/as-of date；
- 评价新颖性、可证伪率、重复率、负结果率、增量 alpha、成本、人工审核一致性和计算消耗。

**Gate**：规模扩大不降低 provenance、测试隔离、失败保存和 resume 完整率。

## 16. 首个 pilot 建议

### 16.1 论文选择

优先选择：

- limit order book、order flow imbalance、liquidity replenishment、spread 或 price impact；
- exact arXiv/DOI/canonical identity；
- Digest 有可信全文和具体变量/公式/实证证据；
- 变量能映射到本地 L2 direct/derived fields；
- 机制适合 30 秒至 30 分钟 horizon；
- 不依赖跨市场实时数据、专有 HFT 标签或大型训练模型。

当前 `2105.13727` 是日度 LSTM/CPD 慢动量与快速反转论文，不适合作为首个 ret60s 盘口因子 pilot。现有 `HFT Synchronizes Prices` 可以用于接口冒烟，但其跨证券同步机制不能无证据地等同于单证券盘口不平衡。

第一版更推荐采用“新计算特征改善相关父因子”的 pilot，而不是要求论文直接给 Alpha：

```text
主论文贡献：multi-level order-flow/book pressure measurement
  -> FeatureCandidate: multi_level_snapshot_ofi_l5（名称仅示意）
  -> 验证计算、时序、盘口边界和 proxy fidelity
  -> Parent A: 已有 L1 depth imbalance factor
  -> Parent B: 已有 short-horizon price/flow confirmation factor
  -> Child: gate/interact/confirm 中最多两个预注册组合
  -> 比较 Parent、Child、旧 feature/placebo Control
```

如果论文需要逐笔委托事件而本地只有 L2 snapshot，新字段必须命名和标记为 `snapshot-derived proxy`，不能声称完成论文原始 OFI 复现。这个限制本身也是 pilot 要验证的 feasibility 结果。

机器学习论文放在第二个 pilot：优先选择可提取为小型 deterministic estimator 或明确 latent-state feature 的论文；不要一开始训练完整深度模型。

### 16.2 pilot 预算

```text
1 research opportunity
1 primary paper + at most 2 context papers
1 primary ResearchContribution
at most 1 FeatureCandidate + 1 conservative simplified variant
at most 2 related parent factors
at most 2 composition operators per parent
Parent + Child + old-feature/placebo Control paired ablation
at most 1 refinement round
ret60s primary horizon
ret30s/ret120s only in robustness
fixed 20-code universe
fixed non-overlapping date splits
locked test used once for finalists
no automatic deployment
```

### 16.3 pilot 输出

```text
manifest.json
research_opportunity.json
graph_snapshot.json
evidence_bundle.json
research_contributions.jsonl
feasibility_assessments.jsonl
hypotheses.jsonl
novelty_reviews.jsonl
preregistrations.jsonl
feature_definitions.jsonl
feature_validation_results.jsonl
feature_registry_decisions.jsonl
augmentation_hypotheses.jsonl
augmentation_experiments.jsonl
augmentation_outcomes.jsonl
factor_candidates.jsonl
mutation_decisions.jsonl
run_attempts.jsonl
raw_metric_refs.jsonl
evaluation_aggregates.jsonl
verified_metrics.jsonl
lineage.jsonl
negative_results.jsonl
memory_promotions.jsonl
scientific_review.json
research_report.md
research_feedback.json
```

## 17. 验收指标

### 17.1 溯源和契约

- 100% hypothesis 有 evidence 或明确 `extrapolation` 标记；
- 100% factor instance 可回链到 hypothesis/proxy；
- 100% metric 可回链到 immutable config/data/result；
- 0 次 title-only 自动身份合并；
- 0 次不同 run 的 metrics/evaluation 串联；
- 0 次无 hash 的生产 artifact 被 resume。

### 17.2 科学质量

- hypothesis 可证伪率；
- 论文 contribution 分类的 evidence 覆盖率和 routing 审核一致率；
- direct/derived/weak/unavailable proxy 分布；
- FeatureCandidate calculator/renderer/fac-eval parity 通过率；
- feature temporal leakage、session reset、coverage 和 measurement validation 通过率；
- Feature augmentation 的 Parent/Child/Control paired ablation 完成率；
- 无独立 IC 但在预注册下游维度提供稳定增量的 feature 数量；
- 新增 feature 与现有 Feature Registry 的重复率、运行成本和跨股票稳定性；
- baseline/placebo 完成率；
- 探索到验证、验证到 locked test 的通过率；
- 方向一致性、置信区间和跨股票/时间稳定性；
- 成本后效果和 Alpha Library 增量；
- 多重检验披露率；
- 负结果保存率 100%；
- 新颖性结论包含检索范围和不确定性。

### 17.3 Memory 质量

- 100% memory 可回链 source artifact；
- 100% global promotion 有 policy/version 和独立证据；
- 0 次 locked-test outcome 泄漏给 mutation；
- stale memory 检出率和 revalidation 记录；
- 冲突/反例保留率 100%；
- 删除 summary 不影响事实重放。

### 17.4 工程质量

- stage/event/checkpoint 恢复成功率；
- Slurm job 与 attempt 对齐率；
- 预算超限为零；
- raw row 与 aggregate reconciliation 100%；
- 字段/算子/未来信息越权为零；
- 登录节点大任务为零；
- 失败原因和 exclusion reason 保存率 100%。

## 18. 推荐目录和所有权

### Paper Graph

```text
configs/quant_research_taxonomy_extensions_v2.json
schemas/paper_classification_v1.json
schemas/claim_relation_v1.schema.json
schemas/graph_value_assessment_v1.schema.json
schemas/research_opportunity_v1.schema.json
schemas/factor_research_package_v1.schema.json
schemas/opportunity_research_feedback_v1.schema.json
schemas/graph_feedback_update_v1.schema.json
schemas/research_feedback_v1.json
src/paper_graph/taxonomy.py
src/paper_graph/claim_relations.py
src/paper_graph/graph_value.py
src/paper_graph/relation_aware_retrieval.py
src/paper_graph/research_opportunity.py
src/paper_graph/opportunity_feedback.py
src/paper_graph/paper_classification.py
src/paper_graph/research_feedback.py
scripts/enrich_graph_claim_relations.py
scripts/rank_research_graphs.py
scripts/build_auto_research_intake.py
scripts/ingest_auto_research_feedback.py
data/processed/paper_classification/<snapshot_id>/
data/processed/claim_relations/<snapshot_id>/
data/processed/graph_value/<batch_id>/
data/processed/research_opportunities/<snapshot>/
data/processed/research_feedback/<run_id>/
```

### Paper Digest New2

```text
src/llm/three_ai/research_artifact_exporter.py
src/llm/three_ai/factor_mechanism_brief.py
src/llm/three_ai/research_contribution_classifier.py
schemas/research_contribution_v1.json
data/runtime/research_artifacts/<artifact_id>/
data/runtime/research_classification/<artifact_id>/
data/runtime/evidence_gap_queue/
```

### Agent Alpha

```text
src/agent_alpha/contracts/factor_research.py
src/agent_alpha/adapters/factor_research_package.py
src/agent_alpha/data_interfaces/data_contracts.py
src/agent_alpha/daily_research/store.py
src/agent_alpha/daily_research/features.py
src/agent_alpha/daily_research/evaluator.py
src/agent_alpha/daily_research/experiment.py
src/agent_alpha/graph_research/
src/agent_alpha/routing/
src/agent_alpha/feasibility/
src/agent_alpha/features/
src/agent_alpha/models/model_feature_contract.py
src/agent_alpha/evaluation/metric_aggregation.py
src/agent_alpha/memory/promotion.py
src/agent_alpha/feedback/upstream_feedback.py
configs/data_contracts/intraday_hf_v1.yaml
configs/data_contracts/daily_ret_wide_v1.yaml
configs/field_registry_intraday_hf.yaml
configs/operator_registry_daily_return_only.yaml
configs/daily_evaluation.yaml
configs/feature_registry.yaml
src/agent_alpha/workflows/run_daily_factor_research.py
outputs/research_routing/batch_id=<batch_id>/
outputs/factor_research/run_id=<research_run_id>/
```

目录只是建议；真正的边界由 schema、ID、hash 和 adapter 决定。

## 19. 最终原则

1. **Graph 提出值得研究的连接，不证明因子新颖或有效。**
2. **Digest 提供可引用证据，不替下游编造可执行 proxy。**
3. **Agent Alpha 研究因子，而不是最大化一次回测分数。**
4. **mutation 是实验树的一部分，locked test 不是 mutation 的反馈源。**
5. **所有尝试都进入 Research Archive，只有严格 finalist 进入 Candidate Alpha Library。**
6. **Memory 必须有 scope、provenance、promotion、反例和过期机制。**
7. **负结果与正结果同等重要；失败不能被静默覆盖。**
8. **新颖性是分层、范围受限的证据结论，不是 LLM 形容词。**
9. **先把聚合、切分、身份和入库门控做正确，再扩大 graph 和 mutation 规模。**
10. **学术论文的贡献默认先分类为机制、效应、测量特征、模型、标签、执行、评价或边界，不强行转成因子。**
11. **新计算特征先证明计算和测量有效，再用 Parent/Child/Control 消融检验对相关因子的增量；自身没有 IC 不等于无价值。**
12. **Feature Registry、Model Method Registry、Candidate Alpha Library 和 Deployment Registry 必须分开。**
13. **最终系统的价值不是自动生成更多因子，而是以更低的重复研究成本产生更可信、更可解释、更可复现的机制、特征、模型和因子结论。**
