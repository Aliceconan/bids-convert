# 已知陷阱与解法

基于 4 个已完成项目（ODLoc / EYEDEP_CRF / MP_CRF / MonoDep）总结。

| # | 陷阱 | 频率 | 解法 |
|---|------|------|------|
| 1 | SeriesDescription 大小写不一致 | 4/4 | config 用 `any` 列出所有变体；按大小写不敏感处理 |
| 2 | 早期被试命名与后期完全不同 | 2/4 | 侦察必须包含最早日期被试 |
| 3 | Aborted run（1 vol 或部分 vol） | 4/4 | `scripts/validate.py` 检测 → `scripts/cleanup_aborted.py` 清理 |
| 4 | 重复结构像（同 session 扫两次 MP2RAGE） | 2/4 | 询问用户保留策略，不要默认假设 |
| 5 | fnmatch 区分大小写 | 4/4 | 显式列出所有大小写形式在 `any` 列表中 |
| 6 | Physio 路径不可预测 | 2/4 | `ls` 确认，不要猜路径或大小写 |
| 7 | 串行转换太慢 | 1/4 | 始终用 `scripts/convert_parallel.sh`（shell `&` + `wait`） |
| 8 | 重跑残留旧文件 | — | 重跑前 `rm -rf bids/sub-XX/ses-YY/`，保留 tmp；见 `convert_parallel.sh --rerun` |
| 9 | fmap 与 bold 的 SD 相同 | 3/4 | 加 `PhaseEncodingDirection` 区分（fmap 通常 PE 反向） |
| 10 | 隐私信息泄露 | 1/4 | `participants_mapping.tsv` 和 `participants.tsv` 不含原始 ID/姓名/年龄 |
| 11 | `--force_dcm2bids` 重跑太慢 | 1/4 | 仅修改匹配规则时不需要重跑 dcm2niix，去掉此 flag |
| 12 | Dummy TRs 被忽略 | 1/4 | 比较 `n_TRs × TR` 与刺激总时长，差值 = dummy + baseline |

## 详细说明

### #8 重跑残留旧文件（重要）

`dcm2bids` 重跑时 **不会清理上一次的 BIDS 输出**。如果修改 config 导致某些文件不再被匹配，旧文件会残留在 BIDS 目录中。

**错误做法：**
```bash
# 直接重跑 — 旧文件残留！
dcm2bids -d ... -p sub-01 -s ses-pre -c new_config.json -o bids
```

**正确做法：**
```bash
# 先清理该 session 的 BIDS 输出
rm -rf bids/sub-01/ses-pre/
# 再重跑（不加 --force_dcm2bids 以复用 tmp 中的 NIfTI）
dcm2bids -d ... -p sub-01 -s ses-pre -c new_config.json -o bids
```

`convert_parallel.sh --rerun` 已内置此逻辑。
