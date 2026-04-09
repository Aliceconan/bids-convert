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

---

## 0. 前置要求

### 工具依赖

| 工具 | 版本 | 用途 |
|------|------|------|
| `dcm2bids` | >= 3.2.0 | DICOM→BIDS 转换（内含 dcm2niix） |
| `dcm2niix` | >= v1.0.20211006 | DICOM→NIfTI（由 dcm2bids 调用） |
| `python3` | >= 3.8 | 后处理脚本 |
| `bash` / `zsh` | — | 并行执行 |

### Agent 能力要求

| 能力 | 必须/可选 | 说明 |
|------|----------|------|
| 执行 shell 命令 | 必须 | 运行 dcm2bids、并行转换、文件操作 |
| 读写文件 | 必须 | 生成 config.json、mapping.tsv、events.tsv |
| 与用户交互 | 必须 | 侦察后确认 config、处理异常时请求决策 |
| 读取 JSON | 必须 | 解析 dcm2bids sidecar |
| 长时间运行命令 | 建议 | 大批量并行转换可能需要 5-10 分钟 |

---

## 1. 工作流总览

```
[1] 初始化     → 复制模板、建立项目目录
[2] 侦察       → dcm2bids_helper 收集 SeriesDescription
[3] 交互确认   → 与用户逐项确认 config 字段
[4] 生成配置   → dcm2bids_config.json + participants_mapping.tsv
[5] 并行转换   → dcm2bids 批量转换
[6] 验证       → volume 检查、文件数核对
[7] 后处理     → 清理 aborted run、重编号、处理重复 anat
[8] 辅助数据   → physio / behavior → sourcedata
[9] Events     → 根据范式文档生成 events.tsv
[10] 记录      → 填写 decision_log.md
```

---

## 2. 各步骤详细规范

### [1] 初始化

```bash
SKILL_DIR="<path-to-this-skill-folder>"
PROJECT_DIR="<project-root>"

mkdir -p "$PROJECT_DIR/code" "$PROJECT_DIR/bids"
cp "$SKILL_DIR/templates/project_config.yaml" "$PROJECT_DIR/code/project_config.yaml"
cp "$SKILL_DIR/templates/decision_log.md" "$PROJECT_DIR/code/decision_log.md"
```

### [2] 侦察

**关键原则：选被试必须覆盖不同时期（尤其是最早期），至少 2-3 个不同日期。**

4 个项目全部遇到了 SeriesDescription 跨被试不一致的问题。最早期被试命名与后期完全不同是常态。

```bash
# 列出所有 session 按日期排序，选最早、中间、最晚各一个
ls -d "$PROJECT_DIR"/YYYYMMDD_* | sort

# 对选定的 session 运行侦察
bash "$SKILL_DIR/scripts/scout.sh" <session_folder> /tmp/scout_<name>
```

**侦察阶段的输出：** 一张 SeriesDescription 变体清单，按大小写不敏感分组。

### [3] 交互确认

必须主动向用户确认以下事项（不要默认假设）：

| 事项 | 为什么问 | 默认值 |
|------|---------|--------|
| 被试编号方式 | 有原始编号 vs 按日期排序 | 有原始编号则用原始，否则按日期 |
| 被试排除 | 数据质量/被试退出 | 无排除 |
| 重复结构像保留策略 | 同 session 扫两次 MP2RAGE | 无默认，必须问 |
| 刺激范式文档 | 生成 events.tsv 所需 | 主动索要 |
| 序列名变体确认 | 侦察结果是否覆盖全部被试 | 展示给用户确认 |

### [4] 生成配置

#### dcm2bids_config.json

```json
{
  "descriptions": [
    {
      "id": "<unique_id>",
      "datatype": "anat|func|fmap",
      "suffix": "<bids_suffix>",
      "custom_entities": "<bids_entities>",
      "criteria": {
        "SeriesDescription": { "any": ["pattern1", "Pattern1", "PATTERN1"] },
        "PhaseEncodingDirection": "j-"
      },
      "intended_for": ["<other_id>"]
    }
  ]
}
```

**SeriesDescription 匹配规则：**
- `dcm2bids` 使用 Python `fnmatch`，**区分大小写**
- 必须用 `any` 列出所有大小写变体
- `*` 匹配任意字符序列，`?` 匹配单字符
- 当 SeriesDescription 不足以区分时，结合 `PhaseEncodingDirection` 或 `ImageType`

MP2RAGE 配置可从 `templates/dcm2bids_config_mp2rage.json` 选取需要的条目。

#### participants_mapping.tsv

```
participant_id	session	dicom_folder
sub-01	ses-pre	20210301_S18_TASK_S01_PRE
sub-01	ses-post	20210401_S18_TASK_S01_POST
...
```

不包含任何隐私信息（姓名、年龄、original_id 等）。

### [5] 并行转换

**必须并行，不要串行。**

```bash
# 全量首次转换
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR"
```

#### 重跑策略

修改 config 后需要重跑部分 session 时，**必须先清理该 session 的 BIDS 输出**。

原因：`dcm2bids` 重跑时不会清理上一次的输出。如果新 config 不再匹配某些文件，旧文件会残留在 BIDS 目录中，导致：
- 已失效的旧匹配文件残留
- run 编号跳跃或冲突
- 新旧文件混合

```bash
# 选择性重跑（自动清理旧输出 + 复用 tmp 中的 NIfTI）
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR" \
  --rerun sub-01 ses-pre sub-03 ses-pre

# 如果 dcm2niix 版本更新，需要从 DICOM 完全重新转换
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR" --force
```

### [6] 验证

```bash
# 完整验证：文件数 + volume + tmp 未匹配
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" \
  --expected-anat 7 --expected-func 7 --expected-fmap 7

# 供 agent / CI 消费的结构化输出；发现异常则退出 1
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" \
  --expected-anat 7 --expected-func 7 --expected-fmap 7 \
  --json --fail-on-anomaly

# 仅 volume 检查
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" --volumes-only

# 仅检查 tmp 未匹配
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" --check-tmp
```

异常值（高于或低于期望数）→ 检查 tmp 中是否有未匹配文件 → 更新 config → 重跑。

### [7] 后处理

#### 7a. Aborted run 清理

4/4 项目有 aborted run。判定标准：volume 数显著低于期望值（如 1 vol、或 < 50% 期望值）。

```bash
# 交互模式：展示异常 run，确认后删除并重编号
python3 "$SKILL_DIR/scripts/cleanup_aborted.py" "$PROJECT_DIR/bids"

# 自动模式：自动删除 1-vol run
python3 "$SKILL_DIR/scripts/cleanup_aborted.py" "$PROJECT_DIR/bids" --auto

# 干跑模式：只报告不执行
python3 "$SKILL_DIR/scripts/cleanup_aborted.py" "$PROJECT_DIR/bids" --dry-run

# 非交互 agent / CI：输出 JSON，并在发现 aborted run 时返回 1
python3 "$SKILL_DIR/scripts/cleanup_aborted.py" "$PROJECT_DIR/bids" \
  --dry-run --json --fail-if-found

# 非交互确认执行删除
python3 "$SKILL_DIR/scripts/cleanup_aborted.py" "$PROJECT_DIR/bids" --yes
```

#### 7b. 重复结构像

如果 anat 数超过期望值，通常是同 session 扫了两次 MP2RAGE。根据用户决策保留 first/last/all。

#### 7c. 多余 fmap

如果 fmap 比 func 多（可能对应已删除的 aborted func run），根据用户决策删除。

### [8] 辅助数据

```bash
# 复制 physio（需要 mapping 中有 physio_subfolder 或 physio_folder 列）
bash "$SKILL_DIR/scripts/copy_auxiliary.sh" "$PROJECT_DIR" --type physio

# 复制行为数据
bash "$SKILL_DIR/scripts/copy_auxiliary.sh" "$PROJECT_DIR" --type beh
```

**注意**：physio 可能在 DICOM 文件夹内的子目录，也可能在顶层同名目录。命名大小写不可预测，必须 `ls` 确认。

### [9] Events.tsv 生成

仅 task fMRI 需要（不含 rest）。

```bash
# 1. 复制模板到项目
cp "$SKILL_DIR/scripts/generate_events_template.py" "$PROJECT_DIR/code/generate_events.py"

# 2. 编辑 TASK_DESIGNS 部分，填入项目实际范式

# 3. 运行（可先 dry-run 检查）
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids" --dry-run
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids"

# 4. 可选：校验扫描时长 vs 范式时长
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids" --verify
```

**时间校验**：`n_TRs x TR` 应 >= 刺激总时长。差值 = dummy TRs + baseline。不确定时问用户。

block 间注视点期 → trial_type 命名为 `baseline`，不要叫 `fixation`。

### [10] 记录

填写 `<project>/code/decision_log.md`，记录所有人工判断的"为什么"。

```bash
# 初始化时已复制模板，按模板中的 5 个段落逐项填写：
# 1. 被试与 Session
# 2. 序列识别
# 3. 异常数据处理
# 4. 刺激范式
# 5. 迁移经验
```

---

## 3. 目录结构

```
bids-convert/
  README.md                              ← GitHub 展示页面 + 快速上手
  scripts/
    scout.sh                             ← 侦察：跑 helper + 收集变体
    convert_parallel.sh                  ← 并行转换（含安全重跑逻辑）
    validate.py                          ← 文件数 + volume 检查 + tmp 未匹配
    cleanup_aborted.py                   ← 检测 aborted run + 删除 + 重编号
    generate_events_template.py          ← events 生成框架（项目特定参数外部传入）
    copy_auxiliary.sh                    ← physio/behavior 复制到 sourcedata
  templates/
    project_config.yaml                  ← 项目配置模板 (v1.4)
    dcm2bids_config_mp2rage.json         ← MP2RAGE 通用 config 片段（按需选取）
    decision_log.md                      ← 决策记录模板
  references/
    schema_notes.md                      ← project_config.yaml 字段说明
    pitfalls.md                          ← 已知陷阱与解法（12 条）
    mp2rage_cheatsheet.md                ← MP2RAGE 11 种输出速查
    project_diffs.md                     ← 4 项目差异对照表
  examples/
    ODLoc/                               ← 最简单：单 session、单 task
      dcm2bids_config.json
      participants_mapping.tsv
    MonoDep/                             ← 最复杂：多变体、多 task、events
      dcm2bids_config.json
      participants_mapping.tsv
      generate_events.py
```

---

## 4. Agent 适配指南

### 4a. 需要适配的部分（与 agent 框架相关）

| 维度 | 说明 |
|------|------|
| **Shell 执行** | 需要能执行 bash 命令并获取 stdout/stderr；并行执行是核心性能需求 |
| **文件读写** | 读取 JSON sidecar、写入 TSV/JSON/Python 文件 |
| **用户交互** | 步骤 [3] 交互密集，需要"暂停等待用户输入"机制 |
| **长时间任务** | 批量转换可能 5-10 分钟；需要超时容忍或异步机制 |
| **上下文管理** | 20+ session 的验证输出很大，需要能处理或截断 |
| **路径** | 脚本使用相对路径 + `$SKILL_DIR` / `$PROJECT_DIR` 变量，agent 负责传入绝对路径 |

### 4b. 需要泛化的部分（与领域相关）

| 维度 | 当前主干 | 后续扩展方向 |
|------|---------|---------|
| **扫描仪** | Siemens (S18/P14) | Philips、GE 等厂商的 sidecar 判据与命名规律 |
| **序列类型** | MP2RAGE + EPI bold + reverse-PE fmap | T1w MPRAGE、T2w、DWI、ASL、multi-echo GRE |
| **数据格式** | Siemens .IMA | 标准 `.dcm`、PAR/REC (Philips)、增强型 DICOM |
| **目录结构** | `YYYYMMDD_Scanner_Experiment_Subject` | 应允许用户自定义 glob pattern |
| **范式格式** | 硬编码 Python onset 表 | PsychoPy log、E-Prime txt、MATLAB .mat |
| **Physio 格式** | Siemens PhysioLog (.ecg/.puls/.resp) | BIOPAC (.acq)、BrainVision (.vhdr) |

### 4c. 接口契约

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

### 4d. 状态机模型（非对话式 agent）

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
