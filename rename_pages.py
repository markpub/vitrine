#!/usr/bin/env python3
"""Rename record pages on the staged copy to human-readable published names.

The source repository keeps its bare-ID filenames (`DEC-001.md`) — they are
the entity-manager convention and are never touched. Publishing under
readable URLs is a *view* concern, so it happens here, on the copy only:
this tool renames each record page to `<id>-<slug>` and writes a JSON map
of the renames for the later stages (vitrine.py rewrites link targets
through it; markpub_post.py points Edit buttons back at the real source
files).

What gets renamed: Markdown files whose stem is a bare record ID
(`DEC-001`, `MTG-001`, `TOOL-003`, ...). Structural pages — folder notes,
README, logging sessions, sitemap — keep their names: their URLs are
already human.

The published stem is `<id lowercased>-<handle>`, where the handle is the
record's frontmatter `slug:` if present (entity-manager treats a slug as a
hand-chosen handle, never derived — DEC-018 in its registry), else the
slugified `title:`. Records with neither keep their bare-ID name.

Usage:
  rename_pages.py CONTENT_DIR MAP_OUT_JSON

The map's keys and values are site-absolute paths without extension:
  {"/entities/decision/DEC-001": "/entities/decision/dec-001-build-a-shared-..."}
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# sibling-module helper (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vitrine import split_front_matter  # noqa: E402

# A bare record ID: type prefix, dash, number (DEC-001, SPEC-006, TOOL-003).
ID_STEM_RE = re.compile(r'^[A-Z][A-Z0-9]*-\d+$')

MAX_HANDLE = 60


def slugify(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    if len(s) > MAX_HANDLE:
        # truncate at a word boundary, never mid-word
        s = s[:MAX_HANDLE + 1].rsplit('-', 1)[0]
    return s


def handle_for(md: Path):
    """The record's published handle: frontmatter slug:, else slugified
    title:, else None (keep the bare-ID name)."""
    fm, _body = split_front_matter(md.read_text(encoding='utf-8'))
    if not fm:
        return None
    inner = ''.join(fm.splitlines(keepends=True)[1:-1])
    try:
        data = yaml.safe_load(inner)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    slug = data.get('slug')
    if isinstance(slug, str) and slug.strip():
        return slugify(slug)
    title = data.get('title')
    if isinstance(title, str) and title.strip():
        return slugify(title)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='rename_pages.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy to rename record pages in (never the source repo)')
    parser.add_argument('map_out', help='path to write the rename map JSON to (outside the copy, so it is not published)')
    args = parser.parse_args(argv)

    content = Path(args.content_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')

    renames = {}
    for md in sorted(content.rglob('*.md')):
        rel = md.relative_to(content)
        if any(part.startswith('.') for part in rel.parts):
            continue
        if not ID_STEM_RE.match(md.stem):
            continue
        handle = handle_for(md)
        if not handle:
            continue
        new_name = f'{md.stem.lower()}-{handle}.md'
        target = md.with_name(new_name)
        if target.exists():
            print(f'rename_pages: ERROR: {target} already exists', file=sys.stderr)
            return 1
        md.rename(target)
        old_abs = '/' + rel.with_suffix('').as_posix()
        new_abs = '/' + target.relative_to(content).with_suffix('').as_posix()
        renames[old_abs] = new_abs

    Path(args.map_out).write_text(
        json.dumps(renames, indent=2, sort_keys=True), encoding='utf-8')
    print(f'rename_pages: renamed {len(renames)} record pages; map -> {args.map_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
