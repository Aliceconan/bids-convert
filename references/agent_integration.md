# Agent 框架适配指南

本文档面向需要把 bids-convert 集成到新 agent 框架，或扩展到新厂商/序列类型的开发者。执行具体转换任务时不需要读这个文件。

## 需要适配的部分（与 agent 框架相关）

| 维度 | 说明 |
|------|------|
| **Shell 执行** | 需要能执行 bash 命令并获取 stdout/stderr；并行执行是核心性能需求 |
| **文件读写** | 读取 JSON sidecar、写入 TSV/JSON/Python 文件 |
| **用户交互** | 步骤 [3] 交互密集，需要"暂停等待用户输入"机制 |
| **长时间任务** | 批量转换可能 5-10 分钟；需要超时容忍或异步机制 |
| **上下文管理** | 20+ session 的验证输出很大，需要能处理或截断 |
| **路径** | 脚本使用 `$SKILL_DIR` / `$PROJECT_DIR` 变量，agent 负责传入绝对路径 |

## 需要泛化的部分（与领域相关）

| 维度 | 当前主干 | 后续扩展方向 |
|------|---------|---------|
| **扫描仪** | Siemens (S18/P14) | Philips、GE 等厂商的 sidecar 判据与命名规律 |
| **序列类型** | MP2RAGE + EPI bold + reverse-PE fmap | T1w MPRAGE、T2w、DWI、ASL、multi-echo GRE |
| **数据格式** | Siemens .IMA | 标准 `.dcm`、PAR/REC (Philips)、增强型 DICOM |
| **目录结构** | `YYYYMMDD_Scanner_Experiment_Subject` | 应允许用户自定义 glob pattern |
| **范式格式** | 硬编码 Python onset 表 | PsychoPy log、E-Prime txt、MATLAB .mat |
| **Physio 格式** | Siemens PhysioLog (.ecg/.puls/.resp) | BIOPAC (.acq)、BrainVision (.vhdr) |

## 接口契约

```yaml
skill:
  name: bids-convert
  version: "1.0"

  requires:
    - shell_execute
    - file_read
    - file_write
    - user_interaction
    - json_parse

  optional:
    - parallel_execution     # 缺失则降级为串行
    - background_task        # 缺失则同步等待
    - structured_output      # 表格等

  inputs:
    skill_dir: string        # 本 skill 文件夹的路径
    raw_data_root: string    # DICOM 数据根目录
    project_name: string     # 项目名
    bids_output: string      # BIDS 输出目录

  outputs:
    bids_directory: string
    decision_log: string
    stats:
      subjects: int
      sessions: int
      total_files: int
      sessions_needing_decision: int
```

## 状态机模型（非对话式 agent）

```
INIT → SCOUT → WAIT_USER_CONFIG → WRITE_DECLARATIONS → PREVIEW ⇄ WAIT_USER_DECISIONS →
CONVERT (⇄ WAIT_USER_DECISIONS on needs_decision) → VALIDATE → METADATA →
AUXILIARY → EVENTS → BIDS_VALIDATOR → RECORD → DONE
```

`WAIT_USER_*` 状态需要外部输入，其余可自动执行。PREVIEW/CONVERT 返回待决事项时，把事项原样交给用户，
用户的决定写进 `code/decisions.tsv`（每行带 reason），再回到 PREVIEW/CONVERT——不要替用户猜。

## 自动化友好接口

关键脚本支持结构化输出和明确退出码，便于在 CI 或非交互 agent 中消费：

- `validate.py --json --fail-on-anomaly` — 输出 JSON，异常时退出 1
- `preview.py` / `finalize.py` — 有待决事项时退出 2，不改任何文件
- `convert.py` — 退出 0/2/1（完成/有待决/有失败），明细写 `code/logs/convert_<时间>.json`
- `lint_config.py --json` — config 静态检查
