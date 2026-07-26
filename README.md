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

1. **copy** — `copy_content.py` copies the source into `$WORK/content`, excluding `.git`, `.obsidian`, `.claude`, `.markpub`, `node_modules` (and the work/output dirs themselves). The source is never written to. A **`.vitrineignore`** at the source root (gitignore syntax, as documented in `copy_content.py`) excludes further paths from the *published site* while leaving them fully git-tracked — for metadata that belongs in the repo but not on the website (e.g. correspondence between collaborators). It is a publish-time filter only; it never touches git. File modes, mtimes, symlinks, and empty directories all survive the copy.
   - **1b. scaffold** — non-interactive `markpub init` on the copy supplies `.markpub/` (config + dolce theme). Answers are piped from `SITE_TITLE` / `SITE_AUTHOR` / `SITE_REPO`; init's `netlify.toml` and `.github/` side-effects are removed. Scaffolding is regenerated each build, so nothing needs committing.
2. **metadata** — `gen_metadata.py` renders each record's relevant frontmatter as a bullet list under the title, per the content repo's optional **`.vitrine.yaml`** (`metadata:` section: field list per entity type, in display order; `_default: none|all|[fields]` for the rest — same travel-with-the-content pattern as `.vitrineignore`, and equally unpublished). Values that reference another record become links labeled with that record's title; URLs autolink. No config, no change.
3. **rename** (only with `VITRINE_PAGE_NAMES=slug`) — `rename_pages.py` renames record pages on the copy to `<id>-<slug>` (frontmatter `slug:` if present, else the slugified `title:`), so records publish under readable URLs (`/entities/decision/dec-001-build-a-shared-password-protected-website...`) while the source repo keeps its bare-ID filenames — publishing names are a view concern. A rename map is written for the later stages: `vitrine.py` rewrites link targets through it, and `markpub_post.py` points Edit buttons back at the real source files.
4. **navigate** — `gen_navigation.py` generates the navigation MarkPub does not provide: a `## Contents` section (the room's tree — subfolders nested, Markdown files linked by frontmatter `title:`, non-Markdown files like transcripts linked by filename) appended to each room's folder note; a site-wide `sitemap.md`; and a `404.md`. A room with no note gets one created in the copy (`README.md`, or `<room>/<room>.md` with `VITRINE_FOLDER_NOTE=1`). Emitted targets are site-absolute and mirror MarkPub's path scrub (spaces → `_`), so links to `zoom transcript.txt` and kin actually resolve. The entity room keeps its own upstream-generated index.
5. **sidebar** — `gen_sidebar.py` writes `Sidebar.md` into the copy from the repo's actual room structure (entity index, library, meetingroom, project, tools, logging — only rooms that exist; door: folder note `<room>/<room>.md` first, else `README.md`; plus a SITEMAP entry). Links are universal Markdown `[LABEL](/path)`, never `[[wikilinks]]` (forbidden by the repo's convention); includes the MarkPub RANDOM PAGE button idiom, an "About this space" block, and an AI-generated disclosure.
6. **vitrine** — `vitrine.py` applies the three transforms in place on the copy (publisher-agnostic; see below).
7. **build** — **vanilla, unmodified** `markpub build` renders the copy into `<output-site>`. If node/npm are present, the lunr search index is built (powers SEARCH and RANDOM PAGE); if not, the build still succeeds without it.
8. **post** — `markpub_post.py` (the one deliberately MarkPub-specific piece) rewrites the places MarkPub keys off the filename stem: page `<title>` tags, all-pages/recent-pages listings, and the lunr posts list that drives search-result display.

## The three transforms (`vitrine.py`)

- **T1 — human titles.** If frontmatter has `title:`, insert `# {title}` as the first body line (unless an H1 already leads). Records without `title:` fall back to their ID. Filenames are never touched.
- **T2 — strip validator shadows.** Remove `^[ID](path)` immediately following a link, leaving the human `[label](path)` intact.
- **T3 — `.md` → `.html`, absolutized.** Rewrite relative/local Markdown link targets (including `#anchors` and reference-style definitions) so cross-references resolve to rendered pages on any static host — and resolve them to **site-absolute** paths (`/entities/decision/DEC-001.html`), computed from each file's location. Relative links are only correct when a page is served at its true URL; hosts that fall back to serving *something* for unknown routes (Cloudflare Pages without a `404.html` serves the home page with a 200) let one bad URL compound into ever-deeper phantom paths. Absolute links end that class of failure; the generated 404 page closes the other half. External `http(s)://`/`mailto:` targets are never touched. Runs after T2.

**Guardrails:** fenced code blocks and inline code spans are never modified — a `^[` or `.md` in an example survives byte-for-byte. Frontmatter is preserved verbatim. Everything outside the three transforms is byte-identical.

## Running it

Requirements: Python 3 with `markpub` (0.4.5+) and `pyyaml`; optionally node/npm for the search index. Nothing outside the Python standard library is used by Vitrine's own stages, so there are no system tools to install.

```
SITE_TITLE=comroom SITE_AUTHOR="WSD group" SITE_REPO=github.com/WSD-Talks/comroom \
  bash vitrine/build.sh /path/to/comroom /path/to/output-site
```

Environment knobs (all optional): `PYTHON` (default `python3.11`), `VITRINE_WORK` (work dir, default `$PWD/_work`, wiped each run), `SITE_TITLE` (default: source basename), `SITE_AUTHOR`, `SITE_REPO` (enables per-page "Edit on GitHub" buttons pointing at the *source* `.md` files), `VITRINE_FOLDER_NOTE` (set to 1 so rooms lacking a note get `<room>/<room>.md` created instead of `README.md`), `VITRINE_PAGE_NAMES` (`filename` — default — publishes under source names; `slug` renames record pages on the copy to `<id>-<slug>`).

## Cloudflare Pages wiring

Vendor `vitrine/` into the content repo (or fetch it in the build command), then in the Pages project settings:

- **Build command:** `pip install markpub && bash vitrine/build.sh . _site`
- **Build output directory:** `_site`
- **Environment variables:** `SITE_TITLE`, `SITE_AUTHOR`, `SITE_REPO` as desired; `PYTHON=python3` if the image has no `python3.11` alias.

The Pages build image provides node/npm, so search and RANDOM PAGE work out of the box.

## The boundary, restated

Vitrine never mutates the source repository. It stages a copy, transforms the copy, and publishes the copy. If you ever find a diff in the source after a build, that is a bug in Vitrine, not a feature.
