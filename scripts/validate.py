#!/usr/bin/env python3
"""
validate.py — 转换后核对（bids-validator 之前的项目级检查；bids-validator 查格式，这里查内容）

  1. 文件数（anat/func/fmap，每个 session）——给了 --expected-* 才判异常
  2. bold 帧数：有 protocol.tsv（--project）时逐 run 核对协议位置与帧数；没有协议表只列分布，
     **不从数据推期望值**（变长范式下「众数/最大值」必然误报，等长范式下也可能把好数据当废片）
  3. tmp_dcm2bids 里没匹配上的 series
  4. fmap IntendedFor：存在、目标文件存在、整个数据集写法统一（且与 config 的 bids_uri 一致）
  5. func sidecar 都有 TaskName（含根目录 task-X_bold.json 继承）
  6. 没有任何 fmap 指向的 bold（提示）

用法:
  python3 validate.py --project <project_dir> [--json --fail-on-anomaly]
  python3 validate.py <bids_dir> [--expected-anat 3 --expected-func 16 --expected-fmap 8]
  python3 validate.py <bids_dir> --volumes-only | --check-tmp | --check-intendedfor | --check-taskname
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402


def get_volumes(nii_path):
    return bc.nifti_volumes(nii_path)


def iter_session_dirs(bids_dir):
    """遍历所有 session 目录；没有 ses-* 层时 session 记为空串。"""
    for sub_dir in sorted(glob.glob(os.path.join(bids_dir, "sub-*"))):
        if not os.path.isdir(sub_dir):
            continue
        sub = os.path.basename(sub_dir)
        ses_dirs = sorted(d for d in glob.glob(os.path.join(sub_dir, "ses-*")) if os.path.isdir(d))
        if ses_dirs:
            for ses_dir in ses_dirs:
                yield sub, os.path.basename(ses_dir), ses_dir
        else:
            yield sub, "", sub_dir


def count_files(session_dir):
    return dict((dt, len(glob.glob(os.path.join(session_dir, dt, "*.nii*"))))
                for dt in ("anat", "func", "fmap"))


def validate_file_counts(bids_dir, expected):
    print("=== 文件数 ===\n")
    anomalies, sessions = [], []
    for sub, ses, d in iter_session_dirs(bids_dir):
        c = count_files(d)
        sessions.append({"subject": sub, "session": ses, "counts": c})
        bad = ["{}={}(期望{})".format(dt, c[dt], e) for dt, e in expected.items()
               if e is not None and c[dt] != e]
        for dt, e in expected.items():
            if e is not None and c[dt] != e:
                anomalies.append({"subject": sub, "session": ses, "datatype": dt,
                                  "actual": c[dt], "expected": e})
        print("  {} {}: anat={} func={} fmap={}{}".format(
            sub, ses, c["anat"], c["func"], c["fmap"], "  *** " + " ".join(bad) if bad else ""))
    print("\n" + ("发现 {} 个异常".format(len(anomalies)) if anomalies else "全部正常"))
    return {"sessions": sessions, "anomalies": anomalies}


def validate_volumes(bids_dir, protocol=None):
    """有协议表：逐 run 核对；没有：只汇报分布。"""
    print("=== bold 帧数 ===\n")
    runs, anomalies, warnings = [], [], []
    dist = defaultdict(lambda: defaultdict(int))
    for sub, ses, d in iter_session_dirs(bids_dir):
        present = defaultdict(set)
        for f in sorted(glob.glob(os.path.join(d, "func", "*_bold.nii*"))):
            name = os.path.basename(f)
            ents, _ = bc.parse_name(bc.split_image(name)[0])
            task = ents.get("task", "")
            vols = get_volumes(f)
            run = int(ents["run"]) if ents.get("run", "").isdigit() else None
            runs.append({"file": f, "name": name, "task": "task-" + task, "run": run, "volumes": vols})
            dist[task][vols] += 1
            if protocol is None:
                continue
            if task not in protocol:
                anomalies.append({"file": name, "problem": "protocol.tsv 没有 task-{}".format(task)})
                continue
            spec_runs = protocol[task]
            key = run if run is not None else (1 if len(spec_runs) == 1 else None)
            if key is None or key not in spec_runs:
                anomalies.append({"file": name, "problem": "run {} 不在协议表里".format(run)})
                print("  {}: {} vol  *** run 不在协议表里".format(name, vols))
                continue
            present[task].add(key)
            want, tol = spec_runs[key]
            if abs(vols - want) > tol:
                anomalies.append({"file": name, "problem": "{} vol，协议 {}±{}".format(vols, want, tol),
                                  "volumes": vols, "expected": want})
                print("  {}: {} vol  *** 协议 {}±{}（若是记录在案的例外，忽略）".format(name, vols, want, tol))
        if protocol:
            for task, got in present.items():
                miss = sorted(set(protocol[task]) - got)
                if miss:
                    warnings.append("{} {} task-{} 缺 run {}".format(sub, ses, task, miss))
    print("--- 分布 ---")
    for task, dd in sorted(dist.items()):
        print("  task-{}: ".format(task) + ", ".join("{} vol ×{}".format(v, n) for v, n in sorted(dd.items())))
    if protocol is None:
        print("  （没有协议表，不判异常。用 --project 读 code/protocol.tsv）")
    for w in warnings:
        print("  [warn] " + w)
    print("\n" + ("发现 {} 个异常".format(len(anomalies)) if anomalies else "未发现异常"))
    return {"runs": runs, "anomalies": anomalies, "warnings": warnings}


def check_tmp(bids_dir):
    tmp_dir = os.path.join(bids_dir, "tmp_dcm2bids")
    print("=== tmp 里未匹配的 series ===\n")
    if not os.path.isdir(tmp_dir):
        print("  tmp_dcm2bids 不存在")
        return {"sessions": [], "unmatched": []}
    unmatched, reports = [], []
    for ses_dir in sorted(glob.glob(os.path.join(tmp_dir, "*"))):
        if not os.path.isdir(ses_dir) or os.path.basename(ses_dir) == "log":
            continue
        meaningful = []
        for j in sorted(glob.glob(os.path.join(ses_dir, "*.json"))):
            try:
                sd = json.load(open(j)).get("SeriesDescription", "")
            except ValueError:
                continue
            if any(k in sd.lower() for k in ("localizer", "scout", "b1map", "physiolog")):
                continue
            meaningful.append((os.path.basename(j), sd))
        if meaningful:
            print("  {}: {} 个".format(os.path.basename(ses_dir), len(meaningful)))
            for _, sd in meaningful:
                print("    " + sd)
            reports.append({"session_tmp": os.path.basename(ses_dir), "count": len(meaningful),
                            "series": [{"file": n, "series_description": s} for n, s in meaningful]})
            unmatched.extend(meaningful)
    if not unmatched:
        print("  无")
    print("  （SBRef of reverse-PE、测试序列等本来就不进 BIDS 的会出现在这里，逐个确认即可）")
    return {"sessions": reports, "unmatched": unmatched}


def resolve_intended(bids_dir, sub_dir, target):
    if target.startswith("bids::"):
        return os.path.join(bids_dir, target[len("bids::"):])
    return os.path.join(sub_dir, target)


def check_intendedfor(bids_dir, style=None):
    """每个 fmap 都有非空 IntendedFor、目标都存在、写法统一。返回含 targeted（被指向的 bold）。"""
    print("=== fmap IntendedFor ===\n")
    anomalies, fmaps, styles, targeted = [], [], defaultdict(int), set()
    for sub, ses, d in iter_session_dirs(bids_dir):
        sub_dir = os.path.join(bids_dir, sub)
        for j in sorted(glob.glob(os.path.join(d, "fmap", "*.json"))):
            name = os.path.basename(j)
            try:
                meta = json.load(open(j))
            except ValueError as e:
                anomalies.append({"fmap": name, "problem": "json 读取失败: {}".format(e)})
                continue
            ifor = meta.get("IntendedFor")
            targets = [] if ifor is None else ([ifor] if isinstance(ifor, str) else list(ifor))
            missing = [t for t in targets if not os.path.exists(resolve_intended(bids_dir, sub_dir, t))]
            for t in targets:
                styles["URI" if t.startswith("bids::") else "relative"] += 1
                targeted.add(os.path.normpath(resolve_intended(bids_dir, sub_dir, t)))
            fmaps.append({"subject": sub, "session": ses, "fmap": name,
                          "n_targets": len(targets), "missing_targets": missing})
            if not targets:
                anomalies.append({"subject": sub, "session": ses, "fmap": name, "problem": "没有 IntendedFor"})
                print("  {}: *** 没有 IntendedFor".format(name))
            elif missing:
                anomalies.append({"subject": sub, "session": ses, "fmap": name,
                                  "problem": "{} 个目标不存在".format(len(missing)), "missing": missing})
                print("  {}: *** {} 个目标不存在: {}".format(name, len(missing), missing[:2]))
    if len(styles) > 1:
        anomalies.append({"problem": "IntendedFor 写法混用：{}".format(dict(styles))})
        print("  *** 写法混用 {} —— 同一数据集应统一（自己写的脚本拼路径时会踩坑）".format(dict(styles)))
    elif style and styles and list(styles)[0] != style:
        anomalies.append({"problem": "IntendedFor 写法是 {}，config 声明 bids_uri={}".format(list(styles)[0], style)})
        print("  *** 写法 {} 与 config 的 bids_uri={} 不一致".format(list(styles)[0], style))
    if not fmaps:
        print("  没有 fmap")
    elif anomalies:
        print("\n发现 {} 个异常".format(len(anomalies)))
        if sum(a.get("problem") == "没有 IntendedFor" for a in anomalies) == len(fmaps):
            print("  全部 fmap 都没有 IntendedFor —— 多半是 config 用了顶层 intended_for（dcm2bids 3.x 静默忽略），"
                  "或 project.json 的 fmap_pairing=none")
    else:
        print("{} 个 fmap 全部正常（写法 {}）".format(len(fmaps), "/".join(styles) or "-"))
    return {"fmaps": fmaps, "anomalies": anomalies, "targeted": sorted(targeted)}


def check_taskname(bids_dir):
    print("=== TaskName ===\n")
    inherited = {}
    for p in glob.glob(os.path.join(bids_dir, "task-*_bold.json")):
        m = re.match(r"task-([^_]+)_", os.path.basename(p))
        try:
            if m and json.load(open(p)).get("TaskName"):
                inherited[m.group(1)] = json.load(open(p))["TaskName"]
        except ValueError:
            pass
    anomalies = []
    n = 0
    for sub, ses, d in iter_session_dirs(bids_dir):
        for j in sorted(glob.glob(os.path.join(d, "func", "*.json"))):
            name = os.path.basename(j)
            if "_physio" in name or "_events" in name:
                continue
            ents, suffix = bc.parse_name(name[: -len(".json")])
            if suffix not in ("bold", "sbref", "cbv", "phase"):
                continue
            n += 1
            tn = json.load(open(j)).get("TaskName") or inherited.get(ents.get("task"))
            if not tn:
                anomalies.append({"file": name, "problem": "缺 TaskName"})
            elif tn != ents.get("task"):
                anomalies.append({"file": name, "problem": "TaskName={!r} ≠ task-{}".format(tn, ents.get("task"))})
    if anomalies:
        print("  {} / {} 个 func sidecar 有问题，例如 {}".format(len(anomalies), n, anomalies[0]))
        print("  （config 的 func 条目在 sidecar_changes 里写 TaskName；finalize.py 也会补）")
    else:
        print("  {} 个 func sidecar 都有 TaskName".format(n))
    return {"anomalies": anomalies}


def bolds_without_fmap(bids_dir, targeted):
    out = []
    for sub, ses, d in iter_session_dirs(bids_dir):
        if not glob.glob(os.path.join(d, "fmap", "*.json")):
            continue
        for f in sorted(glob.glob(os.path.join(d, "func", "*_bold.nii*"))):
            if os.path.normpath(f) not in targeted:
                out.append(os.path.basename(f))
    if out:
        print("\n[提示] {} 个 bold 没有任何 fmap 指向：{}".format(len(out), out[:5]))
    return out


def main():
    ap = argparse.ArgumentParser(description="转换后核对")
    ap.add_argument("bids_dir", nargs="?")
    ap.add_argument("--project", help="项目目录：读 protocol.tsv、config 的 bids_uri、bids_dir")
    ap.add_argument("--expected-anat", type=int)
    ap.add_argument("--expected-func", type=int)
    ap.add_argument("--expected-fmap", type=int)
    ap.add_argument("--volumes-only", action="store_true")
    ap.add_argument("--check-tmp", action="store_true")
    ap.add_argument("--check-intendedfor", action="store_true")
    ap.add_argument("--check-taskname", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-anomaly", action="store_true")
    a = ap.parse_args()

    protocol, style, bids_dir = None, None, a.bids_dir
    if a.project:
        try:
            spec = bc.load_project(a.project)
            protocol = bc.load_protocol(spec) or None
            style = bc.load_config(spec).get("bids_uri", "URI")
        except bc.SpecError as e:
            sys.exit("错误：{}".format(e))
        bids_dir = bids_dir or str(spec["bids_dir"])
    if not bids_dir:
        sys.exit("给 bids_dir 或 --project")

    payload = {}
    single = a.volumes_only or a.check_tmp or a.check_intendedfor or a.check_taskname
    if not single or a.volumes_only:
        payload["volumes"] = validate_volumes(bids_dir, protocol)
        print()
    if not single or a.check_tmp:
        payload["tmp"] = check_tmp(bids_dir)
        print()
    if not single or a.check_intendedfor:
        payload["intendedfor"] = check_intendedfor(bids_dir, style)
        print()
    if not single or a.check_taskname:
        payload["taskname"] = check_taskname(bids_dir)
        print()
    if not single:
        payload["file_counts"] = validate_file_counts(
            bids_dir, {"anat": a.expected_anat, "func": a.expected_func, "fmap": a.expected_fmap})
        payload["bolds_without_fmap"] = bolds_without_fmap(bids_dir, set(payload["intendedfor"]["targeted"]))

    summary = {
        "file_count_anomalies": len(payload.get("file_counts", {}).get("anomalies", [])),
        "volume_anomalies": len(payload.get("volumes", {}).get("anomalies", [])),
        "tmp_unmatched": len(payload.get("tmp", {}).get("unmatched", [])),
        "intendedfor_anomalies": len(payload.get("intendedfor", {}).get("anomalies", [])),
        "taskname_anomalies": len(payload.get("taskname", {}).get("anomalies", [])),
        "bold_runs_checked": len(payload.get("volumes", {}).get("runs", [])),
    }
    if a.json:
        payload["summary"] = summary
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    # tmp 里本来就有不进 BIDS 的 series，不算失败
    bad = [k for k in ("file_count_anomalies", "volume_anomalies", "intendedfor_anomalies",
                       "taskname_anomalies") if summary[k]]
    if a.fail_on_anomaly and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
