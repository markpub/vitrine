# Vitrine

Vitrine prepares a structured-Markdown "entity-manager" repository for publishing as a static website with **vanilla MarkPub**, by transforming a **copy** of the content — never the source.

The name is the boundary: a vitrine is a museum display case; it presents the objects unaltered. The source repository is read-only to this tool. Every change happens on a staged copy under a throwaway work directory, and the publisher runs against that copy.

## Why it exists

Entity-manager repos keep records as Markdown-with-YAML-frontmatter, with three conventions that plain MarkPub publishes badly:

1. **Filenames are bare IDs** (`DEC-001.md`); the human title lives in frontmatter `title:`. MarkPub derives the page name from the filename, so titles, `<h1>`s, nav, and all-pages listings all show `DEC-001`. (The filenames are load-bearing for the upstream validator, so renaming is not an option.)
2. **References carry a validator-only shadow**: `[label](../x/ID.md)^[ID](../x/ID.md)`. MarkPub renders the trailing `^[ID](path)` as a literal caret plus a duplicate link.
3. **Relative `.md` links stay `.md`** in the rendered HTML, so cross-references open raw Markdown source instead of the rendered page.

## The build chain

`build.sh <source-repo> <output-site>` orchestrates:

1. **copy** — `rsync -a` the source into `$WORK/content`, excluding `.git`, `.obsidian`, `.claude`, `.markpub`, `node_modules` (and the work/output dirs themselves). The source is never written to. A **`.vitrineignore`** at the source root (gitignore-style patterns) excludes further paths from the *published site* while leaving them fully git-tracked — for metadata that belongs in the repo but not on the website (e.g. correspondence between collaborators). It is a publish-time filter only; it never touches git.
   - **1b. scaffold** — non-interactive `markpub init` on the copy supplies `.markpub/` (config + dolce theme). Answers are piped from `SITE_TITLE` / `SITE_AUTHOR` / `SITE_REPO`; init's `netlify.toml` and `.github/` side-effects are removed. Scaffolding is regenerated each build, so nothing needs committing.
2. **sidebar** — `gen_sidebar.py` writes `Sidebar.md` into the copy from the repo's actual room structure (entity index, library, meetingroom, project, tools, logging — only rooms that exist). Links are universal Markdown `[LABEL](/path)`, never `[[wikilinks]]` (forbidden by the repo's convention); includes the MarkPub RANDOM PAGE button idiom, an "About this space" block, and an AI-generated disclosure.
3. **vitrine** — `vitrine.py` applies the three transforms in place on the copy (publisher-agnostic; see below).
4. **build** — **vanilla, unmodified** `markpub build` renders the copy into `<output-site>`. If node/npm are present, the lunr search index is built (powers SEARCH and RANDOM PAGE); if not, the build still succeeds without it.
5. **post** — `markpub_post.py` (the one deliberately MarkPub-specific piece) rewrites the places MarkPub keys off the filename stem: page `<title>` tags, all-pages/recent-pages listings, and the lunr posts list that drives search-result display.

## The three transforms (`vitrine.py`)

- **T1 — human titles.** If frontmatter has `title:`, insert `# {title}` as the first body line (unless an H1 already leads). Records without `title:` fall back to their ID. Filenames are never touched.
- **T2 — strip validator shadows.** Remove `^[ID](path)` immediately following a link, leaving the human `[label](path)` intact.
- **T3 — `.md` → `.html`.** Rewrite relative/local Markdown link targets (including `#anchors` and reference-style definitions) so cross-references resolve to rendered pages on any static host. External `http(s)://`/`mailto:` targets are never touched. Runs after T2.

**Guardrails:** fenced code blocks and inline code spans are never modified — a `^[` or `.md` in an example survives byte-for-byte. Frontmatter is preserved verbatim. Everything outside the three transforms is byte-identical.

## Running it

Requirements: Python 3 with `markpub` (0.4.5+) and `pyyaml`; `rsync`; optionally node/npm for the search index.

```
SITE_TITLE=comroom SITE_AUTHOR="WSD group" SITE_REPO=github.com/WSD-Talks/comroom \
  bash vitrine/build.sh /path/to/comroom /path/to/output-site
```

Environment knobs (all optional): `PYTHON` (default `python3.11`), `VITRINE_WORK` (work dir, default `$PWD/_work`, wiped each run), `SITE_TITLE` (default: source basename), `SITE_AUTHOR`, `SITE_REPO` (enables per-page "Edit on GitHub" buttons pointing at the *source* `.md` files).

## Cloudflare Pages wiring

Vendor `vitrine/` into the content repo (or fetch it in the build command), then in the Pages project settings:

- **Build command:** `pip install markpub && bash vitrine/build.sh . _site`
- **Build output directory:** `_site`
- **Environment variables:** `SITE_TITLE`, `SITE_AUTHOR`, `SITE_REPO` as desired; `PYTHON=python3` if the image has no `python3.11` alias.

The Pages build image provides node/npm, so search and RANDOM PAGE work out of the box.

## The boundary, restated

Vitrine never mutates the source repository. It stages a copy, transforms the copy, and publishes the copy. If you ever find a diff in the source after a build, that is a bug in Vitrine, not a feature.
