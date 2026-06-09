#!/bin/bash
# AgentIQ loop with reviewer every 5 sessions
# Usage: ./run_with_review.sh [--init] [--project-dir PATH]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${2:-$(pwd)}"
LOG_FILE="$SCRIPT_DIR/loop_log.txt"
FEATURES_FILE="$PROJECT_DIR/features_list.json"
MAX_SESSIONS=100
REVIEW_EVERY=1
SESSION=0
RUN_INIT=false

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --init) RUN_INIT=true ;;
    --project-dir) PROJECT_DIR="$2"; shift ;;
  esac
  shift
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

count_passing() {
  python3 -c "import json; f=json.load(open('$FEATURES_FILE'))['features']; print(len([x for x in f if x['passes']]))"
}

next_feature() {
  python3 -c "
import json
f=json.load(open('$FEATURES_FILE'))['features']
failing=[x for x in f if not x['passes']]
print('ALL_DONE' if not failing else failing[0]['id']+' — '+failing[0]['description'])
"
}

cd "$PROJECT_DIR"

if [ "$RUN_INIT" = true ]; then
  log "Running initializer..."
  claude --print "$(<"$SCRIPT_DIR/INIT_PROMPT.md")" 2>&1 | tee -a "$LOG_FILE"
fi

while true; do
  SESSION=$((SESSION + 1))
  NEXT=$(next_feature)
  PASSING=$(count_passing)

  [ "$NEXT" = "ALL_DONE" ] && { log "ALL DONE: $PASSING/67 features complete"; break; }
  [ "$SESSION" -gt "$MAX_SESSIONS" ] && { log "Max sessions reached"; break; }

  log "Session $SESSION | $PASSING/67 passing | Next: $NEXT"

  # Run coding agent
  PASSING_BEFORE=$PASSING
  claude --print "$(cat "$SCRIPT_DIR/CODING_PROMPT.md")

Current: $PASSING/67 passing. Next: $NEXT" 2>&1 | tee -a "$LOG_FILE"

  # Verify tests still pass
  if ! pytest tests/ -q 2>&1 | tee -a "$LOG_FILE"; then
    log "TESTS FAILED — stopping"
    break
  fi

  # Run reviewer every N sessions
  if (( SESSION % REVIEW_EVERY == 0 )); then
    log "═══ REVIEWER running after session $SESSION ═══"
    claude --print "$(<"$SCRIPT_DIR/REVIEWER_PROMPT.md")" 2>&1 | tee -a "$LOG_FILE"
    log "═══ REVIEWER complete ═══"
  fi

  # Stop if no progress for 2 sessions
  PASSING_NOW=$(count_passing)
  if [ "$PASSING_NOW" -le "$PASSING_BEFORE" ]; then
    NO_PROGRESS=$((${NO_PROGRESS:-0} + 1))
    [ "$NO_PROGRESS" -ge 2 ] && { log "No progress for 2 sessions — stopping"; break; }
  else
    NO_PROGRESS=0
  fi

  sleep 2
done

log "Final: $(count_passing)/67 features complete after $SESSION sessions"
