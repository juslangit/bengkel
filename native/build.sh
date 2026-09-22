#!/usr/bin/env bash
#
# Build bengkel.app.
#
# bengkel carries no engine of its own: it starts the tools where they already
# live, on disk, so the bundle holds only the studio page, the tool list and
# the program that joins them. That means a change to boneka or gerak is live
# in bengkel the next time it starts, with nothing to rebuild.
#
# There is no Xcode project and nothing to install: swiftc comes with the
# command line tools, and everything else here is assembling a folder in the
# shape macOS expects an application to be.
#
#   native/build.sh              build it into native/build/bengkel.app
#   native/build.sh --install    ...and put it in /Applications
#   native/build.sh --run        ...and open it
#
# An app bundle is just a folder:
#
#   bengkel.app/Contents/Info.plist          what it is called and what it opens
#   bengkel.app/Contents/MacOS/bengkel         the compiled program
#   bengkel.app/Contents/Resources/          the icon, and bengkel's own engine
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build"
APP="$BUILD/bengkel.app"
CONTENTS="$APP/Contents"

INSTALL=0
RUN=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --run)     INSTALL=1; RUN=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }

echo
echo "building bengkel.app"

# ── start clean ─────────────────────────────────────────────────────
rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

# ── the icon ────────────────────────────────────────────────────────
# macOS wants every size in one .icns. The 1024 px source is rendered from
# native/icon.html; re-render it with build.sh --icon if the drawing changes.
ICONSET="$BUILD/bengkel.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

if [ ! -f "$HERE/icon-1024.png" ]; then
  echo "  icon-1024.png is missing — render it first:"
  echo "    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --headless \\"
  echo "      --window-size=1024,1024 --screenshot=native/icon-1024.png \\"
  echo "      --default-background-color=00000000 file://$HERE/icon.html"
  exit 1
fi

for size in 16 32 64 128 256 512; do
  sips -z $size $size "$HERE/icon-1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1
  double=$((size * 2))
  sips -z $double $double "$HERE/icon-1024.png" \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/bengkel.icns"
rm -rf "$ICONSET"
say "icon: $(du -h "$CONTENTS/Resources/bengkel.icns" | cut -f1)"

# ── what macOS needs to know about it ───────────────────────────────
cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>                 <string>bengkel</string>
  <key>CFBundleDisplayName</key>          <string>bengkel</string>
  <key>CFBundleExecutable</key>           <string>bengkel</string>
  <key>CFBundleIdentifier</key>           <string>com.luqmanhakeem.bengkel</string>
  <key>CFBundleIconFile</key>             <string>bengkel</string>
  <key>CFBundlePackageType</key>          <string>APPL</string>
  <key>CFBundleShortVersionString</key>   <string>1.0</string>
  <key>CFBundleVersion</key>              <string>1</string>
  <key>LSMinimumSystemVersion</key>       <string>13.0</string>
  <key>NSHighResolutionCapable</key>      <true/>
  <key>LSApplicationCategoryType</key>    <string>public.app-category.graphics-design</string>
  <key>LSUIElement</key>                  <false/>
  <key>NSHumanReadableCopyright</key>     <string>Luqman Hakeem</string>

  <!-- The window draws its own top bar over a transparent title strip. -->
  <key>NSRequiresAquaSystemAppearance</key> <false/>

  <!-- bengkel talks to its own server on 127.0.0.1 over plain HTTP. Without
       this, App Transport Security refuses the connection and the window
       comes up empty. -->
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key> <true/>
  </dict>

</dict>
</plist>
PLIST
say "Info.plist written"

# ── compile ─────────────────────────────────────────────────────────
swiftc -O \
  -target arm64-apple-macosx13.0 \
  -framework AppKit -framework WebKit -framework UniformTypeIdentifiers \
  "$HERE/Sources/main.swift" \
  -o "$CONTENTS/MacOS/bengkel"
say "compiled: $(du -h "$CONTENTS/MacOS/bengkel" | cut -f1)"

# ── bengkel's own engine, carried inside the bundle ───────────────────
# The app is self-contained: it runs the copy in its own Resources folder,
# never the working tree, so moving or reinstalling it changes nothing.
cp "$ROOT/tools.json" "$CONTENTS/Resources/"
[ -f "$ROOT/README.md" ] && cp "$ROOT/README.md" "$CONTENTS/Resources/"
cp -R "$ROOT/web" "$CONTENTS/Resources/"
say "carrying: the studio page and the tool list ($(du -sh "$CONTENTS/Resources" | cut -f1))"

# ── sign it ─────────────────────────────────────────────────────────
# Ad-hoc, because there is no Developer ID on this machine and none is needed
# for an app that never leaves it. Without any signature at all, macOS refuses
# to launch an arm64 binary.
codesign --force --deep --sign - "$APP" 2>/dev/null
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/  /'

echo
say "built $APP"

# ── install ─────────────────────────────────────────────────────────
if [ $INSTALL -eq 1 ]; then
  DEST="/Applications/bengkel.app"
  rm -rf "$DEST"
  cp -R "$APP" "$DEST"
  # Tell Finder about it, so the icon and the "Open With" entry appear now
  # rather than whenever macOS next gets round to noticing.
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$DEST" 2>/dev/null || true
  say "installed to $DEST"
  [ $RUN -eq 1 ] && open "$DEST" && say "opened it"
fi

echo
