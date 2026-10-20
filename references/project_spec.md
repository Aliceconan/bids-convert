# 项目声明文件

**原则：所有人工判断都写进文件，从 DICOM 一条命令重跑得到同样的 BIDS。**
不要在转换后手工 `mv` / `rm` / 改 json——那样的结果不可复现，重转一次就丢了。

```
<project>/
  code/
    dcm2bids_config.json      series → BIDS 文件名的匹配规则（dcm2bids 原生格式）
    participants_mapping.tsv  哪个 DICOM 目录是哪个被试/session
    project.json              项目级设置与默认策略
    protocol.tsv              每个 task 每个 run 的期望帧数
    decisions.tsv             逐 session 的人工决策（每行带原因）
    decision_log.md           叙述性记录（为什么这么定、发现了什么）
    logs/                     convert / dcm2bids 日志、状态 json
  bids/                       BIDS 数据集（含 sourcedata/physio）
  work/                       可再生的中间产物：dcm2niix 缓存、scout、preview、discarded、finalize 报告
```

`work/` 可以放 scratch（`project.json` 的 `work_dir` 写绝对路径），但 `cache_mode: hardlink`
要求它和 `bids/` 在同一文件系统，否则自动退化为复制。

## dcm2bids_config.json

dcm2bids 3.x 原生格式，另有三条**强制**约定（`lint_config.py` 检查，`--fix` 可补）：

| 键 | 写法 | 为什么 |
|---|---|---|
| `"case_sensitive": false` | 顶层 | 默认区分大小写，序列名大小写一变就漏匹配；有了它不用再在 `any` 里列大小写变体 |
| `"bids_uri": "URI"` | 顶层 | IntendedFor 写法由这里声明（`URI` → `bids::sub-XX/...`，BIDS 1.9 推荐；`relative` → `func/...`）。finalize 和 validate 都跟随它 |
| `sidecar_changes.TaskName` | 每个 func 条目 | 写死 `task-X` 时 dcm2bids **不会**自动填 TaskName（只有用 extractors 提取 task 才填），validator 报 ERROR |
| `sidecar_changes.IntendedFor` | fmap 条目 | **不能**写在顶层 `intended_for`（被静默忽略）。它的内容最终会被 finalize 按 `fmap_pairing` 重写 |

匹配写法要点：
- 默认 `fnmatch`。`*` 任意串、`?` 单字符、`[0-9]` 字符集。
- `search_method: "re"` 时用 `re.match`：**只锚定开头**（`run_01` 也匹配 `run_01_SBRef`，末尾要加 `$`），
  且 `case_sensitive` 对 re 不生效（要忽略大小写用 `(?i)`）。
- 数值字段可用 `{"btwe": [1.1, 1.3]}`、`{"lt": 60}` 等（`lt/gt/le/ge/btw/btwe`）。
  同名测试序列（比如 0.9mm 测试协议也叫 `reverse_PE_01`）用 `SliceThickness` 区分，比按 SeriesNumber 写死更稳。
- list 型字段（`ImageType`）按**整个列表逐项**比较，长度不同就不匹配。
- 一个 series 匹配多条规则时 dcm2bids 会**跳过它**（Several Pairing）。convert/preview 会把它当错误报出。

## participants_mapping.tsv

按表头读，列顺序随意。**不含隐私信息**（姓名、原始编号、出生日期）。

| 列 | 必需 | 说明 |
|---|---|---|
| `participant_id` | ✓ | `sub-01` 或 `01` |
| `session` | | 多 session 项目才写；`ses-pre` 或 `pre` |
| `dicom_dir` | ✓ | 绝对路径，或相对 `project.json` 的 `raw_root` |
| `physio_mode` | | `none`（默认）/ `dicom`（PhysioLog 在 DICOM 里）/ `file`（独立 .log） |
| `physio_dir` | | `physio_mode=file` 时 log 所在目录 |
| 其他 | | 任意附加列（如 `beh_dir`、`scan_date`、`series_naming`），脚本不读，`copy_sourcedata.py` 可用 |

## project.json

| 键 | 默认 | 说明 |
|---|---|---|
| `name` | | 数据集名，进 dataset_description.json |
| `raw_root` | | mapping 里 `dicom_dir` 相对路径的根 |
| `bids_dir` / `work_dir` | `bids` / `work` | 相对项目目录或绝对路径 |
| `dcm2bids` / `dcm2niix` | 在 PATH 里找 | 不在 PATH 时写绝对路径 |
| `jobs` | 4 | 并行 session 数（7T 一场 dcm2niix 吃内存和 IO，别开太大） |
| `cache_mode` | `hardlink` | dcm2niix 缓存进 tmp 的方式；`copy` 更保险但占双倍空间 |
| `fmap_pairing` | **必填** | fmap 与 bold 的配对规则，见下 |
| `anat_duplicates` | `ask` | 同一结构像多套时：`ask` / `first` / `last` / `all`（`all` 存为 run-01/02） |
| `unmatched_func` | `ask` | 与协议表对不上的 bold（废 run）：`ask` / `discard` |
| `unpaired_fmap` | `ask` | 配不上 bold 的 fmap：`ask` / `discard` / `keep`（保留但无 IntendedFor） |
| `authors` / `license` | 空 | 填了才写进 dataset_description（Authors 要问用户，别编） |
| `participants_demographics` | false | true 时 participants.tsv 加 age/sex（取自 DICOM，BIDS 标准列） |

`ask` 的意思是：遇到这种情况就停下等人决定（写 decisions.tsv）。确认某类情况一律怎么处理后，
再把项目默认改成 `discard` 等——这本身也是一个决策，记进 decision_log。

### fmap_pairing

| 值 | 规则 | 适用 |
|---|---|---|
| `after` | fmap 属于它**之前**最近的保留 bold；中间若隔着另一个同方向 fmap 则不配 | 每个 run 后面跟一个 reverse-PE（HS7T） |
| `before` | fmap 属于它**之后**最近的保留 bold；同上 | 每个 run 前面先扫 fmap |
| `nearest` | 每个 bold 配时间上最近的 fmap（按 bold 的起止区间算距离） | fmap 比 run 少（几个 run 共用一个） |
| `index` | 同方向第 k 个 fmap ↔ 第 k 个保留 bold | 顺序固定且数量相等，又不方便用时间 |
| `all` | 每个 fmap 指向全部 bold | 整场一个 fieldmap |
| `none` | 去掉 IntendedFor | 没有 fmap，或不做畸变校正 |

「之前/之后」看的是采集时间（sidecar 的 AcquisitionTime），不是文件名或 run 号。
被剔除的 bold 不参与配对——废 run 后面紧跟的那个 fmap 会变成「配不上」，按 `unpaired_fmap` 处理。
`after` 和 `nearest` 在「fmap 夹在两个 run 正中间」时结论不同，所以必须由人声明，不能猜。

严格 1:1 时 fmap 的 run 号跟随所配 bold（缺扫时同样缺号）；否则按时间顺序编号。

**规则只是默认，不是写死的。** 规则回答「按协议这张 fmap 是给谁扫的」，回答不了「它实际能不能用」。
所以每个配对都会做**体检**（只报警，不自动换）：

| 检查 | 字段 | 不一致说明 |
|---|---|---|
| 同一次匀场 | `ShimSetting`、`ImagingFrequency`（>10 Hz） | 中途重新匀场/调频，topup 前提不成立 |
| 同一发射校准 | `TxRefAmp`（>1%） | 翻转角不同、对比度不同（常见于手动钉死 reference amplitude） |
| 同一扫描框 | NIfTI sform 的扫描框中心（>1 mm）与层面法向（>1°） | 中途重新定位（出舱重进、重调 FOV） |

报警里列出能通过体检的候选（按时间就近排序），并给出可照抄的 `pair` 行；没有候选就提示该 run 考虑不做
畸变校正或排除。改配写进 decisions.tsv（`pair` 对所涉 bold 独占：同方向的其他 fmap 不再按规则指向它；
被换下的 fmap 若因此无配对，按 `unpaired_fmap` 处理）。
体检看不出被试头动造成的错位——那要 fmri-qc-raw 的配准（func↔fmap 头位差）。

实测（HS7T）：andy/sub-01 run-02 体检报「扫描框中心差 4.4 mm、法向 11.1°，且重新匀过场」，无候选；
coco/sub-06 run-01 报「重新匀场」，run-02/03 报「发射参考幅度 220 vs 252（翻转角约 87%）」——
与 9 月 QC 的人工结论一致。

## protocol.tsv

```
task	run	volumes	tolerance
movie	1	464	0
movie	2	470	0
rest	1	300	0
```

- `volumes` **来自扫描协议表**，不要从数据推。变长范式（电影分段、自定步调）每个 run 不同；
  等长范式每行相同。
- finalize 按「采集顺序单调对应协议顺序」把 bold 对到 run 上：帧数在 `±tolerance` 内才算对上，
  取匹配数最多的对应方式。
  - **run 号 = 协议里的位置**：缺扫第 3 段时得到 run-01/02/04（BIDS 允许缺号）。
  - 对不上的 bold（废 run）按 `unmatched_func` 处理。
  - 有不止一种最优对应（比如等长范式多出一个完整长度的 run）→ 停下，要人用 `discard`/`assign` 定。
- 协议里只有 1 个 run 的 task，文件名不带 run 实体；多于 1 个的，即使这场只扫到 1 个也带 `run-01`
  （同数据集内命名一致）。

## decisions.tsv

```
participant_id	session	action	target	value	reason
sub-05		anat_duplicates		last	SN5-7 头动大，现场重扫
sub-01		volumes	run=1	470	现场记录 run-01 实际 470 TR
sub-03		discard	sd=*TEST*		调试序列
sub-02		assign	sn=58	run=3	run-03 的重扫放到了最后
sub-01		pair	sn=24	sn=15	run-02 改用 reverse_PE_01（场更接近）
```

`session` 留空 = 对该被试所有 session 生效。**每行必须写 reason**（不写会报 warn）。

| action | target | value | 作用 |
|---|---|---|---|
| `discard` | 选择器 | | 剔除匹配到的文件（移到 `work/discarded/`，附原因）；一个都没匹配到算错误（防拼错） |
| `assign` | 选择器（恰好 1 个 bold） | `run=N` 或 `N` | 强制该 bold 为协议第 N 个 run |
| `volumes` | `run=N`（可 `&task=X`） | 帧数 | 该 session 的期望帧数例外 |
| `pair` | fmap 选择器 | bold 选择器 | 显式指定该 fmap 的 IntendedFor |
| `anat_duplicates` / `fmap_pairing` / `unmatched_func` / `unpaired_fmap` | | 取值同 project.json | 覆盖该 session 的策略 |
| `note` | | | 只记录，不做事 |

选择器：`sn=5,6,7`（SeriesNumber）、`sd=*TEST*`（SeriesDescription，fnmatch，忽略大小写）、
`time=13:41:07`（AcquisitionTime ±1 s；只写到分钟则 ±60 s）、`run=3`、`task=x`、`datatype=fmap`、
`suffix=sbref`，用 `&` 组合。扫描仪软件重启后 SeriesNumber 会撞号，此时用 `sn=5&time=15:02`。
