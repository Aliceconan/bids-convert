---
name: bids-convert
description: Convert raw MRI DICOM datasets into BIDS using dcm2bids. Use this skill when the user needs end-to-end DICOM-to-BIDS conversion, project setup, sequence scouting across subjects and dates, dcm2bids config generation, parallel conversion, validation, aborted-run cleanup, auxiliary-data copying, or task events.tsv generation for fMRI projects.
---

# BIDS Convert

这个 skill 用于 MRI 原始数据到 BIDS 的转换工作，尤其适合需要先侦察序列命名、再生成 `dcm2bids` 配置、最后做批量转换和验证的场景。
English: Use this skill for MRI rawdata-to-BIDS workflows that require scouting, config generation, batch conversion, and validation.

当前仓库已经包含工作流、脚本、模板、参考资料和示例。保持这里简洁，只在需要时再读取其他文件。
English: Keep this file lean and load references only when needed.

## 适用范围

这个 skill 适合以下任务：

- 把 MRI 原始 DICOM 数据整理成 BIDS
- 先侦察不同被试和日期的 `SeriesDescription`，再生成 `dcm2bids` 配置
- 并行批量转换、检查 volume 和文件数、清理 aborted run
- 为 task fMRI 补充 `events.tsv`

当前经验最强的是 Siemens + MP2RAGE + EPI BOLD + reverse-PE fieldmap 这一路，但不要把它理解成硬限制。
English: Siemens-style projects are the strongest-covered path today, but the workflow is intentionally extensible.

如果后续扩展到 Philips、GE、DWI、ASL 或其他序列类型，应优先复用现有流程骨架，只替换或扩展以下部分：

- 侦察时读取的关键 sidecar 字段
- config 生成规则
- 序列判别提示与模板
- 验证规则与后处理策略

不要把当前未覆盖的机型或序列写成“永不支持”或“不可用”；更合适的表达是“当前优先覆盖 Siemens，其他厂商待迭代补充”。
English: Do not frame non-Siemens paths as unsupported forever; treat them as future extensions on top of the same workflow.

## 执行原则

执行时优先遵守这些原则：

- 侦察必须覆盖最早期和后期被试，不能只看一个样本。
- `SeriesDescription` 在 `dcm2bids` 里按大小写敏感匹配，配置时要显式列出变体。
- 修改 config 后重跑单个 session 时，先清理该 session 的旧 BIDS 输出，再重跑。
- 被试编号、排除策略、重复结构像保留规则、events 设计来源，这几件事必须问用户，不要擅自假设。
- 能用仓库内脚本时，优先直接调用脚本，不要重复手写同类逻辑。

## 工作顺序

默认按下面顺序执行，除非用户明确只要求其中一步。
English: Follow this order unless the user explicitly asks for only one step.

1. Initialize a project folder and copy the templates you need.
2. Scout representative sessions before writing config.
3. Stop for user decisions on numbering, exclusions, duplicate anat handling, and events design inputs.
4. Generate `dcm2bids_config.json` and `participants_mapping.tsv`.
5. Run parallel conversion.
6. Validate counts, volumes, and tmp leftovers.
7. Clean aborted runs or duplicate outputs if needed.
8. Copy physio or behavior data if present.
9. Generate `events.tsv` only for task fMRI.
10. Record human decisions in `decision_log.md`.

## 先读哪些文件

先读下面两个：
English: Read these first.

- [README.md](README.md) for the full workflow and command patterns.
- [templates/project_config.yaml](templates/project_config.yaml) when you need a structured intake sheet.

下面这些按需读取：
English: Open these only when relevant.

- [references/pitfalls.md](references/pitfalls.md) when config matching, reruns, or missing files behave unexpectedly.
- [references/schema_notes.md](references/schema_notes.md) when editing `project_config.yaml`.
- [references/mp2rage_cheatsheet.md](references/mp2rage_cheatsheet.md) when mapping MP2RAGE outputs.
- [references/project_diffs.md](references/project_diffs.md) when choosing between patterns seen in prior projects.
- Files under `examples/` when you need a concrete config or mapping example.

## 必须向用户确认的事项

以下事项不能默认假设：
English: Do not silently assume these.

- Subject numbering strategy: preserve original IDs or assign by date/order.
- Subject or session exclusions.
- Duplicate structural scans: keep first, keep last, or keep all.
- Events design source: paradigm document or explicit onset rules.
- Whether the scouting result covers early and late sessions well enough.

如果信息不够，只询问会阻塞下一步的最小问题集。
English: Ask only for the missing decisions that block the next step.

## 操作规则

- 侦察至少覆盖 2 到 3 个不同日期的 session，且必须包含最早日期。
- `dcm2bids` 使用 `fnmatch`，因此 `SeriesDescription` 匹配按大小写敏感处理。
- config 中优先使用 `criteria.SeriesDescription.any` 明确列出观察到的变体。
- 单靠 `SeriesDescription` 不够区分时，补充 `PhaseEncodingDirection`、`ImageType` 等辅助判据。
- 默认使用并行转换。
- 修改 config 后重跑某个 session，先清理该 session 的旧 BIDS 输出；除非用户要求彻底重转，否则复用 tmp 中已有 NIfTI。
- `participants_mapping.tsv` 不要写入隐私信息。
- task fMRI 的 block 间注视期优先命名为 `baseline`，除非项目明确要求其他命名。

English summary: scout across dates, match variants explicitly, use extra discriminators when needed, rerun safely, prefer parallelism, and keep mappings de-identified.

## 优先使用的脚本

优先直接调用仓库内脚本，而不是重写同类逻辑。
English: Prefer bundled scripts over re-implementing the same logic.

- `scripts/scout.sh <dicom_session_folder> [output_dir]`
- `scripts/convert_parallel.sh <project_dir> [--rerun sub-XX ses-YY ...] [--force]`
- `python3 scripts/validate.py <bids_dir> [--expected-anat N --expected-func N --expected-fmap N] [--json] [--fail-on-anomaly]`
- `python3 scripts/cleanup_aborted.py <bids_dir> [--auto|--dry-run|--threshold R|--yes] [--json] [--fail-if-found]`
- `bash scripts/copy_auxiliary.sh <project_dir> --type physio|beh`
- Copy `scripts/generate_events_template.py` into the project and customize `TASK_DESIGNS`

## 预期产物

正常执行结束后，至少应产出：
English: Expected outputs from a normal run.

- `<project>/code/dcm2bids_config.json`
- `<project>/code/participants_mapping.tsv`
- `<project>/bids/...`
- `<project>/code/decision_log.md`

可选产物：

- `<project>/code/generate_events.py`
- `sourcedata/` copies for physio or behavior files

## 默认工作姿态

对不可逆清理保持谨慎，但不要只停留在高层建议。如果用户要求你执行转换任务，就实际运行工作流、调用脚本、检查输出，只在上面列出的人工决策点暂停。
English: Be conservative with destructive cleanup, but execute the workflow rather than stopping at abstract advice.
