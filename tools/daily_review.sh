#!/usr/bin/env bash
# Generate a visual contact sheet for a given day's screenshots
# Usage: ./daily_review.sh YYYYMMDD [interval_minutes] [--open]
#
# Examples:
#   ./daily_review.sh 20260320          # Every 5 minutes (default)
#   ./daily_review.sh 20260320 10       # Every 10 minutes
#   ./daily_review.sh 20260320 10 --open  # Open after generating
#
# Gaps (computer off/asleep) show as dark placeholders with timestamp.

DATE="${1:?Usage: daily_review.sh YYYYMMDD [interval_minutes] [--open]}"
INTERVAL="${2:-5}"
OPEN_AFTER=false
[[ "$*" == *"--open"* ]] && OPEN_AFTER=true
SCREENSHOTS_DIR="/Users/colinwillson/Repositories/time-monitor/screenshots"
OUTPUT_DIR="/Users/colinwillson/Repositories/work-tracker/reviews"
THUMB_DIR=$(mktemp -d)

START_HOUR=7
END_HOUR=22
COLS=6

mkdir -p "$OUTPUT_DIR"

# Find source directory
if [ -d "$SCREENSHOTS_DIR/$DATE" ]; then
    SRC_DIR="$SCREENSHOTS_DIR/$DATE"
else
    SRC_DIR="$SCREENSHOTS_DIR"
fi

# Build a lookup file: slot_minute -> filepath
SLOT_MAP="$THUMB_DIR/slot_map.txt"
> "$SLOT_MAP"
TOTAL=0

for f in "$SRC_DIR"/${DATE}_*.png; do
    [ -f "$f" ] || continue
    TOTAL=$((TOTAL + 1))

    basename_f=$(basename "$f" .png)
    time_part="${basename_f#${DATE}_}"
    hour=$((10#${time_part:0:2}))
    minute=$((10#${time_part:2:2}))

    [ "$hour" -lt "$START_HOUR" ] && continue
    [ "$hour" -ge "$END_HOUR" ] && continue

    total_min=$(( hour * 60 + minute ))
    slot_min=$(( total_min - (total_min % INTERVAL) ))

    # Only keep first match per slot
    if ! grep -q "^${slot_min} " "$SLOT_MAP" 2>/dev/null; then
        echo "${slot_min} ${f}" >> "$SLOT_MAP"
    fi
done

echo "Found $TOTAL screenshots for $DATE"

# Get dimensions from a sample screenshot for placeholders
SAMPLE_FILE=$(head -1 "$SLOT_MAP" | cut -d' ' -f2-)
if [ -z "$SAMPLE_FILE" ]; then
    echo "No screenshots in working hours"
    rm -rf "$THUMB_DIR"
    exit 1
fi

# Get scaled height (width will be 480)
ORIG_W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$SAMPLE_FILE")
ORIG_H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$SAMPLE_FILE")
THUMB_W=480
THUMB_H=$(( ORIG_H * THUMB_W / ORIG_W ))

echo "Creating thumbnails (${THUMB_W}x${THUMB_H})..."
INDEX=0
FILLED=0
GAPS=0

for ((min=START_HOUR*60; min<END_HOUR*60; min+=INTERVAL)); do
    slot_hour=$((min / 60))
    slot_min=$((min % 60))
    printf -v timestamp "%02d\\:%02d" "$slot_hour" "$slot_min"
    printf -v padded "%04d" "$INDEX"

    # Look up file for this slot
    MATCH=$(grep "^${min} " "$SLOT_MAP" | head -1 | cut -d' ' -f2-)

    if [ -n "$MATCH" ] && [ -f "$MATCH" ]; then
        ffmpeg -y -i "$MATCH" \
            -vf "scale=${THUMB_W}:${THUMB_H},drawtext=text='${timestamp}':x=10:y=10:fontsize=28:fontcolor=white:borderw=2:bordercolor=black" \
            -update 1 -frames:v 1 \
            "$THUMB_DIR/thumb_${padded}.jpg" 2>/dev/null
        FILLED=$((FILLED + 1))
    else
        ffmpeg -y -f lavfi -i "color=c=0x1a1a1a:s=${THUMB_W}x${THUMB_H}:d=0.04" \
            -vf "drawtext=text='${timestamp}':x=(w-text_w)/2:y=(h/2)-20:fontsize=32:fontcolor=0x666666,drawtext=text='No Screenshot':x=(w-text_w)/2:y=(h/2)+15:fontsize=20:fontcolor=0x555555" \
            -update 1 -frames:v 1 \
            "$THUMB_DIR/thumb_${padded}.jpg" 2>/dev/null
        GAPS=$((GAPS + 1))
    fi

    INDEX=$((INDEX + 1))
done

echo "Slots: $INDEX ($FILLED with screenshots, $GAPS gaps)"

# Pad last row if needed
REMAINDER=$((INDEX % COLS))
if [ "$REMAINDER" -ne 0 ]; then
    PAD_COUNT=$((COLS - REMAINDER))
    for ((p=0; p<PAD_COUNT; p++)); do
        idx=$((INDEX + p))
        printf -v padded "%04d" "$idx"
        ffmpeg -y -f lavfi -i "color=c=0x333333:s=${THUMB_W}x${THUMB_H}:d=0.04" \
            -update 1 -frames:v 1 \
            "$THUMB_DIR/thumb_${padded}.jpg" 2>/dev/null
    done
    INDEX=$((INDEX + PAD_COUNT))
fi

ROWS=$((INDEX / COLS))
OUTPUT="$OUTPUT_DIR/review_${DATE}.jpg"

echo "Assembling ${COLS}x${ROWS} grid..."

# Build each row with hstack
ROW_LIST="$THUMB_DIR/row_list.txt"
> "$ROW_LIST"

for ((row=0; row<ROWS; row++)); do
    ROW_INPUTS=""
    for ((col=0; col<COLS; col++)); do
        idx=$((row * COLS + col))
        printf -v padded "%04d" "$idx"
        ROW_INPUTS="$ROW_INPUTS -i $THUMB_DIR/thumb_${padded}.jpg"
    done

    ffmpeg -y $ROW_INPUTS \
        -filter_complex "hstack=inputs=${COLS}" \
        -update 1 -frames:v 1 \
        "$THUMB_DIR/row_${row}.jpg" 2>/dev/null

    [ -f "$THUMB_DIR/row_${row}.jpg" ] && echo "$THUMB_DIR/row_${row}.jpg" >> "$ROW_LIST"
done

ROW_COUNT=$(wc -l < "$ROW_LIST" | tr -d ' ')

# Stack all rows vertically
if [ "$ROW_COUNT" -eq 1 ]; then
    cp "$(head -1 "$ROW_LIST")" "$OUTPUT"
elif [ "$ROW_COUNT" -gt 1 ]; then
    VINPUTS=""
    while IFS= read -r rf; do
        VINPUTS="$VINPUTS -i $rf"
    done < "$ROW_LIST"

    ffmpeg -y $VINPUTS \
        -filter_complex "vstack=inputs=${ROW_COUNT}" \
        -update 1 -frames:v 1 \
        "$OUTPUT" 2>/dev/null
fi

if [ -f "$OUTPUT" ]; then
    SIZE=$(ls -lh "$OUTPUT" | awk '{print $5}')
    echo "Done! $OUTPUT ($SIZE)"
    [ "$OPEN_AFTER" = true ] && open "$OUTPUT"
else
    echo "Failed to create contact sheet"
fi

rm -rf "$THUMB_DIR"
