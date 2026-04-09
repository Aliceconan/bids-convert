# MP2RAGE 序列配置速查

MP2RAGE 是最复杂的 anat 序列。不同项目可能只有其中的子集。

## 输出对照表

| 输出 | BIDS suffix | BIDS entities | criteria SeriesDescription | criteria ImageType | 出现项目 |
|------|-------------|---------------|---------------------------|-------------------|---------|
| INV1 magnitude ND | MP2RAGE | inv-1_rec-ND | `*INV1_ND` | — | ODLoc, MP_CRF, MonoDep |
| INV1 magnitude DIS2D | MP2RAGE | inv-1_rec-DIS2D | `*INV1` | ∋ DIS2D, MAGNITUDE | ODLoc, MP_CRF, MonoDep |
| INV2 magnitude ND | MP2RAGE | inv-2_rec-ND | `*INV2_ND` | — | 同上 |
| INV2 magnitude DIS2D | MP2RAGE | inv-2_rec-DIS2D | `*INV2` | ∋ DIS2D, MAGNITUDE | 同上 |
| UNI | UNIT1 | — | `*UNI_Images` | — | 全部 4 项目 |
| T1map | T1map | — | `*T1_Images` | — | ODLoc, MP_CRF, MonoDep |
| DIV | MP2RAGE | rec-DIV | `*DIV_Images` | — | ODLoc, MP_CRF, MonoDep |
| INV1 phase ND | MP2RAGE | inv-1_part-phase_rec-ND | `*INV1_PHS_FILT_ND` | — | MP_CRF |
| INV1 phase DIS2D | MP2RAGE | inv-1_part-phase_rec-DIS2D | `*INV1_PHS_FILT` | ∋ DIS2D, PHASE | MP_CRF |
| INV2 phase ND | MP2RAGE | inv-2_part-phase_rec-ND | `*INV2_PHS_FILT_ND` | — | MP_CRF |
| INV2 phase DIS2D | MP2RAGE | inv-2_part-phase_rec-DIS2D | `*INV2_PHS_FILT` | ∋ DIS2D, PHASE | MP_CRF |

## 常见子集

| 配置 | 输出数 | 项目 |
|------|--------|------|
| 全输出（无 phase） | 7 | ODLoc, MonoDep |
| 全输出 + phase | 11 | MP_CRF |
| 仅 INV1 + INV2 + UNI | 3 | EYEDEP_CRF |

## 使用方式

`templates/dcm2bids_config_mp2rage.json` 包含全部 11 种输出的配置。按侦察结果选择需要的条目复制到项目 config 中。

## 注意事项

- ND = No Distortion correction（原始重建）
- DIS2D = 2D Distortion correction
- INV1 和 INV2 的 magnitude 都有 ND 和 DIS2D 两种，用 `ImageType` 中的 `DIS2D` 区分
- Phase 数据（PHS_FILT）不是所有项目都有，侦察时确认
- 如果同 session 扫了两次 MP2RAGE，需要询问用户保留哪一个
