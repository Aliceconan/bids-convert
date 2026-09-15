#!/usr/bin/env python3
"""
CMRR physio log (File 模式) -> BIDS _physio.tsv.gz + _physio.json

输入：一个目录，含成组的 Physio_<date>_<time>_<uuid>_{Info,PULS,RESP}.log
输出：按 Info.log 里的 NumVolumes 匹配到对应的 BIDS bold 文件，
      为每个 run 写出 _recording-pulse_physio 和 _recording-respiratory_physio。

PULS 与 RESP 采样率不同（实测 200 Hz / 50 Hz），BIDS 要求单个 tsv 内
所有列共享一个 SamplingFrequency，因此用 recording-<label> 分开存，不做重采样。

Siemens tick = 2.5 ms。
StartTime = (physio 首个采样 tick - 首个 volume 的 ACQ_START_TICS) * 2.5ms / 1000
负值表示生理记录早于扫描开始，符合 BIDS 定义。
"""
import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path

TICK_MS = 2.5


def parse_kv_header(path):
    """读 log 文件顶部的 key = value 段。"""
    hdr = {}
    with open(path) as f:
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
    """Info.log 中第一个数据行的 ACQ_START_TICS。"""
    with open(info_path) as f:
        for line in f:
            p = line.split()
            if len(p) == 5 and p[0].isdigit():
                return int(p[2])
    raise ValueError(f"{info_path}: 找不到数据行")


def parse_signal(path):
    """返回 [(tick, value), ...]，跳过表头和非数据行。"""
    out = []
    with open(path) as f:
        for line in f:
            p = line.split()
            if len(p) >= 3 and p[0].isdigit():
                try:
                    out.append((int(p[0]), int(p[2])))
                except ValueError:
                    continue  # SIGNAL 标记行等
    return out


def infer_fs(ticks):
    """由相邻 tick 差的众数推采样率 (Hz)。"""
    if len(ticks) < 2:
        raise ValueError("采样点太少")
    diffs = [ticks[i + 1] - ticks[i] for i in range(min(len(ticks) - 1, 2000))]
    step = Counter(d for d in diffs if d > 0).most_common(1)[0][0]
    return 1000.0 / (step * TICK_MS), step


def write_physio(out_stem, ticks, values, t0_tic, label, n_vol, src_name):
    fs, step = infer_fs(ticks)
    start_time = (ticks[0] - t0_tic) * TICK_MS / 1000.0

    tsv = Path(f"{out_stem}_recording-{label}_physio.tsv.gz")
    with gzip.open(tsv, "wt") as f:
        for v in values:
            f.write(f"{v}\n")

    meta = {
        "SamplingFrequency": round(fs, 4),
        "StartTime": round(start_time, 4),
        "Columns": [label],
        "Manufacturer": "Siemens",
        "PhysioType": "CMRR EJA_1 log",
        "SourceFile": src_name,
        "NumVolumes": n_vol,
        "TickIntervalMs": step * TICK_MS,
    }
    Path(f"{out_stem}_recording-{label}_physio.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    return fs, start_time, len(values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("physio_dir", help="含 Physio_*_{Info,PULS,RESP}.log 的目录")
    ap.add_argument("func_dir", help="BIDS 的 func 目录（写出目标）")
    ap.add_argument("--prefix", required=True, help="如 sub-02_task-nezha")
    ap.add_argument(
        "--map",
        required=True,
        help="NumVolumes->run 映射，如 469:01,470:02,382:03",
    )
    ap.add_argument(
        "--recursive",
        action="store_true",
        help="递归查找 *_Info.log（DICOM 模式提取出来的按 run 分了子目录）",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vol2run = {}
    for item in args.map.split(","):
        nv, run = item.split(":")
        vol2run[int(nv)] = run

    pdir = Path(args.physio_dir)
    fdir = Path(args.func_dir)
    groups = sorted(pdir.rglob("*_Info.log") if args.recursive
                    else pdir.glob("*_Info.log"))
    if not groups:
        raise SystemExit(f"{pdir}: 没找到 *_Info.log")

    print(f"{'组':<18} {'NumVol':>7} {'run':>5} {'信号':>12} {'fs(Hz)':>9} "
          f"{'StartTime':>10} {'采样点':>9}")
    print("-" * 80)

    used_runs = Counter()
    skipped = []
    for info in groups:
        hdr = parse_kv_header(info)
        n_vol = int(hdr.get("NumVolumes", -1))
        stem = str(info)[: -len("_Info.log")]
        tag = Path(stem).name.replace("Physio_", "")[:15]

        # 归属：优先用父目录名里的 run 号（DICOM 模式的 SeriesDescription 带 run 名，
        # 比按 volume 数反查更权威），两者都可得时做交叉校验。
        m = re.search(r"run_(\d+)$", info.parent.name, re.I)
        run_dir = f"{int(m.group(1)):02d}" if m else None
        run_vol = vol2run.get(n_vol)

        if run_dir and run_vol and run_dir != run_vol:
            print(f"  !! 归属冲突 {tag}: 目录名->run-{run_dir} "
                  f"但 NumVolumes={n_vol}->run-{run_vol}，跳过")
            continue

        run = run_dir or run_vol
        if run is None:
            skipped.append((tag, n_vol))
            continue

        used_runs[run] += 1
        if used_runs[run] > 1:
            print(f"  !! NumVolumes={n_vol} 匹配到 run-{run} 多于一次，"
                  f"跳过重复组 {tag}")
            continue

        t0 = first_volume_tic(info)
        out_stem = str(fdir / f"{args.prefix}_run-{run}")

        for label, suffix in (("pulse", "PULS"), ("respiratory", "RESP")):
            sig_path = Path(f"{stem}_{suffix}.log")
            if not sig_path.exists():
                print(f"  !! 缺 {sig_path.name}")
                continue
            data = parse_signal(sig_path)
            if not data:
                print(f"  !! {sig_path.name} 无数据")
                continue
            ticks = [d[0] for d in data]
            values = [d[1] for d in data]
            if args.dry_run:
                fs, step = infer_fs(ticks)
                st = (ticks[0] - t0) * TICK_MS / 1000.0
                n = len(values)
            else:
                fs, st, n = write_physio(
                    out_stem, ticks, values, t0, label, n_vol, sig_path.name
                )
            print(f"{tag:<18} {n_vol:>7} {run:>5} {label:>12} "
                  f"{fs:>9.2f} {st:>10.2f} {n:>9}")

    if skipped:
        print("\n未匹配（通常是 reverse_PE 的 3-volume 组，BIDS fmap 不放 physio）：")
        for tag, nv in skipped:
            print(f"  {tag}  NumVolumes={nv}")

    missing = set(vol2run.values()) - set(used_runs)
    if missing:
        print(f"\n!! 以下 run 没有匹配到 physio: {sorted(missing)}")


if __name__ == "__main__":
    main()
