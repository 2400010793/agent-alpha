# paper-digest new2

`my-paper-digest-new2` 用于抓取研究资料、构建 arXiv evidence pack、运行 three-AI 论文解析、生成高频代理因子，并渲染静态网页。

当前代码已经迁移到 `src/` 包结构；旧脚本目录已删除。新的命令入口统一使用 `python -m src.<package>.<module>`，运维 shell 入口放在 `deploy/bin/`。

## 目录结构

- `src/io/`：JSONL、配置、datetime、identity、RSS/Atom/sitemap 和 HTTP source fetch。
- `src/arxiv/`：arXiv id、stage-1 gate、TeX/evidence pack 相关逻辑。
- `src/llm/common/`：LLM JSON、错误处理和评分等共享工具。
- `src/llm/article/`：单阶段文章解析流程。
- `src/llm/three_ai/`：three-AI 读取、因子生成、faithfulness audit 流程。
- `src/factor/core/`：factor 规范化等核心数据整理。
- `src/factor/generation/`：HF proxy factor 生成和公式渲染。
- `src/factor/calculation/`：fac-eval 因子计算入口。
- `src/factor/evaluation/`：候选筛选、质量规则和评估结果汇总。
- `src/factor/proxy/`：proxy registry 和论文变量到可执行代理变量的映射。
- `src/render/`：网页和报告渲染、HF proxy diversity summary。
- `src/pipeline/`：daily pipeline、crawler、hourly parser、render all、报告刷新等入口。
- `deploy/bin/`：shell wrapper，供 cron/systemd/手动运维调用。
- `deploy/systemd/`：systemd service/timer 配置。
- `config/`：sources、proxy registry、机制 taxonomy、质量阈值和 fac-eval 配置。
- `data/`：JSONL、runtime state、factor manifest 和评估结果。
- `public/`：静态网页输出。
- `reports/`：运维和质量报告。
- `logs/`：服务与批处理日志。

## 常用入口

手动抓取/日报 pipeline：

```bash
cd /home/gaozh/my-paper-digest-new2
python3 -m src.pipeline.daily_research_pipeline --project-root . --config config/sources.yaml
```

dry-run：

```bash
python3 -m src.pipeline.daily_research_pipeline --project-root . --config config/sources.yaml --dry-run
```

检查单个 source：

```bash
python3 -m src.pipeline.probe_source_fetch --source-id quant_wiki_internal --max-items 3
python3 -m src.pipeline.probe_source_fetch --source-id quantocracy_mashup --max-items 3
python3 -m src.pipeline.probe_source_fetch --source-id arxiv_qf --fetch-month 202601 --max-items 20
```

重建稳定文章池：

```bash
python3 -m src.pipeline.build_paper_hf_archive_input --output data/analysis_archive.jsonl
cp data/analysis_archive.jsonl data/latest.jsonl
```

刷新运维报告：

```bash
python3 -m src.pipeline.update_pipeline_reports
```

重新渲染全部页面：

```bash
python3 -m src.pipeline.render_all_daily_pages
```

运行 three-AI 单篇解析入口：

```bash
python3 -m src.llm.three_ai.pipeline --project-root .
```

单次 API 但保留分块 evidence 结构的阅读模式：

```bash
python3 -m src.llm.three_ai.pipeline --project-root . --single-call-chunked-reading
```

运行 hourly three-AI 调度一次：

```bash
bash deploy/bin/run_three_ai_hourly_once.sh
```

连续 arXiv evidence crawler：

```bash
bash deploy/bin/run_arxiv_evidence_crawler_continuous.sh
```

生成 HF proxy factor 测试文件：

```bash
python3 -m src.factor.generation.generate_paper_hf_factor_tests \
  --input data/analysis_archive.jsonl \
  --output-dir data/paper_hf_factor_tests_v2
```

运行 fac-eval：

```bash
python3 -m src.factor.calculation.run_factor_eval \
  --factor-dir data/paper_hf_factor_tests_v2 \
  --result-dir data/paper_hf_factor_results_v2 \
  --force
```

生成 HF proxy diversity summary：

```bash
python3 -m src.render.summarize_hf_proxy_diversity
```

## systemd

当前 service 文件已指向 `deploy/bin/`：

- `deploy/systemd/paper-arxiv-evidence-crawler.service`
- `deploy/systemd/paper-three-ai-hourly.service`
- `deploy/systemd/paper-three-ai-hourly.timer`
- `deploy/systemd/paper-web-new2.service`

修改 service 文件后需要手动执行：

```bash
systemctl --user daemon-reload
```

本次结构迁移只更新仓库内配置，不主动重启或 kill 正在运行的服务。

## 关键数据口径

- 稳定文章池：`data/analysis_archive.jsonl`，同步展示文件为 `data/latest.jsonl`。
- arXiv evidence archive：`data/arxiv_evidence_archive.jsonl`。
- three-AI hourly runtime evidence：`data/runtime/three_ai_hourly_current_evidence.jsonl`。
- three-AI attempts/state：`data/runtime/three_ai_hourly_attempts.jsonl` 和 `data/runtime/three_ai_hourly_state.json`。
- HF proxy manifest：`data/paper_hf_factor_tests_v2/manifest.json`。
- HF proxy small 评估：`data/paper_hf_factor_results_v2/`。

稳定文章池保留规则：

```text
1. 保留 analysis_agent 包含 schema-v6 的 LLM 解析文章。
2. 保留 analysis_version == v2 的历史解析文章。
3. 额外保留 YAML 抓取且通过展示质量过滤、recommendation_score >= 5 的相关文章。
```

## 配置

- `config/sources.yaml`：抓取源、关键词、开关、RSS/sitemap 地址、`max_items`、`max_age_days`、`source_timeout_sec`、`latest_limit`、`use_proxy` 和本地缓存文件。
- `config/proxy_registry.yaml`：论文变量到可执行 proxy family 的映射。
- `config/proxy_variant_templates.yaml`：proxy 变体生成模板。
- `config/factor_quality_thresholds.yaml`：small / medium / large 质量阈值。
- `config/factor_eval_small1.yaml`、`config/factor_eval_medium1.yaml`、`config/factor_eval_large1.yaml`：fac-eval 配置。

修改 YAML 后建议先检查：

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

for path in sorted(Path('config').glob('*.yaml')):
    yaml.safe_load(path.read_text(encoding='utf-8'))
    print(f'ok {path}')
PY
```

## 验证

结构调整后可以运行：

```bash
python3 -m py_compile $(find src -name '*.py' -print)
python3 -m src.pipeline.daily_research_pipeline --help
python3 -m src.pipeline.render_all_daily_pages --help
python3 -m src.llm.three_ai.pipeline --help
python3 -m src.pipeline.three_ai_hourly_once --help
python3 -m src.pipeline.arxiv_evidence_crawler --help
python3 -m src.factor.generation.generate_paper_hf_factor_tests --help
python3 -m src.factor.calculation.run_factor_eval --help
python3 -m src.factor.evaluation.select_paper_hf_medium_candidates --help
```

确认没有旧入口残留：

```bash
test ! -e ./scripts
grep -R "old script entrypoint" src deploy README.md .github
```
