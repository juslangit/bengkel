#!/usr/bin/env bash
#
# Tests for hantar.
#
# hantar is the only tool in the workshop that writes into one of the game
# projects, which makes it the only one that can leave a mess somewhere that
# matters. So two things are tested above all: that it writes where it says it
# will and nowhere else, and that what arrives is really the shape the engine
# asked for.
#
# The deliveries here all go into a throwaway project made for the test and
# deleted afterwards. Nothing in this file touches real work.
#
#   hantar/tests/run.sh                everything
#   hantar/tests/run.sh --quick        skip the Blender runs
#
set -uo pipefail
cd "$(dirname "$0")/.."

WORK="${TMPDIR:-/tmp}/hantar-test"
rm -rf "$WORK"; mkdir -p "$WORK"

BLENDER="${BENGKEL_BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
GAMES="$HOME/Desktop/project/game"
FAKE="$GAMES/zz-hantar-test"

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  ok   %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  FAIL %s\n' "$*"; FAIL=$((FAIL + 1)); }
skip() { printf '  --   %s (skipped)\n' "$*"; SKIP=$((SKIP + 1)); }
check(){ if [ "$1" = "0" ]; then ok "$2"; else bad "$2"; fi; }

field() { python3 -c 'import json,sys
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d[int(k)] if isinstance(d, list) else d.get(k)
    if d is None: print(""); raise SystemExit
print(d if not isinstance(d, (list, dict)) else json.dumps(d))' "$1"; }

# A project of its own to deliver into, so no real one is touched. It is made
# to look like a Godot project with a house style already in it, because
# following a project's existing style is most of what hantar does.
setup_fake() {
  mkdir -p "$FAKE/assets/characters"
  touch "$FAKE/project.godot"
  : > "$FAKE/assets/characters/athlete_average.glb"
  : > "$FAKE/assets/characters/athlete_stocky.glb"
}
teardown_fake() { rm -rf "$FAKE"; }
trap 'teardown_fake; kill ${SERVER:-} 2>/dev/null' EXIT

setup_fake

echo
echo "── starting up ─────────────────────────────────────────────────"

python3 ./server.py --no-open > "$WORK/out.log" 2>&1 &
SERVER=$!

READY=""
for _ in $(seq 1 40); do
  READY=$(grep -o '@@HANTAR-READY@@.*' "$WORK/out.log" 2>/dev/null | head -1)
  [ -n "$READY" ] && break
  sleep 0.25
done
if [ -z "$READY" ]; then
  bad "the server starts and says where it is"
  sed -n '1,20p' "$WORK/out.log"; exit 1
fi
ok "the server starts and says where it is"

LINE="${READY#@@HANTAR-READY@@}"
PORT=$(printf '%s' "$LINE" | field port)
TOKEN=$(printf '%s' "$LINE" | field token)
BASE="http://127.0.0.1:$PORT"
ORIGIN="http://127.0.0.1:$PORT"
GET()  { curl -s -H "Origin: $ORIGIN" "$BASE$1&t=$TOKEN"; }
POST() { curl -s -m 1200 -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
              -H "Content-Type: application/json" -d "$2" "$BASE$1"; }

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/projects")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request with no token is refused ($CODE)"

echo
echo "── reading the projects ────────────────────────────────────────"

PROJECTS=$(GET "/api/projects?")
echo "$PROJECTS" > "$WORK/projects.json"

python3 - "$WORK/projects.json" <<'PY'
import json, sys
found = json.load(open(sys.argv[1]))["projects"]
assert found, "no game projects found at all"
fake = next((p for p in found if p["id"] == "zz-hantar-test"), None)
assert fake, "the test project was not found"
# A project.godot and nothing else is a Godot project, and Godot takes .glb.
assert fake["engine"] == "godot", fake["engine"]
assert fake["format"] == "glb", fake["format"]
PY
check $? "a project's engine is read from the file only that engine leaves"

python3 - "$WORK/projects.json" <<'PY'
import json, sys
found = json.load(open(sys.argv[1]))["projects"]
fake = next(p for p in found if p["id"] == "zz-hantar-test")
best = fake["places"][0]
# It has to find where the project already keeps its models, and follow how
# those files are already spelled. athlete_average.glb is snake_case.
assert best["shown"] == "assets/characters", best
assert best["style"] == "snake", best
assert best["count"] == 2, best
PY
check $? "it finds where a project already keeps models, and how they are spelled"

echo
echo "── saying where it will land, before writing ───────────────────"

enc() { python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$1"; }
WHERE=$(GET "/api/landing?name=$(enc "Walker Walk")&style=snake&engine=godot&into=$(enc "$FAKE/assets/characters")")
[ "$(printf '%s' "$WHERE" | field name)" = "walker_walk.glb" ]
check $? "a name is put into the folder's own style (Walker Walk → $(printf '%s' "$WHERE" | field name))"

[ "$(GET "/api/landing?name=$(enc "walker walk")&style=kebab&engine=godot&into=x" | field name)" = "walker-walk.glb" ]
check $? "kebab where the folder is kebab"
[ "$(GET "/api/landing?name=$(enc "walker walk")&style=pascal&engine=unreal&into=x" | field name)" = "WalkerWalk.fbx" ]
check $? "and Unreal gets .fbx, in that folder's PascalCase"

echo
echo "── what it will not do ─────────────────────────────────────────"

# The one that matters. A page asking for a path outside the game folder must
# not be able to write there, whatever it says.
OUT=$(POST /api/send "{\"path\": \"$HOME/.zshrc\", \"into\": \"$HOME\", \"engine\": \"godot\"}")
printf '%s' "$OUT" | grep -q '"ok": false'
check $? "it refuses to deliver anywhere outside the game folder"

OUT=$(POST /api/send "{\"path\": \"/etc/hosts\", \"into\": \"$FAKE/assets/characters\", \"engine\": \"godot\"}")
printf '%s' "$OUT" | grep -q '"ok": false'
check $? "and refuses to read a file it has no business reading"

echo
echo "── delivering ──────────────────────────────────────────────────"

MODEL="${HANTAR_TEST_MODEL:-}"
if [ -z "$MODEL" ]; then
  MODEL=$(find "$HOME/Documents/bengkel/jaring/out" -maxdepth 2 -name '*.glb' \
          ! -name '*_LOD*' 2>/dev/null | head -1)
fi

if [ "${1:-}" = "--quick" ]; then
  skip "delivering (--quick)"
elif [ ! -x "$BLENDER" ]; then
  skip "delivering (no Blender)"
elif [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  skip "delivering (nothing to deliver; set HANTAR_TEST_MODEL)"
else
  OUT=$(POST /api/send "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1], "into": sys.argv[2], "engine": "godot",
    "style": "snake", "name": "Walker Walk",
    "ground": True, "height": 1.8}))' "$MODEL" "$FAKE/assets/characters")")
  echo "$OUT" > "$WORK/send.json"

  [ "$(printf '%s' "$OUT" | field ok)" = "True" ]
  check $? "a model goes into the project"

  [ -f "$FAKE/assets/characters/walker_walk.glb" ]
  check $? "under the name that folder's own style gives it"

  # The two fixes periksa asks for, actually done rather than reported.
  python3 - "$WORK/send.json" <<'PY'
import json, sys
answer = json.load(open(sys.argv[1]))
now = answer["now"]
assert abs(max(now) - 1.8) < 0.01, ("asked for 1.8 m, got", now)
assert any("floor" in f for f in answer["fixed"]), answer["fixed"]
assert any("1.80" in f for f in answer["fixed"]), answer["fixed"]
PY
  check $? "it is really 1.80 m and really standing on the floor"

  # And the delivered file has to agree, read back from scratch rather than
  # believed because the tool said so.
  python3 - "$FAKE/assets/characters/walker_walk.glb" <<'PY'
import json, struct, sys
data = open(sys.argv[1], "rb").read()
assert data[:4] == b"glTF", "not a .glb at all"
length = struct.unpack("<I", data[12:16])[0]
doc = json.loads(data[20:20 + length])
assert doc.get("meshes"), "the delivered file has no meshes in it"
PY
  check $? "and the file that arrived is a real .glb with a mesh in it"

  grep -q "walker_walk.glb" "$FAKE/assets/characters/WHERE-THESE-CAME-FROM.md"
  check $? "a line is added to the folder's own record of what came from where"

  # Sending the same name twice has to be a question, not a silent overwrite.
  AGAIN=$(POST /api/send "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1], "into": sys.argv[2], "engine": "godot",
    "style": "snake", "name": "Walker Walk"}))' "$MODEL" "$FAKE/assets/characters")")
  [ "$(printf '%s' "$AGAIN" | field exists)" = "True" ]
  check $? "sending over something already there is refused until you say so"

  # Unreal takes .fbx and counts in centimetres.
  FBX=$(POST /api/send "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1], "into": sys.argv[2], "engine": "unreal",
    "style": "pascal", "name": "Walker Walk", "ground": True}))' "$MODEL" "$FAKE/assets/characters")")
  [ "$(printf '%s' "$FBX" | field ok)" = "True" ] && [ -f "$FAKE/assets/characters/WalkerWalk.fbx" ]
  check $? "the same model goes to Unreal as .fbx, in that folder's style"
fi

echo
echo "── the page ────────────────────────────────────────────────────"

if [ ! -x "$CHROME" ]; then
  skip "the page (no Chrome)"
elif [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  skip "the page (nothing to open)"
else
  node ../jaring/tests/run-browser.mjs \
    "$BASE/?t=$TOKEN&model=$(enc "$MODEL")" tests/app.smoke.mjs
  check $? "the page, driven the way a person drives it"
fi

echo
echo "────────────────────────────────────────────────────────────────"
printf '  %d passed, %d failed' "$PASS" "$FAIL"
[ "$SKIP" -gt 0 ] && printf ', %d skipped' "$SKIP"
echo
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
