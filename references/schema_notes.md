# project_config_template.yaml 字段说明 (v1.3)

> 与 `project_config_template.yaml` 配合阅读。

## 字段分类

- **核心字段**：每个项目都需要填写，直接影响转换流程
- **扩展字段**：部分项目需要，为特殊情况保留结构

## 字段速查表

| 字段 | 必填 | 核心/扩展 | 说明 |
|------|------|----------|------|
| `config_version` | 必填 | 核心 | 模板版本号，脚本据此判断兼容性 |
| `project_name` | 必填 | 核心 | 项目标识 |
| `raw_data_root` | 必填 | 核心 | 原始 DICOM 根目录绝对路径 |
| `bids_output` | 必填 | 核心 | BIDS 输出目录绝对路径 |
| `sessions.enabled` | 必填 | 核心 | 单/多 session 是最基本的结构分叉 |
| `sessions.labels` | enabled=true 时必填 | 核心 | session 标签列表 |
| `subjects.total_expected` | 必填 | 核心 | 用于转换后验证被试数是否齐全 |
| `subjects.excluded` | 可为空 | 核心 | 空表示无排除；非空时记录排除事实 |
| `subjects.numbering` | 必填 | 核心 | 决定编号策略，影响 mapping 生成 |
| `anat[].sequence_type` | 必填 | 核心 | 区分 MP2RAGE / MPRAGE 等不同结构像 |
| `anat[].series_description_variants` | 必填 | 核心 | 侦察阶段收集，直接用于写 config.json |
| `anat[].duplicate_handling` | 必填 | 核心 | 三个项目中两个遇到了重复结构像 |
| `anat[].outputs` | 必填 | 核心 | MP2RAGE 有多输出，MPRAGE 通常只有一个 |
| `anat[].outputs[].entities` | 可为空 | 核心 | 结构化表达 BIDS entities，空 `{}` 表示无额外 entity |
| `anat[].outputs[].criteria_hint` | 必填 | 核心 | 人可读的匹配提示，直接对应 dcm2bids criteria |
| `func[].sequence_type` | 必填 | 核心 | bold / bold_phase / sbref 等 |
| `func[].task_name` | 必填 | 核心 | BIDS task label |
| `func[].runs_per_session` | 必填 | 核心 | 用于验证转换结果 |
| `func[].expected_volumes` | 必填 | 核心 | 用于检测 aborted run |
| `func[].series_description_variants` | 必填 | 核心 | 同 anat |
| `func[].discrimination_hint` | 可为空 | 核心 | 当 variants 相同需靠其他字段区分时填写，如 "ImageType contains PHASE" |
| `fmap[].sequence_type` | 必填 | 核心 | 目前只遇到 reverse_pe_epi |
| `fmap[].pe_direction` | 必填 | 核心 | 区分 AP/PA 的关键 |
| `fmap[].per_run` | 必填 | 核心 | 影响 fmap 数量验证和 intended_for |
| `fmap[].series_description_variants` | 必填 | 核心 | 同上 |
| `fmap[].discrimination_hint` | 可为空 | 核心 | 同 func，用于 fmap mag/phase 区分等 |
| `auxiliary.physio` | 可为空 | 核心 | enabled=false 时其余字段忽略 |
| `auxiliary.behavior` | 可为空 | 核心 | 同上 |
| `events.enabled` | 必填 | 扩展 | 提醒是否需要生成 events.tsv |
| `events.generator_script` | 可为空 | 扩展 | 范式参数在脚本内部，不在模板展开 |
| `events.notes` | 可为空 | 扩展 | 指向范式文档或简述要点 |
| `manual_review[]` | 可为空 | 扩展 | 空表示无需人工确认的事项（理想情况） |
| `special_cases[]` | 可为空 | 扩展 | 空表示无特殊规则 |

## 设计理由

### 为什么是这些字段，不多也不少

1. **所有核心字段都是三个已完成项目中至少两个实际用到的信息。** 没有一个字段是"也许将来有用"而加的。

2. **anat/func/fmap 统一为列表结构。** 三个项目都遇到了"同一 datatype 下有多种序列"：MP2RAGE 多输出、bold + phase、fmap 命名变体。列表是最小成本实现可扩展的方式。

3. **entities 用 dict 而非字符串。** `inv-1_part-mag_rec-ND` 这种拼接串在三个项目里出了多次拼写顺序问题，dict 形式 `{inv: 1, part: mag, rec: ND}` 更不容易出错，也更方便程序读取。

4. **events 只保留入口信息。** 三个项目中只有 MP_CRF 做了 events.tsv，且每个项目的范式参数结构完全不同（block design 参数、条件平衡方案、dummy TRs 等）。强行在模板里统一范式字段会过度设计，不如将细节留给每个项目自己的生成脚本。

5. **manual_review 和 special_cases 有固定结构但内容留空。** 每个项目都有例外需要记录，但例外的类型无法预测。四字段结构（item/reason/decision/affected）是从实际记录中提炼的最小完整表达。

6. **没有把 dcm2bids_config.json 的完整规则放进来。** config.json 本身就是最终产物。模板的作用是提供生成 config.json 所需的输入信息（variants、entities、criteria_hint），不是替代它。

### 核心与扩展的划分依据

- **核心**：缺了这个字段，转换流程会缺少必要信息或无法验证结果
- **扩展**：不是每个项目都需要，但需要时应有固定位置存放，而不是临时发明字段

### 未来演进方向

模板刻意没有覆盖的内容（待积累更多项目经验后再决定是否纳入主干）：
- 多 task 项目（同一 session 内多种 task）
- DWI / perfusion 等非 fMRI 序列
- 跨 session 序列不一致的结构化表达
- events.tsv 的通用范式描述格式
