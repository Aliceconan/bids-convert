# bids-convert 各步骤细节

SKILL.md 只列命令和决策点；执行某一步遇到细节问题时读这里对应小节。
项目声明文件的格式见 `project_spec.md`。

### [1] 初始化

```bash
mkdir -p "$PROJECT_DIR/code"
cp "$SKILL_DIR"/templates/{project.json,protocol.tsv,decisions.tsv,dcm2bids_config.json,decision_log.md} "$PROJECT_DIR/code/"
```

`participants_mapping.tsv` 手写（或按 DICOM 目录名用脚本生成后人工核对）：至少
`participant_id` + `dicom_dir`，多 session 加 `session`，有生理记录加 `physio_mode`。
被试编号优先沿用扫描系统/招募记录里的原始编号（缺号就缺着，不重排），方便与行为数据对照。

### [2] 侦察

```bash
# 已有 mapping
<pyt-python> "$SKILL_DIR/scripts/scout.py" "$PROJECT_DIR" [-j 16]
# 还没写 mapping：直接给目录
<pyt-python> "$SKILL_DIR/scripts/scout.py" --dirs /raw/2026*_X_S0{1,2} --out "$PROJECT_DIR/work/scout"
```

每个 session 一张表（SN、文件数、采集时间、PE、层厚、SeriesDescription、ImageType），最后是**跨 session 汇总**：
同一 SeriesDescription（忽略大小写）出现在几个 session、文件数分布、写法变体、PE。怎么看：

- **写法变体**：早期 session 的命名常与后期完全不同（实测 4/4 项目；HS7T 有 3 套）。必须覆盖最早日期。
- **mosaic EPI 的文件数 = volume 数**：同一 run 名在各 session 的文件数应一致——这就是 protocol.tsv 的来源之一
  （以扫描协议表为准，侦察结果用来核对）。偏少的是中断的 run。
- **PE 方向**：序列名里的 AP/PA 字样不可信（HS7T 有同 PE 值、名字相反的情况），只信 `pe=` 列。
  fmap 与 bold 的 PE 应相反；协议中途改过 PE 方向时，config 的 fmap 条目按 `PhaseEncodingDirection` 区分 dir。
- **同名不同协议**：测试序列可能与正式序列同名（HS7T：0.9mm 测试的 reverse 也叫 `reverse_PE_01`），
  看 `th=`（层厚）等字段找区分依据。
- **SN 撞号**：扫描仪软件中途重启后 SeriesNumber 从 1 重来。scout 按 SeriesInstanceUID 归组，不受影响；
  写 decisions 时用 `sn=…&time=…` 区分。
- `PhysioLog` 计数 > 0 → 该 session `physio_mode=dicom`。

### [3] 交互确认（⏸）

只问会阻塞下一步的最小集合：

| 事项 | 为什么必须问 |
|---|---|
| 被试编号方式、排除谁 | 影响 mapping |
| **fmap 配对规则**（after/before/nearest/…） | 「fmap 夹在两个 run 中间」时只有协议设计者知道它属于谁；`project.json` 必填 |
| 重复结构像保留哪套 | 只有现场记录知道哪套好；`anat_duplicates` 默认 ask |
| 对不上协议表的 bold 是否一律丢 | 默认 ask；用户确认「中断的 run 都不要」后可设 `unmatched_func=discard` |
| 协议帧数的来源 | 要协议表，不要从数据推 |
| 范式文档 | events.tsv 需要 |

展示侦察里的命名变体让用户确认。用户的每个回答落到 project.json 或 decisions.tsv，并在 decision_log 记原因。

### [4] 写声明

见 `project_spec.md`。写完 config 先 lint：

```bash
python3 "$SKILL_DIR/scripts/lint_config.py" "$PROJECT_DIR/code/dcm2bids_config.json"        # 检查
python3 "$SKILL_DIR/scripts/lint_config.py" "$PROJECT_DIR/code/dcm2bids_config.json" --fix  # 改写 intended_for、补 TaskName/bids_uri/case_sensitive
```

MP2RAGE 条目从 `templates/dcm2bids_config_mp2rage.json` 挑。

### [5] 预演

```bash
python3 "$SKILL_DIR/scripts/preview.py" "$PROJECT_DIR" [--only sub-01] [--show-all]
```

用 scout 的 sidecar + 只有头的占位 NIfTI（mosaic 的 volume 数 = 文件数）喂给**真正的 dcm2bids**，
再对结果跑 finalize 计划。每个 session 输出：

- 每个 series → 目标文件名 / 「不进 BIDS」/ 「!! 同时匹配多条规则」
- finalize 计划：剔除、改名、IntendedFor、警告、**需要决定**的事项

循环：有事项 → 问用户 → 写 decisions.tsv / 改 config / 改 project.json → 再预演，直到汇总全是「可以转换」。
几秒一个 session，比转完再返工便宜得多。局限：非 mosaic 多文件 EPI 推不出 volume 数（按 3D 处理）。

### [6] 转换

```bash
python3 "$SKILL_DIR/scripts/convert.py" "$PROJECT_DIR"                    # 全部
python3 "$SKILL_DIR/scripts/convert.py" "$PROJECT_DIR" --only sub-03 sub-05:ses-post
python3 "$SKILL_DIR/scripts/convert.py" "$PROJECT_DIR" --refresh-cache    # 换了 dcm2niix 或改了 dcm2niixOptions
```

每个 session：

1. **dcm2niix 缓存** `work/dcm2niix/<sub[_ses]>/`。`.complete` 标记记录 DICOM 路径、dcm2niix 版本、参数，
   任一变化自动重建；否则复用（重跑只需几十秒到几分钟）。
2. 删掉该 session 旧的 BIDS 输出和 dcm2bids tmp，把缓存**硬链接**进 `bids/tmp_dcm2bids/<sub[_ses]>/`，
   调 dcm2bids（不加 `--force_dcm2bids`：它看到 tmp 非空就跳过 dcm2niix）。
3. 检查：有产出、没有 Several Pairing。
4. `finalize`（按协议分配 run、剔除、fmap 配对、TaskName）。有待决事项 → 状态 `needs_decision`，
   该 session 停在 dcm2bids 原始输出，不做任何收拾。
5. `physio_mode` 为 dicom/file 时转生理记录。

为什么这样设计（都是踩过的坑，见 pitfalls #8、#30）：
- dcm2bids 匹配成功后把 NIfTI 从 tmp **移走**。旧做法「删 BIDS 输出 + 不加 force 重跑」实测**产出为空、退出码 0**。
- 硬链接不占额外空间；dcm2bids 的 `rename`/`remove` 只动 tmp 里的那个链接，缓存不受影响。
  不要用会**原地修改** NIfTI 的工具（dcm2bids `post_op` 原地改写）——硬链接下会连缓存一起改；需要时设 `cache_mode: copy`。

结束时打印每个 session 的状态（`ok` / `needs_decision` / `failed`）、待决事项和警告，明细写 `code/logs/convert_<时间>.json`，
每个 session 的完整日志在 `code/logs/<sub[_ses]>.log`。退出码 0/2/1 对应全部完成/有待决/有失败。

**剔除的文件**移到 `work/discarded/<sub[_ses]>/<时间戳>/`，附 `REASONS.tsv`（重转该 session 时旧的会被清掉，因为能从缓存重新产生）；每次 finalize 的动作记录在
`work/finalize/<sub[_ses]>_<时间戳>.json`。

单独重跑收拾步骤（不重转）：`python3 "$SKILL_DIR/scripts/finalize.py" "$PROJECT_DIR" --only sub-01 [--apply]`。
它可重复执行；但已经剔除的文件不会回来——改了决定要恢复被剔除的文件，就对该 session 重跑 convert.py。

### [7] 核对

```bash
python3 "$SKILL_DIR/scripts/validate.py" --project "$PROJECT_DIR" [--expected-anat 3] [--json --fail-on-anomaly]
```

| 检查 | 异常时 |
|---|---|
| bold 帧数对 protocol.tsv（run 号 = 协议位置） | 协议表错，或该 session 确有例外（decisions `volumes`） |
| 缺 run（warn） | 确认是缺扫；记 decision_log |
| tmp 里未匹配的 series | 逐个确认：reverse-PE 的 SBRef、测试序列、报告等本来就不进；该进的去改 config |
| IntendedFor：存在、目标存在、全数据集写法统一且等于 config 的 `bids_uri` | 见 SKILL.md 异常表 |
| func sidecar 都有 TaskName | config 补 `sidecar_changes.TaskName` |
| 没有 fmap 指向的 bold（提示） | 配对规则不对，或那个 run 确实没扫 fmap |

### [8] 元数据

```bash
python3 "$SKILL_DIR/scripts/init_metadata.py" "$PROJECT_DIR"
```

- `dataset_description.json`：不存在才写（`--force-description` 覆盖）。Authors/License 只在 project.json 填了才写；
  **Authors 要问用户**，不要编。
- `participants.tsv`：每次按 mapping 重建；`participants_demographics: true` 时从 scout 结果补 age/sex。
- `README`、`.bidsignore`（含 `tmp_dcm2bids/`）：不存在才建。README 的采集参数、被试说明、已知问题要人写。

### [9] 辅助数据

行为数据等：mapping 加一列（如 `beh_dir`），然后

```bash
python3 "$SKILL_DIR/scripts/copy_sourcedata.py" "$PROJECT_DIR" --column beh_dir --kind beh
```

路径和大小写不可预测，先 `ls` 确认再写进 mapping。

#### Siemens CMRR 生理记录

由 convert.py 在 finalize 之后自动处理（mapping 的 `physio_mode`）；单独跑：
`<pyt-python> "$SKILL_DIR/scripts/physio_to_bids.py" "$PROJECT_DIR" [--only …] [--dry-run]`。

| 模式 | 识别 | 处理 |
|---|---|---|
| `dicom` | scout 的 PhysioLog 计数 > 0（`ImageType` 含 PHYSIO，单帧 1–19 MB） | 从 CSA Data `(7fe1,1010)` 提取 log 到 `bids/sourcedata/physio/<sub>/<SN>_<SD>/`（需 pydicom） |
| `file` | 扫描仪单独导出的 `Physio_*_{Info,PULS,RESP}.log` | 拷到 `bids/sourcedata/physio/<sub>/` |

两种模式之后一样：**按采集时间配对**——Info.log 第一个 volume 的 `ACQ_START_TICS × 2.5 ms` 与 bold 的
AcquisitionTime 相差 < 1 ms（实测），所以不依赖序列名、run 号、NumVolumes，等长范式和重编号后都不会配错。
NumVolumes 只做交叉核对（不等说明 run 被中断）。产物 `_recording-pulse_physio`（200 Hz）与
`_recording-respiratory_physio`（50 Hz）两套（采样率不同，BIDS 不允许放一个 tsv，不重采样）。
fmap 的 3-volume 组和测试序列的 log 报为「未配对」，正常。

**StartTime** = physio 首个采样相对第一帧的时间，同协议下应基本相同（HS7T 1.2mm/124 层：−50.24 s）。
个别 run 明显偏离时先怀疑 log 配错（pitfalls #43），再考虑序列启动后停顿；NumVolumes 与 bold 帧数不等会单独报警。

dcm2niix 对 DICOM 模式 PhysioLog 的处理随版本变（pitfalls #25）：v1.0.20250505 无产物也无警告；
v1.0.20260724 会产出 `*_physio.tsv.gz` 但 dcm2bids 不配对、只留在 tmp。上面的提取在两种版本下都可靠。

### [10] Events.tsv

需要：侦察结果有 task 语义的序列，或用户提到要建模。Resting state 和纯电影观看（连续刺激、按需另做标注）
通常不需要；不确定就问。

```bash
cp "$SKILL_DIR/scripts/generate_events_template.py" "$PROJECT_DIR/code/generate_events.py"
# 编辑 TASK_DESIGNS
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids" --dry-run
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids"
python3 "$PROJECT_DIR/code/generate_events.py" "$PROJECT_DIR/bids" --verify
```

`n_TRs × TR` 应 ≥ 刺激总时长，差值 = dummy TRs + baseline。block 间注视点期 trial_type 叫 `baseline`。

### [11] BIDS 合规

**每次转换后都跑**，不只是上传前——9 月起 HS7T 三个数据集的 TaskName 缺失就是因为一直没跑 validator 才没发现。

```bash
npx bids-validator "$PROJECT_DIR/bids" --ignoreNiftiHeaders
```

- 裸命令 `bids-validator` 通常不在 PATH，用 npx。
- 服务器没有 node（CentOS 7 / glibc 2.17 也装不了新版）时，在能挂载数据集的机器上跑（例如 Mac 上 sshfs 挂载后
  `npx -y bids-validator@1.15.0 <挂载路径>/bids --ignoreNiftiHeaders`；`--ignoreNiftiHeaders` 让它只读 json 和文件名，网络挂载也够快）。
- ERROR 必修；WARNING 酌情（OpenNeuro 允许带 warning）。常见报错见 pitfalls #13–#24。

## 附：脚本一览

```
scripts/
  bids_common.py        公共：项目声明读取、BIDS 文件名、sidecar、NIfTI 头（库，不直接运行）
  scout.py              侦察（需 pydicom）
  lint_config.py        config 静态检查（--fix）
  preview.py            预演匹配 + finalize 计划（不转影像）
  convert.py            并行转换：dcm2niix 缓存 → dcm2bids → finalize → physio
  finalize.py           按声明收拾一个 session（convert 自动调用；也可单独 dry-run / --apply）
  physio_to_bids.py     CMRR 生理记录（DICOM 模式需 pydicom）
  validate.py           转换后核对
  init_metadata.py      dataset_description / participants / README / .bidsignore
  copy_sourcedata.py    行为数据等拷进 sourcedata
  generate_events_template.py  events.tsv 生成框架
  create_synthetic_bids_demo.py  合成演示数据
templates/
  project.json  protocol.tsv  decisions.tsv  dcm2bids_config.json  dcm2bids_config_mp2rage.json  decision_log.md
```
