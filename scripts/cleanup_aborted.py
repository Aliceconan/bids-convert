#!/usr/bin/env python3
"""
cleanup_aborted.py — 检测并清理 aborted run，然后重编号

功能:
  1. 扫描所有 bold 文件，检测 volume 数异常的 run
  2. 交互式确认删除（或 --auto 模式自动删除 1-vol 文件）
  3. 删除后自动重编号使 run 连续

用法:
  python3 cleanup_aborted.py <bids_dir>                    # 交互模式
  python3 cleanup_aborted.py <bids_dir> --auto             # 自动删除 1-vol run
  python3 cleanup_aborted.py <bids_dir> --threshold 0.5    # 删除 < 50% 期望值的 run
  python3 cleanup_aborted.py <bids_dir> --dry-run          # 只报告，不删除
"""

import argparse
import glob
import gzip
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict


def get_volumes(nii_path):
    with gzip.open(nii_path, "rb") as f:
        hdr = f.read(352)
    dims = struct.unpack_from("<8h", hdr, 40)
    return dims[4] if dims[0] >= 4 else 1


def find_aborted_runs(bids_dir, threshold_ratio):
    """找出 volume 异常的 bold run"""
    # 按 task 收集所有 volume 数
    task_volumes = defaultdict(list)
    all_runs = []

    for f in sorted(glob.glob(os.path.join(bids_dir, "sub-*/ses-*/func/*bold.nii.gz"))):
        vols = get_volumes(f)
        name = os.path.basename(f)
        parts = name.split("_")
        task_parts = [p for p in parts if p.startswith("task-")]
        if not task_parts:
            continue
        task = task_parts[0]
        task_volumes[task].append(vols)
        all_runs.append({"path": f, "name": name, "vols": vols, "task": task})

    # 确定每个 task 的期望 volume 数（众数）
    task_expected = {}
    for task, vol_list in task_volumes.items():
        task_expected[task] = Counter(vol_list).most_common(1)[0][0]

    # 标记 aborted
    aborted = []
    for run in all_runs:
        expected = task_expected[run["task"]]
        if run["vols"] < expected * threshold_ratio:
            run["expected"] = expected
            aborted.append(run)

    return aborted, task_expected


def delete_run(nii_path, dry_run=False):
    """删除 bold run 的 .nii.gz 和 .json"""
    json_path = nii_path.replace(".nii.gz", ".json")
    events_path = nii_path.replace("_bold.nii.gz", "_events.tsv")
    deleted = []

    for f in [nii_path, json_path, events_path]:
        if os.path.exists(f):
            if dry_run:
                print(f"  [dry-run] 将删除: {os.path.basename(f)}")
            else:
                os.remove(f)
                print(f"  删除: {os.path.basename(f)}")
            deleted.append(f)
    return deleted


def renumber_runs(func_dir, task, dry_run=False):
    """对指定 func_dir 中的 task 的 run 重编号"""
    pattern = os.path.join(func_dir, f"*{task}_run-*")
    files = sorted(glob.glob(pattern))
    if not files:
        return

    # 按 run 号分组
    runs = defaultdict(list)
    for f in files:
        match = re.search(r"run-(\d+)", os.path.basename(f))
        if match:
            runs[match.group(0)].append(f)

    sorted_runs = sorted(runs.keys())
    expected = [f"run-{i+1:02d}" for i in range(len(sorted_runs))]

    if sorted_runs == expected:
        return []  # 已经连续

    # 两步重命名防冲突
    temp_renames = []
    final_renames = []
    for old_run, new_run in zip(sorted_runs, expected):
        if old_run == new_run:
            continue
        for f in runs[old_run]:
            temp = f.replace(old_run, new_run + "_TEMP")
            if dry_run:
                print(f"  [dry-run] 重命名: {os.path.basename(f)} → ...{new_run}...")
            else:
                os.rename(f, temp)
            temp_renames.append((temp, temp.replace(new_run + "_TEMP", new_run)))
            final_renames.append({"from": f, "to": temp.replace(new_run + "_TEMP", new_run)})

    if not dry_run:
        for temp, final in temp_renames:
            os.rename(temp, final)
    return final_renames


def main():
    parser = argparse.ArgumentParser(description="清理 aborted run 并重编号")
    parser.add_argument("bids_dir")
    parser.add_argument("--auto", action="store_true", help="自动删除 1-vol run")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="删除 volume < 期望值 × threshold 的 run (默认 0.5)")
    parser.add_argument("--dry-run", action="store_true", help="只报告不执行")
    parser.add_argument("--yes", action="store_true", help="非交互模式下确认执行删除")
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要到 stdout")
    parser.add_argument("--fail-if-found", action="store_true",
                        help="只要发现 aborted run 就返回退出码 1")
    args = parser.parse_args()

    aborted, task_expected = find_aborted_runs(args.bids_dir, args.threshold)

    print("=== 期望 volume 数 ===")
    for task, exp in sorted(task_expected.items()):
        print(f"  {task}: {exp} vols")

    if not aborted:
        print("\n未发现 aborted run")
        if args.json:
            print(json.dumps({
                "summary": {
                    "aborted_found": 0,
                    "deleted_files": 0,
                    "renamed_files": 0,
                    "dry_run": args.dry_run,
                },
                "expected_volumes": task_expected,
                "aborted_runs": [],
                "renames": [],
            }, ensure_ascii=False, indent=2))
        return

    print(f"\n=== 发现 {len(aborted)} 个 aborted run ===\n")
    for run in aborted:
        print(f"  {run['name']}: {run['vols']} vols (期望 {run['expected']})")

    if not args.auto and not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            print("\n错误: 当前是非交互环境；请改用 --yes、--auto 或 --dry-run", file=sys.stderr)
            sys.exit(2)
        confirm = input("\n确认删除以上文件并重编号? [y/N] ")
        if confirm.lower() != "y":
            print("取消")
            return

    # 收集需要重编号的 (func_dir, task) 对
    renumber_targets = set()
    deleted_files = []
    renames = []

    for run in aborted:
        deleted_files.extend(delete_run(run["path"], dry_run=args.dry_run))
        func_dir = os.path.dirname(run["path"])
        renumber_targets.add((func_dir, run["task"]))

    print("\n=== 重编号 ===")
    for func_dir, task in sorted(renumber_targets):
        ses_label = os.path.basename(os.path.dirname(func_dir))
        sub_label = os.path.basename(os.path.dirname(os.path.dirname(func_dir)))
        print(f"\n  {sub_label}/{ses_label} {task}:")
        renames.extend(renumber_runs(func_dir, task, dry_run=args.dry_run))

    print("\n=== 完成 ===")

    if args.json:
        print(json.dumps({
            "summary": {
                "aborted_found": len(aborted),
                "deleted_files": len(deleted_files),
                "renamed_files": len(renames),
                "dry_run": args.dry_run,
            },
            "expected_volumes": task_expected,
            "aborted_runs": aborted,
            "renames": renames,
        }, ensure_ascii=False, indent=2))

    if args.fail_if_found:
        sys.exit(1)


if __name__ == "__main__":
    main()
