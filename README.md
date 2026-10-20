# DICOM-to-BIDS Conversion Skill

> 基于 ODLoc / EYEDEP_CRF / MP_CRF / MonoDep 四个项目与 HS7T 电影 fMRI（2026）提炼的端到端工作流。
> 设计目标：任何具备 shell 执行、文件读写和有限用户交互能力的 AI agent 均可执行此流程。

English version: [README_EN.md](README_EN.md)

这是一个面向 agent 的 MRI DICOM-to-BIDS workflow/skill 包，而不是单一脚本：

- skill 入口：`SKILL.md`（完整流程的唯一真源）
- 可直接调用的 Python 脚本（只用标准库，兼容 Python 3.6；侦察和 DICOM 生理记录另需 pydicom）
- 项目声明模板、参考文档、真实项目抽象出的示例
- 可选的 agent 平台 metadata 示例：`agents/openai.yaml`

**核心设计**：所有人工判断写进项目声明文件（`project.json` / `protocol.tsv` / `decisions.tsv` / config），
从 DICOM 一条命令重跑出同样的 BIDS；转换前可用真实 dcm2bids 预演每个 session 的结果；
无法自动决定的情况整体停下、不改任何文件，交给人决定。

## Quick Start

```bash
SKILL_DIR="<path-to-this-repo>"
PROJECT_DIR="<project-root>"
PY_DCM="<python of the env where dcm2bids + pydicom are installed>"

# 1. 初始化：复制模板，手写 participants_mapping.tsv（participant_id, [session], dicom_dir, [physio_mode]）
mkdir -p "$PROJECT_DIR/code"
cp "$SKILL_DIR"/templates/{project.json,protocol.tsv,decisions.tsv,dcm2bids_config.json,decision_log.md} "$PROJECT_DIR/code/"

# 2. 侦察：每个 series 一行 + 跨 session 汇总（命名变体、帧数分布）
$PY_DCM "$SKILL_DIR/scripts/scout.py" "$PROJECT_DIR"

# 3. 按侦察结果写 config / protocol / project.json，然后检查
python3 "$SKILL_DIR/scripts/lint_config.py" "$PROJECT_DIR/code/dcm2bids_config.json" --fix

# 4. 预演（不转影像）：每个 series 会变成什么、哪些 session 需要人工决定
python3 "$SKILL_DIR/scripts/preview.py" "$PROJECT_DIR"

# 5. 转换：dcm2niix 缓存 → dcm2bids → finalize（run 编号 / 剔除 / fmap 配对 / TaskName）→ 生理记录
$PY_DCM "$SKILL_DIR/scripts/convert.py" "$PROJECT_DIR"

# 6. 核对 + 元数据 + BIDS 合规
python3 "$SKILL_DIR/scripts/validate.py" --project "$PROJECT_DIR" --json --fail-on-anomaly
python3 "$SKILL_DIR/scripts/init_metadata.py" "$PROJECT_DIR"
npx bids-validator "$PROJECT_DIR/bids" --ignoreNiftiHeaders
```

## Dependencies

| 工具 | 版本 | 用途 |
|------|------|------|
| `dcm2bids` | 3.2.x（Python ≥3.7 即可） | series 匹配与命名 |
| `dcm2niix` | ≥ v1.0.20211006 | DICOM→NIfTI |
| `python3` | ≥ 3.6 | 所有脚本（只用标准库） |
| `pydicom` | 2.x | `scout.py`、DICOM 模式生理记录（用 dcm2bids 所在环境即可） |
| `npx bids-validator` | — | 最终合规检查（服务器无 node 时在挂载数据的机器上跑） |

不需要 `dcm2bids --skip_dcm2niix`（它要求 Python ≥3.8）；convert.py 自己管理 dcm2niix 缓存。

## Safety And Privacy

- mapping 与 decisions 不写姓名、原始编号、出生日期；`participants.tsv` 的 age/sex 由用户决定是否加入。
- 不把真实 DICOM 或可识别信息提交到仓库；示例只含序列名和匿名编号。
- 被剔除的文件移到 `work/discarded/`（附原因），不直接删除；`finalize.py` 默认 dry-run。
- 改了 config / decisions 后对 session 重跑 `convert.py` 是安全的（每次从缓存重新匹配，不残留、不丢数据）。

## Validation And Automation

结构化输出与退出码：

- `convert.py`：0 全部完成 / 2 有 session 需要人工决定 / 1 有失败；明细 `code/logs/convert_<时间>.json`
- `preview.py`、`finalize.py`：有待决事项时退出 2，且不改任何文件
- `validate.py --json --fail-on-anomaly`
- `lint_config.py --json`

测试（Python 3.6+，无需真实影像）：

```bash
python3 -m unittest discover -s tests
```

## Minimal Demo

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo --with-aborted
python3 scripts/validate.py /tmp/bids-convert-demo --json
```

见 `examples/smoke-demo/README.md`。

## Repository Layout

```text
bids-convert/
  SKILL.md              完整流程（唯一真源）
  scripts/              scout / lint_config / preview / convert / finalize / physio_to_bids /
                        validate / init_metadata / copy_sourcedata / generate_events_template / bids_common
  templates/            project.json  protocol.tsv  decisions.tsv  dcm2bids_config*.json  decision_log.md
  references/           project_spec  workflow  pitfalls  mp2rage_cheatsheet  project_diffs  agent_integration  extension_roadmap
  examples/             HS7T-movie（完整声明文件）  ODLoc  MonoDep  smoke-demo
  tests/
```

| 文档 | 内容 |
|---|---|
| [`references/project_spec.md`](references/project_spec.md) | 项目声明文件格式、fmap 配对规则、decisions 选择器 |
| [`references/workflow.md`](references/workflow.md) | 各步骤细节 |
| [`references/pitfalls.md`](references/pitfalls.md) | 44 条已知陷阱（dcm2bids 静默行为、Siemens/CMRR、bids-validator） |
| [`references/mp2rage_cheatsheet.md`](references/mp2rage_cheatsheet.md) | MP2RAGE 11 种输出 |
| [`references/project_diffs.md`](references/project_diffs.md) | 已完成项目差异对照 |
| [`references/agent_integration.md`](references/agent_integration.md) | 接入其他 agent 框架 |
| [`references/extension_roadmap.md`](references/extension_roadmap.md) | 扩展路线 |

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-09 | 初版，基于 4 个项目 |
| v1.1 | 2026-09-15 | Siemens CMRR 生理记录支持；README 去重 |
| v2.0 | 2026-10-19 | 重构为声明式流程：project.json / protocol.tsv / decisions.tsv；新增 scout.py（只读头）、preview.py（真 dcm2bids 预演）、convert.py（dcm2niix 缓存，修复旧 `--rerun` 静默产出为空的丢数据 bug）、finalize.py（run 号 = 协议位置、按采集时间配对 fmap、补 TaskName、剔除可回溯）、physio_to_bids.py（按采集时间配对生理记录）；config 强制 `case_sensitive` / `bids_uri` / `TaskName`；删除 scout.sh、convert_parallel.sh、cleanup_aborted.py、postprocess_runs.py、copy_auxiliary.sh；全部脚本兼容 Python 3.6。详见 RELEASE_NOTES_v2.0.0.md |
