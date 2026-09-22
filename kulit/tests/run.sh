#!/usr/bin/env bash
#
# Tests for kulit.
#
# What can go wrong here is not a crash either. It is a model that comes back
# looking dressed and is not: a colour lost on export because the wrong node
# was used, a texture that never made it into the file, a part silently
# skipped, or — the one that matters most — a Texturelabs photograph shipped
# inside a .glb with nothing saying it must not be handed on.
#
#   kulit/tests/run.sh                everything
#   kulit/tests/run.sh --quick        skip the Blender run
#
set -uo pipefail
cd "$(dirname "$0")/.."

WORK="${TMPDIR:-/tmp}/kulit-test"
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

echo
echo "── starting up ─────────────────────────────────────────────────"

python3 ./server.py --no-open > "$WORK/out.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

READY=""
for _ in $(seq 1 40); do
  READY=$(grep -o '@@KULIT-READY@@.*' "$WORK/out.log" 2>/dev/null | head -1)
  [ -n "$READY" ] && break
  sleep 0.25
done
if [ -z "$READY" ]; then
  bad "the server starts and says where it is"
  sed -n '1,20p' "$WORK/out.log"; exit 1
fi
ok "the server starts and says where it is"

LINE="${READY#@@KULIT-READY@@}"
PORT=$(printf '%s' "$LINE" | field port)
TOKEN=$(printf '%s' "$LINE" | field token)
BASE="http://127.0.0.1:$PORT"
ORIGIN="http://127.0.0.1:$PORT"
GET()  { curl -s -H "Origin: $ORIGIN" "$BASE$1&t=$TOKEN"; }
POST() { curl -s -m 1800 -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
              -H "Content-Type: application/json" -d "$2" "$BASE$1"; }

[ -n "$PORT" ] && [ "$PORT" != "0" ]
check $? "it reports the port it really bound"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/surfaces")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request with no token is refused ($CODE)"

echo
echo "── what a thing can be made of ─────────────────────────────────"

SURFACES=$(GET "/api/surfaces?")
COUNT=$(printf '%s' "$SURFACES" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["surfaces"]))')
[ "$COUNT" -ge 8 ]
check $? "there are surfaces to choose from ($COUNT)"

# A surface with no photograph behind it would come out as flat colour, and
# the page has to know that before he picks it rather than after.
printf '%s' "$SURFACES" | python3 -c 'import json,sys
d = json.load(sys.stdin)
for s in d["surfaces"]:
    assert ("ready" in s) and isinstance(s["ready"], bool), s
    assert s["about"], s
    if s["photographs"]:
        assert s["ready"], s
assert any(s["ready"] for s in d["surfaces"]), "no surface has a photograph"'
check $? "each says whether there is really a photograph behind it"

PALETTES=$(GET "/api/palettes?" | python3 -c 'import json,sys
d = json.load(sys.stdin)["palettes"]
assert d, "no palettes"
for p in d:
    assert p["colors"], p
print(len(d))')
check $? "the colours come from the palettes boneka already has ($PALETTES)"

echo
echo "── dressing something ──────────────────────────────────────────"

MODEL="${KULIT_TEST_MODEL:-}"
if [ -z "$MODEL" ]; then
  # Whatever jaring made most recently: a clean grey mesh with no colour at
  # all is exactly what this stage is for.
  MODEL=$(find "$HOME/Documents/bengkel/jaring/out" -maxdepth 2 -name '*.glb' \
          ! -name '*_LOD*' 2>/dev/null | head -1)
fi

if [ "${1:-}" = "--quick" ]; then
  skip "dressing (--quick)"
elif [ ! -x "$BLENDER" ]; then
  skip "dressing (no Blender)"
elif [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  skip "dressing (nothing from jaring to dress; set KULIT_TEST_MODEL)"
else
  # The part names have to be the ones in the file, or the page would be
  # choosing colours for parts that do not exist.
  PART=$(python3 - "$MODEL" <<'PY'
import json, struct, sys
data = open(sys.argv[1], "rb").read()
length = struct.unpack("<I", data[12:16])[0]
doc = json.loads(data[20:20 + length])
print((doc.get("nodes") or [{}])[0].get("name", ""))
PY
)
  [ -n "$PART" ]
  check $? "the model's own part names are readable ($PART)"

  OUT=$(POST /api/dress "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1],
    "parts": [{"name": sys.argv[2], "colour": "#3e8948",
               "surface": "wood", "scale": 2.0}]}))' "$MODEL" "$PART")")
  echo "$OUT" > "$WORK/dress.json"

  [ "$(printf '%s' "$OUT" | field ok)" = "True" ]
  check $? "a model goes through Blender and comes back dressed"

  GLB=$(printf '%s' "$OUT" | field glb)
  [ -f "$GLB" ]
  check $? "the .glb is on disk"

  # The two things that go wrong quietly on export. glTF stores a base colour
  # as a factor times a texture, and only one node shape survives; the legacy
  # mix node is ignored, which loses the colour and leaves everything grey.
  python3 - "$GLB" <<'PY'
import json, struct, sys
data = open(sys.argv[1], "rb").read()
length = struct.unpack("<I", data[12:16])[0]
doc = json.loads(data[20:20 + length])

materials = doc.get("materials") or []
assert materials, "the file has no materials at all"

pbr = (materials[0].get("pbrMetallicRoughness") or {})
factor = pbr.get("baseColorFactor")
assert factor, "no baseColorFactor - the colour was lost on export"
assert not all(abs(c - 1.0) < 1e-3 for c in factor[:3]), (
    "the base colour is plain white, so the colour did not survive")

assert pbr.get("baseColorTexture") is not None, "no colour texture in the file"
assert materials[0].get("normalTexture") is not None, "no normal map in the file"
assert doc.get("images"), "no images embedded at all"
PY
  check $? "the colour, the detail map and the normal map are all really in it"

  FOLDER=$(printf '%s' "$OUT" | field folder)

  # The one that matters beyond this machine. Texturelabs allows a texture
  # inside a finished game and forbids handing over a model somebody can pull
  # it back out of, and that obligation has to travel with the file.
  grep -q "cannot be distributed or sold as part of a 3D model" \
       "$FOLDER/WHAT-IS-IN-IT.md" 2>/dev/null
  check $? "the licence restriction is written down beside the result"

  MINE=$(GET "/api/mine?" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["items"]))')
  [ "${MINE:-0}" -gt 0 ]
  check $? "what it dressed turns up in What I have dressed ($MINE)"

  # A part nobody named must be left alone rather than painted a default.
  BAD=$(POST /api/dress "$(python3 -c 'import json,sys;print(json.dumps({
    "path": sys.argv[1],
    "parts": [{"name": "no-such-part", "colour": "#ffffff",
               "surface": "wood", "scale": 1.0}]}))' "$MODEL")")
  [ "$(printf '%s' "$BAD" | field ok)" != "True" ]
  check $? "naming a part that is not there is refused, not ignored"
fi

echo
echo "── the page ────────────────────────────────────────────────────"

if [ ! -x "$CHROME" ]; then
  skip "the page (no Chrome)"
elif [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
  skip "the page (no model to open)"
else
  ENC=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$MODEL")
  node ../jaring/tests/run-browser.mjs "$BASE/?t=$TOKEN&model=$ENC" tests/app.smoke.mjs
  check $? "the page, driven the way a person drives it"
fi

echo
echo "────────────────────────────────────────────────────────────────"
printf '  %d passed, %d failed' "$PASS" "$FAIL"
[ "$SKIP" -gt 0 ] && printf ', %d skipped' "$SKIP"
echo
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
