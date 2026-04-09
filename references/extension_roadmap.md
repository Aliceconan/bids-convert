# 扩展路线说明

> 本说明用于定义 `bids-convert` 后续演进方向。
> 它强调的是“在统一工作流骨架上持续扩展”，而不是把仓库锁死在当前 Siemens/fMRI 经验上。

## 1. 这个仓库当前是什么

这个仓库的当前主干，是基于 4 个已完成项目提炼出的 MRI rawdata → BIDS 工作流：

- ODLoc
- EYEDEP_CRF
- MP_CRF
- MonoDep

这些项目的共同点决定了当前覆盖最成熟的路径：

- Siemens 数据
- fMRI 项目
- MP2RAGE 结构像
- EPI BOLD
- reverse-PE fieldmap
- 有限的 physio / behavior / events 后处理

但这只是**当前经验最充足的起点**，不是这个仓库的长期边界。

## 2. 这个仓库未来不想变成什么

后续扩展时，不希望把仓库变成下面这些形态：

- 只服务 Siemens 的一次性脚本集合
- 每增加一种机型就复制一整套平行工作流
- 每增加一种序列就新增一堆互不兼容的例外逻辑
- 写死“某些机型/序列不支持”，导致未来扩展需要推翻已有结构

换句话说，这个仓库不应被定义为“Siemens skill”，而应被定义为：

**一个以 Siemens/fMRI 经验起步、但面向多厂商、多序列类型持续演进的 DICOM-to-BIDS 工作流框架。**

## 3. 核心思路：骨架稳定，可变部分逐步模块化

未来扩展时，优先保持以下主流程不变：

1. 初始化项目
2. 侦察原始数据
3. 与用户确认关键决策
4. 生成 config 与 mapping
5. 批量转换
6. 验证结果
7. 后处理异常
8. 补充 auxiliary 数据
9. 生成 events
10. 记录人工判断

真正应该逐步抽象和替换的，是下面这些“可变层”：

- 侦察时读取哪些 sidecar 字段
- 不同厂商/序列的判别规则
- `dcm2bids_config.json` 的生成模式
- 不同 datatype 的验证规则
- 特定序列的后处理策略
- events 输入格式和生成逻辑

因此，扩展方向不是“推翻现有流程”，而是“让可变层越来越清楚、越来越独立”。

## 4. 后续扩展的优先级

### 第一优先级：厂商扩展

先从 Siemens 主干扩展到：

- Philips
- GE

这里的目标不是一开始就追求全覆盖，而是先搞清楚以下差异：

- 哪些 DICOM sidecar 字段在不同厂商下稳定可用
- `SeriesDescription` 是否仍是主要判据，还是要更多依赖其他字段
- fieldmap / phase / magnitude / 派生重建的区分方式是否不同
- 原始目录结构和命名模式是否需要新的 glob 或 mapping 策略

在这一阶段，建议新增的是：

- 厂商差异参考文档
- 厂商特定的侦察提示
- 厂商特定的 config 片段或模板

而不是直接复制整套 Siemens 工作流。

### 第二优先级：序列扩展

在厂商扩展之外，逐步覆盖更多 datatype：

- MPRAGE / T1w 常规结构像
- T2w
- DWI
- ASL / perfusion
- multi-echo GRE 或其他更复杂序列

这里要沿用当前模板的设计思想：

- `anat / func / fmap` 用列表结构继续承载扩展
- sequence-specific 的复杂性放进模板片段或 reference，而不是塞爆主 README
- 能通过 `criteria_hint`、`discrimination_hint` 表达的，尽量先用结构化字段表达

如果未来确实需要新的 datatype 分支，也应优先在 `project_config.yaml` 中扩展结构，而不是让所有特殊情况只存在于临时脚本里。

### 第三优先级：输入与范式扩展

目前 events 生成仍以“每项目自定义 Python 脚本”方式为主，这个选择是合理的，因为现阶段项目差异太大。

未来可以逐步补充：

- PsychoPy log → events
- E-Prime txt → events
- MATLAB `.mat` → events
- CSV / TSV 行为日志 → events

但这个方向应该继续遵守一个原则：

**先统一入口，不急着统一所有范式内部结构。**

也就是说，先定义“如何接一个新的范式输入源”，而不是过早设计一个试图覆盖所有实验的通用范式 DSL。

## 5. 结构层面的演进建议

结合当前仓库内容，后续演进最自然的方向是：

### 5.1 `templates/` 继续保持“稳定主干 + 可选片段”

当前已经有：

- `project_config.yaml`
- `dcm2bids_config_mp2rage.json`
- `decision_log.md`

未来可以继续加，但建议遵守同样的组织方式：

- 主模板保持简洁稳定
- 厂商或序列特定内容用独立片段文件表达

例如未来可能出现：

- `templates/dcm2bids_config_mprage.json`
- `templates/dcm2bids_config_dwi.json`
- `templates/dcm2bids_config_philips_epi.json`
- `templates/dcm2bids_config_ge_epi.json`

### 5.2 `references/` 用来承载差异知识，而不是塞进主流程

当前 `references/` 已经在做这件事，这是对的。

未来可以自然增加：

- `references/vendor_philips_notes.md`
- `references/vendor_ge_notes.md`
- `references/dwi_notes.md`
- `references/asl_notes.md`

这些文件的作用不是重复主流程，而是记录：

- 特定厂商/序列最稳定的判据
- 常见坑
- config 片段如何选
- 哪些判断仍然必须人工确认

### 5.3 `scripts/` 优先抽象“稳定动作”，不要塞太多项目特例

当前脚本的边界整体是健康的：

- `scout.sh` 负责侦察
- `convert_parallel.sh` 负责批量转换
- `validate.py` 负责验证
- `cleanup_aborted.py` 负责异常清理
- `copy_auxiliary.sh` 负责辅助数据复制
- `generate_events_template.py` 负责 events 框架

未来扩展时，建议保持这一原则：

- 稳定动作放在通用脚本里
- 厂商/序列差异尽量体现在输入配置和 reference 中
- 只有当某个差异已经稳定复用时，再提升为脚本能力

## 6. 对外表述建议

为了避免误导用户或其他 agent，仓库对外应优先用下面这种表述：

- 当前覆盖最好的是 Siemens-style fMRI 项目
- Philips、GE 和更多序列类型是明确的后续扩展方向
- 仓库设计上保留了扩展这些方向的接口
- 当前未完整覆盖，不等于未来不支持

不建议使用的表述包括：

- “仅支持 Siemens”
- “不支持 Philips / GE”
- “只适用于 MP2RAGE 项目”

更好的说法是：

- “当前以 Siemens/fMRI 经验为主干”
- “其他厂商和序列类型将沿同一工作流逐步补充”
- “当前模板和脚本已经为多厂商、多序列扩展预留了结构空间”

## 7. 实施顺序建议

如果后续按增量方式推进，比较稳妥的顺序是：

1. 补厂商差异参考文档
2. 为 Philips / GE 增加最小侦察与 config 片段
3. 用 1 到 2 个真实项目验证扩展结构
4. 再决定哪些规则应该升格进主模板或主脚本
5. 最后才考虑把更多序列类型系统性并入主干

这样做的好处是：

- 不会过早设计
- 不会因为少量样本就把模板写死
- 可以持续保持当前仓库“真实项目驱动”的风格

## 8. 一句话总结

这个仓库的长期目标，不是成为“Siemens 项目的专用工具箱”，而是成为：

**一个以 Siemens/fMRI 项目经验为起点、逐步吸纳 Philips、GE 以及更多 MRI 序列类型的可扩展 DICOM-to-BIDS 工作流框架。**
