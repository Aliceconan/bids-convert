---
name: bids-convert
description: Convert raw MRI DICOM datasets into BIDS using dcm2bids. Use this skill when the user needs end-to-end DICOM-to-BIDS conversion, project setup, sequence scouting across subjects and dates, dcm2bids config generation, parallel conversion, validation, aborted-run cleanup, auxiliary-data copying, or task events.tsv generation for fMRI projects.
---

# BIDS Convert

```
SKILL_DIR=${CLAUDE_SKILL_DIR}
```

MRI DICOM → BIDS。经验最强的是 Siemens + MP2RAGE + EPI BOLD + reverse-PE fieldmap。
依赖：`dcm2bids` ≥ 3.2（内含调用 `dcm2niix` ≥ v1.0.20211006）、python3 ≥ 3.8、
`npx bids-validator`（不要直接调裸命令）。

**默认姿态**：用户要求转换就实际跑脚本、查输出，只在下面标 ⏸ 的人工决策点停下。
对不可逆清理（删 run、重编号）保持谨慎。

## 工作流

| 步骤 | 做什么 | 命令 / 要点 |
|---|---|---|
| [1] 初始化 | 建 `code/` `bids/`，复制模板 | `cp $SKILL_DIR/templates/{project_config.yaml,decision_log.md} $PROJECT_DIR/code/` |
| [2] 侦察 | 收集 SeriesDescription 变体 | `bash $SKILL_DIR/scripts/scout.sh <session> /tmp/scout_<name>`；**必须覆盖最早期被试**，至少 2–3 个不同日期（早期命名常完全不同） |
| [3] ⏸ 交互确认 | 只问阻塞下一步的最小问题集 | 被试编号方式、排除谁、**重复结构像保留 first/last/all（必须问）**、范式文档（events 用）、展示序列名变体 |
| [4] 生成配置 | `dcm2bids_config.json` + `participants_mapping.tsv` | 见下「config 要点」；写完跑 `lint_config.py` |
| [5] 并行转换 | 必须并行 | `bash $SKILL_DIR/scripts/convert_parallel.sh $PROJECT_DIR`（开跑前自动 lint）；改 config 后 `--rerun sub-XX ses-YY …`（自动清旧输出、复用 tmp NIfTI）；换 dcm2niix 版本才 `--force` |
| [6] 验证 | 文件数、volume、tmp 未匹配、fmap IntendedFor | `python3 $SKILL_DIR/scripts/validate.py $PROJECT_DIR/bids --expected-anat N --expected-func N --expected-fmap N [--json --fail-on-anomaly]` |
| [7] ⏸ 后处理 | aborted run、重编号、重复 anat、多余 fmap、IntendedFor 收敛 1:1 | 见下「aborted run：先判范式」 |
| [8] 辅助数据 | physio / behavior → `sourcedata/` | `copy_auxiliary.sh --type physio|beh`；CMRR 生理记录分 File / DICOM 两种模式，先判断再走对应脚本（workflow.md [8]） |
| [9] Events | 仅 task fMRI（rest 不需要） | 复制 `generate_events_template.py` 到项目、填 `TASK_DESIGNS`、`--dry-run` → 正式 → `--verify`；注视点期叫 `baseline` 不叫 `fixation` |
| [10] 记录 | 所有人工判断的「为什么」 | 填 `code/decision_log.md` |
| [11] BIDS 合规 | 上传 OpenNeuro 前最后一道门 | `npx bids-validator $PROJECT_DIR/bids --ignoreNiftiHeaders`；ERROR 必修，WARNING 酌情 |

## config 要点（[4]）

```json
{"descriptions": [{
  "id": "<unique_id>", "datatype": "anat|func|fmap", "suffix": "<bids_suffix>",
  "custom_entities": "<entities>",
  "criteria": {"SeriesDescription": {"any": ["pat", "Pat", "PAT"]}, "PhaseEncodingDirection": "j-"},
  "sidecar_changes": {"IntendedFor": ["<other_id>"]}
}]}
```

- 匹配用 `fnmatch`，**区分大小写**：`any` 列出所有大小写变体；SD 不够区分时加
  `PhaseEncodingDirection` / `ImageType` / `SeriesNumber`（同名 series 撞名时）。
- **IntendedFor 只能写在 `sidecar_changes` 里**。顶层 `intended_for` 会被 dcm2bids 3.x
  静默吞掉（pitfalls #29）。`lint_config.py <config> [--fix]` 会拦住并只改那一行。
- MP2RAGE 条目从 `templates/dcm2bids_config_mp2rage.json` 挑；mapping 表不含任何隐私信息。

## aborted run：先判范式（[7]，⏸ 选错会删掉好数据）

| 范式 | 特征 | 用哪个 |
|---|---|---|
| 等长 | 同 task 所有 run 一样长（固定时长 block/event、rest） | `cleanup_aborted.py`（按众数推期望值；先 `--dry-run`） |
| 变长 | run 本来就不等长（自定步调、按键结束、素材分段） | `postprocess_runs.py --task T --expected 464,470,…`（期望值**来自协议表**，对不上整体停下；`--apply` 才执行，同时把 IntendedFor 收敛成 1:1） |

变长范式上 `cleanup_aborted.py` 会把合法的短 run 当 aborted 删掉。
重复结构像、多余 fmap（对应已删 aborted run）按用户决策处理。

## 验证异常怎么走（[6]）

| 现象 | 去向 |
|---|---|
| 文件数少 | `--check-tmp` 看 tmp 未匹配 → 改 config → `--rerun` |
| 文件数多 | 重复结构像或 config 多匹配 |
| volume 异常低 | aborted run → [7] |
| **全部 fmap 没有 IntendedFor** | config 用了顶层 `intended_for` → `lint_config.py --fix` → `--rerun` |

## 预期产物

`code/dcm2bids_config.json`、`code/participants_mapping.tsv`、`code/decision_log.md`、
`bids/`（含 `dataset_description.json`、`README`）；可选 `code/generate_events.py`、`sourcedata/`。

## 按需参考（不要预先全读）

| 文件 | 什么时候读 |
|---|---|
| `references/workflow.md` | 执行某一步遇到细节：匹配规则、重跑、清理命令全集、IntendedFor 风格、CMRR physio、events、validator |
| `references/pitfalls.md` | 匹配 / 重跑 / 文件缺失行为异常；bids-validator 报错（#13–#24） |
| `references/schema_notes.md` | 编辑 `project_config.yaml` 字段 |
| `references/mp2rage_cheatsheet.md` | 处理 MP2RAGE 11 种输出 |
| `references/project_diffs.md` | 从已完成项目里挑参考模式 |
| `examples/` | 需要具体 config / mapping 示例 |
| `tests/` | 改脚本后跑 `python3 -m unittest discover -s tests` |
