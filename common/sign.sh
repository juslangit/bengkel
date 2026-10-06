#!/usr/bin/env bash
# Sign a locally-built Mac app so macOS remembers its permissions.
#
# This exists because of one sentence from Luqman on 2026-09-23: "i dont want
# to see any ask for permission folder or anything in bengkel app."
#
# The cause was the signature. An **ad-hoc** signature (`codesign --sign -`)
# identifies an app by the hash of its own bytes:
#
#     designated => cdhash H"50e3a160…"
#
# Every rebuild produces different bytes, so as far as macOS is concerned it
# is a different application that happens to have the same name — and every
# permission it was granted belongs to the old one. bengkel and gerak read
# models out of ~/Desktop/projects, ~/Documents and ~/Downloads, all three of
# which are behind macOS's privacy controls, so a rebuild meant three dialogs
# all over again. This session alone rebuilt gerak three times.
#
# Signed with a certificate instead, the requirement becomes:
#
#     designated => identifier "com.luqmanhakeem.bengkel" and certificate leaf = H"…"
#
# There is no hash of the app in that, so the grant survives every rebuild.
# The certificate is self-signed, lives only in this Mac's login keychain, and
# is trusted by nothing except this Mac's own record of what these apps are.
# It is the same trick Notula needed on 2026-09-22.
#
# The identity is deliberately shared between apps rather than one per app,
# exactly as a real Developer ID is: the requirement above names the bundle
# identifier as well, so each app's permissions stay its own. On this Mac it
# is called "Notula Local Signing" because Notula was the first app to need
# one; `--make-cert` creates a neutrally-named one on a machine that has none.
#
#   common/sign.sh <path-to.app>            sign it
#   common/sign.sh --make-cert              create the certificate, if missing
#
set -euo pipefail

PREFERRED="Luqman Local Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"


# The first local signing identity this Mac has, preferring the neutral name.
# `security find-identity` prints lines like:
#   1) 71EC11…C6353 "Notula Local Signing"
find_identity() {
  local list
  list="$(security find-identity -v -p codesigning 2>/dev/null || true)"
  if grep -q "\"$PREFERRED\"" <<<"$list"; then
    printf '%s' "$PREFERRED"
    return 0
  fi
  # Any other one made for this purpose. Not a Developer ID: those are for
  # apps that leave the machine, and signing with one here would be a change
  # of meaning rather than a convenience.
  sed -n 's/.*"\(.*Local Signing\)"$/\1/p' <<<"$list" | head -1
}


make_cert() {
  local name="$PREFERRED"
  if security find-certificate -c "$name" >/dev/null 2>&1; then
    echo "→ '$name' already exists"
    return 0
  fi

  local work
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' RETURN

  cat > "$work/openssl.cnf" <<CNF
[ req ]
distinguished_name = dn
x509_extensions    = ext
prompt             = no
[ dn ]
CN = $name
[ ext ]
basicConstraints       = critical,CA:false
keyUsage               = critical,digitalSignature
extendedKeyUsage       = critical,codeSigning
subjectKeyIdentifier   = hash
CNF

  openssl req -x509 -newkey rsa:2048 -nodes -days 7300 \
    -config "$work/openssl.cnf" -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null

  # macOS's importer predates OpenSSL 3's defaults and fails on a modern
  # PKCS#12 with "MAC verification failed (wrong password?)", which sends you
  # looking for a typo that is not there. Hence the old-style algorithms.
  openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" \
    -name "$name" -out "$work/id.p12" -passout pass:local \
    -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 2>/dev/null

  security import "$work/id.p12" -k "$KEYCHAIN" -P local -T /usr/bin/codesign -A >/dev/null
  echo "→ approve the keychain dialog if one appears — it is asking to trust"
  echo "  this certificate for signing, and it only happens once"
  security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$work/cert.pem"
  echo "→ created '$name'"
}


sign_app() {
  local app="$1"
  local identity
  identity="$(find_identity)"

  if [ -z "$identity" ]; then
    codesign --force --sign - "$app" 2>/dev/null
    echo "  signed ad-hoc — no local signing certificate on this Mac, so macOS"
    echo "  will ask for folder permissions again after every rebuild."
    echo "  Run common/sign.sh --make-cert once to stop that."
    return 0
  fi

  codesign --force --sign "$identity" --identifier \
    "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist" 2>/dev/null)" \
    "$app"
  codesign --verify --verbose=1 "$app" 2>&1 | sed 's/^/  /'

  # Print the requirement, because this is the whole point of the exercise and
  # a cdhash creeping back in is exactly the kind of thing nobody notices.
  local req
  # The line comes back as "designated => ..." from `codesign -d -r-`, and as
  # "# designated => ..." from some versions, so allow either.
  req="$(codesign -d -r- "$app" 2>&1 | sed -n 's/^#\{0,1\} *designated => //p')"
  echo "  signed as '$identity'"
  if [ -z "$req" ]; then
    echo "  WARNING: could not read the designated requirement back"
  elif [[ "$req" == *cdhash* ]]; then
    echo "  WARNING: the requirement still names a cdhash, so permissions will"
    echo "  not survive a rebuild: $req"
  else
    echo "  permissions will survive a rebuild: $req"
  fi
}


case "${1:-}" in
  --make-cert) make_cert ;;
  "") echo "usage: sign.sh <path-to.app> | --make-cert" >&2; exit 2 ;;
  *) sign_app "$1" ;;
esac
