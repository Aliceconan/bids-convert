#!/usr/bin/env python3
"""preview.py — 不转换任何影像，预演 config + finalize 在每个 session 上的结果。

输入是 scout.py 的产物（每个 series 一个 sidecar）。为每个 series 造一个只有头的占位
NIfTI（mosaic EPI 的 volume 数 = 文件数），放进 dcm2bids 的 tmp 目录，然后：
  1. 调用**真正的 dcm2bids** 做匹配（它看到 tmp 非空就跳过 dcm2niix）——匹配逻辑与正式转换
     是同一份代码，不是重新实现的近似；
  2. 对预演结果跑 finalize 的计划（不执行）。

几秒一个 session。转换前就能看到：每个 series 会变成哪个文件、哪些没匹配上、
哪些同时匹配了多条规则、哪些 session 还需要人工决定（多出来的 bold、重复结构像……）。
把这些都解决（改 config / 写 decisions.tsv）之后再跑 convert.py。

局限：非 mosaic 的多文件 EPI（每层一个文件）无法从文件数推 volume 数，预演里按 3D 处理。

用法：
  python3 preview.py <project_dir> [--only sub-01 …] [--show-all]
退出码：0 全部无事项；2 有 session 需要决定或有 series 匹配冲突
"""
import argparse
import gzip
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402
import finalize  # noqa: E402
import lint_config  # noqa: E402


def placeholder(path, vols):
    hdr = bytearray(352)
    struct.pack_into("<i", hdr, 0, 348)
    if vols > 1:
        struct.pack_into("<8h", hdr, 40, 4, 2, 2, 2, vols, 1, 1, 1)
    else:
        struct.pack_into("<8h", hdr, 40, 3, 2, 2, 2, 1, 1, 1, 1)
    with gzip.open(str(path), "wb") as f:
        f.write(bytes(hdr))


def preview_session(spec, row, root, show_all):
    prefix = bc.prefix_of(row["sub"], row["ses"])
    scout = Path(spec["work_dir"]) / "scout" / prefix
    series = bc.read_tsv(scout / "series.tsv")
    if not series:
        print("===== {}: 没有侦察结果（先跑 scout.py）".format(prefix))
        return "no_scout"
    bids = root / "bids"
    tmp = bids / "tmp_dcm2bids" / prefix
    for d in (tmp, bc.session_dir(dict(spec, bids_dir=bids), row["sub"], row["ses"])):
        if d.exists():
            shutil.rmtree(str(d))
    tmp.mkdir(parents=True)
    by_stem = {}
    for s in series:
        if not s.get("json"):
            continue
        stem = "{:03d}_{}".format(int(s["idx"]), re.sub(r"[^\w.-]", "_", s["SeriesDescription"]))
        shutil.copy2(s["json"], str(tmp / (stem + ".json")))
        vols = int(s["n_files"]) if "MOSAIC" in s["ImageType"].upper() else 1
        placeholder(tmp / (stem + ".nii.gz"), vols)
        by_stem[stem] = s
    log = root / "logs" / "{}.log".format(prefix)
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [spec["dcm2bids"], "-d", str(scout), "-p", row["sub"][4:], "-c", str(spec["config_path"]),
           "-o", str(bids), "-l", "INFO"]
    if row["ses"]:
        cmd[5:5] = ["-s", row["ses"][4:]]
    with open(str(log), "w") as f:
        rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT)
    target, several = {}, set()
    for line in log.read_text(errors="replace").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if "<-" not in line:
            continue
        left, src = [x.strip() for x in line.split("<-", 1)]
        if "Several Pairing" in left:
            several.add(src)
        elif "No Pairing" in left:
            target.setdefault(src, None)
        else:
            target[src] = left.split("|")[-1].strip()

    print("===== {}  ({} series)".format(prefix, len(series)))
    if rc != 0:
        print("  !! dcm2bids 退出码 {}，见 {}".format(rc, log))
    for stem, s in by_stem.items():
        t = target.get(stem)
        if stem in several:
            mark = "!! 同时匹配多条规则（dcm2bids 会跳过）"
        elif t:
            mark = "→ " + t
        else:
            if not show_all and ("PHYSIO" in s["ImageType"].upper() or "scout" in s["SeriesDescription"].lower()):
                continue
            mark = "  （不进 BIDS）"
        print("  SN{:<4} n={:<5} {:<36} {}".format(s["SeriesNumber"], s["n_files"], s["SeriesDescription"][:36], mark))
    status, plan = "ok", None
    if bc.session_dir(dict(spec, bids_dir=bids), row["sub"], row["ses"]).is_dir():
        plan = finalize.build_plan(spec, row["sub"], row["ses"], bids_dir=bids)
        print("  --- finalize 计划 ---")
        finalize.report(plan, applied=False)
        if plan.issues:
            status = "needs_decision"
    else:
        print("  !! dcm2bids 没有产出任何文件")
        status = "nothing"
    if several:
        status = "conflict"
    return status


def main():
    ap = argparse.ArgumentParser(description="预演 config 匹配 + finalize（不转换影像）")
    ap.add_argument("project_dir")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--show-all", action="store_true", help="也列出 PhysioLog / 定位像")
    a = ap.parse_args()
    try:
        spec = bc.load_project(a.project_dir)
        rows = bc.select_rows(bc.load_mapping(spec), a.only)
        errors, warns = lint_config.lint(bc.load_config(spec))
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    for w in warns:
        print("[config warn] " + w)
    if errors:
        for e in errors:
            print("[config error] " + e)
        sys.exit(1)
    root = Path(spec["work_dir"]) / "preview"
    results = {}
    for r in rows:
        try:
            results[bc.prefix_of(r["sub"], r["ses"])] = preview_session(spec, r, root, a.show_all)
        except bc.SpecError as e:
            sys.exit("错误：{}".format(e))
        print()
    print("===== 汇总")
    for k, v in results.items():
        print("  {:<24} {}".format(k, {"ok": "可以转换", "needs_decision": "需要人工决定",
                                       "conflict": "config 有匹配冲突", "nothing": "config 一条都没匹配上",
                                       "no_scout": "没有侦察结果"}[v]))
    sys.exit(0 if all(v == "ok" for v in results.values()) else 2)


if __name__ == "__main__":
    main()
