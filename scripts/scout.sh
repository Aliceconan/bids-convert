#!/usr/bin/env bash
# scout.sh — 侦察 DICOM session，收集 SeriesDescription 变体
#
# 用法:
#   bash scout.sh <dicom_session_folder> [output_dir]
#
# 示例:
#   bash scout.sh /data/20210301_S18_TASK_S01_PRE /tmp/scout_S01
#
# 输出:
#   1. 原始 sidecar 列表
#   2. 按大小写不敏感分组的 SeriesDescription 变体汇总

set -euo pipefail

DICOM_DIR="${1:?用法: scout.sh <dicom_session_folder> [output_dir]}"
SESSION_NAME="$(basename "$DICOM_DIR")"
OUTPUT_DIR="${2:-/tmp/bids_scout_${SESSION_NAME}}"

echo "=== 侦察: $SESSION_NAME ==="
echo "输出目录: $OUTPUT_DIR"

# 运行 dcm2bids_helper
dcm2bids_helper -d "$DICOM_DIR" -o "$OUTPUT_DIR" 2>&1 | tail -5

# 解析 sidecar JSON
echo ""
echo "=== Sidecar 列表 ==="
python3 - "$OUTPUT_DIR" <<'PYEOF'
import collections
import glob
import json
import os
import sys

output_dir = sys.argv[1]
pattern = os.path.join(output_dir, "tmp_dcm2bids", "*", "*.json")
files = sorted(glob.glob(pattern))

if not files:
    print("  [未找到 sidecar JSON]")
    sys.exit(0)

groups = collections.defaultdict(list)

for f in files:
    try:
        with open(f) as handle:
            d = json.load(handle)
    except Exception:
        continue

    sd = d.get("SeriesDescription", "?")
    pe = d.get("PhaseEncodingDirection", "N/A")
    image_type = d.get("ImageType", [])
    if isinstance(image_type, list):
        image_type_str = ",".join(str(x) for x in image_type[:4])
    else:
        image_type_str = str(image_type)

    name = os.path.basename(f).replace(".json", "")
    if len(name) > 40:
        name = name[:37] + "..."

    print(f"  {name:42s} SD={sd:40s} PE={pe:4s} IT={image_type_str}")
    groups[sd.casefold()].append((sd, pe, image_type_str))

print("")
print("=== SeriesDescription 变体分组（大小写不敏感） ===")
for idx, key in enumerate(sorted(groups), start=1):
    variants = sorted({item[0] for item in groups[key]})
    pe_values = sorted({item[1] for item in groups[key] if item[1]})
    image_types = sorted({item[2] for item in groups[key] if item[2]})
    print(f"  [{idx}] 变体: {' | '.join(variants)}")
    if pe_values:
        print(f"      PE: {', '.join(pe_values)}")
    if image_types:
        print(f"      ImageType: {', '.join(image_types[:3])}")
PYEOF

echo ""
echo "=== 侦察完成 ==="
