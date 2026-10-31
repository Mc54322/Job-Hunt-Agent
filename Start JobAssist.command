#!/bin/bash
# Double-click this file to start JobAssist, then use it in your web browser.
# Keep this window open while you use JobAssist. Close it (or press Ctrl+C) to stop.

cd "$(dirname "$0")" || exit 1
DATA_DIR="$HOME/.jobassist"
LOG_DIR="$DATA_DIR/logs"
BROWSER_MARKER="$DATA_DIR/.browser-installed"
APP_URL="http://localhost:8000"
mkdir -p "$LOG_DIR"

say() { printf '\n%s\n' "$*"; }
fail() {
  say "$1"
  read -r -p "Press Enter to close this window. " _
  exit 1
}

# --- 1. The 'uv' tool that runs JobAssist ------------------------------------
for dir in "$HOME/.local/bin" "$HOME/.cargo/bin" /opt/homebrew/bin /usr/local/bin; do
  [ -x "$dir/uv" ] && PATH="$dir:$PATH"
done
if ! command -v uv >/dev/null 2>&1; then
  say "JobAssist needs a small free tool called 'uv' (from astral.sh) to run."
  read -r -p "Install it now? [y/n] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || fail "JobAssist can't start without uv."
  curl -LsSf https://astral.sh/uv/install.sh | sh || fail "Installing uv failed. Check your internet connection."
  PATH="$HOME/.local/bin:$PATH"
fi

# --- 2. API keys (first run only) --------------------------------------------
env_value() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }
if [ -z "$(env_value ANTHROPIC_API_KEY)" ]; then
  say "First-time setup. JobAssist uses Claude to read job pages and score them against your CV."
  say "Paste your Anthropic API key (from https://console.anthropic.com — it starts with sk-ant-):"
  read -r -s anthropic_key; echo
  [ -n "$anthropic_key" ] || fail "No key entered. Run JobAssist again when you have one."
  say "Optional: free Adzuna keys add many more job listings (https://developer.adzuna.com)."
  read -r -p "Adzuna app ID (press Enter to skip): " adzuna_id
  adzuna_key=""
  [ -n "$adzuna_id" ] && read -r -p "Adzuna app key: " adzuna_key
  read -r -p "Reed API key (optional, https://www.reed.co.uk/developers — Enter to skip): " reed_key
  {
    echo "ANTHROPIC_API_KEY=$anthropic_key"
    [ -n "$adzuna_id" ] && echo "ADZUNA_APP_ID=$adzuna_id" && echo "ADZUNA_APP_KEY=$adzuna_key"
    [ -n "$reed_key" ] && echo "REED_API_KEY=$reed_key"
  } >> .env
  chmod 600 .env
  say "Saved. You won't be asked again (keys are in the .env file in this folder)."
fi

# --- 3. Components and the website-reading browser (first run is slower) -----
say "Getting JobAssist ready…"
uv sync --quiet >"$LOG_DIR/setup.log" 2>&1 \
  || fail "Couldn't install JobAssist's components. Check your internet connection (details: $LOG_DIR/setup.log)."
if [ ! -f "$BROWSER_MARKER" ]; then
  say "One-time setup: installing the browser JobAssist uses to read company websites (a few minutes)…"
  if uv run playwright install chromium >>"$LOG_DIR/setup.log" 2>&1; then
    touch "$BROWSER_MARKER"
  else
    say "Note: the browser didn't install, so some company websites will be skipped."
  fi
fi

# --- 4. Start the services ---------------------------------------------------
pkill -f "uvicorn jobassist.Microservices" 2>/dev/null && sleep 1  # an older JobAssist window

PIDS=()
start_service() {
  uv run --env-file .env uvicorn "jobassist.Microservices.$1.api:app" \
    --host 127.0.0.1 --port "$2" --timeout-graceful-shutdown 3 >"$LOG_DIR/$1.log" 2>&1 &
  PIDS+=($!)
}
stop_services() {
  trap - EXIT INT TERM HUP
  say "Stopping JobAssist…"
  kill "${PIDS[@]}" 2>/dev/null
  sleep 2
  pkill -9 -f "uvicorn jobassist.Microservices" 2>/dev/null
  exit 0
}
trap stop_services EXIT INT TERM HUP

export JOB_RECOMMENDER_URL=http://localhost:8003
start_service job_recommender 8003
start_service web_scraper 8001
start_service data_cleaner 8002
start_service cv_feedback_provider 8004
start_service list_builder 8005
start_service frontend 8000

ready=""
for _ in $(seq 1 60); do
  up=0
  for port in 8000 8001 8002 8003 8005; do
    curl -sf "http://localhost:$port/health" >/dev/null && up=$((up + 1))
  done
  [ "$up" -eq 5 ] && ready=yes && break
  sleep 1
done
[ -n "$ready" ] || fail "JobAssist didn't start. Details are in $LOG_DIR"

open "$APP_URL"
say "JobAssist is running at $APP_URL (it should have opened in your browser)."
say "Keep this window open while you use it. To stop JobAssist, close this window or press Ctrl+C."
wait
