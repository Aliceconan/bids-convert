# 已知陷阱与解法

来源：ODLoc / EYEDEP_CRF / MP_CRF / MonoDep 四个项目，以及 HS7T 电影 fMRI（2026-09～10，coco/nezha/andy/xiju）。
dcm2bids 的行为均对照 3.2.0 源码或实测确认（标注「实测」的是在真实数据上跑出来的）。

| # | 陷阱 | 解法 |
|---|------|------|
| 1 | SeriesDescription 大小写不一致（4/4 项目） | config 顶层 `"case_sensitive": false`（dcm2bids 3.x 原生支持，把名字和 pattern 都转小写再 fnmatch）。**不要再在 `any` 里罗列大小写变体** |
| 2 | 早期被试命名与后期完全不同 | 侦察必须覆盖最早日期；看 scout 跨 session 汇总的「变体」列 |
| 3 | 中断的 run（1 vol 或部分 vol） | protocol.tsv 写期望帧数；finalize 对不上协议的 bold 按 `unmatched_func` 处理（ask/discard），剔除的移到 `work/discarded/` |
| 4 | 重复结构像（同 session 扫两次） | `anat_duplicates` 默认 ask；⏸ 问用户后写 decisions（first/last/all 或 discard sn=…） |
| 5 | （并入 #1） | |
| 6 | Physio / 行为数据路径不可预测 | `ls` 确认后写进 mapping；不要猜路径或大小写 |
| 7 | 串行转换太慢 | `convert.py` 并行（`jobs`）；7T 单场 dcm2niix 吃内存和 IO，别开太大 |
| 8 | **重跑丢数据**（旧版 `convert_parallel.sh --rerun` 与本表旧版 #8/#11 的建议） | dcm2bids 匹配成功后把 NIfTI 从 tmp 移走；「删 BIDS 输出 + 不加 force 重跑」实测产出为空、**退出码 0**。现在 convert.py 每次从独立的 dcm2niix 缓存重新灌 tmp。见下文 |
| 9 | fmap 与 bold 的 SeriesDescription 相同/相近 | criteria 加 `PhaseEncodingDirection`；同名不同协议加 `SliceThickness` 等（#35） |
| 10 | 隐私信息泄露 | `participants_mapping.tsv` 与 decisions 不写姓名、原始编号、出生日期。`participants.tsv` 里的 age/sex 是 BIDS 标准列（去标识化），要不要放由用户定（`participants_demographics`） |
| 11 | dcm2niix 太慢 | 缓存 `work/dcm2niix/`；只有换 dcm2niix 版本或改 `dcm2niixOptions` 才 `--refresh-cache`（标记文件会自动发现版本/参数变化） |
| 12 | Dummy TRs 被忽略 | 比较 `n_TRs × TR` 与刺激总时长，差值 = dummy + baseline |
| 13 | `IntendedFor` 路径写法 | 只有两种合法：`bids::sub-01/[ses-x/]func/…`（BIDS 1.9 推荐）或相对被试目录 `[ses-x/]func/…`；不能是绝对路径。写法由 config `bids_uri` 声明，finalize 跟随，validate 检查统一（#42） |
| 14 | func sidecar 缺 `TaskName` → `TASK_NAME_MUST_DEFINE` ERROR | **不是「有时不填」，是确定不填**：dcm2bids 只在用 extractors 从 SeriesDescription 提取 task 时写 TaskName；`custom_entities` 写死 `task-X` 时没有。每个 func 条目写 `"sidecar_changes": {"TaskName": "X"}`（lint 强制，`--fix` 自动补）；finalize 也会兜底补上 |
| 15 | `dataset_description.json` 缺失或字段不全 | `init_metadata.py`：必有 Name/BIDSVersion/DatasetType；Authors 问用户、填了才写；不留空字符串字段 |
| 16 | `participants.tsv` 列 | BIDS 定义的 `age`/`sex`/`handedness` 可直接用；其他列要在 `participants.json` 描述，否则 CUSTOM_COLUMN warning |
| 17 | 额外文件报错 | `.bidsignore` 写 `tmp_dcm2bids/` 等（init_metadata 自动建） |
| 18 | events.tsv 缺 `onset`/`duration` | 必填、全小写、单位秒 |
| 19 | `bids-validator` 找不到 | 用 `npx bids-validator`；服务器无 node 时在能挂载数据的机器上跑（workflow [11]） |
| 20 | `rec-DIV_MP2RAGE` 被报 `NOT_INCLUDED` | 写进 `.bidsignore`：`**/*_rec-DIV_MP2RAGE.*` |
| 21 | events 自定义列 `CUSTOM_COLUMN_WITHOUT_DESCRIPTION` | 根目录 `task-<task>_events.json` 描述每列 |
| 22 | `INCONSISTENT_SUBJECTS` | 真实缺数据时消不掉；记 decision_log，OpenNeuro 可带此 warning |
| 23 | `TOO_FEW_AUTHORS` | 只是提醒 |
| 24 | `EVENTS_TSV_MISSING` | 定位扫描、电影观看等不建模的 task 可接受 |
| 25 | dcm2niix 跳过 CMRR PhysioLog DICOM | v1.0.20250505 无产物无警告；v1.0.20260724 产出 physio.tsv.gz 但 dcm2bids 不配对。用 `physio_to_bids.py`（从 CSA Data 提取，两版都可靠） |
| 26 | CSA Data 里 log 正文不紧跟文件名 | 块起点 +0 dataLen、+4 nameLen、+8 文件名、**+1024 正文**；用正则定位文件名反推块起点并核对 nameLen，不依赖对齐 |
| 27 | PULS / RESP 采样率不同（200 / 50 Hz） | 分 `recording-pulse` / `recording-respiratory` 两套，不重采样 |
| 28 | 同一项目 Physio recording 模式混用（File/DICOM） | mapping 的 `physio_mode` 逐 session 记录；DICOM 模式更可靠（File 模式 log 留在扫描仪本地，漏导就没了） |
| 29 | config 顶层 `intended_for` 被静默忽略 | 3.x 只认 `sidecar_changes.IntendedFor`；`Acquisition(**kwargs)` 吞掉其它键，不报错不警告。lint 拦截、`--fix` 改写 |
| 30 | dcm2bids 不加 force 时看到 tmp 非空就**跳过 dcm2niix** | 这是 #8 的机制。也是 convert.py 能复用缓存的原理：先把缓存灌进 tmp，再调 dcm2bids |
| 31 | dcm2bids 的 `"IntendedFor": ["bold"]` 是**累积**的 | 按处理顺序，第 k 个 fmap 指向此前已处理的全部 bold（实测 1、2、…、8 条）；fmap 若先于 bold 采集则一条都没有。且引用改名前的文件名。finalize 按 `fmap_pairing` 用采集时间重配 |
| 32 | 单个 run 不加 run 实体；废 run 也占 run 号 | dcm2bids 只在同名冲突时编 run。finalize 按协议重编：run 号 = 协议位置；协议多于 1 个 run 的 task 一律带 run |
| 33 | 一个 series 匹配多条规则 → dcm2bids **跳过它**，只打 WARNING（Several Pairing） | convert/preview 把它当错误；改 criteria 使其互斥 |
| 34 | `search_method: "re"` 用 `re.match` | 只锚定开头（`run_01` 也匹配 `run_01_SBRef`），末尾加 `$`；`case_sensitive` 对 re 不生效，用 `(?i)` |
| 35 | 测试序列与正式序列同名（HS7T：0.9mm FALL 测试的 reverse 也叫 `reverse_PE_01`） | criteria 加区分字段，如 `"SliceThickness": {"btwe": [1.1, 1.3]}`；或 decisions `discard`。会撞进 fmap 打乱配对 |
| 36 | 扫描仪软件中途重启 → SeriesNumber 从 1 重来、撞号 | scout/physio 按 SeriesInstanceUID 归组；dcm2niix 文件名模板含 `%p`（协议名）才不会互相覆盖，别改成不含 `%p` 的模板；decisions 用 `sn=…&time=…` |
| 37 | dcm2niix v1.0.20250505 写 AcquisitionTime 秒数不补零（`"11:41:1.870000"`）实测 | 解析时分秒都按 1–2 位接受（bids_common.parse_time）；自己写脚本解析时间时注意 |
| 38 | `dcm2bids --skip_dcm2niix` 要 Python ≥3.8（`copytree(dirs_exist_ok=)`） | 不用它；convert.py 自己灌 tmp，dcm2bids 装在 3.7 也能用。不要为此新建/升级环境 |
| 39 | 剔除废 run 后按顺序重编号 | 缺扫一段时后面的 run 全部前移，电影片段对错（跨被试按 run 对齐就错了）。run 号必须 = 协议位置，允许缺号 |
| 40 | 从数据推期望帧数（众数/最大值） | 变长范式必错：coco 7 段长度 464/470/419/467/479/427/216，众数推出 470，216 的 run-07 被判废片——**按旧脚本 `--auto` 会删掉 4 个被试的好数据**。期望值只能来自协议表 |
| 41 | 硬链接缓存 + 原地修改 NIfTI 的工具 | 硬链接下原地改写会连缓存一起改。dcm2bids `post_op` 或其他原地修改工具 → `cache_mode: copy` |
| 42 | 同一数据集 IntendedFor 写法混用 | 合法但难查（自己写的脚本按「被试目录 + IntendedFor」拼路径会静默找不到 `bids::` 条目）。由 config `bids_uri` 统一声明；validate 检查 |
| 43 | 从目录名/序列名里抠 run 号来配对（旧版 physio 按 `run_(\d+)$`） | 测试序列 `FALL_run_01` 也被认成 run 01，且按字母顺序先占位，真正的 XIJU_run_01 被当重复跳过——交付数据里 run-01 的生理记录其实是测试序列的（实测，NumVolumes 50 ≠ 406）。配对一律按采集时间，名字只用于显示 |
| 44 | 默认配对规则给出的 reverse 实际用不了（中途重新匀场 / 重新定位 / 发射校准被改） | 时间相邻≠可用。finalize 对每个配对体检（ShimSetting、ImagingFrequency、TxRefAmp、sform 扫描框），不通过只报警并给候选和 `pair` 行，由人决定；头动造成的错位仍需 QC 配准 |

## 详细说明

### #8 / #30 重跑丢数据

dcm2bids 3.2.0 `dcm2bids_gen.move()`：NIfTI 用 `os.rename` 从 `tmp_dcm2bids/<sub>/` **移**到 BIDS 目录，
sidecar 写出新文件后 `os.remove` 掉 tmp 里的。所以转换完 tmp 里只剩**没匹配上**的文件。
`dcm2niix_gen.run()`：tmp 目录非空且没有 `--force_dcm2bids` 时**不跑 dcm2niix**，直接用 tmp 里现有的文件。

两者叠加：删掉 BIDS 输出再不加 force 重跑 → 只剩上次没匹配上的文件可用 → 产出为空。
实测（2026-10-19，COCO_S07 子集）：第一次 4 个文件；删 `bids/sub-T` 后重跑，**产出 0 个文件，退出码 0**，
日志里只有一句 `Use --force_dcm2bids to rerun dcm2bids` 的 WARNING。

旧版 skill 把这当成「快速重跑」推荐（`convert_parallel.sh --rerun`、本表旧 #8/#11），是错的。现在：

```
work/dcm2niix/<sub>/     dcm2niix 原始输出，永不被 dcm2bids 碰
   │  硬链接（或复制）
   ▼
bids/tmp_dcm2bids/<sub>/  每次转换前清空重灌，dcm2bids 随便移
```

### #14 TaskName

`sidecar.py` 的 `searchDcmTagEntity()` 只在 `concatenated_matches` 里有 `task`（即 extractors 从
SeriesDescription 用正则提取到了 task）时执行 `sidecar.data['TaskName'] = …`；`acquisition.py` 只在
dcm2niix 原始 sidecar 里有 TaskName 时复制（dcm2niix 不写这个字段）。写死 `task-X` 两条路都不走。
HS7T 的 coco/nezha/andy 从 9 月起所有 bold 都缺 TaskName，因为一直没跑 bids-validator 才没发现。

### #29 顶层 `intended_for`

description 除 `criteria` 外整个作为 `Acquisition(participant, **desc)` 的参数，`__init__` 带 `**kwargs`，
不认识的键被吞掉。IntendedFor 只在 `sidecar_changes` 里处理（`DEFAULT.keyWithPathsidecar_changes`）。
实测：`sidecar_changes` 写法 → 有 IntendedFor；顶层 `intended_for` → 没有，日志无警告。
后果：下游只能按 run 号或时间猜配对；实测一场里两套同矩阵测试协议，QC 把 A 协议的 func 配到 B 协议的
reverse-PE 上，报出假的 3.65 mm 头位差。

### #31 IntendedFor 累积

`move()` 维护 `idList[id] = [已处理的同 id 文件…]`，处理到某个 fmap 时把 `idList["bold"]` 当前的内容写进去。
处理顺序按 sidecar 排序（AcquisitionTime、SeriesNumber、文件名）。所以：每 run 后跟一个 reverse 的协议，
fmap_k 指向 bold_1..k；fmap 在 bold 之前采的协议，第一个 fmap 一条都没有（且有 `No id found` WARNING）。
这不是任何人想要的配对，只能后处理。配对规则必须由人声明（after/before/…），因为「夹在两个 run 中间的 fmap
属于谁」只有协议设计者知道。

### #25–#28 CMRR 生理记录

| 模式 | 产物 | 风险 |
|---|---|---|
| DICOM | `*_PhysioLog` series 混在 DICOM 目录，`ImageType = ORIGINAL\PRIMARY\RAWDATA\PHYSIO`，单帧 1–19 MB | dcm2niix 静默跳过，易误判「没采」 |
| File | 独立 `Physio_<date>_<time>_<uuid>_{Info,PULS,RESP}.log` | 留在扫描仪本地 log 目录，漏导就没了，且会被定期清理 |

两种模式的 log 内容相同（`LogVersion = EJA_1`），提取后走同一条路径。

**配对靠时间，不靠名字或帧数**：Info.log 数据行 `VOLUME SLICE ACQ_START_TICS ACQ_FINISH_TICS ECHO`，
第一个 volume 的 `ACQ_START_TICS × 2.5 ms` = 第一帧时刻（自零点），与 bold sidecar 的 AcquisitionTime 相差 < 1 ms
（HS7T nezha 实测 3 个 run：14:04:28.543 vs 14:04:28.5425 等）。旧版按 NumVolumes 反查，等长范式（每个 run 帧数相同）
根本配不了；按目录名里的 run 号，重编号后会配错。

**StartTime** = (physio 首个采样 tick − 第一帧 tick) × 2.5 ms，负值 = 生理记录先于扫描开始，
是该协议「序列启动到第一帧」的开销，同协议下稳定（HS7T 1.2mm/124 层全部为 −50.24 s）。
**某个 run 明显偏离，先怀疑配错了 log**。实例（#43）：旧脚本给 xiju sub-02 run-01 算出 −174.5 s，
当时被解释成「启动后停了 2 分钟」——实际是把同场 FALL 测试序列（50 帧）的 log 配给了这个 406 帧的 run。
按时间配对后恢复为 −50.24 s；NumVolumes 与 bold 帧数不等时 physio_to_bids 会报警。
