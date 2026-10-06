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

# The list it should read is whatever tools.json says, not a list written out
# here as well. Two copies of the same list is how a tool gets added to one of
# them and the suite goes on passing without ever opening it.
REGISTERED=$(python3 -c 'import json;print(", ".join(t["id"] for t in json.load(open("tools.json"))["tools"]))')

run_app 8
grep -q "tools: $REGISTERED" "$LOG"
check $? "it reads its tool list ($REGISTERED)"
[ -f "$WORK/shot.png" ]
check $? "the studio screen renders"
grep -qE "$(python3 -c 'import json;print("|".join(t["id"] + ": started" for t in json.load(open("tools.json"))["tools"]))')" "$LOG"
if [ $? -eq 0 ]; then bad "a tool was started before it was asked for"
else ok "no tool is started until you open one — boneka holds a Blender open, and that can wait"; fi

echo
echo "── opening each tool ───────────────────────────────────────────"

# Every tool, not just the convenient one. The first version of this suite
# only ever opened gerak, and boneka shipped advertising port 0 - a page that
# could never load - because nothing here had ever asked for it.
TOOLS=$(python3 -c "
import json
print(' '.join(t['id'] for t in json.load(open('tools.json'))['tools']))")

for tool in $TOOLS; do
  run_app 18 --open "$tool"

  grep -q "$tool: started" "$LOG"
  check $? "opening $tool starts its server"

  port=$(grep -o "$tool: ready on port [0-9]*" "$LOG" | head -1 | awk '{print $NF}')
  { [ -n "$port" ] && [ "$port" != "0" ]; }
  check $? "$tool reports the port it really bound${port:+ ($port)}, not the one it was asked for"

  grep -q "$tool: shut down" "$LOG"
  check $? "and $tool stops when bengkel does"

  sleep 2
  if pgrep -f "bengkel/$tool/server.py" > /dev/null 2>&1; then
    bad "$tool was left running"
  else
    ok "and $tool left nothing running"
  fi
done

echo
echo "── each tool's page really appears ─────────────────────────────"

# A server that is up is not the same as a page that appears. boneka's did
# not, and the log said "ready" the whole time.
for tool in $TOOLS; do
  run_app 22 --open "$tool" --js "
    return (async () => {
      for (let i = 0; i < 200 && document.body.innerText.trim().length < 40; i++) {
        await new Promise(r => setTimeout(r, 100));
      }
      return JSON.stringify({
        bridge: !!window.bengkel,
        words: document.body.innerText.trim().split(/\s+/).length,
      });
    })()"

  answer=$(grep "SCRIPT RESULT" "$LOG" | tail -1)
  echo "$answer" | grep -q '"bridge":true'
  check $? "$tool's page loads inside bengkel and can see it"

  words=$(echo "$answer" | grep -o '"words":[0-9]*' | cut -d: -f2)
  { [ -n "$words" ] && [ "$words" -gt 20 ]; }
  check $? "and $tool's pane has something on it - ${words:-0} words, not blank"
done

echo
echo "── carrying a model from one tool to the other ─────────────────"

MODEL=$(ls "$HOME"/Desktop/projects/3d/bengkel/boneka/sessions/*.glb 2>/dev/null | head -1)
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
  EXPECTED=$(python3 -c 'import json;print(json.dumps([t["id"] for t in json.load(open("tools.json"))["tools"]], separators=(",", ":")))')
  echo "$answer" | grep -qF "\"tools\":$EXPECTED"
  check $? "the bridge reports every tool: ${answer#*SCRIPT RESULT: }"
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
echo "── the assistant, in every tool ────────────────────────────────"

# What is tested here is the machinery, not the model: that every tool really
# hands over an action list, that an action runs and undoes, and that the
# risky ones are marked. Asking claude itself is behind BENGKEL_ASK=1, because
# it takes the best part of a minute and spends his plan's usage.
for tool in $TOOLS; do
  run_app 26 --open "$tool" --js "
    return (async () => {
      const wait = (ms) => new Promise(r => setTimeout(r, ms));
      const a = () => window.bengkel.assistant;
      for (let i = 0; i < 220 && !(a() && a().kit); i++) await wait(100);
      const kit = a() && a().kit;
      if (!kit) return JSON.stringify({ registered: false });

      // Run one action that changes nothing outside the tool, then undo it,
      // and check the tool really went back to where it was.
      const safe = Object.entries(kit.actions).find(([, x]) => !x.risky);
      let ran = null, undone = null;
      if (safe && kit.snapshot) {
        const was = JSON.stringify(kit.snapshot());
        try {
          await a().perform({ action: '__nope__', args: {} });
          ran = a().said[a().said.length - 1].kind;   // must be 'bad', not a throw
        } catch (e) { ran = 'threw'; }
        kit.restore(JSON.parse(was));
        undone = JSON.stringify(kit.snapshot()) === was;
      }

      return JSON.stringify({
        registered: true,
        tool: kit.tool,
        panel: !!document.querySelector('.bk-assist'),
        tab: !!document.querySelector('.bk-assist-tab'),
        actions: Object.keys(kit.actions).length,
        risky: Object.values(kit.actions).filter((x) => x.risky).length,
        described: Object.values(kit.actions).every((x) => typeof x.what === 'string' && x.what),
        snapshot: !!kit.snapshot && !!kit.restore,
        context: typeof kit.context === 'function' && !!kit.context(),
        unknownAction: ran,
        restored: undone,
      });
    })()"

  answer=$(grep "SCRIPT RESULT" "$LOG" | tail -1)
  echo "$answer" | grep -q '"registered":true'
  check $? "$tool gives the assistant an action list"

  if echo "$answer" | grep -q '"registered":true'; then
    n=$(echo "$answer" | grep -o '"actions":[0-9]*' | cut -d: -f2)
    [ "${n:-0}" -ge 1 ]
    check $? "  ...with $n action(s), and the panel on screen"
    echo "$answer" | grep -q '"panel":true.*"tab":true'
    check $? "  ...the floating window is there"
    echo "$answer" | grep -q '"described":true'
    check $? "  ...every action says what it is for"
    echo "$answer" | grep -q '"snapshot":true'
    check $? "  ...it can photograph and restore this tool"
    echo "$answer" | grep -q '"context":true'
    check $? "  ...and it can see what is on screen"
    echo "$answer" | grep -q '"unknownAction":"bad"'
    check $? "  ...an action it does not have is refused, not thrown"
    echo "$answer" | grep -q '"restored":true'
    check $? "  ...and restoring a photograph puts the tool back"
  fi
done

# The reply parser, on the shapes a model actually produces.
run_app 20 --js "
  return (async () => {
    const r = window.bengkel.assistant.readReply;
    const plain = r('{\"say\":\"hello\",\"do\":[{\"action\":\"x\",\"args\":{}}]}');
    const fenced = r('here you go\\n\`\`\`json\\n{\"say\":\"hi\",\"do\":[]}\\n\`\`\`');
    const prose = r('I cannot do that.');
    return JSON.stringify({
      plain: plain.say === 'hello' && plain.do.length === 1,
      fenced: fenced.say === 'hi' && fenced.do.length === 0,
      prose: prose.say === 'I cannot do that.' && prose.do.length === 0,
    });
  })()"
answer=$(grep "SCRIPT RESULT" "$LOG" | tail -1)
echo "$answer" | grep -q '"plain":true'
check $? "a plain JSON reply is understood"
echo "$answer" | grep -q '"fenced":true'
check $? "so is one wrapped in a code fence"
echo "$answer" | grep -q '"prose":true'
check $? "and prose with no JSON in it is shown as it is, not dropped"

if [ "${BENGKEL_ASK:-0}" = "1" ]; then
  echo
  echo "── asking claude for real ──────────────────────────────────────"
  run_app 90 --open gerak --js "
    return (async () => {
      const wait = (ms) => new Promise(r => setTimeout(r, ms));
      const a = () => window.bengkel.assistant;
      for (let i = 0; i < 300 && !(a() && a().kit && window.gerak.state.bones.length); i++) await wait(100);
      await a().ask('move the playhead to frame 12');
      for (let i = 0; i < 500 && a().busy; i++) await wait(100);
      const at = window.gerak.state.frame;
      a().undo();
      return JSON.stringify({ went: at, back: window.gerak.state.frame,
                              depth: a().past.length });
    })()"
  answer=$(grep "SCRIPT RESULT" "$LOG" | tail -1)
  echo "$answer" | grep -q '"went":12'
  check $? "it understood \"move the playhead to frame 12\" and did it"
  echo "$answer" | grep -q '"back":0'
  check $? "and undo put the playhead back"
else
  echo
  echo "  --   BENGKEL_ASK=1 tests/run.sh also asks claude for real (~1 min)"
fi

echo
[ $FAIL -eq 0 ] && echo "$PASS passed, everything green" || echo "$PASS passed, $FAIL failed"
exit $FAIL
