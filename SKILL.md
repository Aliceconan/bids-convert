---
name: bids-convert
description: Convert raw MRI DICOM datasets into BIDS using dcm2bids. Use this skill when the user needs end-to-end DICOM-to-BIDS conversion, project setup, sequence scouting across subjects and dates, dcm2bids config generation, parallel conversion, validation, aborted-run / duplicate-scan handling, fieldmap IntendedFor pairing, physiological recordings, or task events.tsv generation for fMRI projects.
---

# BIDS Convert

```
SKILL_DIR=${CLAUDE_SKILL_DIR}
```

MRI DICOM → BIDS。经验最强的是 Siemens + MP2RAGE + EPI BOLD + reverse-PE fieldmap + CMRR 生理记录。

**核心原则：所有人工判断写进项目声明文件，从 DICOM 一条命令重跑出同样的结果。**
转换后不手工 `mv`/`rm`/改 json；要改就改 `decisions.tsv` / config，然后重跑该 session（安全、几分钟）。

**默认姿态**：用户要求转换就实际跑脚本、查输出，只在 ⏸ 处停下问人。脚本遇到无法自动决定的情况会
**整体停下、不改任何文件**并列出待决事项——把问题带给用户，不要替用户猜。

## 环境

- `dcm2bids` 3.2（任意 Python ≥3.7 环境）+ `dcm2niix`；不需要 `--skip_dcm2niix`（那个要 py≥3.8）。
- 脚本只用标准库，兼容 Python 3.6（服务器节点默认 python3）。
- `scout.py` 和 DICOM 模式的生理记录需要 **pydicom**：用 dcm2bids 所在环境的 python 跑。
- bids-validator：`npx bids-validator`；服务器没有 node 时，在能挂载数据的机器（如 Mac + sshfs）上跑。
- 不要为了跑脚本去新建/升级环境；现有版本不满足就换做法。

## 工作流

| 步骤 | 做什么 | 命令 / 要点 |
|---|---|---|
| [1] 初始化 | 建 `code/`，复制模板 | `cp $SKILL_DIR/templates/{project.json,protocol.tsv,decisions.tsv,dcm2bids_config.json,decision_log.md} $PROJECT_DIR/code/`；写 `participants_mapping.tsv` |
| [2] 侦察 | 每个 series 一行 + sidecar 字段 | `<pyt-python> $SKILL_DIR/scripts/scout.py $PROJECT_DIR`（还没 mapping：`--dirs … --out …`）；**覆盖最早期 session**，早期命名常完全不同；看跨 session 汇总 |
| [3] ⏸ 确认 | 只问阻塞下一步的 | 被试编号、排除谁、**fmap 默认配对规则（必填；配对体检报警时逐个改 `pair`）**、重复结构像策略、废 run 策略、协议帧数来源、范式文档 |
| [4] 写声明 | config / protocol / project / decisions | 见 `references/project_spec.md`；`lint_config.py code/dcm2bids_config.json [--fix]` |
| [5] 预演 | 不转影像，用真 dcm2bids + finalize 跑一遍 | `python3 $SKILL_DIR/scripts/preview.py $PROJECT_DIR`；有「需要决定」→ ⏸ 问用户 → 写 decisions.tsv → 再预演，直到全部「可以转换」 |
| [6] 转换 | 并行：dcm2niix 缓存 → dcm2bids → finalize → physio | `python3 $SKILL_DIR/scripts/convert.py $PROJECT_DIR [--only sub-03]`；长任务放 screen/nohup；改了 config/decisions 后对受影响 session 重跑即可 |
| [7] 核对 | 帧数对协议、TaskName、IntendedFor 写法统一 | `python3 $SKILL_DIR/scripts/validate.py --project $PROJECT_DIR`；tmp 里未匹配的 series 逐个确认是不是本来就不要 |
| [8] 元数据 | dataset_description / participants / README | `python3 $SKILL_DIR/scripts/init_metadata.py $PROJECT_DIR`；README 内容要人写；Authors ⏸ 问用户 |
| [9] 辅助数据 | 行为数据等 → `bids/sourcedata/` | `copy_sourcedata.py --column beh_dir --kind beh`；生理记录已在 [6] 处理（mapping 的 `physio_mode`） |
| [10] Events | 仅 task fMRI | 复制 `generate_events_template.py` 到 `code/`、填 `TASK_DESIGNS`、`--dry-run` → 正式 → `--verify`；注视点期叫 `baseline` |
| [11] BIDS 合规 | **每次转换后都跑** | `npx bids-validator $PROJECT_DIR/bids --ignoreNiftiHeaders`；ERROR 必修，WARNING 酌情 |
| [12] 记录 | 叙述性的「为什么」 | `code/decision_log.md`；逐 session 的决定已在 decisions.tsv 的 reason 列 |

## 文件放哪

- `$PROJECT_DIR` 由用户给；没给就问，**不要默认用 `$HOME` 或当前目录**（ssh 远程时当前目录就是 `~`）。
  只是试转一两个 session，用 `$HOME/work/<YYYYMMDD>_bids_<说明>/`。
- 日志在 `code/logs/`；dcm2niix 缓存、侦察、预演、被剔除的文件在 `work/`（可删可再生，`discarded/` 删前确认）。

## 转换结果异常怎么走

| 现象 | 去向 |
|---|---|
| convert 状态 `needs_decision` | 看列出的事项 → ⏸ 问用户 → 写 decisions.tsv → `convert.py --only <这些 session>` |
| convert 状态 `failed`：dcm2bids 没产出 / Several Pairing | 改 config（preview 先验证）→ 重跑 |
| tmp 里有该进 BIDS 的 series | config 没匹配上：看 scout 的 sidecar 字段改 criteria |
| validate 报帧数不符 | 协议表错了，或该 session 确有例外（decisions: `volumes`） |
| fmap 没有 IntendedFor | `fmap_pairing=none`，或被判为配不上（看 finalize 报告 `work/finalize/`） |
| validator `TASK_NAME_MUST_DEFINE` | config 的 func 条目缺 `sidecar_changes.TaskName`（`lint_config.py --fix`） |

## 按需参考（不要预先全读）

| 文件 | 什么时候读 |
|---|---|
| `references/project_spec.md` | 写 project.json / protocol.tsv / decisions.tsv / config 的约定；fmap 配对规则 |
| `references/workflow.md` | 某一步的细节：侦察怎么看、预演怎么读、缓存与重跑、physio、events、validator |
| `references/pitfalls.md` | 行为异常时：dcm2bids 的静默行为、Siemens 特有坑、bids-validator 报错 |
| `references/mp2rage_cheatsheet.md` | MP2RAGE 的 11 种输出 |
| `references/project_diffs.md` / `examples/` | 从已完成项目挑参考（`examples/HS7T-movie` 是完整的声明文件示例） |
| `tests/` | 改脚本后跑 `python3 -m unittest discover -s tests` |
