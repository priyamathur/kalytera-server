#!/bin/bash
# AgentIQ Autonomous Development Loop — Pro Plan Edition
# Optimized for ~45 messages per 8-hour window on Claude Pro
#
# Usage:
#   First run:  ./run_with_review.sh --init
#   Resume:     ./run_with_review.sh
#   Night run:  ./run_with_review.sh --max-sessions 20 &

set -e

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$PROJECT_DIR/loop_log.txt"
PROGRESS="$PROJECT_DIR/claude-progress.txt"
FEATURES="$PROJECT_DIR/features_list.json"
MAX_SESSIONS=20        # Safe default for Pro plan per 8hr window
NO_PROGRESS=0
SESSION=0
RUN_INIT=false

# Categories that get reviewer — only where correctness matters
REVIEW_CATEGORIES="evaluation patterns api"

# Categories that batch together (trivial, no reviewer needed)
BATCH_CATEGORIES="database sdk seed_data deployment"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --init) RUN_INIT=true ;;
    --max-sessions) MAX_SESSIONS="$2"; shift ;;
    --project-dir) PROJECT_DIR="$2"; shift ;;
  esac
  shift
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

count_passing() {
  python3 -c "
import json
f = json.load(open('$FEATURES'))['features']
print(len([x for x in f if x['passes']]))
"
}

next_batch() {
  # Returns up to 3 features if they are in a batch category, else returns 1
  python3 -c "
import json
f = json.load(open('$FEATURES'))['features']
failing = [x for x in f if not x['passes']]
if not failing:
    print('ALL_DONE')
    exit()

batch_cats = '${BATCH_CATEGORIES}'.split()
first = failing[0]

# If trivial category — batch up to 3 together
if first['category'] in batch_cats:
    batch = [x for x in failing if x['category'] == first['category']][:3]
    ids = ', '.join(x['id'] for x in batch)
    descs = '\n'.join(f'  {x[\"id\"]}: {x[\"description\"]}' for x in batch)
    print(f'BATCH|{ids}|{descs}')
else:
    print(f'SINGLE|{first[\"id\"]}|{first[\"id\"]}: {first[\"description\"]}')
"
}

needs_review() {
  local category="$1"
  echo "$REVIEW_CATEGORIES" | grep -qw "$category" && echo "yes" || echo "no"
}

get_category() {
  local feature_id="$1"
  python3 -c "
import json, sys
f = json.load(open('$FEATURES'))['features']
match = [x for x in f if x['id'] == sys.argv[1]]
print(match[0]['category'] if match else 'unknown')
" "$feature_id"
}

mark_done() {
  # Mark one or more feature IDs as passing=true
  python3 -c "
import json, sys
ids = sys.argv[1].split(',')
with open('$FEATURES') as f:
    data = json.load(f)
for feature in data['features']:
    if feature['id'].strip() in [i.strip() for i in ids]:
        feature['passes'] = True
with open('$FEATURES', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Marked done: {ids}')
" "$1"
}

# ── Minimal prompts — tokens matter ──────────────────────────────────────────
coding_prompt() {
  local task="$1"
  local passing="$2"
  cat << PROMPT
Read CLAUDE.md. Read claude-progress.txt last 20 lines.

TASK: $task

RULES:
- Implement only this task. Nothing else.
- Write the test first, then the implementation.
- Run: pytest tests/ -q
- All tests must pass before finishing.
- Update features_list.json: set passes=true for completed feature(s) only.
- Append to claude-progress.txt: "DONE: [ID] | [what you built] | [test name]"
- git commit -am "feat: [ID] [one line description]"

Current: $passing/67 passing.
PROMPT
}

reviewer_prompt() {
  local feature_id="$1"
  cat << PROMPT
Review only: $feature_id

Check:
1. Does the test actually verify the feature — not a mock returning hardcoded data?
2. Does the implementation match the feature description in features_list.json?
3. If SDK: does trace() still return in <5ms and never raise?
4. If eval: does judge use last 3 steps as prior context?
5. Run: pytest tests/ -k "$feature_id" -v

If gap found: append to claude-progress.txt "GAP: $feature_id | [what is wrong] | [fix needed]"
If clean: append "REVIEW OK: $feature_id"
One git commit if you fix anything: "fix: $feature_id [what you fixed]"
PROMPT
}

# ── Safety checks ─────────────────────────────────────────────────────────────
[ ! -f "$FEATURES" ] && { log "ERROR: features_list.json not found"; exit 1; }
command -v claude &>/dev/null || { log "ERROR: claude CLI not found. Run: npm install -g @anthropic-ai/claude-code"; exit 1; }

cd "$PROJECT_DIR"
log "AgentIQ loop starting — max $MAX_SESSIONS sessions"
log "Passing: $(count_passing)/67"

# ── Init ──────────────────────────────────────────────────────────────────────
if [ "$RUN_INIT" = true ]; then
  log "Initializing..."
  claude --print "$(cat << 'INIT'
Read CLAUDE.md fully.
Run: alembic upgrade head
Run: pytest tests/ -q
Write claude-progress.txt with: date, passing count, first failing feature ID.
git commit -am "init: development loop initialized"
Print: INIT COMPLETE
INIT
)" 2>&1 | tee -a "$LOG"
  log "Init done. Starting loop."
fi

# ── Main loop ─────────────────────────────────────────────────────────────────
while true; do
  SESSION=$((SESSION + 1))
  PASSING=$(count_passing)
  NEXT_RAW=$(next_batch)

  # Done?
  [ "$NEXT_RAW" = "ALL_DONE" ] && {
    log "ALL 67 FEATURES COMPLETE ✓"
    pytest tests/ -q 2>&1 | tee -a "$LOG"
    break
  }

  # Max sessions?
  [ "$SESSION" -gt "$MAX_SESSIONS" ] && {
    log "Max sessions ($MAX_SESSIONS) reached. $PASSING/67 complete."
    log "Resume tomorrow: ./run_with_review.sh"
    break
  }

  # Parse next task
  MODE=$(echo "$NEXT_RAW" | cut -d'|' -f1)
  IDS=$(echo "$NEXT_RAW" | cut -d'|' -f2)
  TASK=$(echo "$NEXT_RAW" | cut -d'|' -f3)
  FIRST_ID=$(echo "$IDS" | cut -d',' -f1 | tr -d ' ')
  CATEGORY=$(get_category "$FIRST_ID")

  log "─────────────────────────────────────"
  log "Session $SESSION/$MAX_SESSIONS | $PASSING/67 | $MODE: $IDS"

  # Check for GAP blocker from previous review
  if grep -q "^GAP:" "$PROGRESS" 2>/dev/null; then
    LAST_GAP=$(grep "^GAP:" "$PROGRESS" | tail -1)
    # Only block if it's about current feature
    if echo "$LAST_GAP" | grep -q "$FIRST_ID"; then
      log "BLOCKER on $FIRST_ID: $LAST_GAP"
      log "Fix the gap then resume."
      break
    fi
  fi

  PASSING_BEFORE=$PASSING

  # ── Coding agent ────────────────────────────────────────────────────────────
  log "Coding: $TASK"
  claude --print "$(coding_prompt "$TASK" "$PASSING")" 2>&1 | tee -a "$LOG"

  # ── Tests must pass ─────────────────────────────────────────────────────────
  if ! pytest tests/ -q 2>&1 | tee -a "$LOG"; then
    log "TESTS FAILED after session $SESSION. Stopping."
    log "Fix manually then: ./run_with_review.sh"
    break
  fi

  # ── Reviewer — only for categories that need it ──────────────────────────────
  if [ "$(needs_review "$CATEGORY")" = "yes" ]; then
    log "Reviewing: $FIRST_ID"
    claude --print "$(reviewer_prompt "$FIRST_ID")" 2>&1 | tee -a "$LOG"
  else
    log "Skipping review for $CATEGORY feature (trivial)"
  fi

  # ── Verify progress ──────────────────────────────────────────────────────────
  PASSING_NOW=$(count_passing)
  if [ "$PASSING_NOW" -le "$PASSING_BEFORE" ]; then
    NO_PROGRESS=$((NO_PROGRESS + 1))
    log "WARNING: No progress in session $SESSION ($NO_PROGRESS/2 before stop)"
    [ "$NO_PROGRESS" -ge 2 ] && {
      log "No progress for 2 sessions. Check claude-progress.txt."
      break
    }
  else
    NO_PROGRESS=0
    log "✓ $PASSING_NOW/67 passing"
  fi

  sleep 2
done

# ── Summary ───────────────────────────────────────────────────────────────────
FINAL=$(count_passing)
log "═══════════════════════════════════════"
log "Done. $FINAL/67 features complete. $SESSION sessions used."
log "Remaining: $((67 - FINAL)) features"
[ "$FINAL" -lt 67 ] && log "Resume: ./run_with_review.sh"