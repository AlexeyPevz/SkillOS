#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_FILE="$ROOT_DIR/.ralph/prompt.md"
PROGRESS_FILE="$ROOT_DIR/.ralph/progress.md"
LAST_MESSAGE_FILE="$ROOT_DIR/.ralph/last_message.txt"

MAX_ITERATIONS="${MAX_ITERATIONS:-20}"
ITERATION=1
DONE_PATTERN='Promise Complete|<promise>DONE</promise>'

# Example:
#   AGENT_CMD="codex"
#   AGENT_ARGS="exec - --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -C /path/to/repo"
AGENT_CMD="${AGENT_CMD:-codex}"
if [ -n "${AGENT_ARGS:-}" ]; then
  read -r -a AGENT_ARGS_ARR <<< "$AGENT_ARGS"
else
  AGENT_ARGS_ARR=(exec - --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -C "$ROOT_DIR" --output-last-message "$LAST_MESSAGE_FILE")
fi

while [ "$ITERATION" -le "$MAX_ITERATIONS" ]; do
  echo "Iteration $ITERATION"

  if [ ! -f "$PROMPT_FILE" ]; then
    echo "Missing prompt file: $PROMPT_FILE"
    exit 1
  fi

  # Feed the prompt on stdin. Codex reads stdin when prompt is "-".
  if ! cat "$PROMPT_FILE" | "$AGENT_CMD" "${AGENT_ARGS_ARR[@]}"; then
    echo "Agent command failed; continuing loop."
  fi

  if [ -f "$PROGRESS_FILE" ] && grep -E -q "$DONE_PATTERN" "$PROGRESS_FILE"; then
    echo "Job Done"
    break
  fi

  if [ -f "$LAST_MESSAGE_FILE" ] && grep -E -q "$DONE_PATTERN" "$LAST_MESSAGE_FILE"; then
    echo "Job Done"
    break
  fi

  ITERATION=$((ITERATION + 1))
done
