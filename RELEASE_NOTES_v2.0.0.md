# v2.0.0（2026-10-19）

声明式重构：所有人工判断写进项目声明文件，从 DICOM 一条命令可复现。

## 修复的数据错误（v1.x 用户请核对已有数据）

- **`convert_parallel.sh --rerun` 静默清空 session**：dcm2bids 匹配后把 NIfTI 移出 tmp，「删输出 + 不加 force 重跑」
  产出为空、退出码 0（实测）。v1.x 按文档「改 config 后 --rerun」的 session 需要检查。
- **生理记录按目录名里的 run 号配对**：同场测试序列 `FALL_run_01` 被配成 run-01（实测 HS7T xiju sub-02，
  NumVolumes 50 ≠ 406）。v1.x 产出的 `_physio.json` 请核对 `NumVolumes` 是否等于对应 bold 的帧数。
- **func sidecar 全部缺 TaskName**：写死 `task-X` 时 dcm2bids 不填（bids-validator ERROR）。
- **`lint_config.py --fix` 把已经正确的 `sidecar_changes.IntendedFor` 再套一层**。
- `cleanup_aborted.py` 在变长范式上把好 run 当废片（众数推期望值）；重编号后 IntendedFor 悬空。
- `postprocess_runs.py` 按顺序重编号，缺扫时后面的电影片段 run 号前移；要求协议所有 run 都在。
- `copy_auxiliary.sh` 无 session 列时取错列；`convert_parallel.sh` 按位置读 mapping，无 session 列时把 DICOM 目录当 session。

## 新流程

`scout.py → (写声明) → preview.py → convert.py → validate.py → init_metadata.py → bids-validator`

| 新增 | 作用 |
|---|---|
| `project.json` / `protocol.tsv` / `decisions.tsv` | 项目设置、期望帧数、逐 session 决策（带原因） |
| `scout.py` | 只读 DICOM 头 + 每 series 一个 sidecar（按 SeriesInstanceUID 归组，SN 撞号不丢 series） |
| `preview.py` | 用真实 dcm2bids + finalize 预演，不转影像 |
| `convert.py` | dcm2niix 缓存（硬链接灌 tmp），重跑安全且快；兼容 dcm2bids 装在 Python 3.7 |
| `finalize.py` | run 号 = 协议位置（可缺号）、剔除移到 `work/discarded/`、fmap 按声明规则用采集时间配对、补 TaskName；无法自动决定时整体停下 |
| 配对体检（finalize 内） | 每个 fmap↔bold 配对查同一次匀场 / 发射校准 / 扫描框，不通过只报警并给候选 `pair` 行（HS7T 已知问题全部复现） |
| `physio_to_bids.py` | 提取 + 转换合一，按采集时间与 bold 配对（< 1 ms） |
| `init_metadata.py` / `copy_sourcedata.py` | 数据集元数据；行为数据等 |

config 必须声明 `case_sensitive`、`bids_uri`，func 条目必须有 `sidecar_changes.TaskName`（lint 强制，`--fix` 补）。

## 删除

`scout.sh`、`convert_parallel.sh`、`cleanup_aborted.py`、`postprocess_runs.py`、`extract_cmrr_physio_dicom.py`、
`cmrr_physio2bids.py`、`copy_auxiliary.sh`、`templates/project_config.yaml`、`references/schema_notes.md`。

## 验证

- 44 个单元测试，Python 3.9（Mac）与 3.6.8（服务器节点默认）均通过。
- 真实数据端到端（HS7T 3 场：只扫 1 个 run、重复 T1 + rescan fmap、混测试序列与同名 reverse）：
  预演准确指出唯一待决事项；转换后帧数、IntendedFor、TaskName、生理记录全部正确；
  缓存重跑 35 s、产出与首次逐字节一致；bids-validator 0 ERROR。
