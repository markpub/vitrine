#!/usr/bin/env python3
"""Generate the navigation aids MarkPub does not provide: per-room content
indexes, a site-wide sitemap page, and a real 404 page.

Runs on the staged content copy (never the source repo), after the MarkPub
scaffold and BEFORE gen_sidebar.py (so the sidebar's door detection sees any
folder note this tool creates) and before vitrine.py (so the emitted `.md`
links go through the same `.md` -> `.html` rewrite as everything else).

Three jobs:

  1. Room contents. Each room's folder note gets a generated `## Contents`
     section: the room's tree, subfolders nested, Markdown files linked by
     their frontmatter `title:` (falling back to the filename), non-Markdown
     files (transcripts, chats) linked by filename. A room with no folder
     note gets one created in the copy — `README.md` by default,
     `<room>/<room>.md` when VITRINE_FOLDER_NOTE=1 (Obsidian folder-note
     convention).
  2. Sitemap. `sitemap.md` at the content root maps the whole published
     tree — every room plus anything else the copy carries — one page,
     rendered with the site theme.
  3. 404. `404.md` at the content root; Cloudflare Pages serves the built
     `404.html` for unknown routes instead of falling back to the home page
     with a 200 (which, combined with relative links, produced ever-growing
     phantom URLs). All its links are site-absolute: a 404 page renders at
     arbitrary paths.

Link targets are emitted site-absolute and pass through markpub_post's
scrub_path, mirroring how MarkPub rewrites file paths on disk (spaces and
`_?#%"` runs become `_`) — a link to `zoom transcript.txt` must point at
`zoom_transcript.txt` or it 404s.

The entity room is left to its own generated index (`entities/entities.md`,
from entity_lint.py upstream): no Contents section is added there, but its
records do appear in the sitemap.

Usage:
  gen_navigation.py CONTENT_DIR

Environment:
  VITRINE_FOLDER_NOTE  set to 1 to create missing room notes as
                       `<room>/<room>.md` instead of `README.md`
"""

import argparse
import os
import sys
from pathlib import Path

# sibling-module helpers (same directory): frontmatter parsing from
# vitrine.py, MarkPub's path scrub from markpub_post.py, the room list and
# folder-note resolution from gen_sidebar.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_sidebar import ROOMS, folder_note  # noqa: E402
from markpub_post import scrub_path  # noqa: E402
from vitrine import escape_link_label, get_title, split_front_matter  # noqa: E402

# Infrastructure pages that must not list themselves.
SELF_PAGES = {'Sidebar.md', 'sitemap.md', '404.md'}


def md_label(path: Path) -> str:
    """Human label for a Markdown file: frontmatter title, else stem."""
    fm, _body = split_front_matter(path.read_text(encoding='utf-8'))
    return get_title(fm) or path.stem


def link_target(content: Path, path: Path) -> str:
    """Site-absolute, scrub-mirrored target for a file in the copy."""
    return scrub_path('/' + path.relative_to(content).as_posix())


def tree_lines(content: Path, d: Path, depth: int, skip: set):
    """Nested Markdown bullets for the tree under d (files first, then
    subfolders), skipping hidden entries and the paths in `skip`."""
    indent = '  ' * depth
    lines = []
    entries = sorted(d.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    for entry in entries:
        if entry.name.startswith('.') or entry in skip:
            continue
        if entry.is_dir():
            note = folder_note(entry)
            if note:
                lines.append(f'{indent}- [{escape_link_label(entry.name)}/]({link_target(content, note)})')
            else:
                lines.append(f'{indent}- {entry.name}/')
            lines.extend(tree_lines(content, entry, depth + 1, skip | ({note} if note else set())))
        elif entry.suffix == '.md':
            lines.append(f'{indent}- [{escape_link_label(md_label(entry))}]({link_target(content, entry)})')
        else:
            lines.append(f'{indent}- [{escape_link_label(entry.name)}]({link_target(content, entry)})')
    return lines


def room_contents(content: Path, room: str, use_folder_note: bool) -> str:
    """Append a generated Contents section to the room's note (created in
    the copy if missing). Returns a short status string."""
    d = content / room
    note = folder_note(d)
    if note is None:
        name = f'{room}.md' if use_folder_note else 'README.md'
        note = d / name
        note.write_text(f'---\ntitle: {room}/\n---\n\n', encoding='utf-8')
        created = f' (created {name})'
    else:
        created = ''
    lines = tree_lines(content, d, 0, {note})
    listing = '\n'.join(lines) if lines else '_none yet_'
    text = note.read_text(encoding='utf-8').rstrip('\n')
    note.write_text(f'{text}\n\n## Contents\n\n{listing}\n', encoding='utf-8')
    return f'{room}{created}: {len(lines)} entries'


def write_sitemap(content: Path):
    """One page mapping the whole published tree, root included."""
    skip = {content / n for n in SELF_PAGES}
    lines = tree_lines(content, content, 0, skip)
    body = '\n'.join(lines)
    (content / 'sitemap.md').write_text(
        f'---\ntitle: Sitemap\n---\n\n'
        f'Everything published on this site, one page. Rooms link to their '
        f'own contents; records keep their catalog titles.\n\n{body}\n',
        encoding='utf-8')


def write_404(content: Path):
    """A real not-found page; links are site-absolute on purpose."""
    (content / '404.md').write_text(
        '---\ntitle: Page not found\n---\n\n'
        'This address does not match anything on the site. The link that '
        'brought you here may be stale, or the page may have moved.\n\n'
        '- [HOME](/)\n'
        '- [Sitemap](/sitemap.md)\n'
        '- [Search](/search.html)\n',
        encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='gen_navigation.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy to generate navigation into (never the source repo)')
    args = parser.parse_args(argv)

    content = Path(args.content_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')

    use_folder_note = os.environ.get('VITRINE_FOLDER_NOTE', '') == '1'
    statuses = [room_contents(content, room, use_folder_note)
                for room, _label in ROOMS if (content / room).is_dir()]
    write_sitemap(content)
    write_404(content)
    print(f'gen_navigation: rooms [{", ".join(statuses)}]; wrote sitemap.md, 404.md')
    return 0


if __name__ == '__main__':
    sys.exit(main())
