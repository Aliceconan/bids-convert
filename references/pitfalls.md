# 已知陷阱与解法

基于 4 个已完成项目（ODLoc / EYEDEP_CRF / MP_CRF / MonoDep）总结。

| # | 陷阱 | 频率 | 解法 |
|---|------|------|------|
| 1 | SeriesDescription 大小写不一致 | 4/4 | config 用 `any` 列出所有变体；按大小写不敏感处理 |
| 2 | 早期被试命名与后期完全不同 | 2/4 | 侦察必须包含最早日期被试 |
| 3 | Aborted run（1 vol 或部分 vol） | 4/4 | `scripts/validate.py` 检测 → `scripts/cleanup_aborted.py` 清理 |
| 4 | 重复结构像（同 session 扫两次 MP2RAGE） | 2/4 | 询问用户保留策略，不要默认假设 |
| 5 | fnmatch 区分大小写 | 4/4 | 显式列出所有大小写形式在 `any` 列表中 |
| 6 | Physio 路径不可预测 | 2/4 | `ls` 确认，不要猜路径或大小写 |
| 7 | 串行转换太慢 | 1/4 | 始终用 `scripts/convert_parallel.sh`（shell `&` + `wait`） |
| 8 | 重跑残留旧文件 | — | 重跑前 `rm -rf bids/sub-XX/ses-YY/`，保留 tmp；见 `convert_parallel.sh --rerun` |
| 9 | fmap 与 bold 的 SD 相同 | 3/4 | 加 `PhaseEncodingDirection` 区分（fmap 通常 PE 反向） |
| 10 | 隐私信息泄露 | 1/4 | `participants_mapping.tsv` 和 `participants.tsv` 不含原始 ID/姓名/年龄 |
| 11 | `--force_dcm2bids` 重跑太慢 | 1/4 | 仅修改匹配规则时不需要重跑 dcm2niix，去掉此 flag |
| 12 | Dummy TRs 被忽略 | 1/4 | 比较 `n_TRs × TR` 与刺激总时长，差值 = dummy + baseline |
| 13 | `IntendedFor` 路径写错 | 常见 | fmap JSON 里的 `IntendedFor` 必须是相对于 subject 目录的路径（如 `ses-pre/func/sub-01_ses-pre_task-rest_bold.nii.gz`），不是绝对路径 |
| 14 | func sidecar 缺 `TaskName` → `TASK_NAME_MUST_DEFINE` ERROR | 常见 | 在根目录建 `task-<taskname>_bold.json`，写入 `{"TaskName": "<taskname>"}`；dcm2bids 有时不自动填 |
| 15 | `dataset_description.json` 缺失或字段不全 | 常见 | 必须有 `Name`、`BIDSVersion`；`Authors` 向用户确认，`License` 默认填 `"CC0"`；空字符串字段（`""`）删掉，不要保留 |
| 16 | `participants.tsv` 列名不合规 | 偶见 | 只允许 `participant_id` + BIDS 定义的列（`age`、`sex`、`handedness`）；自定义列不会报错但会被忽略 |
| 17 | `.bidsignore` 缺失导致额外文件报错 | 偶见 | BIDS 目录内所有不符合命名规范的文件都会报 ERROR；把 `code/`、`sourcedata/` 以外的杂项加进 `.bidsignore` |
| 18 | events.tsv 缺 `onset` 或 `duration` 列 | 偶见 | 这两列是必填；列名必须全小写；时间单位为秒 |
| 19 | `bids-validator` 命令找不到（`command not found`） | 常见 | 全局安装不在 `$PATH` 是常态；始终用 `npx bids-validator` 调用，不要直接调用裸命令 |
| 20 | dcm2bids 输出的 `rec-DIV_MP2RAGE` 被报 `NOT_INCLUDED` ERROR | MP2RAGE 项目 | BIDS validator 不识别无 `inv-`/`part-` 的 `_MP2RAGE` suffix 变体；把 `**/*_rec-DIV_MP2RAGE.nii.gz` 和 `**/*_rec-DIV_MP2RAGE.json` 写入根目录 `.bidsignore` |
| 21 | events.tsv 自定义列（如 `contrast`、`condition`）报 `CUSTOM_COLUMN_WITHOUT_DESCRIPTION` | task fMRI | 在根目录建 `task-<taskname>_events.json`，为每个自定义列写 `LongName` 和 `Description`（以及 `Levels` 如果是类别变量） |
| 22 | `INCONSISTENT_SUBJECTS`：部分被试缺某些 anat 文件 | 常见 | 如果是真实缺数据（扫描时未采集），此 warning 无法消除；记录在 decision_log 中，OpenNeuro 允许带此 warning 上传 |
| 23 | `TOO_FEW_AUTHORS`：只有一位作者触发提示 | 偶见 | 仅为提醒是否漏填；确认无误后可忽略 |
| 24 | `EVENTS_TSV_MISSING`：localizer / block-design 定位扫描无 events.tsv | localizer 项目 | 纯定位用途的 task fMRI（如 ODLoc）不需要 events.tsv；此 warning 可接受，OpenNeuro 允许带此 warning 上传 |

## 详细说明

### #8 重跑残留旧文件（重要）

`dcm2bids` 重跑时 **不会清理上一次的 BIDS 输出**。如果修改 config 导致某些文件不再被匹配，旧文件会残留在 BIDS 目录中。

**错误做法：**
```bash
# 直接重跑 — 旧文件残留！
dcm2bids -d ... -p sub-01 -s ses-pre -c new_config.json -o bids
```

**正确做法：**
```bash
# 先清理该 session 的 BIDS 输出
rm -rf bids/sub-01/ses-pre/
# 再重跑（不加 --force_dcm2bids 以复用 tmp 中的 NIfTI）
dcm2bids -d ... -p sub-01 -s ses-pre -c new_config.json -o bids
```

`convert_parallel.sh --rerun` 已内置此逻辑。
