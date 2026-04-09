# 已完成项目差异对照表

| 维度 | ODLoc | EYEDEP_CRF | MP_CRF | MonoDep |
|------|-------|------------|--------|---------|
| 被试数 | 25 | 11 | 12 | 10 |
| Sessions | 单 session | ses-pre / ses-post | ses-pre / ses-post | ses-pre / ses-post |
| 扫描仪 | S18 | S18 + P14 | S18 | S18 |
| MP2RAGE 输出数 | 7 | 3 | 11 (含 phase) | 7 |
| 功能像 | 1 task × 4 runs × 170 vol | 1 task × 1 run × 482 vol | 1 task × 8 runs × 158 vol | 3 tasks: eyedep 2×242 + loc 4×170 + rest 1×242 |
| Phase 数据 | 无 | 有（bold mag+phase） | 有（MP2RAGE phase） | sub-01 有 MP2RAGE phase |
| Fieldmap | 每 run 一个 reverse-PE | 单个 PA（部分缺失） | 每 run 一个 PA | 每 run 一个 PA |
| Noise scan | 无 | 有（2 vol） | 无 | 无 |
| 校准扫描 | 无 | 部分有 | 无 | 无 |
| Physio | 无 | 部分有 | 部分有（DICOM 子目录） | 无 |
| 行为数据 | 无 | 部分有 (.mat) | 无 | 无 |
| Events.tsv | 无 | 无 | 有 (block design) | 有 (block design) |
| 被试编号 | 按日期 | 按日期 | 按原始 S-number | 按日期 |
| SD 一致性 | 低（3 种命名） | 中 | 低（大小写） | 极低（早/晚期完全不同） |
| Aborted runs | 有 | 有（calibration） | 有 | 有（6/20 session） |
| 重复 MP2RAGE | 无 | 无 | 有（部分被试扫两次） | 无 |
| 多余 fmap | 无 | 无 | 有 | 无 |

## 复杂度排序

1. **EYEDEP_CRF** — 最多特殊类型（phase bold、noise scan、calibration、physio、behavior）
2. **MonoDep** — 序列名变体最多（早/晚期完全不同命名体系）
3. **MP_CRF** — 重复 MP2RAGE + run 数最多（8 runs）
4. **ODLoc** — 最简单的单 session，但序列名仍有 3 种变体
