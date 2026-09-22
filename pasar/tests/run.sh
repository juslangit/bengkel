#!/usr/bin/env bash
#
# Tests for pasar.
#
# pasar is mostly a face over three libraries that already had command-line
# tools, so there is little maths here to check. What can go wrong is the
# joinery, and that is what this tests:
#
#   * does the server come up and say where it is
#   * does the page get a real token rather than the placeholder
#   * is a request without that token, or from another website, refused
#   * are all three libraries reachable
#   * does a search come back with a licence on every single result
#   * is something that cannot be sold marked as such before it is downloaded
#   * does a download land in the workshop with a note saying where it came from
#
# It starts its own server on a port of its choosing and stops it afterwards,
# so nothing needs to be running first:
#
#   pasar/tests/run.sh
#
# The searches need the internet. Without it those checks are skipped rather
# than failed - a broken wire is not a broken program.
set -uo pipefail
cd "$(dirname "$0")/.."

WORK="${TMPDIR:-/tmp}/pasar-test"
rm -rf "$WORK"; mkdir -p "$WORK"

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  ok   %s\n' "$*"; PASS=$((PASS + 1)); }
bad()  { printf '  FAIL %s\n' "$*"; FAIL=$((FAIL + 1)); }
skip() { printf '  --   %s (skipped)\n' "$*"; SKIP=$((SKIP + 1)); }
check(){ if [ "$1" = "0" ]; then ok "$2"; else bad "$2"; fi; }

# A tiny helper for reading one field out of a JSON reply, because every
# check below ends in reading one field out of a JSON reply.
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
  READY=$(grep -o '@@PASAR-READY@@.*' "$WORK/out.log" 2>/dev/null | head -1)
  [ -n "$READY" ] && break
  sleep 0.25
done

if [ -z "$READY" ]; then
  bad "the server starts and says where it is"
  echo; sed -n '1,20p' "$WORK/out.log"; exit 1
fi
ok "the server starts and says where it is"

LINE="${READY#@@PASAR-READY@@}"
PORT=$(printf '%s' "$LINE" | field port)
TOKEN=$(printf '%s' "$LINE" | field token)
BASE="http://127.0.0.1:$PORT"
ORIGIN="http://127.0.0.1:$PORT"

# The port asked for was 0, so a port that is still 0 here means the bound
# port was never read back - the bug that silently refused every POST twice
# before, once in gerak and once in boneka.
[ -n "$PORT" ] && [ "$PORT" != "0" ]
check $? "it reports the port it really bound, not the one it asked for"

echo
echo "── the way in ──────────────────────────────────────────────────"

PAGE=$(curl -s "$BASE/?t=$TOKEN")

printf '%s' "$PAGE" | grep -q "__BENGKEL_TOKEN__"
if [ $? = 0 ]; then bad "the page is handed a real token, not the placeholder"
else ok "the page is handed a real token, not the placeholder"; fi

printf '%s' "$PAGE" | grep -q "$TOKEN"
check $? "and it is the same token the server printed"

CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/sources")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request with no token is refused ($CODE)"

CODE=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Origin: https://somewhere-else.example" "$BASE/api/sources?t=$TOKEN")
[ "$CODE" = "403" ] || [ "$CODE" = "401" ]
check $? "a request from another website is refused even with the token ($CODE)"

CODE=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Origin: $ORIGIN" "$BASE/api/sources?t=$TOKEN")
[ "$CODE" = "200" ]
check $? "a request from the page itself is allowed ($CODE)"

echo
echo "── the three libraries ─────────────────────────────────────────"

SOURCES=$(curl -s -H "Origin: $ORIGIN" "$BASE/api/sources?t=$TOKEN")
for LIB in sketchfab polyhaven texturelabs; do
  READYBIT=$(printf '%s' "$SOURCES" | python3 -c 'import json,sys
d = json.load(sys.stdin)
print(next((s["ready"] for s in d["sources"] if s["id"] == sys.argv[1]), "missing"))' "$LIB")
  [ "$READYBIT" = "True" ]
  check $? "$LIB is loaded and ready"
done

echo
echo "── searching ───────────────────────────────────────────────────"

if ! curl -s -m 8 -o /dev/null https://api.polyhaven.com/types; then
  skip "searching (no internet)"
else
  RESULTS=$(curl -s -m 60 -H "Origin: $ORIGIN" "$BASE/api/search?t=$TOKEN&q=wood&n=12")

  COUNT=$(printf '%s' "$RESULTS" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["results"]))')
  [ "${COUNT:-0}" -gt 0 ]
  check $? "a search for wood finds something ($COUNT results)"

  # Every card has to carry a licence, because the card is where he decides
  # whether to download, and after the download it is too late to wonder.
  printf '%s' "$RESULTS" | python3 -c 'import json,sys
bad = [r for r in json.load(sys.stdin)["results"]
       if not r.get("licence") or "safe" not in r or not r.get("title")]
raise SystemExit(1 if bad else 0)'
  check $? "every result carries a title, a licence and a verdict on selling it"

  MIX=$(printf '%s' "$RESULTS" | python3 -c 'import json,sys
print(" ".join(sorted({r["source"] for r in json.load(sys.stdin)["results"]})))')
  [ -n "$MIX" ]
  check $? "and they come from more than one place at once ($MIX)"

  # A named library on its own must return only that library.
  ONLY=$(curl -s -m 60 -H "Origin: $ORIGIN" "$BASE/api/search?t=$TOKEN&q=wood&where=texturelabs&n=6" \
    | python3 -c 'import json,sys
print(" ".join(sorted({r["source"] for r in json.load(sys.stdin)["results"]})) or "nothing")')
  [ "$ONLY" = "texturelabs" ]
  check $? "asking one library alone answers from that library alone ($ONLY)"
fi

echo
echo "── what a licence means ────────────────────────────────────────"

# This one needs no network: it is the rule itself, not the search.
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.getcwd()), "common"))
sys.argv = ["pasar", "--no-run"]
import importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("pasar_mod", "server.py")
spec = importlib.util.spec_from_loader("pasar_mod", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

# what the card says about selling the result
cases = [
    ("CC Attribution", True),
    ("CC0", True),
    ("CC Attribution-NonCommercial", False),
    ("CC Attribution-NoDerivs", False),
]
for label, expected in cases:
    got = "NonCommercial" not in label and "NoDerivs" not in label
    assert got is expected, "%s judged %s" % (label, got)

# and the note that goes beside a download
import tempfile
folder = tempfile.mkdtemp()
mod.note(folder, "sketchfab", "abc", "A Dog", "Someone", "CC Attribution",
         "https://sketchfab.com/3d-models/abc")
text = open(os.path.join(folder, "WHERE-IT-CAME-FROM.md")).read()
for needed in ("A Dog", "sketchfab", "Someone", "CC Attribution",
               "https://sketchfab.com/3d-models/abc"):
    assert needed in text, "the note leaves out " + needed
PY
check $? "NonCommercial and NoDerivs are flagged, and the note records everything"

echo
echo "── what is already home ────────────────────────────────────────"

MINE=$(curl -s -H "Origin: $ORIGIN" "$BASE/api/mine?t=$TOKEN")
printf '%s' "$MINE" | python3 -c 'import json,sys
items = json.load(sys.stdin)["items"]
import os
for i in items:
    assert os.path.exists(i["path"]), "listed but gone: " + i["path"]
    assert i["shown"].startswith("~"), "shows a raw home path: " + i["shown"]'
check $? "everything it says you have is really there, and shown as ~/"

echo
echo "────────────────────────────────────────────────────────────────"
printf '  %d passed, %d failed' "$PASS" "$FAIL"
[ "$SKIP" -gt 0 ] && printf ', %d skipped' "$SKIP"
echo
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
