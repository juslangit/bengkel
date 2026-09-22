#!/usr/bin/env bash
#
# Tests for bengkel.
#
# bengkel has no engine of its own, so there is nothing here about joints or
# keyframes — boneka and gerak have their own suites for that. What is tested
# is only what bengkel adds, which is exactly what breaks when two programs
# are made to live in one window:
#
#   * does it read its tool list and draw a door for each
#   * does a tool start when you ask for it, on a port it chose
#   * does everything stop when the window closes
#   * does a file handed from one tool arrive in the other
#   * does a piece of work get remembered, and can it be opened again
#
#   tests/run.sh                build it first, then test
#   tests/run.sh --no-build     test whatever is already built
#
set -uo pipefail
cd "$(dirname "$0")/.."

APP="native/build/bengkel.app"
BIN="$APP/Contents/MacOS/bengkel"
LOG="$HOME/Library/Logs/bengkel.log"
PIECES="$HOME/Documents/bengkel/pieces.json"
WORK="${TMPDIR:-/tmp}/bengkel-test"
mkdir -p "$WORK"

PASS=0
FAIL=0
ok()    { printf '  ok   %s\n' "$*"; PASS=$((PASS + 1)); }
bad()   { printf '  FAIL %s\n' "$*"; FAIL=$((FAIL + 1)); }
check() { if [ "$1" = "0" ]; then ok "$2"; else bad "$2"; fi; }

quiet() { pkill -f "MacOS/bengkel" 2>/dev/null; sleep 1; }

# Run bengkel with a script, wait for it to photograph itself and quit.
run_app() {                       # run_app <seconds> [extra args...]
  local wait_for="$1"; shift
  rm -f "$LOG" "$WORK/shot.png"
  "$BIN" --shot "$WORK/shot.png" "$wait_for" "$@" > /dev/null 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 $pid 2>/dev/null && [ $waited -lt 90 ]; do
    sleep 1; waited=$((waited + 1))
  done
  wait $pid 2>/dev/null
}

if [ "${1:-}" != "--no-build" ]; then
  native/build.sh > "$WORK/build.log" 2>&1
  check $? "the app builds"
  grep -q "satisfies its Designated Requirement" "$WORK/build.log"
  check $? "and its signature verifies"
fi

quiet

echo
echo "── the bundle ──────────────────────────────────────────────────"

[ -x "$BIN" ];                                  check $? "there is an executable"
[ -f "$APP/Contents/Resources/tools.json" ];    check $? "the tool list is inside it"
[ -f "$APP/Contents/Resources/web/home.html" ]; check $? "so is the studio page"
[ -f "$APP/Contents/Resources/bengkel.icns" ];  check $? "so is the icon"
plutil -lint "$APP/Contents/Info.plist" > /dev/null 2>&1
check $? "the Info.plist is valid"

# bengkel carries no copy of the tools: it runs them where they live, so a
# change to either is live the next time bengkel starts.
[ ! -d "$APP/Contents/Resources/blender" ]
check $? "it carries no copy of a tool's engine"

python3 -c "
import json, os, sys
d = json.load(open('$APP/Contents/Resources/tools.json'))
missing = [t['id'] for t in d['tools']
           if not os.path.exists(os.path.expanduser(t['root']) + '/' + t['server'])]
sys.exit(1 if missing else 0)"
check $? "every tool it lists is actually on the disk"

echo
echo "── starting and stopping ───────────────────────────────────────"

run_app 8
grep -q "tools: boneka, gerak" "$LOG"
check $? "it reads its tool list"
[ -f "$WORK/shot.png" ]
check $? "the studio screen renders"
grep -qE "boneka: started|gerak: started" "$LOG"
if [ $? -eq 0 ]; then bad "a tool was started before it was asked for"
else ok "no tool is started until you open one — boneka holds a Blender open, and that can wait"; fi

echo
echo "── opening a tool ──────────────────────────────────────────────"

run_app 14 --open gerak
grep -q "gerak: started" "$LOG";        check $? "opening gerak starts its server"
grep -q "gerak: ready on port" "$LOG"
check $? "$(grep -o 'gerak: ready on port [0-9]*' "$LOG" | head -1) — a port the system chose, not gerak's usual one"
grep -q "gerak: shut down" "$LOG";      check $? "and it stops when bengkel does"

sleep 2
pgrep -f "bengkel/gerak/server.py" > /dev/null 2>&1
if [ $? -eq 0 ]; then bad "a tool server was left running"; else ok "nothing was left running"; fi

echo
echo "── carrying a model from one tool to the other ─────────────────"

MODEL=$(ls "$HOME"/Desktop/project/3d/bengkel/boneka/sessions/*.glb 2>/dev/null | head -1)
if [ -n "$MODEL" ]; then
  MODEL_JS=$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$MODEL")
  rm -f "$PIECES"
  run_app 26 --js "
    return (async () => {
      for (let i = 0; i < 100 && !window.bengkel; i++) await new Promise(r => setTimeout(r, 100));
      if (!window.bengkel) return 'NO BRIDGE';
      const tools = await window.bengkel.tools();
      await window.bengkel.handOver('gerak', $MODEL_JS, 'a test piece');
      await new Promise(r => setTimeout(r, 6000));
      const pieces = await window.bengkel.pieces();
      return JSON.stringify({ tools: tools.map(t => t.id), pieces: pieces.length,
                              named: pieces[0] && pieces[0].name });
    })()"

  answer=$(grep "SCRIPT RESULT" "$LOG" | tail -1)
  echo "$answer" | grep -q '"tools":\["boneka","gerak"\]'
  check $? "the bridge reports both tools: ${answer#*SCRIPT RESULT: }"
  grep -q "→ gerak: $(basename "$MODEL")" "$LOG"
  check $? "bengkel carried $(basename "$MODEL") to gerak"
  grep -q "handed $(basename "$MODEL") to gerak" "$LOG"
  check $? "and gerak took it"

  echo
  echo "── remembering what you are making ─────────────────────────────"

  echo "$answer" | grep -q '"pieces":1'
  check $? "a hand-off is remembered as a piece of work"
  echo "$answer" | grep -q '"named":"a test piece"'
  check $? "under the name it was given"
  [ -f "$PIECES" ]
  check $? "written where you can read it: ~/Documents/bengkel/pieces.json"
  python3 -c "
import json, sys
d = json.load(open('$PIECES'))
sys.exit(0 if d and d[0]['trail'] and d[0]['trail'][0]['what'].startswith('sent it to') else 1)"
  check $? "with a note of what happened to it"
  rm -f "$PIECES"
else
  echo "  --   skipped: boneka has made no models to carry"
fi

echo
[ $FAIL -eq 0 ] && echo "$PASS passed, everything green" || echo "$PASS passed, $FAIL failed"
exit $FAIL
