# Scripts

## Auto-Research intake and feedback

`build_auto_research_intake.py` 离线消费一个冻结 graph、
`GraphValueFeaturesV1`、外部论文结构化模块产生的
`StructuredPaperArtifactRefV1` JSONL，以及可选的 `ClaimRelationV1` JSONL。
它固定 graph/evidence/data/registry/memory/budget 身份，先输出
`ResearchOpportunityV1`；只有硬门槛通过时才输出
`FactorResearchPackageV1`，否则写入 evidence/data/human-review queue。

`rank_research_graphs.py` 在多个 graph 之间执行透明价值排序和预算/主题多样性
选择；`enrich_graph_claim_relations.py` 只把 verified、双侧 evidence 完整的
claim relations 投影为正式 graph edges。

Agent Alpha 完成研究后输出 `OpportunityResearchFeedbackV1`，再由
`ingest_auto_research_feedback.py` 转成受限的 `GraphFeedbackUpdateV1`。
该更新可以请求证据、复核关系、记录 scope-bound 负结果或调整下一轮优先级，
但禁止据本地因子结果直接修改论文真假或跨数据契约迁移结论。

## OpenAlex snapshot

`sync_openalex_snapshot.py` 根据官方 manifest 可恢复地同步一个实体，仅下载
manifest 列出的单一格式。文件按快照日期隔离，已有且大小匹配的对象会复用。

- 小范围连通性/格式探针：`sbatch slurm/openalex_snapshot_probe.sbatch`
- 完整 Works Parquet：`sbatch slurm/openalex_snapshot_full.sbatch`
- 四节点互斥分片下载：`sbatch slurm/openalex_snapshot_sharded.sbatch`

分片任务使用 `--shard-count` 和 `--shard-index` 按 manifest 位置取模，所有
分片互斥且并集等于原始选择集。每个分片写独立的 `sync-summary-shard-*.json`，
因此可以安全共享同一快照目录；分片全部成功后再运行完整同步脚本，可快速
校验全部文件并生成最终 `sync-summary.json`。

`fetch_openalex_api_candidates.py` 是受预算保护的 API 备选通道。它只从环境变量
`OPENALEX_API_KEY` 读取 key，按页原子落盘并保存 cursor；`--max-pages` 和
`--max-cost-usd` 是每次运行的硬限制，403/5xx 使用退避，429 会安全停止。
Slurm 脚本会先使用已导出的环境变量；如果未设置，则从
`~/.config/paper-graph/openalex_api_key` 读取只包含 key 的私密文件。建议权限设为
`0600`，不要把 key 写入仓库或日志。配置好后可运行
`sbatch slurm/openalex_api_candidates.sbatch`；脚本会从匿名
pilot 的 cursor 继续，最多再请求 250 页并限制本次费用不超过 0.25 美元。

无法申请 key 时，可运行
`sbatch slurm/openalex_api_candidates_anonymous.sbatch`。它会显式清除继承的 key，
仅使用匿名每日额度，单次最多 80 个搜索页（0.08 美元）；如果共享出口的
当日额度已被用完，会保存 cursor 后安全停止。

快照尚未下载完时，可运行
`sbatch slurm/openalex_extract_available_v5.sbatch` 立即扫描启动时已完整下载的
`*.parquet` 分片。下载中的 `*.partial` 文件不会被读取，因此可与快照同步任务
并行运行；后续重跑会通过 checkpoint 复用已处理分片。

2026-06-26 的 Works Parquet manifest 包含 2,446 个文件、510,372,821 条
Work，总下载量 724,970,323,127 bytes。开始完整同步前应先通过探针验证计算节点的
公网访问和 Parquet schema。
