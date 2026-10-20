#!/usr/bin/env python3
"""physio_to_bids.py — Siemens CMRR 生理记录 → BIDS *_recording-{pulse,respiratory}_physio.tsv.gz

两种来源（participants_mapping.tsv 的 physio_mode 列）：
  dicom  *_PhysioLog series 混在 DICOM 目录里（ImageType 含 PHYSIO），log 打包在 CSA Data
         (7fe1,1010)；需要 pydicom（用 dcm2bids 所在环境的 python 跑）。dcm2niix 对它无产物也无警告。
  file   扫描仪导出的独立 Physio_<date>_<time>_<uuid>_{Info,PULS,RESP}.log；目录写在 physio_dir 列。

原始 log 统一放 <bids>/sourcedata/physio/<sub[_ses]>/（BIDS 规定 sourcedata/ 在数据集根下，validator 不检查它）。

**与 bold 的配对靠采集时间**：Info.log 第一个 volume 的 ACQ_START_TICS × 2.5 ms
就是该 run 第一帧的时刻，与 bold sidecar 的 AcquisitionTime 相差 < 1 ms（HS7T 实测）。
不依赖序列名、run 号、NumVolumes——等长范式（每个 run 帧数相同）也能配，
run 被重编号或剔除后也不会配错。NumVolumes 只用来交叉核对。

PULS 200 Hz / RESP 50 Hz（实测），BIDS 要求单个 tsv 内所有列共享 SamplingFrequency，
所以分成两套 recording-，不重采样。fmap（3 volume）的 physio 不转，BIDS 的 fmap 不放 physio。

用法：
  python3 physio_to_bids.py <project_dir> [--only sub-01 …] [--dry-run]
"""
import argparse
import gzip
import json
import re
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402

TICK_MS = 2.5
MATCH_TOL = 0.5           # 秒；实测 < 0.001
NAME_RE = re.compile(rb"Physio_\d+_\d+_[0-9a-f\-]+_\w+\.log")
SIGNALS = (("PULS", "pulse"), ("RESP", "respiratory"))


# ---------------------------------------------------------------- DICOM 模式：提取

def find_physio_dicoms(dicom_dir, jobs=8):
    """返回 [(SeriesInstanceUID, SeriesNumber, SeriesDescription, path)]，按 UID 归组。"""
    import pydicom                      # noqa: F401  —— 只有 DICOM 模式需要
    from concurrent.futures import ThreadPoolExecutor

    files = [p for p in Path(dicom_dir).rglob("*") if p.is_file()]

    def head(p):
        try:
            import pydicom as pd
            ds = pd.dcmread(str(p), stop_before_pixels=True, force=True,
                            specific_tags=["ImageType", "SeriesInstanceUID", "SeriesNumber",
                                           "SeriesDescription"])
        except Exception:               # noqa: BLE001
            return None
        it = [str(x).upper() for x in (ds.get("ImageType") or [])]
        if "PHYSIO" not in it:
            return None
        return (str(ds.get("SeriesInstanceUID", "")), int(ds.get("SeriesNumber", -1) or -1),
                str(ds.get("SeriesDescription", "")), p)

    with ThreadPoolExecutor(jobs) as ex:
        hits = [h for h in ex.map(head, files) if h]
    seen, out = set(), []
    for h in sorted(hits, key=lambda x: (x[1], str(x[3]))):
        if h[0] not in seen:
            seen.add(h[0])
            out.append(h)
    return out


def extract_logs(path):
    """CSA Data (7fe1,1010) → {文件名: bytes}。

    打包格式（实测 MR_VE12U）：块起点 +0 UINT32 dataLen，+4 UINT32 nameLen，+8 文件名，
    +1024 正文。用正则定位文件名、反推块起点，再核对 nameLen，不依赖对齐规则。"""
    import pydicom
    ds = pydicom.dcmread(str(path), force=True)
    tag = (0x7FE1, 0x1010)
    if tag not in ds:
        raise ValueError("{}: 没有 (7fe1,1010) CSA Data".format(Path(path).name))
    raw = bytes(ds[tag].value)
    out = {}
    for m in NAME_RE.finditer(raw):
        blk = m.start() - 8
        if blk < 0:
            continue
        data_len, name_len = struct.unpack_from("<II", raw, blk)
        if name_len != len(m.group(0)):
            continue
        beg = blk + 1024
        out[m.group(0).decode()] = raw[beg:min(beg + data_len, len(raw))]
    return out


def extract_session(dicom_dir, dest):
    """把一个 session 的 PhysioLog 全部提取到 dest/<SN>_<SeriesDescription>/。返回提取的 series 数。"""
    n = 0
    for uid, sn, sd, path in find_physio_dicoms(dicom_dir):
        sub = Path(dest) / "{:03d}_{}".format(sn, re.sub(r"[^\w.-]", "_", sd))
        if sub.exists() and any(sub.glob("*_Info.log")):
            sub = sub.with_name(sub.name + "_" + uid[-6:])        # SeriesNumber 撞号（软件重启）
        sub.mkdir(parents=True, exist_ok=True)
        for name, blob in extract_logs(path).items():
            (sub / name).write_bytes(blob)
        n += 1
    return n


# ---------------------------------------------------------------- 解析 log

def parse_kv_header(path):
    hdr = {}
    with open(str(path), errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if "=" in s and not s[0].isdigit():
                k, v = s.split("=", 1)
                hdr[k.strip()] = v.strip()
            elif s[0].isdigit() or s.startswith(("VOLUME", "ACQ_TIME")):
                break
    return hdr


def first_volume_tic(info_path):
    with open(str(info_path), errors="replace") as f:
        for line in f:
            p = line.split()
            if len(p) == 5 and p[0].isdigit():
                return int(p[2])
    raise ValueError("{}: 找不到 volume 数据行".format(info_path))


def parse_signal(path):
    out = []
    with open(str(path), errors="replace") as f:
        for line in f:
            p = line.split()
            if len(p) >= 3 and p[0].isdigit():
                try:
                    out.append((int(p[0]), int(p[2])))
                except ValueError:
                    continue
    return out


def infer_fs(ticks):
    if len(ticks) < 2:
        raise ValueError("采样点太少")
    diffs = [ticks[i + 1] - ticks[i] for i in range(min(len(ticks) - 1, 2000))]
    step = Counter(d for d in diffs if d > 0).most_common(1)[0][0]
    return 1000.0 / (step * TICK_MS), step


def write_physio(stem, label, ticks, values, t0_tic, src, n_vol):
    fs, step = infer_fs(ticks)
    with gzip.open(stem + "_recording-{}_physio.tsv.gz".format(label), "wt") as f:
        for v in values:
            f.write("{}\n".format(v))
    meta = {"SamplingFrequency": round(fs, 4),
            "StartTime": round((ticks[0] - t0_tic) * TICK_MS / 1000.0, 4),
            "Columns": [label], "Manufacturer": "Siemens", "PhysioType": "CMRR EJA_1 log",
            "SourceFile": src, "NumVolumes": n_vol, "TickIntervalMs": step * TICK_MS}
    Path(stem + "_recording-{}_physio.json".format(label)).write_text(json.dumps(meta, indent=2) + "\n")
    return meta


# ---------------------------------------------------------------- 一个 session

def process_session(spec, row, log=None, dry_run=False):
    """返回 {'matched': [...], 'unmatched_logs': [...], 'bolds_without_physio': [...], 'problems': [...]}"""
    prefix = bc.prefix_of(row["sub"], row["ses"])
    src = Path(spec["bids_dir"]) / "sourcedata" / "physio" / prefix   # BIDS 规定 sourcedata/ 在数据集根下
    res ={"matched": [], "unmatched_logs": [], "bolds_without_physio": [], "problems": []}
    if row["physio_mode"] == "dicom":
        if not dry_run:
            if src.exists():
                shutil.rmtree(str(src))
            n = extract_session(row["dicom_path"], src)
            if n == 0:
                res["problems"].append("physio_mode=dicom，但 DICOM 里没有 PhysioLog series")
                return res
    elif row["physio_mode"] == "file":
        if not row["physio_dir"] or not Path(row["physio_dir"]).is_dir():
            res["problems"].append("physio_mode=file，但 physio_dir 不存在：{}".format(row["physio_dir"]))
            return res
        if not dry_run:
            src.mkdir(parents=True, exist_ok=True)
            for p in Path(row["physio_dir"]).glob("Physio_*.log"):
                if not (src / p.name).exists():
                    shutil.copy2(str(p), str(src / p.name))
    else:
        return res

    sess = bc.session_dir(spec, row["sub"], row["ses"])
    bolds = [im for im in bc.session_images(sess) if im.suffix == "bold"] if sess.is_dir() else []
    infos = sorted(src.rglob("*_Info.log")) if src.exists() else []
    if not infos:
        res["problems"].append("{} 下没有 *_Info.log".format(src))
        return res

    used = {}
    for info in infos:
        hdr = parse_kv_header(info)
        n_vol = int(hdr.get("NumVolumes", -1))
        try:
            t0 = first_volume_tic(info)
        except ValueError as e:
            res["problems"].append(str(e))
            continue
        t_sec = t0 * TICK_MS / 1000.0
        cand = [(abs(b.time - t_sec), b) for b in bolds if b.time is not None and abs(b.time - t_sec) < MATCH_TOL]
        if not cand:
            res["unmatched_logs"].append("{} (NumVolumes={}, 首帧 {})".format(
                info.parent.name if info.parent != src else info.name, n_vol, bc.fmt_time(t_sec)))
            continue
        b = min(cand, key=lambda x: x[0])[1]
        if b in used:
            res["problems"].append("{} 与 {} 都对上了 {}，跳过后者".format(used[b].name, info.name, b.stem.name))
            continue
        used[b] = info
        if n_vol != b.volumes:
            res["problems"].append("{}: physio NumVolumes={} ≠ bold {} vol（被中断的 run？）".format(
                b.stem.name, n_vol, b.volumes))
        stem_base = str(b.stem)[: -len("_bold")]
        info_stem = str(info)[: -len("_Info.log")]
        for code, label in SIGNALS:
            sig = Path(info_stem + "_{}.log".format(code))
            if not sig.exists():
                res["problems"].append("{}: 缺 {}".format(b.stem.name, sig.name))
                continue
            data = parse_signal(sig)
            if not data:
                res["problems"].append("{}: {} 无数据".format(b.stem.name, sig.name))
                continue
            if not dry_run:
                meta = write_physio(stem_base, label, [d[0] for d in data], [d[1] for d in data],
                                    t0, sig.name, n_vol)
            else:
                meta = {"StartTime": round((data[0][0] - t0) * TICK_MS / 1000.0, 4)}
            res["matched"].append({"bold": b.stem.name, "recording": label, "StartTime": meta["StartTime"]})
    res["bolds_without_physio"] = [b.stem.name for b in bolds if b not in used]
    st = Counter(round(m["StartTime"], 1) for m in res["matched"])
    if len(st) > 1:
        res["problems"].append("StartTime 不一致 {}（同协议应基本相同；先怀疑 log 配错，见 pitfalls #43）".format(dict(st)))
    if log:
        with open(str(log), "a") as f:
            f.write("\n--- physio ---\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    return res


def main():
    ap = argparse.ArgumentParser(description="CMRR 生理记录 → BIDS physio")
    ap.add_argument("project_dir")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        spec = bc.load_project(a.project_dir)
        rows = bc.select_rows(bc.load_mapping(spec), a.only)
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    for r in rows:
        if r["physio_mode"] == "none":
            continue
        res = process_session(spec, r, dry_run=a.dry_run)
        print("=== {} ({}) ===".format(bc.prefix_of(r["sub"], r["ses"]), r["physio_mode"]))
        runs = sorted({m["bold"] for m in res["matched"]})
        print("  配上 {} 个 bold：{}".format(len(runs), ", ".join(runs)))
        for u in res["unmatched_logs"]:
            print("  未配对 log（多为 fmap 的 3-volume 组或测试序列）：" + u)
        for b in res["bolds_without_physio"]:
            print("  [warn] 没有生理记录：" + b)
        for p in res["problems"]:
            print("  [warn] " + p)


if __name__ == "__main__":
    main()
