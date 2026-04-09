#!/usr/bin/env python3
"""
validate.py — 验证 BIDS 转换结果

功能:
  1. 文件数核对（anat/func/fmap 每个 session）
  2. Volume 检查（func bold 的 TR 数）
  3. 检测 tmp 中未匹配的文件

用法:
  python3 validate.py <bids_dir> [--expected-anat 7] [--expected-func 7] [--expected-fmap 7]
  python3 validate.py <bids_dir> --volumes-only
  python3 validate.py <bids_dir> --check-tmp
"""

import argparse
import glob
import gzip
import json
import os
import struct
import sys
from collections import defaultdict


def get_volumes(nii_path):
    """读取 NIfTI header 获取 volume 数（不依赖 nibabel）"""
    with gzip.open(nii_path, "rb") as f:
        hdr = f.read(352)
    dims = struct.unpack_from("<8h", hdr, 40)
    return dims[4] if dims[0] >= 4 else 1


def iter_session_dirs(bids_dir):
    """遍历所有 session 目录；若无 ses-* 层，则兼容单 session 结构。"""
    for sub_dir in sorted(glob.glob(os.path.join(bids_dir, "sub-*"))):
        sub = os.path.basename(sub_dir)
        ses_dirs = sorted(glob.glob(os.path.join(sub_dir, "ses-*")))
        if ses_dirs:
            for ses_dir in ses_dirs:
                yield sub, os.path.basename(ses_dir), ses_dir
        else:
            yield sub, "ses-01", sub_dir


def count_files(session_dir):
    """统计 session 下各 datatype 的 .nii.gz 文件数"""
    counts = {}
    for dtype in ["anat", "func", "fmap"]:
        dtype_dir = os.path.join(session_dir, dtype)
        if os.path.isdir(dtype_dir):
            counts[dtype] = len(glob.glob(os.path.join(dtype_dir, "*.nii.gz")))
        else:
            counts[dtype] = 0
    return counts


def validate_file_counts(bids_dir, expected):
    """检查每个 session 的文件数是否符合期望"""
    print("=== 文件数核对 ===\n")
    anomalies = []
    sessions = []

    for sub, ses, ses_dir in iter_session_dirs(bids_dir):
        counts = count_files(ses_dir)
        sessions.append({"subject": sub, "session": ses, "counts": counts})
        status = ""
        for dtype, exp in expected.items():
            actual = counts.get(dtype, 0)
            if exp is not None and actual != exp:
                status += f" {dtype}={actual}(期望{exp})"
                anomalies.append({
                    "subject": sub,
                    "session": ses,
                    "datatype": dtype,
                    "actual": actual,
                    "expected": exp,
                })

        line = f"  {sub} {ses}: anat={counts['anat']} func={counts['func']} fmap={counts['fmap']}"
        if status:
            line += f"  *** 异常:{status}"
        print(line)

    if anomalies:
        print(f"\n发现 {len(anomalies)} 个异常")
    else:
        print("\n全部正常")
    return {"sessions": sessions, "anomalies": anomalies}


def validate_volumes(bids_dir):
    """检查所有 bold 文件的 volume 数"""
    print("=== Volume 检查 ===\n")
    results = defaultdict(set)
    runs = []

    for f in sorted(glob.glob(os.path.join(bids_dir, "sub-*/ses-*/func/*bold.nii.gz"))):
        vols = get_volumes(f)
        name = os.path.basename(f)
        print(f"  {name}: {vols} vols")

        # 按 task 分组收集 volume 数
        parts = name.split("_")
        task = [p for p in parts if p.startswith("task-")]
        if task:
            task_name = task[0]
            results[task_name].add(vols)
            runs.append({"file": f, "name": name, "task": task_name, "volumes": vols})

    # 汇总每个 task 的 volume 分布
    print("\n--- 按 task 汇总 ---")
    anomaly_runs = []
    for task, vol_set in sorted(results.items()):
        if len(vol_set) == 1:
            expected = sorted(vol_set)[0]
            print(f"  {task}: {expected} vols (一致)")
        else:
            expected = max(vol_set)
            bad = sorted(v for v in vol_set if v != expected)
            print(f"  {task}: 期望 {expected} vols, 异常值 {bad}")
            anomaly_runs.append({
                "task": task,
                "expected": expected,
                "observed_outliers": bad,
            })

    return {"runs": runs, "anomalies": anomaly_runs}


def check_tmp(bids_dir):
    """检查 tmp_dcm2bids 中是否有未匹配的文件"""
    tmp_dir = os.path.join(bids_dir, "tmp_dcm2bids")
    if not os.path.isdir(tmp_dir):
        print("=== tmp 检查 ===\n  tmp_dcm2bids 不存在（已清理）")
        return {"sessions": [], "unmatched": []}

    print("=== tmp 未匹配文件 ===\n")
    unmatched = []
    session_reports = []

    for ses_dir in sorted(glob.glob(os.path.join(tmp_dir, "*"))):
        if not os.path.isdir(ses_dir) or os.path.basename(ses_dir) == "log":
            continue
        jsons = sorted(glob.glob(os.path.join(ses_dir, "*.json")))
        ses_name = os.path.basename(ses_dir)

        # 忽略 localizer 和 b1map（这些通常不纳入 BIDS）
        meaningful = []
        for j in jsons:
            try:
                d = json.load(open(j))
                sd = d.get("SeriesDescription", "")
                # 跳过常见的非目标序列
                if any(skip in sd.lower() for skip in ["localizer", "b1map", "scout"]):
                    continue
                meaningful.append((os.path.basename(j), sd))
            except Exception:
                continue

        if meaningful:
            print(f"  {ses_name}: {len(meaningful)} 个未匹配文件")
            for name, sd in meaningful:
                print(f"    {sd}")
            session_reports.append({
                "session_tmp": ses_name,
                "count": len(meaningful),
                "series": [{"file": name, "series_description": sd} for name, sd in meaningful],
            })
            unmatched.extend(meaningful)

    if not unmatched:
        print("  无有意义的未匹配文件")
    return {"sessions": session_reports, "unmatched": unmatched}


def build_summary(file_counts, volumes, tmp_report):
    return {
        "file_count_anomalies": len(file_counts["anomalies"]),
        "volume_anomalies": len(volumes["anomalies"]),
        "tmp_unmatched": len(tmp_report["unmatched"]),
        "sessions_checked": len(file_counts["sessions"]),
        "bold_runs_checked": len(volumes["runs"]),
    }


def main():
    parser = argparse.ArgumentParser(description="验证 BIDS 转换结果")
    parser.add_argument("bids_dir", help="BIDS 输出目录")
    parser.add_argument("--expected-anat", type=int, default=None, help="期望的 anat 文件数")
    parser.add_argument("--expected-func", type=int, default=None, help="期望的 func 文件数")
    parser.add_argument("--expected-fmap", type=int, default=None, help="期望的 fmap 文件数")
    parser.add_argument("--volumes-only", action="store_true", help="只检查 volumes")
    parser.add_argument("--check-tmp", action="store_true", help="只检查 tmp 未匹配文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要到 stdout")
    parser.add_argument("--fail-on-anomaly", action="store_true",
                        help="发现任何异常时返回退出码 1")
    args = parser.parse_args()

    if args.volumes_only:
        volumes = validate_volumes(args.bids_dir)
        summary = {
            "file_count_anomalies": 0,
            "volume_anomalies": len(volumes["anomalies"]),
            "tmp_unmatched": 0,
            "sessions_checked": 0,
            "bold_runs_checked": len(volumes["runs"]),
        }
        if args.json:
            print(json.dumps({"summary": summary, "volumes": volumes}, ensure_ascii=False, indent=2))
        if args.fail_on_anomaly and summary["volume_anomalies"] > 0:
            sys.exit(1)
        return

    if args.check_tmp:
        tmp_report = check_tmp(args.bids_dir)
        summary = {
            "file_count_anomalies": 0,
            "volume_anomalies": 0,
            "tmp_unmatched": len(tmp_report["unmatched"]),
            "sessions_checked": 0,
            "bold_runs_checked": 0,
        }
        if args.json:
            print(json.dumps({"summary": summary, "tmp": tmp_report}, ensure_ascii=False, indent=2))
        if args.fail_on_anomaly and summary["tmp_unmatched"] > 0:
            sys.exit(1)
        return

    # 完整验证
    expected = {
        "anat": args.expected_anat,
        "func": args.expected_func,
        "fmap": args.expected_fmap,
    }
    file_counts = validate_file_counts(args.bids_dir, expected)
    print()
    volumes = validate_volumes(args.bids_dir)
    print()
    tmp_report = check_tmp(args.bids_dir)

    summary = build_summary(file_counts, volumes, tmp_report)
    if args.json:
        payload = {
            "summary": summary,
            "file_counts": file_counts,
            "volumes": volumes,
            "tmp": tmp_report,
        }
        print()
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.fail_on_anomaly and any(summary[key] > 0 for key in [
        "file_count_anomalies", "volume_anomalies", "tmp_unmatched"
    ]):
        sys.exit(1)


if __name__ == "__main__":
    main()
