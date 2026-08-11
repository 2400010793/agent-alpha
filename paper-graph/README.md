# Paper Graph

用于构建量化金融论文知识图谱的独立项目。项目的设计目标是借鉴
Connected Papers 的局部论文网络思路，同时保留可复现、可扩展的本地数据管线。

## 统一路线

新 AI 或新会话开始工作前，应先阅读
[三项目闭环 AI 交接文档](docs/ai-handoff-three-project-loop.md)。该文档记录 Paper Graph、
Paper Digest New2、Agent Alpha 的职责边界、OpenAlex 下载状态、Slurm 约束、跨项目数据契约和
当前推荐执行顺序。

仓库的全局目标、分层数据契约、实施阶段、当前任务和验收标准统一记录在
[全局实施计划](docs/global-implementation-plan.md)。OpenAlex 85关键词语料和seed试验的
专项细节记录在[OpenAlex 85关键词计划](docs/openalex-85-keyword-seed-plan.md)；SciNet的
资产审计、关系感知任务和量化金融benchmark设计记录在
[SciNet借鉴计划](docs/scinet-adaptation-plan.md)。后续实现应以这三个文档为准，避免将
召回、金融审核、身份合并、结构图、全文证据和评测混为一个阶段。

Agent Alpha 从单篇论文/扁平候选升级为“每个版本化 Paper Graph 一个独立学术研究 run”的
架构、契约、状态机和分阶段交付门槛记录在
[Agent Alpha Graph Auto-Research 专项计划](docs/agent-alpha-graph-autoresearch-plan.md)。

## 目标

- 统一 arXiv、DOI、OpenAlex、Semantic Scholar 论文身份
- 构建引用图、相似性图和语义证据图
- 支持 JSONL/SQLite 等本地可复现存储
- 为后续因子研究和研究假设发现提供可查询的论文网络

## 设计原则

1. **身份先于关系**：任何节点和边都使用规范化的 `canonical_paper_id`。
2. **引用和相似度分开**：真实引用是证据关系，embedding 相似度是计算关系，不能混成一个 `RELATED_TO`。
3. **局部扩展优先**：围绕种子论文构建局部网络，再逐步扩展，避免一开始抓取整个学术数据库。
4. **来源可追溯**：边保留数据来源、模型和计算指标等 provenance。
5. **先本地、后联网**：外部 API 接入必须经过缓存、断点、小规模测试和请求预算验证。

## 当前阶段

第一阶段只包含本地数据模型、论文 ID 规范化接口、JSONL 读写工具和最小测试。不会自动访问外部 API，也不会修改既有项目或数据。

## 完整项目框架

- `src/paper_graph/`：核心 Python 包
- `tests/`：单元测试
- `data/raw/`：原始输入数据
- `data/processed/`：标准化后的数据
- `configs/`：配置文件
- `docs/`：设计文档
- `scripts/`：可执行脚本
- `outputs/`：导出结果
- `.vscode/`：编辑器和测试设置

核心模块：

- [models.py](src/paper_graph/models.py)：`PaperId`、`PaperNode`、`PaperEdge` 数据模型
- [normalize.py](src/paper_graph/normalize.py)：arXiv、DOI 等外部 ID 规范化
- [graph.py](src/paper_graph/graph.py)：`CITES` 边生成、去重和校验
- [similarity.py](src/paper_graph/similarity.py)：余弦相似度和 Top-K embedding 边
- [pipeline.py](src/paper_graph/pipeline.py)：仅基于本地输入构建两类边
- [jsonl.py](src/paper_graph/jsonl.py)：JSONL 持久化

后续计划模块：

- `ingest.py`：导入已有 JSONL 论文池
- `resolve.py`：统一 arXiv、DOI、OpenAlex、Semantic Scholar 身份
- `metadata.py`：保存论文元数据和本地缓存
- `citations.py`：读取引用和参考文献关系
- `embeddings.py`：批量生成或读取论文 embedding
- `export.py`：导出 JSONL、SQLite 和可视化格式
- `query.py`：查询引用邻居、相似论文和研究路径
- `validate.py`：运行节点、边、ID 和数据完整性检查

## 当前边类型

## 本地网页运行与后端连接

前端开发服务器使用 `5173`，后端固定使用 `8009`。前端代理配置位于
`frontend/vite.config.ts`，指向 `http://127.0.0.1:8009`。后端启动前应确认
`docs/generated/integration-tests/first-full-graph/graph.json` 存在。

后端 readiness 检查同时验证进程和展示 graph：

```text
/api/ready
/api/graphs/realized-volatility?limit=20
/api/graphs/realized-volatility?limit=40
/api/graphs/realized-volatility?limit=80
```

可使用 `scripts/check_backend.py` 进行检查。仅 `/api/health` 返回 200 不代表展示
接口正常；只有 readiness 和三个节点预算都通过，网页才会加载本地完整 graph。

建议启动命令使用项目虚拟环境，并启用 reload：

```text
PAPER_GRAPH_RELOAD=1 /home/gaozh/paper\ graph/.venv/bin/python -m uvicorn scripts.serve:app --host 127.0.0.1 --port 8009
```

不要同时使用多个不同端口的旧后端实例，否则网页可能连接到未更新的代码。

项目暂时只保留两类论文关系：

- `CITATION_SIMILAR_TO`：由文献耦合和同被引共同计算的结构相似关系
- `EMBEDDING_SIMILAR_TO`：基于 embedding 相似度的论文关系，使用 `weight` 保存相似度

两类边分开保存，不合并为统一的 `RELATED_TO`，以保留关系的实际含义。

### Embedding 文本优先级

本项目默认将**标题和关键词作为主体，摘要作为截断后的辅助信息**。原因是关键词通常更直接地表达论文主题，而完整摘要可能过长、包含背景性叙述，容易稀释主题信号。

推荐文本结构：

```text
Title: <title>
Keywords: <keyword 1>; <keyword 2>; ...
Abstract: <abstract 的前 N 个词或字符>
```

默认策略：

- 标题：必须保留；
- 关键词：优先保留，并进行去重、大小写统一和空值过滤；
- 摘要：默认截断到前 1,500 个字符，仅作为方法和结论补充；
- 缺少摘要时：仍然可以使用标题和关键词生成 embedding；
- 缺少关键词时：退化为标题加截断摘要，并降低质量等级。

关键词不是绝对可靠：不同论文的关键词质量和数量可能差异很大。因此后续会保留两个可比较的文本版本：

- `title_keywords`：主版本，突出主题；
- `title_keywords_abstract`：扩展版本，加入截断摘要。

最终 `EMBEDDING_SIMILAR_TO` 默认使用主版本；扩展版本用于小样本稳定性检查，确认摘要是否改变了 Top-K 邻居。

### `CITATION_SIMILAR_TO` 的 Connected Papers 风格实现

Connected Papers 的核心启发是：从一篇或一组种子论文出发，构建一个规模可控的局部论文网络，而不是直接展示全库。Paper Graph 将按以下规则实现：

1. 节点先通过 arXiv、DOI 等 ID 合并，避免同一论文重复出现。
2. 为每篇论文建立 references 集合和 cited_by 集合。
3. 文献耦合比较两篇论文共同引用的参考文献。
4. 同被引比较同时引用这两篇论文的后续论文。
5. 使用两个分数的加权组合筛选每篇论文的 Top-K（默认 40）邻居。
6. 删除自环和重复边，并保留两个分量分数、权重和数据来源。

因此，Connected Papers 风格体现在**候选集扩展、共引/耦合度计算、局部网络、相似度排序和可视化布局**，而不是把引用边和 embedding 边合并。

推荐的边 JSONL 形式：

```json
{"source":"arxiv:2401.00001","target":"arxiv:2301.00002","relation":"CITATION_SIMILAR_TO","weight":0.64,"metadata":{"method":"co_citation_and_bibliographic_coupling","bibliographic_coupling":0.72,"co_citation":0.56}}
{"source":"arxiv:2401.00001","target":"arxiv:2402.00003","relation":"EMBEDDING_SIMILAR_TO","weight":0.87,"metadata":{"metric":"cosine","model":"SPECTER2"}}
```

### 局部网络算法草案

```text
种子论文
	-> references / cited_by
	-> 过滤无效节点、去重
	-> 获取局部论文元数据
	-> 生成 embedding
	-> 计算候选论文相似度
	-> 每个节点保留 Top-K 相似邻居
	-> 输出 CITATION_SIMILAR_TO + EMBEDDING_SIMILAR_TO
```

第一版只要求稳定生成节点和边；布局算法、网页可视化和大规模 API 同步放到后续阶段。

## 开发

安装开发依赖后运行测试：

```text
pip install -e '.[dev]'
pytest
```

也可以执行本地空管线：

```text
python scripts/build_local_graph.py
```

该脚本不会访问任何外部 API。

## OpenAlex v5 筛选

v4 保留为已提交全量作业的冻结基线；v5 通过显式 profile 启用，不会改变或混写 v4
断点。v5 只有在通用方法词（如 `machine learning`）与标题/摘要中的金融市场对象共同
出现时才保留候选，并将 `microstructure` 的材料学单独命中降为弱候选。它还支持一组
高精度中文、法文、西班牙文和印尼文金融别名。

直接从 OpenAlex Works 使用 v5：

```text
python scripts/extract_openalex_quant_candidates.py \
  --input-root data/raw/openalex/2026-06-26/parquet/works \
  --output-root data/processed/openalex_quant_full_v5 \
  --filter-profile v5
```

推荐在已有 v4 紧凑候选上流式重审，避免再次扫描原始快照：

```text
python scripts/reaudit_openalex_candidates_v5.py \
  --input-root data/processed/openalex_quant_full_v4/legacy_jsonl \
  --output-root data/processed/openalex_quant_full_v5
```

流式输出只保留 v5 候选；`ai_review/` 仅包含确定性规则判为高优先级的边界论文，
medium/low review 不调用 AI。

## 数据安全边界

- 不覆盖现有项目 `/home/gaozh/my-paper-digest-new2` 的数据。
- 不自动复制或修改既有 8,732 篇正式论文池。
- `data/raw/`、`data/processed/` 和 `outputs/` 默认不提交大文件。
- 任何联网抓取功能都必须显式开启，并先通过小规模 probe。

## 分阶段路线

### Phase 1：本地骨架（当前）

- 数据模型和 ID 规范化
- JSONL 读写
- `CITATION_SIMILAR_TO` 边生成、去重、校验
- embedding 相似度和 Top-K 边

### Phase 2：导入现有论文池

- 导入旧池和新增链接池
- canonical ID 去重
- 输出标准化 Paper JSONL

### Phase 3：引用网络

- 使用缓存的元数据接口获取 references/citations
- 构建局部 Connected Papers 风格网络
- 增加增量更新和失败记录

### Phase 4：embedding 网络

- 生成论文标题、摘要 embedding
- 计算局部候选集相似度
- 输出 Top-K `CITATION_SIMILAR_TO` 和 `EMBEDDING_SIMILAR_TO` 边

### Phase 5：查询和可视化

- SQLite/DuckDB 查询
- Prior Works、Derivative Works
- 交互式局部网络
- 论文路径和证据回溯

## 前端可视化原型

`frontend/` 包含一个不依赖后端接口的 React/Vite 原型，使用本地示例数据展示以
seed 论文为中心的研究图谱。页面目前支持：

- 节点大小映射 Global Impact（总被引频次）
- 节点颜色映射发表年份
- 独立切换 `EMBEDDING_SIMILAR_TO` 和 `CITES` 两种连线
- 相似度阈值过滤
- 论文搜索和节点详情面板
- Graph view / List view 切换
- Seed、Prior Work、Derivative Work 角色标识

启动前端：

```text
cd frontend
npm install
npm run dev
```

当前页面使用本地 mock 数据，后续可将 `App.tsx` 中的论文和边数据替换为 API 响应，
而不需要改变图谱视觉层的核心结构。

外部 API 接入、批量抓取和大规模运行将在完成小范围验证后单独实现。

## 当前页面 API 契约

当前先提供本地数据驱动的接口，页面可以围绕用户选中的 seed 论文工作：

- `GET /api/search?q=...&limit=20`：搜索论文候选，不直接生成全局图。
- `GET /api/graphs/{paper_id}`：生成以该论文为 seed 的局部图谱。
- `GET /api/papers/{paper_id}`：获取论文详情。

图谱响应固定包含 `seed`、`nodes`、`edges` 和 `stats`。节点通过 `is_seed` 和 `role` 标记 seed；边只使用 `CITATION_SIMILAR_TO` 与 `EMBEDDING_SIMILAR_TO`。FastAPI 是可选依赖，当前接口不会自动访问外部数据源。
