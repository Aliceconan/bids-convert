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
| 25 | dcm2niix 完全跳过 CMRR PhysioLog DICOM | Siemens+CMRR | 对 `ImageType` 含 `RAWDATA\PHYSIO` 的 series，dcm2niix（实测 v1.0.20250505）无产物也无警告，极易被当成"没采生理数据"；用 `scripts/extract_cmrr_physio_dicom.py` 从 CSA Data `(7fe1,1010)` 提取内嵌 log |
| 26 | CSA Data 里 log 正文不紧跟文件名 | Siemens+CMRR | 打包格式是 `UINT32 dataLen` + `UINT32 nameLen` + 文件名 + **填充到块起点 +1024** + 正文；必须从 `块起点+1024` 读，不要假设紧邻文件名 |
| 27 | PULS 与 RESP 采样率不同（实测 200 / 50 Hz） | Siemens+CMRR | BIDS 要求单个 `_physio.tsv.gz` 内所有列共享一个 `SamplingFrequency`；用 `recording-pulse` / `recording-respiratory` 分开存，不要重采样合并 |
| 28 | 同一项目内 Physio recording 模式不一致 | CMRR 项目 | 同一天的两个 session 可能一个走 File 模式（独立 `.log`，留在扫描仪本地易漏导）一个走 DICOM 模式（PhysioLog series 混在 DICOM 里）；在 `participants_mapping.tsv` 加 `physio_mode` 列记录，两条路径分别处理后汇到同一 BIDS 格式 |

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

### #25–#28 CMRR 生理记录（Siemens）

西门子 CMRR 序列的 `Physio recording` 有两种输出模式，**同一个项目里可能混用**，
两条路径的产物完全不同：

| 模式 | 产物 | 归属方式 | 风险 |
|---|---|---|---|
| **DICOM** | `*_PhysioLog` series 混在 DICOM 目录里，`ImageType = ORIGINAL\PRIMARY\RAWDATA\PHYSIO`，单帧 1–19 MB | `SeriesDescription` 直接是 `<task>_run_01_PhysioLog`，**无歧义** | dcm2niix 静默跳过，容易被误判为"没采" |
| **File** | 独立的 `Physio_<date>_<time>_<uuid>_{Info,PULS,RESP}.log` | 只能靠 `Info.log` 里的 `NumVolumes` 反查对应哪个 run | 文件留在扫描仪本地 log 目录，**漏导就没了**，且会被定期清理 |

两种模式的 log 内容格式完全相同（`LogVersion = EJA_1`），所以提取出来后
可以走同一条转换路径。**DICOM 模式更可靠**，建议在协议里统一成它。

#### 处理流程

```bash
# DICOM 模式：先从 CSA Data 提取出 .log
python3 "$SKILL_DIR/scripts/extract_cmrr_physio_dicom.py" \
    <dicom_dir> <project>/sourcedata/physio/sub-XX

# File 模式：原样复制到 sourcedata 即可
cp <physio_dir>/*.log <project>/sourcedata/physio/sub-XX/

# 两种模式都用同一个脚本转 BIDS
python3 "$SKILL_DIR/scripts/cmrr_physio2bids.py" \
    <project>/sourcedata/physio/sub-XX <project>/bids/sub-XX/func \
    --prefix sub-XX_task-<task> \
    --map 469:01,470:02,382:03 \
    [--recursive]        # DICOM 模式提取出来按 run 分了子目录时加
```

`--map` 是 `NumVolumes:run` 映射，从各 bold 的 volume 数得到。
加 `--recursive` 时脚本会**优先用父目录名里的 run 号**（DICOM 模式权威），
并与 `NumVolumes` 反查结果**交叉校验**，冲突则跳过并报警。

#### 关键细节

**CSA Data `(7fe1,1010)` 的打包格式**（实测 `MR_VE12U` / `syngo MR E12`）：

```
块起点 +0      UINT32  dataLen     正文字节数
块起点 +4      UINT32  nameLen     文件名字节数
块起点 +8      char[]  filename    Physio_<date>_<time>_<uuid>_<TYPE>.log
块起点 +1024   char[]  data        log 正文（从 UUID = ... 起）
下一块起点 = 块起点 + 1024 + dataLen，再向上对齐到 512 字节
```

正文固定从 **+1024** 开始，不紧跟文件名。解析时不要依赖对齐规则，
改用正则定位所有文件名偏移、反推块起点（文件名偏移 −8），
再校验该处的 `nameLen` 与文件名等长（排除正文里的巧合匹配）。

**采样率**：Siemens tick = 2.5 ms。实测 PULS 每 2 tick 一采样（200 Hz），
RESP 每 8 tick（50 Hz）。因为 BIDS 规定单个 `_physio.tsv.gz` 内所有列
共享一个 `SamplingFrequency`，必须用 `recording-<label>` 分开存。
不要为了合并而重采样——会引入插值伪影，而原始保真对 RETROICOR 更重要。

**StartTime**：`(physio 首个采样 tick − Info.log 里首个 volume 的 ACQ_START_TICS) × 2.5ms`。
正常为负值（生理记录早于第一个 volume 开始）。这个值同时是该协议
"序列启动到第一个 volume"的实测开销，在同一协议内应当高度稳定
（HS7T 1.2mm/124 层实测 16 个 run 全为 −50.24 s）。**若各 run 差异很大，
说明 physio 与 run 的配对出错了**，可以当作校验手段。

**reverse-PE 的 physio 不转**：BIDS 的 fmap 不放 physio。这些组的
`NumVolumes` 通常是 3，不在 `--map` 里，脚本会自动跳过并列出。
