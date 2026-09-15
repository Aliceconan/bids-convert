# DICOM-to-BIDS Conversion Skill

> 基于 4 个已完成项目（ODLoc / EYEDEP_CRF / MP_CRF / MonoDep）提炼的端到端工作流。
> 设计目标：任何具备 shell 执行、文件读写、基础 JSON 处理和有限用户交互能力的 AI agent 均可执行此流程。

English version: [README_EN.md](README_EN.md)

这是一个面向 agent 的 MRI DICOM-to-BIDS workflow/skill 包，而不是单一脚本。仓库内包含：

- 可触发的 skill 入口：`SKILL.md`
- 一个可选的 Codex UI metadata 示例：`agents/openai.yaml`
- 可直接调用的 shell / Python 脚本
- 模板、参考文档和真实项目抽象出的示例

你不需要使用 Codex 才能使用这个仓库。`SKILL.md` 和 `agents/openai.yaml` 只是其中一种 agent 集成形式；核心工作流由普通的 CLI 脚本和文档驱动，其他 agent 只要能执行 shell、读写文件并处理少量用户确认，也可以接入。

适用场景：

- 用 `dcm2bids` 把原始 MRI DICOM 目录转换为 BIDS
- 先侦察 `SeriesDescription` 变体，再生成 `dcm2bids_config.json`
- 并行批量转换、验证 volume 和文件数、处理 aborted run
- 复制 physio / behavior 数据到 `sourcedata`
- 为 task fMRI 生成 `events.tsv`

当前主干之外、仍在持续扩展中的方向：

- Philips / GE 等其他厂商数据的稳定转换经验
- DWI / ASL / 多回波 GRE 等更多序列类型的成熟模板
- 更少人工确认的高自动化转换流程

## Quick Start

1. 准备依赖：

```bash
dcm2bids --version
dcm2niix -h
python3 --version
```

2. 创建项目目录并复制模板：

```bash
SKILL_DIR="<path-to-this-repo>"
PROJECT_DIR="<project-root>"

mkdir -p "$PROJECT_DIR/code" "$PROJECT_DIR/bids"
cp "$SKILL_DIR/templates/project_config.yaml" "$PROJECT_DIR/code/project_config.yaml"
cp "$SKILL_DIR/templates/decision_log.md" "$PROJECT_DIR/code/decision_log.md"
```

3. 先做侦察，再写 config：

```bash
bash "$SKILL_DIR/scripts/scout.sh" <dicom_session_folder> /tmp/scout_example
```

4. 生成 `dcm2bids_config.json` 和 `participants_mapping.tsv` 后并行转换：

```bash
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR"
```

5. 验证：

```bash
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" \
  --expected-anat 7 --expected-func 7 --expected-fmap 7 \
  --json --fail-on-anomaly
```

## Dependencies

最低建议环境：

| 工具 | 版本 | 用途 |
|------|------|------|
| `dcm2bids` | >= 3.2.0 | DICOM→BIDS 转换（内含 dcm2niix） |
| `dcm2niix` | >= v1.0.20211006 | DICOM→NIfTI（由 dcm2bids 调用） |
| `python3` | >= 3.8 | 后处理脚本 |
| `bash` / `zsh` | — | 并行执行 |

## Agent Compatibility

这个仓库优先适配具备以下能力的 agent：

| 能力 | 必须/可选 | 说明 |
|------|----------|------|
| 执行 shell 命令 | 必须 | 运行 dcm2bids、并行转换、文件操作 |
| 读写文件 | 必须 | 生成 config.json、mapping.tsv、events.tsv |
| 与用户交互 | 必须 | 侦察后确认 config、处理异常时请求决策 |
| 读取 JSON | 必须 | 解析 dcm2bids sidecar |
| 长时间运行命令 | 建议 | 大批量并行转换可能需要 5-10 分钟 |
| 消费 JSON stdout | 建议 | 使用 `validate.py --json` / `cleanup_aborted.py --json` |

对其他 agent 框架的最低接口契约：

- 可以传递绝对路径给脚本
- 能处理非零退出码
- 遇到用户决策点时暂停
- 最好支持非交互模式调用 CLI 脚本

## Safety And Privacy

- `participants_mapping.tsv` 不应包含姓名、年龄、原始受试者 ID 等隐私信息。
- 示例文件应保持脱敏；不要把真实原始 DICOM 或可识别信息提交到仓库。
- `cleanup_aborted.py` 会删除文件；自动化环境中建议先用 `--dry-run --json`。
- 修改 config 后重跑某个 session 时，必须先清掉该 session 的旧 BIDS 输出，避免残留文件污染结果。

## Validation And Automation

为了适配不同 agent 和 CI，关键脚本支持结构化输出和明确退出码：

- `validate.py --json --fail-on-anomaly`
- `cleanup_aborted.py --dry-run --json --fail-if-found`
- `cleanup_aborted.py --yes` 用于非交互确认执行

本仓库包含一个最小 smoke test：

```bash
python3 -m unittest tests/test_validate_and_cleanup.py
```

GitHub Actions 会检查：

- shell 脚本语法
- Python 脚本语法
- 最小单元测试

## Minimal Demo

仓库附带一个完全合成的 smoke demo，用来验证脚本接口和 agent 集成，不包含真实 MRI 数据：

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo --with-aborted

python3 scripts/validate.py /tmp/bids-convert-demo --json
python3 scripts/cleanup_aborted.py /tmp/bids-convert-demo --dry-run --json --fail-if-found
```

更详细的演示说明见 `examples/smoke-demo/README.md`。

## 扩展路线

这个仓库当前最成熟的主干来自 Siemens-style fMRI 项目，但这不是长期边界。后续会在保持统一工作流骨架的前提下，逐步扩展到 Philips、GE 以及更多序列类型，而不是为每种机型复制一套彼此割裂的流程。

扩展路线说明见 `references/extension_roadmap.md`。

## Repository Layout

```text
bids-convert/
  SKILL.md
  README.md
  README_EN.md
  agents/
    openai.yaml
  scripts/
  templates/
  references/
  examples/
    smoke-demo/
  tests/
```

## 完整工作流

完整的 11 步流程、每一步的命令与判读规范，见 **[SKILL.md](SKILL.md)** —— 那是唯一真源。
本 README 只保留安装、快速上手与 agent 集成说明，**不重复流程内容**，避免两份文档失去同步。

配套参考文档：

| 文档 | 内容 |
|---|---|
| [`references/pitfalls.md`](references/pitfalls.md) | 28 条已知陷阱与解法（含 Siemens CMRR 生理记录 #25–#28） |
| [`references/mp2rage_cheatsheet.md`](references/mp2rage_cheatsheet.md) | MP2RAGE 11 种输出速查 |
| [`references/project_diffs.md`](references/project_diffs.md) | 已完成项目的差异对照表 |
| [`references/schema_notes.md`](references/schema_notes.md) | `project_config.yaml` 字段说明 |
| [`references/extension_roadmap.md`](references/extension_roadmap.md) | 扩展路线 |

## Agent 适配指南

### 需要适配的部分（与 agent 框架相关）

| 维度 | 说明 |
|------|------|
| **Shell 执行** | 需要能执行 bash 命令并获取 stdout/stderr；并行执行是核心性能需求 |
| **文件读写** | 读取 JSON sidecar、写入 TSV/JSON/Python 文件 |
| **用户交互** | 步骤 [3] 交互密集，需要"暂停等待用户输入"机制 |
| **长时间任务** | 批量转换可能 5-10 分钟；需要超时容忍或异步机制 |
| **上下文管理** | 20+ session 的验证输出很大，需要能处理或截断 |
| **路径** | 脚本使用相对路径 + `$SKILL_DIR` / `$PROJECT_DIR` 变量，agent 负责传入绝对路径 |

### 需要泛化的部分（与领域相关）

| 维度 | 当前主干 | 后续扩展方向 |
|------|---------|---------|
| **扫描仪** | Siemens (S18/P14) | Philips、GE 等厂商的 sidecar 判据与命名规律 |
| **序列类型** | MP2RAGE + EPI bold + reverse-PE fmap | T1w MPRAGE、T2w、DWI、ASL、multi-echo GRE |
| **数据格式** | Siemens .IMA | 标准 `.dcm`、PAR/REC (Philips)、增强型 DICOM |
| **目录结构** | `YYYYMMDD_Scanner_Experiment_Subject` | 应允许用户自定义 glob pattern |
| **范式格式** | 硬编码 Python onset 表 | PsychoPy log、E-Prime txt、MATLAB .mat |
| **Physio 格式** | Siemens PhysioLog (.ecg/.puls/.resp) | BIOPAC (.acq)、BrainVision (.vhdr) |

### 接口契约

```yaml
skill:
  name: bids-convert
  version: "1.0"

  requires:
    - shell_execute
    - file_read
    - file_write
    - user_interaction
    - json_parse

  optional:
    - parallel_execution     # 缺失则降级为串行
    - background_task        # 缺失则同步等待
    - structured_output      # 表格等

  inputs:
    skill_dir: string        # 本 skill 文件夹的路径
    raw_data_root: string    # DICOM 数据根目录
    project_name: string     # 项目名
    bids_output: string      # BIDS 输出目录

  outputs:
    bids_directory: string
    decision_log: string
    stats:
      subjects: int
      sessions: int
      total_files: int
      aborted_runs_cleaned: int
```

### 状态机模型（非对话式 agent）

```
INIT → SCOUT → WAIT_USER_CONFIG → GENERATE_CONFIG → CONVERT →
VALIDATE → POST_PROCESS → WAIT_USER_REVIEW → AUXILIARY →
EVENTS → RECORD → DONE
```

`WAIT_USER_*` 状态需要外部输入，其余可自动执行。

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-09 | 初版，基于 4 个项目；含 6 个脚本、3 个模板、4 个参考文档、2 个示例 |
| v1.1 | 2026-09-15 | 新增 Siemens CMRR 生理记录支持（`extract_cmrr_physio_dicom.py` / `cmrr_physio2bids.py`，pitfalls #25–#28）；README 去重，完整流程统一到 `SKILL.md` |
