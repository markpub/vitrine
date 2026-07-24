#!/usr/bin/env bash
# Vitrine build orchestrator — the command Cloudflare Pages (or any CI) runs.
#
#   build.sh <source-repo> <output-site>
#
# Chain (the source repo is NEVER mutated; everything happens on a copy):
#   1. copy      <source-repo> -> $WORK/content   (rsync, excluding VCS/tool dirs)
#   1b. scaffold non-interactive `markpub init` supplies .markpub/ (config + theme)
#   2. metadata  gen_metadata.py renders selected frontmatter fields as a
#                bullet list on each record page (per .vitrine.yaml)
#   3. rename    (VITRINE_PAGE_NAMES=slug only) rename_pages.py: record pages
#                -> <id>-<slug> on the copy, rename map for the later stages
#   4. navigate  gen_navigation.py: room Contents indexes, sitemap.md, 404.md
#   5. sidebar   gen_sidebar.py writes Sidebar.md into the copy
#   6. vitrine   vitrine.py applies the three transforms in place on the copy
#   7. build     VANILLA markpub renders the copy -> <output-site>
#   8. post      markpub_post.py puts human titles into <title>/all-pages/search
#
# Environment (all optional):
#   PYTHON        python interpreter with markpub + pyyaml (default: python3.11)
#   VITRINE_WORK  work directory (default: $PWD/_work; wiped each run)
#   SITE_TITLE    website title      (default: basename of <source-repo>)
#   SITE_AUTHOR   author line        (default: empty)
#   SITE_REPO     git repo url for the Edit button, e.g. github.com/org/repo
#                 (default: empty — no Edit buttons)
#   VITRINE_FOLDER_NOTE  set to 1 so rooms lacking a folder note get
#                 `<room>/<room>.md` created instead of `README.md`
#   VITRINE_PAGE_NAMES  filename (default) publishes under the source names;
#                 slug renames record pages on the copy to `<id>-<slug>`
#                 (frontmatter slug:, else slugified title:). The source
#                 repo keeps its bare-ID filenames either way.
#
# Cloudflare Pages wiring (vitrine/ vendored in the content repo):
#   Build command:    pip install markpub && bash vitrine/build.sh . _site
#   Output directory: _site
#
# Search + RANDOM PAGE need a lunr index, which needs node/npm; if they are
# missing the build still succeeds, without the index.

set -euo pipefail

if [ $# -ne 2 ]; then
    echo "usage: build.sh <source-repo> <output-site>" >&2
    exit 2
fi

SRC="$(cd "$1" && pwd)"
OUT_ARG="$2"
mkdir -p "$(dirname "$OUT_ARG")"
OUT="$(cd "$(dirname "$OUT_ARG")" && pwd)/$(basename "$OUT_ARG")"

VITRINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3.11}"
WORK="${VITRINE_WORK:-$PWD/_work}"
CONTENT="$WORK/content"
SITE_TITLE="${SITE_TITLE:-$(basename "$SRC")}"
SITE_AUTHOR="${SITE_AUTHOR:-}"
SITE_REPO="${SITE_REPO:-}"
PAGE_NAMES="${VITRINE_PAGE_NAMES:-filename}"
case "$PAGE_NAMES" in
    filename|slug) ;;
    *) echo "error: VITRINE_PAGE_NAMES must be 'filename' or 'slug', got '$PAGE_NAMES'" >&2; exit 2 ;;
esac

echo "==> 1. copy: $SRC -> $CONTENT (source stays untouched)"
rm -rf "$WORK"
mkdir -p "$CONTENT"
# .vitrineignore (optional, at the source root): gitignore-style patterns for
# paths that stay in the repo but are kept OUT of the published site — metadata,
# not website (e.g. correspondence between the estates). It is a publish-time
# exclude only; it never touches git, so ignored files remain tracked and shared.
IGNORE_OPT=()
if [ -f "$SRC/.vitrineignore" ]; then
    IGNORE_OPT=(--exclude-from="$SRC/.vitrineignore")
    echo "    honoring .vitrineignore"
fi
rsync -a \
      --exclude .git --exclude .obsidian --exclude .claude \
      --exclude .markpub --exclude node_modules --exclude .vitrineignore \
      --exclude .vitrine.yaml \
      "${IGNORE_OPT[@]}" \
      --exclude "$(basename "$WORK")" --exclude "$(basename "$OUT")" \
      "$SRC"/ "$CONTENT"/

echo "==> 1b. scaffold: non-interactive markpub init"
printf '%s\n%s\n%s\n' "$SITE_TITLE" "$SITE_AUTHOR" "$SITE_REPO" \
    | "$PYTHON" -c "from markpub.markpub import main; main()" init "$CONTENT"
# init side-effects this pipeline does not want in the published copy:
rm -rf "$CONTENT/.github" "$CONTENT/netlify.toml"

echo "==> 2. metadata: frontmatter bullet lists (per .vitrine.yaml)"
"$PYTHON" "$VITRINE_DIR/gen_metadata.py" --config "$SRC/.vitrine.yaml" "$CONTENT"

RENAME_OPT=()
if [ "$PAGE_NAMES" = "slug" ]; then
    echo "==> 3. rename: record pages -> <id>-<slug> (copy only)"
    "$PYTHON" "$VITRINE_DIR/rename_pages.py" "$CONTENT" "$WORK/rename-map.json"
    RENAME_OPT=(--rename-map "$WORK/rename-map.json")
fi

echo "==> 4. navigate: room indexes, sitemap.md, 404.md"
"$PYTHON" "$VITRINE_DIR/gen_navigation.py" "$CONTENT"

echo "==> 5. sidebar: generate Sidebar.md"
"$PYTHON" "$VITRINE_DIR/gen_sidebar.py" "$CONTENT"

echo "==> 6. vitrine: three transforms, in place on the copy"
"$PYTHON" "$VITRINE_DIR/vitrine.py" "${RENAME_OPT[@]}" "$CONTENT"

echo "==> 7. markpub build (vanilla) -> $OUT"
LUNR=""
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    if (cd "$CONTENT/.markpub" && npm ci --no-audit --no-fund --loglevel=error); then
        LUNR="--lunr"
    else
        echo "WARN: npm ci failed; building without search index" >&2
    fi
else
    echo "WARN: node/npm not found; building without search index" >&2
fi
# run from .markpub so markpub's `node build-index.js` finds its files
(cd "$CONTENT/.markpub" && "$PYTHON" -c "from markpub.markpub import main; main()" build \
    -i "$CONTENT" -o "$OUT" \
    --config "$CONTENT/.markpub/markpub.yaml" \
    --templates "$CONTENT/.markpub/this-website-themes/dolce" \
    $LUNR)

echo "==> 8. post: human titles into <title>, all-pages, recent-pages, search"
"$PYTHON" "$VITRINE_DIR/markpub_post.py" "${RENAME_OPT[@]}" "$CONTENT" "$OUT"

echo "==> done: $OUT"
