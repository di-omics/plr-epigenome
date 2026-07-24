#!/usr/bin/env bash
#
# Run a hamilton-star script on the Pi-controlled Hamilton STAR, from this repo.
#
# Dev lives here in plr-epigenome. This script syncs the hamilton-star/ tree to a
# dedicated run directory on the Pi and executes the chosen script in the
# existing PyLabRobot venv. It never writes to the Pi's own ~/star-lab working
# directory, so live work there is not clobbered.
#
# Usage:
#   ./run_on_pi.sh <script-path-relative-to-hamilton-star> [args...]
#
# Examples:
#   ./run_on_pi.sh starlab_live/test_star_no_autoload.py
#   ./run_on_pi.sh starlab_live/01_pcr_enrichment_round1_mastermix_col1.py --mode deck
#
# Safety: many scripts move the deck. Confirm the deck and area are clear before
# running anything that homes, aspirates, or moves plates.

set -euo pipefail

PI="${PI:-starpi}"                 # ssh alias, see ~/.ssh/config
VENV="${VENV:-\$HOME/star-lab/env}"   # existing PyLabRobot venv on the Pi
REMOTE="${REMOTE:-plr-epigenome-run}"   # dedicated run dir on the Pi (not ~/star-lab)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <script-relative-to-hamilton-star> [args...]" >&2
  exit 2
fi
SCRIPT="$1"; shift

if [ ! -f "$HERE/$SCRIPT" ]; then
  echo "error: $SCRIPT not found under $HERE" >&2
  exit 2
fi

echo "[run_on_pi] sync $HERE/ -> $PI:~/$REMOTE/"
rsync -a --delete \
  --exclude 'env' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  -e ssh "$HERE/" "$PI:$REMOTE/"

echo "[run_on_pi] run $SCRIPT on $PI"
ssh "$PI" "source $VENV/bin/activate && cd ~/$REMOTE && python '$SCRIPT' $*"
