#!/bin/bash
# ChordPro Maker launcher: starts the local server (if it isn't running) and opens it in your browser.
# Everything it uses lives in the folder this app sits in. The server quits by itself after the tab is closed.
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PY="$ROOT/.venv/bin/python"
RUN="$ROOT/.run"; mkdir -p "$RUN"
exec 2>>"$RUN/launcher.log"; echo "--- $(date) launched: \$0=$0 ROOT=$ROOT" >>"$RUN/launcher.log"
say()   { /usr/bin/osascript -e "display notification \"$1\" with title \"ChordPro Maker\"" >/dev/null 2>&1; }
alert() { /usr/bin/osascript -e "display alert \"ChordPro Maker\" message \"$1\" as critical" >/dev/null 2>&1; }

if [ ! -d "$ROOT/chordpro_maker" ]; then
  alert "Can't find the ChordPro Maker project next to this app. Keep the app inside the project folder."; exit 1
fi

# the private Python environment can break if the folder was moved or copied: rebuild it from requirements.txt
if ! "$PY" -c "import fitz, docx" >/dev/null 2>&1; then
  say "First-time setup - this can take a few minutes..."
  BASEPY="$(command -v python3 || echo /usr/bin/python3)"
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x "$c" ] && BASEPY="$c" && break; done
  rm -rf "$ROOT/.venv"
  if ! { "$BASEPY" -m venv "$ROOT/.venv" && "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"; } >"$RUN/setup.log" 2>&1; then
    alert "Setup failed (it needs an internet connection the first time). Details: .run/setup.log in the project folder."; exit 1
  fi
fi

url_if_running() {   # prints the URL if our server answers on the recorded port
  local p; p="$(cat "$RUN/port" 2>/dev/null)"
  [ -n "$p" ] && /usr/bin/curl -s -m 2 "http://127.0.0.1:$p/" 2>/dev/null | grep -q "<title>ChordPro Maker" && echo "http://127.0.0.1:$p/"
}

URL="$(url_if_running)"
if [ -z "$URL" ]; then
  rm -f "$RUN/port"
  cd "$ROOT" && nohup "$PY" -m chordpro_maker serve --no-browser --auto-quit >>"$RUN/server.log" 2>&1 &
  for i in $(seq 1 60); do URL="$(url_if_running)"; [ -n "$URL" ] && break; sleep 0.5; done
fi
if [ -z "$URL" ]; then alert "The server didn't start. See .run/server.log in the project folder."; exit 1; fi
[ -z "$CPM_NO_OPEN" ] && /usr/bin/open "$URL"
exit 0
