# SciNet 借鉴与量化金融关系感知检索计划

## 1. 目的

本计划是 Paper Graph 的第二专项计划。第一专项计划解决“如何从 OpenAlex 找到85关键词
相关论文并建立可靠身份和seed”；本计划解决“得到论文网络以后，如何借鉴SciNet把它
变成可评测、可查询、可用于科学发现的关系感知系统”。

目标不是复制 `SciNet/` 中的脚本，而是复用其三层任务思想，并基于本仓库的OpenAlex
2026快照、量化金融语料和Paper Digest证据层重新实现一个可复现的 **FinSciNet**：

1. Ego-centric：寻找某个量化主题中最具新颖性或颠覆性的论文；
2. Pair-wise：寻找支持、批评、共现、比较或扩展目标论文的研究；
3. Path-wise：构建从经典论文到前沿论文的有向引用和方法演化路径。

## 2. 对克隆仓库的事实审计

### 2.1 可直接借鉴的资产

`SciNet/` 公开了：

- 三层任务分类和自然语言查询模板；
- 七个领域的子领域列表；
- 14个评测脚本；
- novelty、disruption、citation sentiment、co-mention和citation path的评测思路；
- 使用OpenAlex结构图、arXiv/OA全文、GROBID和少量人工审核的组合方法。

仓库中的查询文件实际计数：

| 任务 | 文件数 | 当前checkout中的查询数 |
|---|---:|---:|
| Task 1 | 14 | 2,640 |
| Task 2 | 14 | 4,200 |
| Task 3 | 7 | 2,185 |
| 合计 | 35 | 9,025 |

论文和README声称总任务为8,940，其中Task 3为2,100。当前checkout的Task 3多出85条，
因此在复用前必须固定commit、记录文件哈希，并对查询数量和论文版本做一致性审计。

### 2.2 不能直接运行或复制的部分

当前checkout不包含：

- novelty/disruption ground truth；
- OpenAlex正向、反向引用SQLite数据库；
- works数据库；
- arXiv PDF语料；
-模型retrieval结果；
-完整依赖和可复现实验配置。

评测脚本还存在工程性风险：

- 多个Python文件含Markdown围栏，不能直接执行；
- 路径、模型分数和结果文件硬编码；
- LLM endpoint/API key是占位符；
- 部分query/result路径疑似写反或相同；
- path connectivity通过随机排列尝试连通，结果不确定，也没有严格保证查询端点；
- citation context通过标题模糊匹配，存在同名或近似标题误配；
- co-mention脚本中第三方citing paper的标题/PDF解析仍有placeholder；
- README声明MIT，但当前文件清单中没有独立LICENSE文件，复用代码前仍需核实许可边界。

结论：**借鉴任务定义、指标思想和数据构建流程；不把原脚本作为生产依赖。**

## 3. SciNet 与 Paper Graph 的映射

| SciNet能力 | Paper Graph已有基础 | 需要新增 |
|---|---|---|
| OpenAlex全局图 | manifest固定Parquet、DuckDB查询 | 正反引用生产索引 |
| 子领域 | 85词、79规范短语、现有54主题taxonomy | 量化主题层级和版本化映射 |
| Novelty | references、topics | 时间安全pair z-score和p10 |
| Disruption | references、反向引用查询 | Ni/Nj/Nk窗口统计 |
| Positive/negative citation | Digest全文入口 | citation span和stance schema |
| Co-mention | references、共引 | 同段落证据和第三方citer节点 |
| Evolution path | 本地seed双向邻域 | 有向、时间单调、主题约束路径算法 |
| Retrieval benchmark | API和图响应 | query/GT/run/metric统一schema |
| Human QA | 尚未标准化 | 盲审样本、双标注和仲裁流程 |

## 4. FinSciNet 数据范围

### 4.1 语料范围

第一版只使用通过以下条件的论文：

- OpenAlex 2026-06-26固定快照；
- 2016年至快照日期发表；
- 命中85词召回规则；
- `finance_status=accepted`，或经人工确认的review记录；
- 完成canonical identity去重；
- 非撤稿、非paratext、非XPAC。

为了构建历史路径和计算结构指标，可以把2016年前论文作为**背景图节点**，但它们不进入
“近十年85词检索语料”的主统计。背景节点必须标记 `corpus_role=historical_context`。

### 4.2 主题体系

不能把85个词直接等同于85个互斥主题。第一版建立三级体系：

1. `domain`: quantitative_finance；
2. `topic`: 市场微观结构、订单簿、流动性、执行、订单流、波动率、反转/动量、
   量价、市场做市、回测/机器学习；
3. `keyword`: 85个原始词和79个规范短语。

一篇论文允许多topic、多keyword。所有benchmark query固定taxonomy版本和论文集合版本。

## 5. 统一Benchmark数据契约

### 5.1 Query

每个query保存：

- `query_id`；
- `task_level`: ego/pair/path；
- `task_type`；
- 自然语言query及可选同义改写；
- topic/keyword范围；
- 时间截面 `as_of_date`；
- 查询端点或目标paper ID；
- 候选语料版本；
- 构建规则版本；
- 人工审核状态。

### 5.2 Ground truth

每条ground truth保存：

- canonical paper IDs和OpenAlex IDs；
- 排序或路径顺序；
- 原始结构分数；
- percentile；
- 计算窗口和公式版本；
- citation/context证据；
- 自动、规则或人工来源；
- 审核者匿名ID、分歧和仲裁结果。

### 5.3 Retrieval run

每次系统运行保存：

- `run_id`、系统/模型版本和配置；
- 输入query版本；
- 有序结果及每条结果的检索理由；
- 使用的结构边、全文证据和工具调用摘要；
- token、延迟和成本；
- 失败及未找到原因。

### 5.4 Metric report

同时报告macro和micro指标，并按topic、年份、arXiv覆盖、引用密度和查询难度分层。
不允许只报告总平均数。

## 6. Task 1：Ego-centric结构价值检索

### 6.1 Novelty

借鉴SciNet/Uzzi方法，对论文参考文献中的所有无序pair计算其在论文发表前、同领域和同年份
背景下的异常组合分数：

$$
z_{ij,t}=\frac{O_{ij,t}-E_{ij,t}}{\sigma_{ij,t}}
$$

论文新颖度使用pair z-score的第10百分位：

$$
N_p=P_{10}\left(\{z_{ij,t}:i,j\in R_p\}\right)
$$

$N_p$越低，结构组合越新颖。实现要求：

- 只使用论文发表时已经存在的引用和历史共引频率；
- 分年度或滚动窗口计算，避免未来信息泄漏；
- 少于2条可解析references的论文标记为不可计算，不赋0分；
- 保存pair覆盖率，防止只有少量pair命中却产生极端分数；
- 同时保存raw score、topic内percentile和全语料percentile。

首版ground truth：每个量化topic中满足最低引用完整度的Top 20；稳定后扩展Top 50。

### 6.2 Disruption

SciNet正文采用：

$$
D_{2}=\frac{N_i-N_j}{N_i+N_j}
$$

其中$N_i$为只引用焦点论文、不引用其前序工作的后续论文；$N_j$为同时引用焦点论文和其
前序工作的后续论文。经典CD指标还常包含只引用前序工作的$N_k$：

$$
D_{3}=\frac{N_i-N_j}{N_i+N_j+N_k}
$$

FinSciNet同时计算并明确命名 `disruption_d2_scinet` 与 `disruption_cd3`，不混用。

实现要求：

- 使用固定前向观察窗口，例如发表后5年；
- 对窗口不足的新论文标记right-censored，不能与成熟论文直接排名；
- 分别报告Ni/Nj/Nk和有效后续论文数；
- 设置最低后续引用数，避免1次引用产生极端±1；
- 结果按发表年和topic归一化。

### 6.3 查询和评测

示例：某topic中最具新颖性的Top 5论文；某topic中最具颠覆性的Top 5论文。

指标：

- Recall@K；
- nDCG@K；
- mean percentile of retrieved papers；
- 可计算覆盖率；
- 时间切片稳定性。

LLM标题/摘要评分只作为辅助分析，不作为结构ground truth。

## 7. Task 2：Pair-wise同行评价和上下文关系

### 7.1 Citation stance

查询方向必须固定：给定目标论文A，返回引用A的论文B，并判断B在具体citation context中
对A的态度。

第一层标签借鉴SciNet：

- `positive`：采用、支持、确认或明确赞同；
- `negative`：批评、质疑、报告失败或指出限制；
- `neutral`：背景介绍、事实描述或无明显评价。

第二层扩展为Paper Graph关系：

- `SUPPORTS`
- `CONTRADICTS`
- `REPLICATES`
- `EXTENDS`
- `QUALIFIES`
- `USES`
- `COMPARES`

注意：`positive`不能直接等同于`SUPPORTS`，`negative`也不能直接等同于
`CONTRADICTS`。例如“方法很重要但不适用于高频数据”可能是正面评价加限定关系。

证据记录必须包含：

- citing paper B、target paper A；
- bibliography ref ID和canonical ID；
- 引用句、所在句、段落、章节、页码/TeX anchor；
- stance标签与claim关系；
- 解析方法、模型版本、置信度和人工审核结果。

### 7.2 Co-mention

给定A，返回B，要求存在第三篇论文C：

1. C同时引用A和B；
2. 强ground truth要求A和B出现在C的同一段落；
3. 保存C及其具体段落，不能只保存布尔值；
4. 区分同段共现、同句共现、同一citation cluster和仅全篇共引。

Co-mention只表示“在同一论述语境被比较/联合提及”，不自动表示支持或相似。

### 7.3 全文处理策略

优先顺序：

1. arXiv TeX结构化引用；
2. OpenAlex OA PDF及GROBID TEI；
3. Paper Digest已有解析结果；
4. 无全文时只生成结构候选，不产生上下文ground truth。

匹配优先使用DOI/arXiv/OpenAlex身份；标题模糊匹配只作为回退，并进入人工审核。

### 7.4 评测

- Cite-Precision/Recall；
- Stance macro-F1和每类F1；
- Co-citation precision；
- Same-paragraph precision/recall；
- evidence span exact/overlap score；
- claim-relation macro-F1；
- calibration/Brier score。

## 8. Task 3：Path-wise科学演化路径

### 8.1 Query构建

每个量化topic选：

- 经典端点：较早、引用高、结构中心性高的论文；
- 前沿端点：近期、topic相关、已有可验证引用连接的论文。

端点pair必须满足：

- 时间方向明确；
- OpenAlex有向引用图中可达；
- topic和Digest证据表明技术上相关；
- 人工审核确认不是偶然跨领域引用。

### 8.2 路径算法

不采用SciNet评测脚本中的随机排列连通测试。FinSciNet要求：

- 路径从指定经典端点开始，以指定前沿端点结束；
- 每个后续节点显式引用前一个节点；
- 发表年份非递减；
- 节点不重复；
- 最大hop数和候选扩展数固定；
- 算法和tie-break确定性。

候选路径综合评分：

$$
S(P)=\alpha\sum_{v\in P}\log(1+c_v)
+\beta\sum_{e\in P}r_e
+\gamma\,T(P)
-\lambda\,|P|
$$

其中$c_v$是时间截面内引用数，$r_e$是citation context关系质量，$T(P)$是topic/方法
一致性。先生成若干结构候选，再由人工或证据模型审核逻辑演化，避免仅因高被引而选择
主题不连贯的hub。

### 8.3 评测

- Endpoint accuracy；
- Directed connectivity；
- Ground-truth node/edge precision、recall和F1；
- nDCG/ordered overlap；
- temporal monotonicity；
- path rationality（固定rubric，LLM与人工分开报告）；
- path diversity，避免所有路径经过相同高被引hub。

## 9. FinSciNet构建阶段

### Stage S0：仓库资产审计

状态：已完成第一轮。

- 固定SciNet commit `ed5c76f`；
- 统计当前query文件；
- 确认缺失ground truth、数据库和PDF资产；
- 记录不能直接复用的脚本问题；
- 仅将克隆仓库作为参考资料，不加入生产数据链依赖。

### Stage S1：统一Benchmark schema

任务：

- 建立query、ground truth、run和metric dataclass/JSON schema；
- 建立版本、哈希和provenance字段；
- 写schema验证和示例fixture；
- 将OpenAlex/arXiv canonical identity设为强制字段。

### Stage S2：量化topic与候选语料

依赖第一专项计划Gate 2/3。

- 将85词映射到稳定topic；
- 对accepted语料建立topic membership；
- 冻结benchmark corpus版本；
- 生成每个topic的候选统计和审核样本。

### Stage S3：Ego指标pilot

- 选3个主题：limit order book、realized volatility、market making；
- 每个主题最多1,000篇候选；
- 实现时间安全novelty；
- 实现D2和CD3 disruption；
- 人工检查各主题Top 20；
- 验证年份、引用稀疏和right-censor偏差。

### Stage S4：Pair-wise证据pilot

- 选择30个有arXiv/OA全文的seed；
- 提取显式引用上下文；
- 构建positive/negative/neutral及细粒度claim关系；
- 构建same-paragraph co-mention；
- 双人盲审至少100个context，分歧仲裁；
- 先离线保存候选，不自动写入正式知识图谱。

### Stage S5：Path-wise pilot

- 每个试验topic选择5组classic→frontier端点；
- 生成确定性有向候选路径；
- 比较高引用路径、最短路径和关系加权路径；
- 人工审核路径连贯性；
- 固定15条gold path后进行检索评测。

### Stage S6：Relation-aware retriever

检索分两阶段：

1. 语义/关键词召回候选；
2. 根据任务类型调用结构算子：novelty rank、disruption rank、citing stance、
   co-mention或path search。

Agent回答必须返回paper IDs、路径/关系和证据，不能只返回自然语言标题列表。

### Stage S7：Benchmark与下游评测

- 固定baseline：关键词、BM25、已有embedding（只复用）、结构检索、混合检索；
- 运行ego/pair/path指标；
- 用相同论文预算生成文献综述；
- 评价relevance、completeness、depth、logical consistency和evidence faithfulness；
- 报告错误类型：语义漂移、近期偏差、关系方向错误、断链、身份错配和证据幻觉。

## 10. 建议代码框架

```text
src/paper_graph/evaluation/
    schemas.py             # Query / GroundTruth / Run / Metric
    corpus.py              # benchmark corpus freeze and hashes
    novelty.py             # Uzzi pair z-score and p10
    disruption.py          # D2 and CD3 with windows/censoring
    citation_context.py    # citation span and stance records
    comention.py           # same-sentence/paragraph co-mention
    paths.py               # deterministic directed path search
    metrics.py             # recall, nDCG, F1, connectivity, calibration
    validation.py          # leakage, identity and evidence checks
scripts/
    build_finscinet_corpus.py
    build_finscinet_ego.py
    build_finscinet_pairwise.py
    build_finscinet_paths.py
    evaluate_finscinet_run.py
configs/
    finscinet_topics.json
    finscinet_benchmark.json
slurm/
    finscinet_ego_pilot.sbatch
    finscinet_pairwise_pilot.sbatch
    finscinet_path_pilot.sbatch
```

## 11. 与全局计划的衔接和执行门控

1. OpenAlex 85词sample通过后，才能冻结FinSciNet候选语料；
2. canonical identity完成后，才能构建ground truth；
3. 全量正反引用索引完成后，才能计算完整novelty/disruption和路径；
4. Digest小批全文试验通过后，才能构建pair-wise上下文标签；
5. 每类任务先小规模pilot和人工审核，再扩大；
6. 所有大规模计算、全文处理和模型评测通过Slurm；
7. 不为该计划提交新的embedding生成任务。

## 12. 第一批具体交付物

下一步按顺序实现：

1. `evaluation/schemas.py`及schema测试；
2. `configs/finscinet_topics.json`，把85词映射到稳定量化主题；
3. `evaluation/disruption.py`，先用小型合成引用图验证Ni/Nj/Nk；
4. `evaluation/paths.py`，验证有向端点和时间单调；
5. 等OpenAlex样本审核完成后，选择3主题建立Ego pilot；
6. 从精确arXiv seed中选择全文Pair-wise pilot。

完成以上六项后，Paper Graph将不再只是“找到量化论文并画图”，而会拥有一个能够客观
评测关系感知检索、同行评价理解和科学演化路径重建的量化金融基准框架。
