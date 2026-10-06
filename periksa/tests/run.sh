#!/usr/bin/env bash
#
# Tests for periksa.
#
# periksa has no Blender behind it and nothing it can break in the world — it
# only reads. So the whole risk is that it reads wrong: says a model is a
# metre when it is a hundred, or calls an origin fine when it is nowhere near
# the floor. A checker that is confidently wrong is worse than no checker,
# because it is believed.
#
# So the tests build models with known faults and check that each one is
# caught. Nothing here needs Blender: a .glb is a JSON chunk and a binary
# chunk, and a fault can be introduced by editing the first.
#
#   periksa/tests/run.sh
#
set -uo pipefail
cd "$(dirname "$0")/.."

WORK="${TMPDIR:-/tmp}/periksa-test"
rm -rf "$WORK"; mkdir -p "$WORK"
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

MODEL="${PERIKSA_TEST_MODEL:-$HOME/Desktop/projects/game/The Forsaken/docs/character-revamp/models/paladin.glb}"

echo
echo "── starting up ─────────────────────────────────────────────────"

python3 ./server.py --no-open > "$WORK/out.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

READY=""
for _ in $(seq 1 40); do
  READY=$(grep -o '@@PERIKSA-READY@@.*' "$WORK/out.log" 2>/dev/null | head -1)
  [ -n "$READY" ] && break
  sleep 0.25
done
if [ -z "$READY" ]; then
  bad "the server starts and says where it is"
  sed -n '1,20p' "$WORK/out.log"; exit 1
fi
ok "the server starts and says where it is"

LINE="${READY#@@PERIKSA-READY@@}"
PORT=$(printf '%s' "$LINE" | field port)
TOKEN=$(printf '%s' "$LINE" | field token)
BASE="http://127.0.0.1:$PORT"
ORIGIN="http://127.0.0.1:$PORT"
GET() { curl -s -H "Origin: $ORIGIN" "$BASE$1&t=$TOKEN"; }

[ -n "$PORT" ] && [ "$PORT" != "0" ]
check $? "it reports the port it really bound"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/roles")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request with no token is refused ($CODE)"

ROLES=$(GET "/api/roles?" | python3 -c 'import json,sys
d = json.load(sys.stdin)["roles"]
assert len(d) >= 4, d
for r in d:
    assert r["tris"] > 0 and r["about"], r
print(len(d))')
check $? "a model can be told what it is for ($ROLES roles)"

if [ ! -f "$MODEL" ]; then
  bad "there is a model to read (set PERIKSA_TEST_MODEL)"
  exit 1
fi

echo
echo "── reading a real file ─────────────────────────────────────────"

enc() { python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$1"; }
OUT=$(GET "/api/look?path=$(enc "$MODEL")&role=character")
echo "$OUT" > "$WORK/look.json"

[ "$(printf '%s' "$OUT" | field ok)" = "True" ]
check $? "it reads a real .glb"

# The size it reports has to be the size the model really is. jaring measures
# the same paladin in Blender and gets 1.30 x 0.36 x 1.90 there; glTF is Y-up
# so the same numbers arrive in a different order, and both have to be right
# or one of the two tools is lying to him.
python3 - "$WORK/look.json" <<'PY'
import json, sys
facts = json.load(open(sys.argv[1]))["facts"]
extent = sorted(facts["extent"])
expected = sorted([1.3045, 0.3616, 1.9012])
for a, b in zip(extent, expected):
    assert abs(a - b) < 0.02, (facts["extent"], "expected", expected)
assert facts["triangles"] == 12332, facts["triangles"]
PY
check $? "and measures it the same as jaring does, to the centimetre"

printf '%s' "$OUT" | python3 -c 'import json,sys
d = json.load(sys.stdin)
assert d["findings"], "nothing to say at all"
for f in d["findings"]:
    assert f["level"] in ("bad", "watch", "good"), f
    assert f["what"] and f["why"], f
    if f["level"] == "bad":
        assert f["todo"], "a fault with nothing to do about it: " + f["what"]'
check $? "every finding says what, and why, and a fault says what to do"

echo
echo "── faults it has to catch ──────────────────────────────────────"

# Each of these is a real .glb with one thing wrong with it, made by editing
# the description at the front. No Blender involved.
break_it() {                       # break_it <out> <python that edits `doc`>
  python3 - "$MODEL" "$1" "$2" <<'PY'
import json, struct, sys
source, out, edit = sys.argv[1], sys.argv[2], sys.argv[3]
data = open(source, "rb").read()
length = struct.unpack("<I", data[12:16])[0]
doc = json.loads(data[20:20 + length])
rest = data[20 + length:]

exec(edit)

chunk = json.dumps(doc).encode("utf-8")
chunk += b" " * ((4 - len(chunk) % 4) % 4)
head = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(chunk) + len(rest))
open(out, "wb").write(head + struct.pack("<I", len(chunk)) + b"JSON" + chunk + rest)
PY
  # It lands in a temporary folder, which is not one of the places periksa
  # scans, so it has to be handed over explicitly the way a dropped file is.
  curl -s -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
       -H "Content-Type: application/json" \
       -d "{\"path\": \"$1\"}" "$BASE/api/permit" > /dev/null
}

# A model built in centimetres and exported as if it were metres. This is the
# single most common thing wrong with a downloaded model.
break_it "$WORK/huge.glb" '
root = doc["scenes"][doc.get("scene", 0)]["nodes"][0]
node = doc["nodes"][root]
node.pop("matrix", None)
node["scale"] = [100.0, 100.0, 100.0]
'
HUGE=$(GET "/api/look?path=$(enc "$WORK/huge.glb")&role=character")
printf '%s' "$HUGE" | python3 -c 'import json,sys
d = json.load(sys.stdin)
worst = [f for f in d["findings"] if f["level"] == "bad"]
assert any("metres across" in f["what"] for f in worst), d["findings"]
assert any("centimetres" in f["why"] for f in worst), d["findings"]'
check $? "a model exported in centimetres is caught ($(printf '%s' "$HUGE" | field counts.bad) faults)"

# And the other half of the same mistake.
break_it "$WORK/tiny.glb" '
root = doc["scenes"][doc.get("scene", 0)]["nodes"][0]
node = doc["nodes"][root]
node.pop("matrix", None)
node["scale"] = [0.001, 0.001, 0.001]
'
GET "/api/look?path=$(enc "$WORK/tiny.glb")&role=character" | python3 -c 'import json,sys
d = json.load(sys.stdin)
assert any(f["level"] == "bad" and "millimetres" in f["what"] for f in d["findings"]), d["findings"]'
check $? "and a model a thousand times too small"

# A model with no UVs shows every texture as one smeared pixel, and nothing
# anywhere says why.
break_it "$WORK/nouv.glb" '
for mesh in doc["meshes"]:
    for primitive in mesh["primitives"]:
        primitive["attributes"].pop("TEXCOORD_0", None)
'
GET "/api/look?path=$(enc "$WORK/nouv.glb")&role=character" | python3 -c 'import json,sys
d = json.load(sys.stdin)
assert any(f["level"] == "bad" and "no UVs" in f["what"] for f in d["findings"]), d["findings"]'
check $? "a model with no UVs is caught"

# The same model is fine as a hero and much too heavy as background scenery.
# Nothing is wrong in the abstract, which is the whole point of the roles.
LIGHT=$(GET "/api/look?path=$(enc "$MODEL")&role=hero" | field counts.bad)
HEAVY=$(GET "/api/look?path=$(enc "$MODEL")&role=background" | field counts.bad)
[ "$LIGHT" = "0" ] && [ "$HEAVY" -gt 0 ]
check $? "the same model passes as a hero and fails as background scenery ($LIGHT vs $HEAVY)"

echo
echo "── what it will not do ─────────────────────────────────────────"

GET "/api/look?path=/etc/hosts&role=prop" | grep -q '"ok": false'
check $? "it refuses a file it has no business reading"

printf 'not a model at all' > "$WORK/junk.glb"
curl -s -X POST -H "Origin: $ORIGIN" -H "X-Bengkel-Token: $TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"path\": \"$WORK/junk.glb\"}" "$BASE/api/permit" > /dev/null
GET "/api/look?path=$(enc "$WORK/junk.glb")&role=prop" | grep -q 'not a .glb'
check $? "and says so plainly when a file is not a .glb at all"

echo
echo "── the page ────────────────────────────────────────────────────"

if [ ! -x "$CHROME" ]; then
  skip "the page (no Chrome)"
else
  node ../jaring/tests/run-browser.mjs \
    "$BASE/?t=$TOKEN&model=$(enc "$MODEL")&huge=$(enc "$WORK/huge.glb")" \
    tests/app.smoke.mjs
  check $? "the page, driven the way a person drives it"
fi

echo
echo "────────────────────────────────────────────────────────────────"
printf '  %d passed, %d failed' "$PASS" "$FAIL"
[ "$SKIP" -gt 0 ] && printf ', %d skipped' "$SKIP"
echo
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
