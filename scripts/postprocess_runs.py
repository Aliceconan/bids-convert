#!/usr/bin/env python3
"""按扫描协议表剔废 run → 重编号 → 收敛 fmap IntendedFor。

和 `cleanup_aborted.py` 的分工：

| | cleanup_aborted.py | 本脚本 |
|---|---|---|
| 期望 volume 数 | 同 task **众数推断** | **必须显式给**（协议表） |
| 适用范式 | 等长（所有 run 一样长） | **变长**（各 run 本来就不等长） |
| IntendedFor | 不处理 | 收敛成 1:1 |

**变长范式下绝不能用众数推断。** 实测：coco 的 7 个 run 设计长度是
464/470/419/467/479/427/216，众数推断出 470，于是 216 vol 的 run-07 被判成
aborted —— 那是**删掉 4 个已入库被试的完好数据**。本脚本改为逐 run 与协议表
严格比对，对不上就停下不动任何文件。

IntendedFor 为什么也要修：dcm2bids 的 `"IntendedFor": ["bold"]` 是**累积**的，
fmap run-01 指向 1 个 bold、run-02 指向 2 个……run-07 指向 8 个。
实测 4 个已入库被试全是人工改成 1:1 的，这一步历来没有工具。

用法：
    # dry-run（默认）
    postprocess_runs.py <subject_dir> --task coco \\
        --expected 464,470,419,467,479,427,216

    # 确认后执行
    postprocess_runs.py <subject_dir> --task coco \\
        --expected 464,470,419,467,479,427,216 --apply

    # 数据集用 bids:: URI 风格时
    postprocess_runs.py ... --intendedfor-style uri

<subject_dir> 指到 `sub-XX` 或 `sub-XX/ses-YY`（有 session 层时）。
"""
import argparse
import gzip
import json
import re
import struct
import sys
from pathlib import Path


def n_vols(p):
    """从 .nii.gz 头部读第 4 维长度，不解压整个文件。"""
    with gzip.open(p, "rb") as f:
        hdr = f.read(352)
    dims = struct.unpack_from("<8h", hdr, 40)
    return dims[4] if dims[0] >= 4 else 1


def parse_args():
    ap = argparse.ArgumentParser(
        description="按协议表剔废 run、重编号、收敛 fmap IntendedFor")
    ap.add_argument("subject_dir", help="sub-XX 或 sub-XX/ses-YY")
    ap.add_argument("--task", required=True)
    ap.add_argument("--expected", required=True,
                    help="逐 run 期望 volume 数，逗号分隔，按 run 顺序。"
                         "必须来自扫描协议表，**不要从数据里推**")
    ap.add_argument("--intendedfor-style", choices=["relative", "uri", "keep"],
                    default="relative",
                    help="relative=func/sub-XX_..._bold.nii.gz（多数已有数据集用这个）；"
                         "uri=bids::sub-XX/func/...；keep=不动")
    ap.add_argument("--apply", action="store_true", help="不加则只 dry-run")
    return ap.parse_args()


def match_against_protocol(vols, expected):
    """从尾部向前逐个匹配协议表；多出来的就是废 run。

    从尾部匹配是因为废 run 通常紧跟着它的 rescan，而 rescan 在后。
    任何一个期望值找不到就整体失败——宁可不动，也不能删错。
    """
    remaining = list(vols)
    keep = []
    for want in reversed(expected):
        hit = None
        for i in range(len(remaining) - 1, -1, -1):
            if remaining[i][1] == want:
                hit = i
                break
        if hit is None:
            raise SystemExit(
                f"错误：协议表要求 {want} vol 的 run，实际数据里找不到。\n"
                f"  实际 volume 数：{[v for _f, v in vols]}\n"
                f"  协议表：{expected}\n"
                f"  **未做任何改动。** 先确认协议表是否对得上这个被试。")
        keep.append(remaining.pop(hit))
    keep.reverse()
    return keep, remaining


def main():
    a = parse_args()
    sd = Path(a.subject_dir)
    sub = next((p for p in sd.parts[::-1] if p.startswith("sub-")), sd.name)
    expected = [int(x) for x in a.expected.split(",") if x.strip()]

    bolds = sorted((sd / "func").glob(f"*_task-{a.task}_run-*_bold.nii.gz"))
    if not bolds:
        sys.exit(f"错误：{sd/'func'} 下没有 *_task-{a.task}_run-*_bold.nii.gz。\n"
                 f"  确认 subject_dir 与 --task 是否正确。未做任何改动。")

    vols = [(b, n_vols(b)) for b in bolds]
    print(f"=== {sd} / task-{a.task} ===")
    print(f"协议表期望 {len(expected)} 个 run: {expected}")
    print(f"实际 {len(vols)} 个 bold:")
    for b, v in vols:
        print(f"  {b.name:<50} {v:>5} vol")

    keep, drop = match_against_protocol(vols, expected)

    print(f"\n保留 {len(keep)} 个（与协议表逐一吻合）")
    print(f"删除 {len(drop)} 个:")
    for b, v in drop:
        print(f"  {b.name:<50} {v:>5} vol   ← 与协议表任何一个 run 都对不上")
    if not drop:
        print("  （无）")

    SUFFIXES = ("_bold.nii.gz", "_bold.json", "_sbref.nii.gz", "_sbref.json")

    for b, _v in drop:
        for suf in SUFFIXES:
            f = Path(str(b).replace("_bold.nii.gz", suf))
            if f.exists():
                print(f"  {'删除' if a.apply else '[dry] 将删除'}: {f.name}")
                if a.apply:
                    f.unlink()

    # ---- 重编号 ----
    print("\n=== 重编号 ===")
    renames = []
    for new_i, (b, _v) in enumerate(keep, start=1):
        old_run = re.search(r"_run-(\d+)_", b.name).group(1)
        if int(old_run) == new_i:
            continue
        for suf in SUFFIXES:
            old = Path(str(b).replace("_bold.nii.gz", suf))
            if old.exists():
                renames.append((old, old.parent / old.name.replace(
                    f"_run-{old_run}_", f"_run-{new_i:02d}_")))
    if not renames:
        print("  无需重编号")
    for old, new in renames:
        print(f"  {old.name} -> {new.name}")
    if a.apply and renames:
        # 两阶段改名：直接改会撞上尚未处理的源文件名
        staged = []
        for old, new in renames:
            t = old.parent / (old.name + ".tmprename")
            old.rename(t)
            staged.append((t, new))
        for t, new in staged:
            t.rename(new)

    # ---- fmap IntendedFor ----
    if a.intendedfor_style == "keep":
        print("\n=== fmap IntendedFor：按 --intendedfor-style keep 跳过 ===")
        print(f"\n{'已执行' if a.apply else 'dry-run 完成，加 --apply 执行'}")
        return

    print(f"\n=== fmap IntendedFor → 1:1（{a.intendedfor_style} 风格）===")
    fmaps = sorted((sd / "fmap").glob("*_epi.json")) if (sd / "fmap").exists() else []
    if not fmaps:
        print("  该被试没有 fmap/*_epi.json")
    n_func = len(keep)
    for j in fmaps:
        m = re.search(r"_run-(\d+)_", j.name)
        if not m:
            print(f"  {j.name}: 文件名里没有 run- 实体，跳过（需人工确认）")
            continue
        r = int(m.group(1))
        if r > n_func:
            print(f"  {j.name}: run-{r:02d} 没有对应的 func run（共 {n_func} 个），"
                  f"**留空，需人工确认**")
            target = None
        elif a.intendedfor_style == "uri":
            target = f"bids::{sub}/func/{sub}_task-{a.task}_run-{r:02d}_bold.nii.gz"
        else:
            target = f"func/{sub}_task-{a.task}_run-{r:02d}_bold.nii.gz"

        d = json.loads(j.read_text())
        before = d.get("IntendedFor")
        nb = len(before) if isinstance(before, list) else (1 if before else 0)
        d["IntendedFor"] = [target] if target else []
        print(f"  {j.name:<40} {nb} 条 -> {len(d['IntendedFor'])} 条  {target or '(空)'}")
        if a.apply:
            j.write_text(json.dumps(d, ensure_ascii=False, indent=2))

    print(f"\n{'已执行' if a.apply else 'dry-run 完成，加 --apply 执行'}")


if __name__ == "__main__":
    main()
