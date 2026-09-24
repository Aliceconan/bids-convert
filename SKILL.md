---
name: bids-convert
description: Convert raw MRI DICOM datasets into BIDS using dcm2bids. Use this skill when the user needs end-to-end DICOM-to-BIDS conversion, project setup, sequence scouting across subjects and dates, dcm2bids config generation, parallel conversion, validation, aborted-run cleanup, auxiliary-data copying, or task events.tsv generation for fMRI projects.
---

# BIDS Convert

**SKILL_DIR（执行所有脚本时使用此路径）：**
```
SKILL_DIR=${CLAUDE_SKILL_DIR}
```

这个 skill 用于 MRI 原始数据到 BIDS 的转换工作。当前经验最强的是 Siemens + MP2RAGE + EPI BOLD + reverse-PE fieldmap 这一路。

## 工具依赖

| 工具 | 版本 | 用途 |
|------|------|------|
| `dcm2bids` | >= 3.2.0 | DICOM→BIDS 转换（内含 dcm2niix） |
| `dcm2niix` | >= v1.0.20211006 | DICOM→NIfTI（由 dcm2bids 调用） |
| `bids-validator` | >= 1.14.0 | BIDS 合规验证（步骤 [11]）；通过 `npx bids-validator` 调用，无需全局安装 |
| `python3` | >= 3.8 | 后处理脚本 |
| `bash` / `zsh` | — | 并行执行 |

## 目录结构

```
bids-convert/
  SKILL.md
  scripts/
    scout.sh                             ← 侦察：跑 helper + 收集变体
    convert_parallel.sh                  ← 并行转换（含安全重跑逻辑）
    validate.py                          ← 文件数 + volume 检查 + tmp 未匹配
    cleanup_aborted.py                   ← 检测 aborted run + 删除 + 重编号（**等长范式**，众数推断）
    postprocess_runs.py                  ← 按协议表剔废 run + 重编号 + 收敛 IntendedFor
                                           （**变长范式必须用这个**，见 7a）
    generate_events_template.py          ← events 生成框架（项目特定参数外部传入）
    copy_auxiliary.sh                    ← physio/behavior 复制到 sourcedata
    extract_cmrr_physio_dicom.py         ← 从 PhysioLog DICOM 的 CSA Data 提取内嵌 log
    cmrr_physio2bids.py                  ← CMRR log → BIDS _physio.tsv.gz + .json
  templates/
    project_config.yaml                  ← 项目配置模板 (v1.4)
    dcm2bids_config_mp2rage.json         ← MP2RAGE 通用 config 片段（按需选取）
    decision_log.md                      ← 决策记录模板
  references/
    schema_notes.md                      ← project_config.yaml 字段说明
    pitfalls.md                          ← 已知陷阱与解法（23 条）
    mp2rage_cheatsheet.md                ← MP2RAGE 11 种输出速查
    project_diffs.md                     ← 4 项目差异对照表
  examples/
    ODLoc/                               ← 最简单：单 session、单 task
    MonoDep/                             ← 最复杂：多变体、多 task、events
    smoke-demo/                          ← 合成数据验证示例
```

## 工作流总览

默认按下面顺序执行，除非用户明确只要求其中一步。

```
[1] 初始化     → 复制模板、建立项目目录
[2] 侦察       → dcm2bids_helper 收集 SeriesDescription
[3] 交互确认   → 与用户逐项确认 config 字段
[4] 生成配置   → dcm2bids_config.json + participants_mapping.tsv
[5] 并行转换   → dcm2bids 批量转换
[6] 验证       → volume 检查、文件数核对
[7] 后处理     → 清理 aborted run、重编号、处理重复 anat
[8] 辅助数据   → physio / behavior → sourcedata
[9] Events     → 根据范式文档生成 events.tsv（仅 task fMRI）
[10] 记录      → 填写 decision_log.md
[11] BIDS 合规验证 → bids-validator 官方验证，上传 OpenNeuro 前必跑
```

## 各步骤详细规范

### [1] 初始化

```bash
mkdir -p "$PROJECT_DIR/code" "$PROJECT_DIR/bids"
cp "$SKILL_DIR/templates/project_config.yaml" "$PROJECT_DIR/code/project_config.yaml"
cp "$SKILL_DIR/templates/decision_log.md" "$PROJECT_DIR/code/decision_log.md"
```

### [2] 侦察

**关键原则：选被试必须覆盖不同时期（尤其是最早期），至少 2-3 个不同日期。** 最早期被试命名与后期完全不同是常态（4/4 项目）。

```bash
# 列出所有 session 按日期排序，选最早、中间、最晚各一个
ls -d "$PROJECT_DIR"/YYYYMMDD_* | sort

# 对选定的 session 运行侦察
bash "$SKILL_DIR/scripts/scout.sh" <session_folder> /tmp/scout_<name>
```

侦察输出：一张 SeriesDescription 变体清单，按大小写不敏感分组。

**侦察结果异常时：**
- 未找到 sidecar JSON → 检查 DICOM 目录路径，确认 `dcm2bids_helper` 是否正常运行
- 跨 session 序列名差异很大 → 扩大侦察范围，覆盖更多时期；在 [3] 向用户展示所有变体后再确认
- 某序列只在少数 session 出现 → 确认是否为可选扫描，config 中按需匹配

### [3] 交互确认

必须主动向用户确认以下事项（不要默认假设）：

| 事项 | 默认值 |
|------|--------|
| 被试编号方式 | 有原始编号则用原始，否则按日期 |
| 被试排除 | 无排除 |
| 重复结构像保留策略 | 无默认，**必须问** |
| 刺激范式文档 | 主动索要（生成 events.tsv 所需） |
| 序列名变体确认 | 展示给用户确认 |

只询问会阻塞下一步的最小问题集。

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
```

不包含任何隐私信息（姓名、年龄、original_id 等）。

### [5] 并行转换

**必须并行，不要串行。**

```bash
# 全量首次转换
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR"

# 选择性重跑（自动清理旧输出 + 复用 tmp 中的 NIfTI）
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR" \
  --rerun sub-01 ses-pre sub-03 ses-pre

# 如果 dcm2niix 版本更新，需要从 DICOM 完全重新转换
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR" --force
```

修改 config 后重跑时**必须先清理该 session 的 BIDS 输出**，否则旧文件残留。详见 pitfalls #8。

**转换失败时：**
- 单个 session 失败 → 检查 `$PROJECT_DIR/code/logs/dcm2bids_<sub>_<ses>.log`
- tmp 中有 NIfTI 但 BIDS 下无对应输出 → config 未匹配到该序列，检查 SeriesDescription 大小写和通配符
- 多个 session 均失败 → 优先检查 config.json 格式（JSON 语法错误会导致全部失败）

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

**验证异常的处理路径：**
- 文件数低于期望 → 跑 `--check-tmp` 确认 tmp 中是否有未匹配 NIfTI → 更新 config → 重跑受影响 session
- 文件数高于期望 → 通常是重复结构像（见 7b）或 config 多匹配了序列
- volume 数异常低 → aborted run（见 7a）
- volume 数异常高 → config 可能把多个序列匹配成了一个条目

### [7] 后处理

#### 7a. Aborted run 清理

4/4 项目有 aborted run。判定标准：volume 数显著低于期望值（如 1 vol、或 < 50% 期望值）。

**先判断范式是等长还是变长，选错脚本会删掉好数据。**

| 范式 | 特征 | 用哪个 |
|---|---|---|
| **等长** | 同 task 所有 run 一样长（固定时长的 block/event 设计、rest） | `cleanup_aborted.py` |
| **变长** | 各 run 本来就不等长（自定步调、按键结束、每 run 对应素材的一段） | `postprocess_runs.py` |

⚠️ **变长范式上 `cleanup_aborted.py` 会删错数据。** 它按「同 task 众数」推期望值。
实测 HS7T/coco：7 个 run 的设计长度是 `464/470/419/467/479/427/216`，众数推出 470，
于是 216 vol 的 **run-07 被判成 aborted**——按 `--auto` 跑会删掉 4 个已入库被试的完好数据。
脚本现在会在 run 长度分布过宽时明确警告，但**判断范式类型是你的责任**。

`cleanup_aborted.py` 还有一个历史坑：它原来只 glob `sub-*/ses-*/func/`，
**无 session 布局的数据集会扫到 0 个文件然后报告「未发现 aborted run」**
——什么都没看却报告一切正常。现已同时支持两种布局，且扫不到文件时直接报错。

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

变长范式走这个（期望值**必须来自扫描协议表，不要从数据里推**）：

```bash
# dry-run，逐 run 与协议表严格比对
python3 "$SKILL_DIR/scripts/postprocess_runs.py" "$PROJECT_DIR/bids/sub-06" \
    --task coco --expected 464,470,419,467,479,427,216

# 确认无误后执行：剔废 run + 重编号 + 把 fmap IntendedFor 收敛成 1:1
python3 "$SKILL_DIR/scripts/postprocess_runs.py" "$PROJECT_DIR/bids/sub-06" \
    --task coco --expected 464,470,419,467,479,427,216 --apply
```

对不上协议表就整体停下、不动任何文件——宁可不做，也不能删错。

#### 7a2. fmap 的 IntendedFor 必须收敛成 1:1

**dcm2bids 的 `"IntendedFor": ["bold"]` 是累积的**：fmap run-01 指向 1 个 bold、
run-02 指向 2 个、……run-07 指向 8 个。这几乎肯定不是你要的——每 run 一个
reverse-PE 时，应当是 fmap run-N ↔ func run-N 的 1:1。

实测 HS7T 四个已入库被试全是人工改成 1:1 的，此前没有工具。
`postprocess_runs.py` 顺带做掉了，风格跟随数据集现状：

- `--intendedfor-style relative`（默认）→ `func/sub-XX_task-YY_run-NN_bold.nii.gz`
- `--intendedfor-style uri` → `bids::sub-XX/func/...`（dcm2bids 3.2 新版默认产出这种）

**同一数据集里两种风格混用会很难查**，加被试时先看已有被试用的哪种。

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

#### Siemens CMRR 生理记录

CMRR 序列的 `Physio recording` 有 **File** 和 **DICOM** 两种输出模式，
**同一项目内可能混用**，必须分别识别。先判断每个 session 属于哪种：

```bash
# 有独立 .log 文件 → File 模式
ls <session>_physio/*.log 2>/dev/null

# DICOM 目录里有 *_PhysioLog series（ImageType 含 RAWDATA\PHYSIO）→ DICOM 模式
# 特征：单帧、1–19 MB、每个 series 只有 1 个文件
```

⚠️ **dcm2niix 对 DICOM 模式的 PhysioLog 无产物也无警告**（见 pitfalls #25）。
只看 dcm2niix 输出会误判成"这个 session 没采生理数据"。

```bash
# DICOM 模式：先提取出 .log（按 SeriesDescription 分子目录）
python3 "$SKILL_DIR/scripts/extract_cmrr_physio_dicom.py" \
    <dicom_dir> "$PROJECT_DIR/sourcedata/physio/sub-XX"

# File 模式：原样复制
cp <physio_dir>/*.log "$PROJECT_DIR/sourcedata/physio/sub-XX/"

# 两种模式共用同一个转换脚本
python3 "$SKILL_DIR/scripts/cmrr_physio2bids.py" \
    "$PROJECT_DIR/sourcedata/physio/sub-XX" "$PROJECT_DIR/bids/sub-XX/func" \
    --prefix sub-XX_task-<task> \
    --map 469:01,470:02,382:03 \
    [--recursive]        # DICOM 模式提取出来分了子目录时加
```

`--map` 是 `NumVolumes:run` 映射（从各 bold 的 volume 数得到）。产物是
`_recording-pulse_physio` 和 `_recording-respiratory_physio` 两套
——PULS/RESP 采样率不同，BIDS 不允许放进同一个 tsv（pitfalls #27）。

**在 `participants_mapping.tsv` 里加一列 `physio_mode`**（`file` / `dicom` / `none`）
记录每个 session 走的哪条路径，否则后续无从追溯。

**校验**：同一协议下所有 run 的 `StartTime` 应当高度一致；若差异很大，
说明 physio 与 run 配对错了。详见 `references/pitfalls.md` #25–#28。

### [9] Events.tsv 生成

满足以下任一条件则需要生成 events.tsv：
- 侦察结果中有含 `task-` 语义的序列
- 用户明确提到有任务态 fMRI 需要建模

Resting state 不需要。不确定时询问用户。

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

填写 `<project>/code/decision_log.md`，记录所有人工判断的"为什么"。模板分 5 段：被试与 Session、序列识别、异常数据处理、刺激范式、迁移经验。

### [11] BIDS 合规验证

所有后处理和 events 生成完成后，跑官方 validator 确认符合 BIDS spec。这是上传 OpenNeuro 前的最后一道门。

```bash
# 推荐：npx（无需全局安装）
npx bids-validator "$PROJECT_DIR/bids" --ignoreNiftiHeaders

# 离线备选：全局安装后调用
npm install -g bids-validator
bids-validator "$PROJECT_DIR/bids" --ignoreNiftiHeaders
```

**调用注意**：`bids-validator` 通常不在 `$PATH`，直接调用会报 `command not found`，优先用 `npx`。

**ERROR 必须修复；WARNING 酌情处理（OpenNeuro 允许带 warning 上传，但建议尽量清除）。**

常见报错及解法见 `references/pitfalls.md` #13–#23。

## 预期产物

正常执行结束后，至少应产出：

- `<project>/code/dcm2bids_config.json`
- `<project>/code/participants_mapping.tsv`
- `<project>/bids/...`（含 `dataset_description.json`、`README`）
- `<project>/code/decision_log.md`

可选产物：

- `<project>/code/generate_events.py`
- `sourcedata/` copies for physio or behavior files

## 默认工作姿态

对不可逆清理保持谨慎，但不要只停留在高层建议。如果用户要求你执行转换任务，就实际运行工作流、调用脚本、检查输出，只在上面列出的人工决策点暂停。

## 按需参考

以下文件按需读取，不需要预先全部加载：

- [`templates/project_config.yaml`](templates/project_config.yaml) — 需要结构化的项目配置表时
- [`references/pitfalls.md`](references/pitfalls.md) — config 匹配、重跑或文件缺失行为异常时
- [`references/schema_notes.md`](references/schema_notes.md) — 编辑 `project_config.yaml` 字段时
- [`references/mp2rage_cheatsheet.md`](references/mp2rage_cheatsheet.md) — 处理 MP2RAGE 输出时
- [`references/project_diffs.md`](references/project_diffs.md) — 从已完成项目中选择参考模式时
- `examples/` 下的文件 — 需要具体 config 或 mapping 示例时
