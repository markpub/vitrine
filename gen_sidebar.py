#!/usr/bin/env python3
"""Generate Sidebar.md for a staged content copy (MarkPub sidebar idiom).

Reads the actual room structure of the content directory and writes a
Sidebar.md whose links are universal Markdown links `[LABEL](/path)` —
never `[[wikilinks]]`, which this repository's convention forbids.

Room doors are emitted only for rooms that actually exist, so the sidebar
cannot drift from the repository: `entities/entities.md` (the entity
index), then each of library/ meetingroom/ project/ tools/ logging/,
linking to the room's README.md or, failing that, its first Markdown file.

Door targets are written with their `.md` extension; the vitrine transform
step (which runs after this generator) rewrites them to `.html`.

Usage:
  gen_sidebar.py CONTENT_DIR
"""

import argparse
import sys
from pathlib import Path

# Rooms, in door order. (entity index handled separately, first.)
ROOMS = [
    ('library', 'LIBRARY'),
    ('meetingroom', 'MEETING ROOM'),
    ('project', 'PROJECT'),
    ('tools', 'TOOLS'),
    ('logging', 'LOGGING'),
]

# The MarkPub RANDOM PAGE button idiom, verbatim from the OGM sidebars.
RANDOM_PAGE_BLOCK = """{< div class="navlinks" >}
  <button onclick="location.href=`${randomPageLink()}`">
    RANDOM PAGE
  </button>
{< /div >}"""


def hardwrap(lines):
    """Join short prose lines with Markdown hard breaks (two trailing spaces),
    so a sidebar prose block renders as narrow stacked lines rather than one
    full-width flowing paragraph."""
    return '  \n'.join(lines)


def room_door(content: Path, room: str):
    """Return the site-absolute .md path for a room's door, or None."""
    d = content / room
    if not d.is_dir():
        return None
    if (d / 'README.md').is_file():
        return f'/{room}/README.md'
    mds = sorted(p for p in d.glob('*.md'))
    if mds:
        return f'/{room}/{mds[0].name}'
    return None


def generate(content: Path) -> str:
    nav = ['- [HOME](/)', '- [SEARCH](/search.html)  ']
    if (content / 'entities' / 'entities.md').is_file():
        nav.append('- [ENTITY INDEX](/entities/entities.md)  ')
    for room, label in ROOMS:
        door = room_door(content, room)
        if door:
            nav.append(f'- [{label}]({door})  ')
    nav.append('- [ALL PAGES](/all-pages.html)  ')
    nav.append('- [RECENT CHANGES](/recent-pages.html)')

    nav_lines = '\n'.join(nav)

    # Prose blocks are hard-wrapped so the sidebar column stays narrow:
    # short lines joined with a Markdown hard break (two trailing spaces +
    # newline). This is the MassiveWiki/OGM sidebar convention — keep prose
    # from flowing to full width without needing custom CSS. The `  \n` is
    # produced at runtime so no fragile trailing whitespace lives in source.
    about = hardwrap([
        'Shared working space of the',
        'Adaptive Conversations group:',
        'sources, calls, decisions,',
        'and specifications, kept as',
        'structured Markdown records.',
    ])
    about_start = hardwrap([
        'Start at [HOME](/), or browse',
        'the [ENTITY INDEX](/entities/entities.md).',
    ])
    ai = hardwrap([
        'Parts of this site are',
        'prepared and published by',
        'AI agents; expect some',
        'errors. Records cite their',
        'sources and meetings.',
    ])

    return f"""### Site Navigation

{{< div class="navlinks" >}}
{nav_lines}
{{< /div >}}

{RANDOM_PAGE_BLOCK}

### About this space

{about}

{about_start}

### AI-generated

{ai}
"""


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='gen_sidebar.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy to write Sidebar.md into')
    args = parser.parse_args(argv)

    content = Path(args.content_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')

    sidebar = content / 'Sidebar.md'
    sidebar.write_text(generate(content), encoding='utf-8')
    print(f'gen_sidebar: wrote {sidebar}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
