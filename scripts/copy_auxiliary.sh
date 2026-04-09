#!/usr/bin/env bash
# copy_auxiliary.sh — 复制 physio/behavior 数据到 BIDS sourcedata
#
# 用法:
#   bash copy_auxiliary.sh <project_dir> --type physio|beh
#
# 前提:
#   participants_mapping.tsv 中需要有 physio_subfolder 或 beh_subfolder 列
#   （如果辅助数据在 DICOM 文件夹内的子目录）
#   或 physio_folder / beh_folder 列
#   （如果辅助数据在顶层独立文件夹）
#
# 注意:
#   - 使用 cp -n（不覆盖已有文件）
#   - physio 路径大小写不可预测，脚本会用 ls 确认

set -euo pipefail

PROJECT_DIR="${1:?用法: copy_auxiliary.sh <project_dir> --type physio|beh}"
shift

DATA_TYPE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --type) DATA_TYPE="$2"; shift 2 ;;
        *) echo "未知参数: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$DATA_TYPE" ] || [[ "$DATA_TYPE" != "physio" && "$DATA_TYPE" != "beh" ]]; then
    echo "错误: --type 必须为 physio 或 beh" >&2
    exit 1
fi

MAPPING="$PROJECT_DIR/code/participants_mapping.tsv"
BIDS_DIR="$PROJECT_DIR/bids"

if [ ! -f "$MAPPING" ]; then
    echo "错误: 找不到 $MAPPING" >&2
    exit 1
fi

# 读取 mapping header，找到相关列的索引
HEADER=$(head -1 "$MAPPING")
IFS=$'\t' read -ra COLS <<< "$HEADER"

# 查找列索引
SUB_IDX=-1; SES_IDX=-1; FOLDER_IDX=-1; SOURCE_IDX=-1
for i in "${!COLS[@]}"; do
    case "${COLS[$i]}" in
        participant_id) SUB_IDX=$i ;;
        session) SES_IDX=$i ;;
        dicom_folder) FOLDER_IDX=$i ;;
        ${DATA_TYPE}_subfolder) SOURCE_IDX=$i ;;
        ${DATA_TYPE}_folder) SOURCE_IDX=$i ;;
    esac
done

if [ $SOURCE_IDX -eq -1 ]; then
    echo "错误: mapping 中找不到 ${DATA_TYPE}_subfolder 或 ${DATA_TYPE}_folder 列" >&2
    echo "  可用列: ${COLS[*]}" >&2
    exit 1
fi

echo "=== 复制 $DATA_TYPE 数据 ==="
COUNT=0

while IFS=$'\t' read -ra ROW; do
    sub="${ROW[$SUB_IDX]}"
    [ "$sub" = "participant_id" ] && continue

    ses="${ROW[$SES_IDX]}"
    source="${ROW[$SOURCE_IDX]}"

    # 跳过空值
    [ -z "$source" ] && continue

    # 确定源路径
    if [ $FOLDER_IDX -ge 0 ]; then
        # 可能是 DICOM 子目录或独立目录
        dicom="${ROW[$FOLDER_IDX]}"
        if [ -d "$PROJECT_DIR/$dicom/$source" ]; then
            src="$PROJECT_DIR/$dicom/$source"
        elif [ -d "$PROJECT_DIR/$source" ]; then
            src="$PROJECT_DIR/$source"
        else
            echo "  警告: $sub $ses — 找不到 $source" >&2
            continue
        fi
    else
        src="$PROJECT_DIR/$source"
    fi

    if [ ! -d "$src" ]; then
        echo "  警告: $sub $ses — 目录不存在: $src" >&2
        continue
    fi

    # 目标路径
    dest="$BIDS_DIR/sourcedata/$sub/$ses/$DATA_TYPE"
    mkdir -p "$dest"
    cp -n "$src"/* "$dest/" 2>/dev/null || true

    file_count=$(ls "$dest" 2>/dev/null | wc -l | tr -d ' ')
    echo "  $sub $ses: $file_count 文件 → $dest"
    COUNT=$((COUNT+1))

done < "$MAPPING"

echo ""
echo "=== 完成: $COUNT 个 session ==="
