# HS7T 电影 fMRI（coco）—— 完整声明文件示例

7T（Siemens，怀柔）电影观看：MP2RAGE + 每段电影一个 GE-EPI run（1.2mm，TR 2s，MB4）+ 每个 run 之后一个
3-volume reverse-PE + CMRR 生理记录。coco 分 7 段，长度 `464/470/419/467/479/427/216`（变长范式）。

这里的每个文件对应 `references/project_spec.md` 的一节；从 DICOM 重转只需要
`scout.py → preview.py → convert.py → validate.py → init_metadata.py`。

## 这个项目的坑，以及它们落在哪个文件里

| 情况 | 处理 | 文件 |
|---|---|---|
| 三套互不兼容的序列命名：`cmrr_mbep2d_bold_AP_coco_run2`（06-12）/ `…_PA_coco_run1` + `revers1` 拼写（09-01）/ `coco_run_01` + `reverse_PE_01`（09-07 起） | `any` 列出三套；`case_sensitive: false` 免列大小写 | config |
| 序列名里的 AP/PA 不可信：前两批名字相反但 PE 值相同；09-07 起 BOLD 从 `j` 改成 `j-` | fmap 的 dir 按 `PhaseEncodingDirection` 判定，两个条目 | config |
| 0.9mm 测试协议的 reverse 也叫 `reverse_PE_01`（另一个数据集同场出现过） | `SliceThickness` 限定 1.1–1.3 | config |
| 首场 run 编号错位（run-01 占了 "run2" 的名字，run-02 叫 "run2_2"），且 run 3 的废片与重扫同名 | 不看名字：按协议帧数对位；废片（104/419）对不上协议，按 `unmatched_func: discard` 剔除 | protocol + project |
| 首场 run-01 实际 470 TR（计划 464） | `volumes run=1 470` | decisions |
| 首场只有 2 个 reverse-PE 对 7 个 run | 该被试 `fmap_pairing nearest`，其余被试 `after` | decisions + project |
| 中断后重扫（`coco_run_02_rescan`；sub-06 run-01 只扫到 15 vol） | 同上：对不上协议的剔除；rescan 按帧数落到正确位置 | protocol |
| sub-07 只扫了 run-01 就终止 | 照转；run 号仍是 run-01（协议位置），缺 2–7 记为警告 | decisions（note） |
| sub-03 那场 2/7 run 可用，决定整场不要 | 不写进 mapping（原始 DICOM 保留）；编号不重排，数据集故意缺 sub-03 | mapping |
| 被试编号沿用扫描系统的 subject_code，与 nezha/andy/xiju 同号即同人 | mapping | mapping |
| 9-15 起生理记录统一 DICOM 模式 | `physio_mode` 逐 session 记录 | mapping |

决策的叙述性原因（为什么这么定、当时发现了什么）写在项目的 `code/decision_log.md`。
