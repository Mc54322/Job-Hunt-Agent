#!/bin/bash
# Build the shareable JobAssist download (run on a Mac):
#   bash packaging/build.sh
#
# Produces dist/JobAssist/ and dist/JobAssist.zip containing "JobAssist for Windows.exe",
# "JobAssist for Mac" (Apple Silicon + Intel), the app's source and a READ ME FIRST guide.
# (Not plain "JobAssist": Mac and Windows treat that as the same name as the "jobassist"
# source folder next to it.)
# Personal files (.env, CV, employer sheet, saved results) are never included: the
# folder is assembled from an explicit list, then checked.
#
# Go is downloaded into packaging/.toolchain (checksum-verified) if it isn't installed,
# so nothing is installed system-wide.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

GO_VERSION="go1.27.3"
GO_SHA256_ARM64="dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2"
GO_SHA256_AMD64="b6f8e931e4ab497fcde6da8ae4499a58f9d258e55c8a80824a516eae5950a750"
TOOLCHAIN="$ROOT/packaging/.toolchain"
DIST="$ROOT/dist"
OUT="$DIST/JobAssist"

# --- Go toolchain ------------------------------------------------------------
if command -v go >/dev/null 2>&1; then
  GO="$(command -v go)"
else
  case "$(uname -m)" in
    arm64) arch=arm64; sha="$GO_SHA256_ARM64" ;;
    x86_64) arch=amd64; sha="$GO_SHA256_AMD64" ;;
    *) echo "Unsupported Mac architecture: $(uname -m)"; exit 1 ;;
  esac
  GO="$TOOLCHAIN/go/bin/go"
  if [ ! -x "$GO" ] || ! "$GO" version | grep -q "$GO_VERSION "; then
    echo "Downloading $GO_VERSION (one time, into packaging/.toolchain)…"
    rm -rf "$TOOLCHAIN"
    mkdir -p "$TOOLCHAIN"
    archive="$TOOLCHAIN/$GO_VERSION.darwin-$arch.tar.gz"
    curl -fsSL "https://go.dev/dl/$GO_VERSION.darwin-$arch.tar.gz" -o "$archive"
    echo "$sha  $archive" | shasum -a 256 -c - >/dev/null \
      || { echo "Go download failed its checksum check — not using it."; rm -rf "$TOOLCHAIN"; exit 1; }
    tar -xzf "$archive" -C "$TOOLCHAIN"
    rm "$archive"
  fi
fi
export GOFLAGS="-trimpath" GOTOOLCHAIN=local
echo "Using $("$GO" version)"

# --- Launchers -----------------------------------------------------------------
rm -rf "$OUT" "$DIST/JobAssist.zip"
mkdir -p "$OUT"
build() {  # build <goos> <goarch> <output>
  (cd "$ROOT/packaging/launcher" && CGO_ENABLED=0 GOOS="$1" GOARCH="$2" \
    "$GO" build -ldflags "-s -w" -o "$3" .)
}
WIN_EXE="$OUT/JobAssist for Windows.exe"
MAC_APP="$OUT/JobAssist for Mac"
build windows amd64 "$WIN_EXE"
build darwin arm64 "$DIST/JobAssist-arm64"
build darwin amd64 "$DIST/JobAssist-amd64"
lipo -create -output "$MAC_APP" "$DIST/JobAssist-arm64" "$DIST/JobAssist-amd64"
rm "$DIST/JobAssist-arm64" "$DIST/JobAssist-amd64"
codesign --force --sign - "$MAC_APP"  # ad-hoc signature: required to run on Apple Silicon
chmod +x "$MAC_APP"

# --- App files (explicit list — nothing personal) -------------------------------------
cp pyproject.toml uv.lock .python-version "$OUT/"
cp .env.example "$OUT/.env.example"
cp packaging/READ-ME-FIRST.txt "$OUT/READ ME FIRST.txt"
cp packaging/example-employer-list.txt "$OUT/Example employer list.txt"
cp README.md "$OUT/README (technical).md"
rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
  --exclude 'Dockerfile' jobassist "$OUT/"

# --- Safety check: launchers intact, no personal data, keys or caches ------------------
file "$MAC_APP" | grep -q "Mach-O universal binary" || { echo "Mac launcher missing/broken"; exit 1; }
file "$WIN_EXE" | grep -q "PE32+ executable" || { echo "Windows launcher missing/broken"; exit 1; }
leaks=$(cd "$OUT" && find . \( -name '.env' -o -iname 'resume*.txt' -o -name '*.xlsx' \
  -o -name '*.db' -o -name '__pycache__' -o -name '.venv' -o -name '*.docx' -o -name '*.pdf' \) -print)
if [ -n "$leaks" ]; then
  echo "Refusing to package — these must not be shared:"; echo "$leaks"; exit 1
fi
if grep -rIlE "sk-ant-[A-Za-z0-9_-]{20,}" "$OUT" >/dev/null 2>&1; then
  echo "Refusing to package — an Anthropic API key was found in the files."; exit 1
fi

# ditto keeps the Mac program executable inside the zip; Windows unzips it normally.
(cd "$DIST" && ditto -c -k --keepParent JobAssist JobAssist.zip)
echo
echo "Built:"
echo "  $OUT/"
echo "  $DIST/JobAssist.zip ($(du -h "$DIST/JobAssist.zip" | cut -f1))"
