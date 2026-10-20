#!/usr/bin/env python3
"""copy_sourcedata.py — 把 mapping 里某一列指向的目录（行为数据等）原样拷进 <bids>/sourcedata/<kind>/<sub[_ses]>/。

生理记录不用这个，用 physio_to_bids.py（它会转成 BIDS physio）。

  participants_mapping.tsv 加一列，例如 beh_dir：绝对路径，或相对 project.json 的 raw_root。
  路径和大小写不可预测，先 ls 确认再写进 mapping。不覆盖已有文件。

用法：python3 copy_sourcedata.py <project_dir> --column beh_dir --kind beh [--only sub-01]
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--column", required=True, help="mapping 里的列名，如 beh_dir")
    ap.add_argument("--kind", required=True, help="sourcedata 下的子目录名，如 beh")
    ap.add_argument("--only", nargs="+")
    a = ap.parse_args()
    try:
        spec = bc.load_project(a.project_dir)
        rows = bc.select_rows(bc.load_mapping(spec), a.only)
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    if a.column not in rows[0]:
        sys.exit("mapping 没有 {} 列（现有：{}）".format(a.column, sorted(k for k in rows[0] if k[0] != "_")))
    for r in rows:
        src = r.get(a.column, "")
        if not src:
            continue
        src = Path(src) if Path(src).is_absolute() else Path(spec["raw_root"]) / src
        prefix = bc.prefix_of(r["sub"], r["ses"])
        if not src.is_dir():
            print("  [warn] {}: 目录不存在 {}".format(prefix, src))
            continue
        dest = Path(spec["bids_dir"]) / "sourcedata" / a.kind / prefix
        n = 0
        for p in src.rglob("*"):
            if p.is_file():
                d = dest / p.relative_to(src)
                if not d.exists():
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(p), str(d))
                    n += 1
        print("  {}: 新拷 {} 个文件 → {}".format(prefix, n, dest))


if __name__ == "__main__":
    main()
