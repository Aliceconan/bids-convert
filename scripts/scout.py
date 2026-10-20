#!/usr/bin/env python3
"""scout.py — 侦察 DICOM session：每个 series 一行，附 dcm2bids 匹配时会用到的 sidecar 字段。

做法：只读 DICOM 头（pydicom，按 SeriesInstanceUID 归组——扫描仪软件重启后 SeriesNumber
会撞号，按号归组会静默丢 series），每个 series 挑 InstanceNumber 最小的一个文件，
用 `dcm2niix -b o` 只生成 sidecar JSON。几秒到一两分钟一个 session，
比 dcm2bids_helper 全量转换快两个数量级，而且拿到的就是 dcm2bids 用来匹配的同一批字段
（SeriesDescription / PhaseEncodingDirection / ImageType / SliceThickness …）。

产物（每个 session 一个目录，默认 <project>/work/scout/<sub[_ses]>/）：
  series.tsv     每个 series 一行：SN、SD、文件数（mosaic EPI 即 volume 数）、采集时间、PE、ImageType…
  json/<idx>.json  dcm2niix 生成的 sidecar（preview.py 用它预演 config 匹配）
  session.json   文件数、series 数、PhysioLog series 数（>0 说明 physio_mode=dicom）、性别/年龄
最后打印跨 session 汇总：同一 SeriesDescription（忽略大小写）出现在哪些 session、文件数分布
——直接用来写 config 的匹配规则和 protocol.tsv。

需要 pydicom 和 dcm2niix：用 dcm2bids 所在环境的 python 跑。

用法：
  python3 scout.py <project_dir>                    # mapping 里全部 session
  python3 scout.py <project_dir> --only sub-01 sub-07
  python3 scout.py --dirs /raw/20260612_X /raw/20260901_Y --out /path/scout   # 还没写 mapping 时
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402

TAGS = ["SeriesInstanceUID", "SeriesNumber", "SeriesDescription", "InstanceNumber",
        "ImageType", "AcquisitionTime", "PatientSex", "PatientAge"]
COLS = ["idx", "SeriesNumber", "SeriesDescription", "n_files", "AcquisitionTime", "ImageType",
        "PhaseEncodingDirection", "SliceThickness", "RepetitionTime", "json", "rep"]


def read_head(path):
    try:
        import pydicom
        ds = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=TAGS)
    except Exception:            # noqa: BLE001 —— 非 DICOM 文件
        return None
    uid = str(ds.get("SeriesInstanceUID", ""))
    if not uid:
        return None
    try:
        inst = int(ds.get("InstanceNumber", 0) or 0)
    except (TypeError, ValueError):
        inst = 0
    return (uid, int(ds.get("SeriesNumber", -1) or -1), str(ds.get("SeriesDescription", "")),
            inst, "\\".join(str(x) for x in (ds.get("ImageType") or [])),
            str(ds.get("AcquisitionTime", "")), str(ds.get("PatientSex", "")),
            str(ds.get("PatientAge", "")), path)


def sidecar_for(rep, outdir, dcm2niix):
    """对单个 DICOM 文件跑 dcm2niix -b o，返回 sidecar dict 与路径。"""
    work = Path(tempfile.mkdtemp(prefix="scout_", dir=str(outdir)))
    try:
        os.symlink(str(rep), str(work / Path(rep).name))
        subprocess.call([dcm2niix, "-b", "o", "-ba", "y", "-f", "s%3s", "-o", str(work), str(work)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        js = sorted(work.glob("*.json"))
        if not js:
            shutil.rmtree(str(work))
            return {}, None
        return json.loads(js[0].read_text()), js[0]
    finally:
        if work.exists():
            for p in work.glob("*"):
                if p.suffix != ".json":
                    p.unlink()


def scout_session(dicom_dir, outdir, dcm2niix, jobs):
    outdir = Path(outdir)
    (outdir / "json").mkdir(parents=True, exist_ok=True)
    files = [str(p) for p in Path(dicom_dir).rglob("*") if p.is_file()]
    with ProcessPoolExecutor(jobs) as ex:
        heads = [h for h in ex.map(read_head, files, chunksize=64) if h]
    series = defaultdict(list)
    for h in heads:
        series[h[0]].append(h)
    rows = []
    for uid, hs in series.items():
        hs.sort(key=lambda h: (h[3], h[8]))
        first = hs[0]
        times = [bc.parse_time(h[5]) for h in hs if bc.parse_time(h[5]) is not None]
        rows.append({"uid": uid, "SeriesNumber": first[1], "SeriesDescription": first[2],
                     "n_files": len(hs), "ImageType": first[4],
                     "t": min(times) if times else None, "rep": first[8]})
    rows.sort(key=lambda r: (r["t"] if r["t"] is not None else 1e9, r["SeriesNumber"]))

    def one(args):
        i, r = args
        meta, js = sidecar_for(r["rep"], outdir, dcm2niix)
        dest = outdir / "json" / "{:03d}.json".format(i)
        if js:
            js.rename(dest)
            js.parent.rmdir()
        return i, meta, dest if js else None

    with ThreadPoolExecutor(jobs) as ex:
        for i, meta, dest in ex.map(one, list(enumerate(rows, 1))):
            r = rows[i - 1]
            r.update({"idx": i, "json": str(dest) if dest else "",
                      "PhaseEncodingDirection": meta.get("PhaseEncodingDirection", ""),
                      "SliceThickness": meta.get("SliceThickness", ""),
                      "RepetitionTime": meta.get("RepetitionTime", ""),
                      "AcquisitionTime": meta.get("AcquisitionTime") or bc.fmt_time(r["t"]),
                      "ImageType": "\\".join(meta["ImageType"]) if meta.get("ImageType") else r["ImageType"]})
    with open(str(outdir / "series.tsv"), "w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLS) + "\n")
    physio = sum(1 for r in rows if "PHYSIO" in r["ImageType"].upper())
    sexes = {h[6] for h in heads if h[6]}
    ages = {h[7] for h in heads if h[7]}
    info = {"dicom_dir": str(dicom_dir), "n_files": len(files), "n_dicom": len(heads),
            "n_series": len(rows), "physio_series": physio,
            "suggested_physio_mode": "dicom" if physio else "none (或 file，看有没有单独导出的 log)",
            "PatientSex": "/".join(sorted(sexes)), "PatientAge": "/".join(sorted(ages))}
    (outdir / "session.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    return rows, info


def print_session(name, rows, info):
    print("===== {}  文件 {}  series {}  PhysioLog {}".format(
        name, info["n_files"], info["n_series"], info["physio_series"]))
    for r in rows:
        if "PHYSIO" in r["ImageType"].upper():
            continue
        it = r["ImageType"].split("\\")
        print("  {:>3} SN{:<4} n={:<5} {:<9} pe={:<3} th={:<5} {:<38} {}".format(
            r["idx"], r["SeriesNumber"], r["n_files"], str(r["AcquisitionTime"])[:8],
            r["PhaseEncodingDirection"] or "-", r["SliceThickness"] or "-",
            r["SeriesDescription"][:38], "\\".join(it[2:5])))


def summarize(all_rows, out):
    groups = defaultdict(list)
    for sess, rows in all_rows.items():
        for r in rows:
            if "PHYSIO" in r["ImageType"].upper():
                continue
            groups[r["SeriesDescription"].casefold()].append((sess, r))
    lines = ["SeriesDescription(casefold)\t变体\tsession数\t文件数分布\tPE"]
    print("\n===== 跨 session 汇总（{} 个 session）".format(len(all_rows)))
    print("  {:<40} {:>5}  {:<28} {}".format("SeriesDescription", "场次", "文件数(出现次数)", "写法变体 / PE"))
    for key in sorted(groups, key=lambda k: (min(r["t"] or 0 for _, r in groups[k]), k)):
        items = groups[key]
        variants = sorted({r["SeriesDescription"] for _, r in items})
        sessions = sorted({s for s, _ in items})
        counts = defaultdict(int)
        for _, r in items:
            counts[r["n_files"]] += 1
        dist = ",".join("{}({})".format(n, c) if c > 1 else str(n) for n, c in sorted(counts.items()))
        pes = sorted({r["PhaseEncodingDirection"] for _, r in items if r["PhaseEncodingDirection"]})
        print("  {:<40} {:>5}  {:<28} {}{}".format(
            variants[0][:40], len(sessions), dist[:28],
            ("变体 " + "|".join(variants) + "  ") if len(variants) > 1 else "", "/".join(pes)))
        lines.append("\t".join([key, "|".join(variants), str(len(sessions)), dist, "/".join(pes)]))
    Path(out).write_text("\n".join(lines) + "\n")
    print("\n汇总表：{}".format(out))


def main():
    ap = argparse.ArgumentParser(description="DICOM session 侦察（只读头 + 每 series 一个 sidecar）")
    ap.add_argument("project_dir", nargs="?")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--dirs", nargs="+", help="直接给 DICOM 目录（还没写 mapping 时）")
    ap.add_argument("--out", help="输出根目录（默认 <project>/work/scout）")
    ap.add_argument("--dcm2niix", default=None)
    ap.add_argument("-j", "--jobs", type=int, default=16)
    a = ap.parse_args()

    targets = []
    dcm2niix = a.dcm2niix or "dcm2niix"
    if a.dirs:
        if not a.out:
            sys.exit("--dirs 模式必须给 --out")
        out_root = Path(a.out)
        targets = [(Path(d).name, Path(d)) for d in a.dirs]
    else:
        if not a.project_dir:
            sys.exit("要么给 project_dir，要么用 --dirs")
        try:
            spec = bc.load_project(a.project_dir)
            rows = bc.select_rows(bc.load_mapping(spec), a.only)
        except bc.SpecError as e:
            sys.exit("错误：{}".format(e))
        out_root = Path(a.out) if a.out else Path(spec["work_dir"]) / "scout"
        dcm2niix = a.dcm2niix or spec["dcm2niix"]
        targets = [(bc.prefix_of(r["sub"], r["ses"]), r["dicom_path"]) for r in rows]
    try:
        import pydicom  # noqa: F401
    except ImportError:
        sys.exit("需要 pydicom：用 dcm2bids 所在环境的 python 运行本脚本")

    all_rows = {}
    for name, d in targets:
        if not Path(d).is_dir():
            print("!! {}: 目录不存在 {}".format(name, d))
            continue
        rows, info = scout_session(d, out_root / name, dcm2niix, a.jobs)
        print_session(name, rows, info)
        all_rows[name] = rows
    if all_rows:
        summarize(all_rows, out_root / "summary.tsv")


if __name__ == "__main__":
    main()
