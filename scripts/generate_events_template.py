#!/usr/bin/env python3
"""
generate_events_template.py — events.tsv 生成框架

这是一个模板，每个项目需要根据实际范式修改 TASK_DESIGNS 部分。
框架部分（文件遍历、写入、时间校验）是通用的。

用法:
  1. 复制此文件到 <project>/code/generate_events.py
  2. 修改 TASK_DESIGNS 为项目实际范式
  3. 运行: python3 generate_events.py <bids_dir>

标志:
  --dry-run    只显示将生成哪些文件，不实际写入
  --verify     校验 TR 数 × TR 时长 vs 范式总时长
"""

import argparse
import glob
import gzip
import json
import os
import struct
import sys

# =============================================
# ★★★ 项目特定部分 — 修改此处 ★★★
# =============================================

TASK_DESIGNS = {
    # 每个 task 定义一组 run
    # key = BIDS task label (不含 "task-" 前缀)
    "example": {
        "runs": [
            {
                # run-01 的事件定义
                # key = trial_type, value = onset 列表（秒）
                "ConditionA": [0.0, 30.0, 60.0],
                "ConditionB": [15.0, 45.0, 75.0],
            },
            {
                # run-02 ...
                "ConditionA": [15.0, 45.0, 75.0],
                "ConditionB": [0.0, 30.0, 60.0],
            },
        ],
        "block_duration": 15.0,  # 每个 block 的持续时间（秒）
    },
}

# =============================================
# 通用框架 — 通常不需要修改
# =============================================


def get_volumes(nii_path):
    with gzip.open(nii_path, "rb") as f:
        hdr = f.read(352)
    dims = struct.unpack_from("<8h", hdr, 40)
    return dims[4] if dims[0] >= 4 else 1


def get_tr(json_path):
    """从 sidecar JSON 读取 TR"""
    if os.path.exists(json_path):
        with open(json_path) as f:
            d = json.load(f)
        return d.get("RepetitionTime")
    return None


def write_events_tsv(filepath, events):
    """写入 BIDS events.tsv"""
    cols = ["onset", "duration", "trial_type"]
    with open(filepath, "w") as f:
        f.write("\t".join(cols) + "\n")
        for e in sorted(events, key=lambda x: x["onset"]):
            f.write(f"{e['onset']}\t{e['duration']}\t{e['trial_type']}\n")


def generate_events(run_def, block_dur):
    """从 run 定义生成事件列表"""
    events = []
    for trial_type, onsets in run_def.items():
        for onset in onsets:
            events.append({
                "onset": float(onset),
                "duration": block_dur,
                "trial_type": trial_type,
            })
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bids_dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true",
                        help="校验扫描时长 vs 范式时长")
    args = parser.parse_args()

    bids_dir = args.bids_dir
    n_written = 0
    warnings = []

    for sub_dir in sorted(glob.glob(os.path.join(bids_dir, "sub-*"))):
        sub = os.path.basename(sub_dir)
        for ses_dir in sorted(glob.glob(os.path.join(sub_dir, "ses-*"))):
            ses = os.path.basename(ses_dir)
            func_dir = os.path.join(ses_dir, "func")
            if not os.path.isdir(func_dir):
                continue

            for task_name, design in TASK_DESIGNS.items():
                for run_idx, run_def in enumerate(design["runs"], start=1):
                    bold = os.path.join(
                        func_dir,
                        f"{sub}_{ses}_task-{task_name}_run-{run_idx:02d}_bold.nii.gz"
                    )
                    if not os.path.exists(bold):
                        continue

                    fname = f"{sub}_{ses}_task-{task_name}_run-{run_idx:02d}_events.tsv"
                    fpath = os.path.join(func_dir, fname)

                    # 可选: 时间校验
                    if args.verify:
                        tr = get_tr(bold.replace(".nii.gz", ".json"))
                        vols = get_volumes(bold)
                        if tr:
                            scan_dur = vols * tr
                            max_onset = max(
                                o for onsets in run_def.values() for o in onsets
                            )
                            stim_end = max_onset + design["block_duration"]
                            if scan_dur < stim_end:
                                msg = f"  警告: {fname}: 扫描{scan_dur:.1f}s < 范式{stim_end:.1f}s"
                                warnings.append(msg)
                                print(msg)

                    events = generate_events(run_def, design["block_duration"])

                    if args.dry_run:
                        print(f"  [dry-run] {fname}")
                    else:
                        write_events_tsv(fpath, events)
                        print(f"  wrote: {fname}")
                        n_written += 1

    if not args.dry_run:
        print(f"\n完成: {n_written} 个 events.tsv")
    if warnings:
        print(f"\n{len(warnings)} 个时间校验警告")


if __name__ == "__main__":
    main()
