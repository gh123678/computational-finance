#!/bin/bash
# wind-allskill 测试运行器：读取 cases 文件（每行：id|server|tool|params_json），逐个调用 CLI 并记录结果
# 用法: bash runner.sh <cases_file> <out_dir>
CLI="C:/Users/Admin/AppData/Roaming/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/plugins/managed/wind-allskill/skills/wind-mcp-skill/scripts/cli.mjs"
CASES="$1"
OUT="$2"
mkdir -p "$OUT"
SUMMARY="$OUT/summary.tsv"
: > "$SUMMARY"
while IFS='|' read -r id server tool params; do
  [ -z "$id" ] && continue
  case "$id" in \#*) continue;; esac
  start=$(date +%s%3N)
  node "$CLI" call "$server" "$tool" "$params" > "$OUT/$id.out" 2> "$OUT/$id.err"
  code=$?
  end=$(date +%s%3N)
  dur=$((end - start))
  size=$(wc -c < "$OUT/$id.out" | tr -d ' ')
  echo -e "$id\t$server/$tool\texit=$code\t${dur}ms\tout=${size}B" | tee -a "$SUMMARY"
done < "$CASES"
