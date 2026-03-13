#!/usr/bin/env bash
# run_all.sh — Regenerate all logos from high-quality sources and push to GitHub.
#
# Pipeline:
#   1. Wikimedia Commons scraper  — SVG logos (best quality, no scaling artefacts)
#   2. Logodix scraper            — high-res PNGs for brands wikimedia missed
#   3. process_logos              — rebuild original / optimized / thumb variants
#   4. git commit & push
#
# Options (passed through to the scrapers):
#   --force   Re-download logos that already have a logo.png in dataset/
#   --pause N Override default API pause (seconds between requests)
#
# Usage:
#   bash run_all.sh           # skip brands that already have logo.png
#   bash run_all.sh --force   # replace everything with freshly downloaded logos

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---- activate python environment ----
source .venv/bin/activate

FORCE=""
PAUSE_WIKI="0.5"
PAUSE_LOGODIX="1.0"

for arg in "$@"; do
  case "$arg" in
    --force) FORCE="--force" ;;
    --pause) ;;  # handled below
  esac
done

echo "========================================"
echo "  1/4 Wikimedia Commons scraper (SVG)"
echo "========================================"
python scrapers/wikimedia_scraper.py \
    --brands-file brands-list.txt \
    --dataset-dir dataset \
    --pause "$PAUSE_WIKI" \
    $FORCE

echo ""
echo "========================================"
echo "  2/4 Logodix scraper (fallback)"
echo "========================================"
# Logodix only fills in brands that wikimedia missed (no --force by default
# even when the outer script has --force, because wikimedia results are better).
python scrapers/logodix_scraper.py \
    --brands-file brands-list.txt \
    --dataset-dir dataset \
    --pause "$PAUSE_LOGODIX"

echo ""
echo "========================================"
echo "  3/4 Regenerate all logo variants"
echo "========================================"
python tools/process_logos.py --force

echo ""
echo "========================================"
echo "  4/4 Git commit & push"
echo "========================================"
git add logos/ dataset/ brands-list.txt scrapers/wikimedia_scraper.py scrapers/logodix_scraper.py
git diff --cached --quiet && echo "Nothing to commit." && exit 0

git commit -m "chore: regenerate logos with SVG sources (wikimedia + logodix)"
git push origin main

echo ""
echo "======================================== Done ========================================"
