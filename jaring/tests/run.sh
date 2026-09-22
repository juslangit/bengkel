#!/usr/bin/env bash
#
# Tests for jaring.
#
# The thing that can quietly go wrong here is not a crash. It is a remesh that
# reports success and hands back something useless: a mesh Quadriflow refused
# and silently left untouched, a normal map baked flat because the rays missed,
# a set of LODs stacked inside one file so the "light" version is heavier than
# what went in. None of those raise anything. So the checks are about the
# result, not the exit code:
#
#   * does the arithmetic on the page match the arithmetic in the remesher
#   * does a real model come out with fewer faces than it went in with
#   * is the normal map real detail rather than a flat sheet
#   * does each LOD get its own file, each lighter than the one above
#   * does the note beside the result say what was done
#
#   jaring/tests/run.sh                   everything
#   jaring/tests/run.sh --quick           skip the Blender run (about a minute)
#
# The Blender part needs Blender; the browser part needs Chrome. Either
# missing is a skip, not a failure.
set -uo pipefail
cd "$(dirname "$0")/.."

WORK="${TMPDIR:-/tmp}/jaring-test"
rm -rf "$WORK"; mkdir -p "$WORK"

BLENDER="${BENGKEL_BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

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

# Something real to work on. Any rigged character will do; this one is the
# smallest that is still a whole figure rather than a prop.
MODEL="${JARING_TEST_MODEL:-$HOME/Desktop/project/game/The Forsaken/docs/character-revamp/models/paladin.glb}"

echo
echo "── starting up ─────────────────────────────────────────────────"

python3 ./server.py --no-open > "$WORK/out.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

READY=""
for _ in $(seq 1 40); do
  READY=$(grep -o '@@JARING-READY@@.*' "$WORK/out.log" 2>/dev/null | head -1)
  [ -n "$READY" ] && break
  sleep 0.25
done
if [ -z "$READY" ]; then
  bad "the server starts and says where it is"
  sed -n '1,20p' "$WORK/out.log"; exit 1
fi
ok "the server starts and says where it is"

LINE="${READY#@@JARING-READY@@}"
PORT=$(printf '%s' "$LINE" | field port)
TOKEN=$(printf '%s' "$LINE" | field token)
BASE="http://127.0.0.1:$PORT"
ORIGIN="http://127.0.0.1:$PORT"
GET()  { curl -s -H "Origin: $ORIGIN" "$BASE$1&t=$TOKEN"; }
POST() { curl -s -m 1800 -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
              -H "Content-Type: application/json" -d "$2" "$BASE$1"; }

[ -n "$PORT" ] && [ "$PORT" != "0" ]
check $? "it reports the port it really bound"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/presets")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request with no token is refused ($CODE)"

echo
echo "── how fine? ───────────────────────────────────────────────────"

COUNT=$(GET "/api/presets?" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["presets"]))')
[ "$COUNT" = "3" ]
check $? "three presets, in centimetres rather than face counts"

# faces = area / side². The page shows this number before the remesh, and the
# remesher works from the same one; if the two ever part company he chooses a
# setting on screen and gets something else.
python3 - "$BASE" "$TOKEN" <<'PY'
import json, sys, urllib.request
base, token = sys.argv[1], sys.argv[2]

def ask(area, cm):
    url = "%s/api/estimate?t=%s&area=%s&quad_cm=%s" % (base, token, area, cm)
    req = urllib.request.Request(url, headers={"Origin": base})
    return json.load(urllib.request.urlopen(req))["faces"]

# 4 m² of surface at 2 cm quads: 4 / 0.0004 = 10,000
assert ask(4.0, 2.0) == 10000, ask(4.0, 2.0)
# halving the quad size quadruples the count, because area goes as the square
assert ask(4.0, 1.0) == 40000, ask(4.0, 1.0)
# and it is clamped at both ends rather than asking Quadriflow for nonsense
assert ask(0.000001, 12.0) == 20
assert ask(10000.0, 0.4) == 500000
PY
check $? "the estimate is area ÷ quad², clamped at both ends"

echo
echo "── the remesh itself ───────────────────────────────────────────"

if [ "${1:-}" = "--quick" ]; then
  skip "the remesh (--quick)"
elif [ ! -x "$BLENDER" ]; then
  skip "the remesh (no Blender at $BLENDER)"
elif [ ! -f "$MODEL" ]; then
  skip "the remesh (no model at $MODEL)"
else
  # A quad size deliberately coarser than the model needs, so the result must
  # be lighter. Anything else is the remesh having quietly not happened.
  OUT=$(POST /api/remesh "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1], "quad_cm": 6.0, "texture": 1024, "lods": 2,
    "bake": True, "symmetry": True, "sharp": True}))' "$MODEL")")

  echo "$OUT" > "$WORK/remesh.json"
  [ "$(printf '%s' "$OUT" | field ok)" = "True" ]
  check $? "a real model goes through the whole chain"

  BEFORE=$(printf '%s' "$OUT" | field before)
  AFTER=$(printf '%s' "$OUT" | field after)
  [ -n "$AFTER" ] && [ "$AFTER" -lt "$BEFORE" ]
  check $? "and comes out lighter ($BEFORE → $AFTER triangles)"

  # The check that matters most, and the one that was missing.
  #
  # Quadriflow returns FINISHED on a mesh that is not watertight and hands
  # back shards: a different shape, at a different size, in a different
  # place. A 1.3 metre paladin came back 8 metres across, and every other
  # check here passed - it was lighter, it had UVs, it had a baked map, it
  # was on disk. A remesh of a thing is the same size as the thing.
  python3 - "$WORK/remesh.json" <<'PY'
import json, sys
answer = json.load(open(sys.argv[1]))
was, now = answer["was"], answer["now"]
for axis, (a, b) in enumerate(zip(now, was)):
    assert abs(a - b) <= 0.05 * b, (
        "axis %d changed from %.3f to %.3f" % (axis, b, a))
PY
  check $? "it comes back the same size it went in"

  HOW=$(printf '%s' "$OUT" | field how)
  [ "$HOW" = "quads" ] || [ "$HOW" = "voxels" ]
  check $? "it says which way it remeshed ($HOW)"

  # A fallback that happens silently is the whole problem, so it has to
  # be said out loud.
  if [ "$HOW" = "voxels" ]; then
    printf '%s' "$OUT" | field notes | grep -q watertight
    check $? "and when it falls back to voxels it says why"
  fi

  GLB=$(printf '%s' "$OUT" | field glb)
  [ -f "$GLB" ]
  check $? "the .glb is on disk"

  # A bake whose rays all missed writes a sheet of one colour, which compresses
  # to almost nothing. Real surface detail does not.
  MAP=$(printf '%s' "$OUT" | field normal)
  SIZE=$(stat -f%z "$MAP" 2>/dev/null || echo 0)
  [ "$SIZE" -gt 20000 ]
  check $? "the normal map holds real detail, not a flat sheet ($((SIZE / 1024)) KB)"

  # Each level in its own file. All of them in one .glb would not be LODs, it
  # would be three copies of the model standing inside one another.
  python3 - "$WORK/remesh.json" <<'PY'
import json, os, sys
answer = json.load(open(sys.argv[1]))
levels = answer["lods"]
assert len(levels) == 3, levels
seen = set()
last = None
for level in levels:
    assert os.path.exists(level["path"]), level["path"]
    assert level["path"] not in seen, "two levels sharing one file"
    seen.add(level["path"])
    if last is not None:
        assert level["tris"] < last, "LOD%d is not lighter than the one above" % level["level"]
    last = level["tris"]
PY
  check $? "each LOD has its own file, each lighter than the one above"

  FOLDER=$(printf '%s' "$OUT" | field folder)
  grep -q "Quad size" "$FOLDER/WHAT-JARING-DID.md" 2>/dev/null
  check $? "and a note beside it says what settings produced it"

  MINE=$(GET "/api/mine?" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["items"]))')
  [ "${MINE:-0}" -gt 0 ]
  check $? "what it made turns up in What I have made ($MINE)"
fi

echo
echo "── a mesh Quadriflow can actually take ─────────────────────────"

# Everything above went down the voxel path, because every model on this
# machine is a downloaded game character and not one of them is closed.
# The quad path needs a watertight lump made for the purpose, or it is
# never tested at all.
if [ "${1:-}" = "--quick" ] || [ ! -x "$BLENDER" ]; then
  skip "the quad path"
else
  "$BLENDER" --background --factory-startup --python tests/make-blob.py \
    -- "$WORK/blob.glb" > "$WORK/blob.log" 2>&1
  [ -f "$WORK/blob.glb" ]
  check $? "a watertight lump is built to remesh ($(grep -o 'BLOB.*' "$WORK/blob.log" | head -1))"

  curl -s -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
       -H "Content-Type: application/json" \
       -d "{\"path\": \"$WORK/blob.glb\"}" "$BASE/api/permit" > /dev/null
  BLOB=$(POST /api/remesh "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1], "quad_cm": 3.0, "texture": 1024, "lods": 0,
    "bake": True, "symmetry": True, "sharp": True}))' "$WORK/blob.glb")")
  echo "$BLOB" > "$WORK/blob.json"

  [ "$(printf '%s' "$BLOB" | field how)" = "quads" ]
  check $? "a closed surface is remeshed in quads, not voxels"

  python3 - "$WORK/blob.json" <<'PY'
import json, sys
answer = json.load(open(sys.argv[1]))
assert answer["ok"], answer.get("problems")
for a, b in zip(answer["now"], answer["was"]):
    assert abs(a - b) <= 0.05 * b, (answer["was"], answer["now"])
assert answer["after"] < answer["before"], (answer["before"], answer["after"])
PY
  check $? "and it too comes back lighter and the same size"
fi

echo
echo "── the page ────────────────────────────────────────────────────"

if [ ! -x "$CHROME" ]; then
  skip "the page (no Chrome)"
elif [ ! -f "$MODEL" ]; then
  skip "the page (no model at $MODEL)"
else
  ENC=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$MODEL")
  node tests/run-browser.mjs "$BASE/?t=$TOKEN&model=$ENC" tests/app.smoke.mjs
  check $? "the page, driven the way a person drives it"
fi

echo
echo "────────────────────────────────────────────────────────────────"
printf '  %d passed, %d failed' "$PASS" "$FAIL"
[ "$SKIP" -gt 0 ] && printf ', %d skipped' "$SKIP"
echo
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
