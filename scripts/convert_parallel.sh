#!/usr/bin/env bash
# convert_parallel.sh — 从 participants_mapping.tsv 并行执行 dcm2bids
#
# 用法:
#   bash convert_parallel.sh <project_dir> [--rerun sub-XX ses-YY ...]
#
# 模式:
#   全量转换:  bash convert_parallel.sh /data/MonoDep
#   选择性重跑: bash convert_parallel.sh /data/MonoDep --rerun sub-01 ses-pre sub-03 ses-pre
#
# 重跑策略:
#   修改 config 后需要重跑时，脚本会：
#   1. 清理目标 session 的 BIDS 输出（防止残留旧文件）
#   2. 保留 tmp 中已有 NIfTI（不加 --force_dcm2bids）
#   3. 重新执行 dcm2bids 匹配
#
#   如果需要从 DICOM 重新转换（dcm2niix 版本更新等），加 --force:
#     bash convert_parallel.sh /data/MonoDep --force

set -euo pipefail

PROJECT_DIR="${1:?用法: convert_parallel.sh <project_dir> [--rerun sub ses ...] [--force]}"
shift

CONFIG="$PROJECT_DIR/code/dcm2bids_config.json"
MAPPING="$PROJECT_DIR/code/participants_mapping.tsv"
BIDS_OUT="$PROJECT_DIR/bids"
LOG_DIR="$PROJECT_DIR/code/logs"

if [ ! -f "$CONFIG" ]; then
    echo "错误: 找不到 $CONFIG" >&2
    exit 1
fi
if [ ! -f "$MAPPING" ]; then
    echo "错误: 找不到 $MAPPING" >&2
    exit 1
fi

# 解析参数
FORCE_FLAG=""
RERUN_MODE=false
declare -a RERUN_PAIRS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --force)
            FORCE_FLAG="--force_dcm2bids"
            shift
            ;;
        --rerun)
            RERUN_MODE=true
            shift
            # 收集后续的 sub ses 对
            while [ $# -gt 0 ] && [[ "$1" != --* ]]; do
                RERUN_PAIRS+=("$1")
                shift
            done
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# 判断是否需要转换该 session
should_convert() {
    local sub="$1" ses="$2"
    if ! $RERUN_MODE; then
        return 0  # 全量模式，全部转换
    fi
    local i=0
    while [ $i -lt ${#RERUN_PAIRS[@]} ]; do
        if [ "${RERUN_PAIRS[$i]}" = "$sub" ] && [ "${RERUN_PAIRS[$((i+1))]}" = "$ses" ]; then
            return 0
        fi
        i=$((i+2))
    done
    return 1
}

# 重跑前清理旧 BIDS 输出
clean_before_rerun() {
    local sub="$1" ses="$2"
    local target="$BIDS_OUT/$sub/$ses"
    if [ -d "$target" ]; then
        echo "清理旧输出: $target"
        rm -rf "$target"
    fi
}

echo "=== 开始转换 ==="
echo "项目: $PROJECT_DIR"
echo "模式: $($RERUN_MODE && echo '选择性重跑' || echo '全量转换')"
[ -n "$FORCE_FLAG" ] && echo "强制重新 dcm2niix: 是"
echo ""

mkdir -p "$LOG_DIR"

declare -a PIDS=()
declare -a LABELS=()
COUNT=0
cd "$PROJECT_DIR"

run_conversion() {
    local sub="$1"
    local ses="$2"
    local folder="$3"
    local log_file="$LOG_DIR/dcm2bids_${sub}_${ses}.log"

    echo "启动: $sub $ses"
    {
        echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
        echo "participant: $sub"
        echo "session: $ses"
        echo "dicom: $folder"
        echo ""
        dcm2bids -d "$folder" -p "$sub" -s "$ses" \
            -c code/dcm2bids_config.json -o bids $FORCE_FLAG
    } >"$log_file" 2>&1
}

while IFS=$'\t' read -r sub ses folder rest; do
    [ "$sub" = "participant_id" ] && continue

    if ! should_convert "$sub" "$ses"; then
        continue
    fi

    # 重跑模式下清理旧输出（保留 tmp）
    if $RERUN_MODE; then
        clean_before_rerun "$sub" "$ses"
    fi

    run_conversion "$sub" "$ses" "$folder" &
    PIDS+=("$!")
    LABELS+=("$sub $ses")

    COUNT=$((COUNT+1))
done < code/participants_mapping.tsv

FAILS=0
for i in "${!PIDS[@]}"; do
    if wait "${PIDS[$i]}"; then
        echo "完成: ${LABELS[$i]}"
    else
        echo "失败: ${LABELS[$i]} (见 code/logs/dcm2bids_${LABELS[$i]// /_}.log)" >&2
        FAILS=$((FAILS+1))
    fi
done

echo ""
echo "=== 完成: $COUNT 个 session ==="

if [ "$FAILS" -gt 0 ]; then
    echo "=== 失败: $FAILS 个 session ===" >&2
    exit 1
fi
