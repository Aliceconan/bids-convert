#!/usr/bin/env python3
"""
从 Siemens CMRR PhysioLog DICOM (ImageType = ORIGINAL\\PRIMARY\\RAWDATA\\PHYSIO)
里提取内嵌的 *_Info.log / *_PULS.log / *_RESP.log，还原成 File 模式的同款文件。

CSA Data 标签 (7fe1,1010) 的打包格式（实测 MR_VE12U / syngo MR E12）：

    块起点 +0     UINT32  dataLen    正文字节数
    块起点 +4     UINT32  nameLen    文件名字节数
    块起点 +8     char[]  filename   Physio_<date>_<time>_<uuid>_<TYPE>.log
    块起点 +1024  char[]  data       log 正文
    下一块起点 = 块起点 + 1024 + dataLen，再向上对齐到 512 字节边界

解析不依赖上面的对齐规则：直接用正则定位所有文件名出现的偏移，
反推块起点（= 文件名偏移 - 8），再校验该处的 nameLen 是否与文件名长度一致。

输出目录结构：
    <outdir>/<SeriesDescription 去掉 _PhysioLog>/Physio_..._{Info,PULS,RESP}.log
例如  NEZHA_run_01/Physio_20260910_134921_<uuid>_PULS.log
"""
import argparse
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

import pydicom

NAME_RE = re.compile(rb"Physio_\d+_\d+_[0-9a-f\-]+_\w+\.log")
DATA_OFFSET = 1024


def series_representatives(dicom_dir):
    """每个 SeriesNumber 取一个代表文件（按文件名里的 series 字段分组）。"""
    pat = re.compile(r"\.(\d{4})\.(\d{4})\.")
    best = {}
    for p in Path(dicom_dir).iterdir():
        m = pat.search(p.name)
        if not m:
            continue
        series, inst = m.group(1), m.group(2)
        if series not in best or inst < best[series][0]:
            best[series] = (inst, p)
    return [v[1] for _, v in sorted(best.items())]


def is_physio(path):
    """只读少量标签做快速筛选。"""
    try:
        ds = pydicom.dcmread(
            str(path),
            stop_before_pixels=True,
            specific_tags=["ImageType", "SeriesDescription", "SeriesNumber"],
            force=True,
        )
    except Exception:
        return None
    it = [str(x).upper() for x in (ds.get("ImageType") or [])]
    if "PHYSIO" not in it:
        return None
    return ds.get("SeriesDescription", ""), ds.get("SeriesNumber", -1)


def extract_logs(path):
    """返回 {filename: bytes}。"""
    ds = pydicom.dcmread(str(path), force=True)
    tag = (0x7FE1, 0x1010)
    if tag not in ds:
        raise ValueError(f"{path.name}: 没有 (7fe1,1010) CSA Data")
    raw = bytes(ds[tag].value)

    out = {}
    for m in NAME_RE.finditer(raw):
        blk = m.start() - 8
        if blk < 0:
            continue
        data_len, name_len = struct.unpack_from("<II", raw, blk)
        # 校验：该位置的 nameLen 必须与匹配到的文件名等长，否则是正文里的巧合
        if name_len != len(m.group(0)):
            continue
        beg = blk + DATA_OFFSET
        end = beg + data_len
        if end > len(raw):
            print(f"    !! {m.group(0).decode()} 越界 ({end} > {len(raw)})，截断")
            end = len(raw)
        out[m.group(0).decode()] = raw[beg:end]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dicom_dir")
    ap.add_argument("outdir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reps = series_representatives(args.dicom_dir)
    print(f"扫描 {len(reps)} 个 series 代表文件…\n")

    hits = []
    for p in reps:
        info = is_physio(p)
        if info:
            hits.append((info[1], info[0], p))
    hits.sort()

    if not hits:
        sys.exit("没找到 PhysioLog series")

    print(f"{'Series':>7}  {'SeriesDescription':<32} {'提取到的 log':<12} 字节")
    print("-" * 78)

    outroot = Path(args.outdir)
    total = defaultdict(int)
    for snum, sdesc, path in hits:
        logs = extract_logs(path)
        run_tag = sdesc.replace("_PhysioLog", "")
        dest = outroot / run_tag
        if not args.dry_run:
            dest.mkdir(parents=True, exist_ok=True)
        for fname, blob in sorted(logs.items()):
            kind = fname.rsplit("_", 1)[-1].replace(".log", "")
            if not args.dry_run:
                (dest / fname).write_bytes(blob)
            total[kind] += 1
            print(f"{snum:>7}  {sdesc:<32} {kind:<12} {len(blob):>10,}")

    print("\n汇总：", dict(total))
    print(f"共 {len(hits)} 个 PhysioLog series")
    if args.dry_run:
        print("(dry-run，未写文件)")


if __name__ == "__main__":
    main()
