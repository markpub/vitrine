#!/usr/bin/env python3
"""Vitrine — prepare a COPY of a structured-Markdown "entity-manager" repository
for static publishing.

A vitrine is a museum display case: it presents the objects unaltered. This
tool is therefore only ever pointed at a staged COPY of the content (see
build.sh); it must never be run against the source repository itself.

It applies three surgical, publisher-agnostic transforms in place to every
.md file under CONTENT_DIR:

  T1 — human titles.   If the file's YAML frontmatter has a `title:`, insert
                       `# {title}` as the first body line (unless the body
                       already starts with an H1). Filenames — which are
                       load-bearing bare IDs like DEC-001.md — are never
                       renamed. Records without a title fall back to the ID
                       (i.e. are left untouched).
  T2 — strip shadows.  The entity-manager reference form is
                       `[label](path.md)^[ID](path.md)`; the trailing
                       `^[ID](path.md)` is a validator-only artifact that
                       renders as garbage. It is removed, leaving the human
                       `[label](path.md)` intact.
  T3 — .md → .html,    Relative/local Markdown link targets `x.md` (and
       absolutized.    `x.md#anchor`) are rewritten to `x.html`, so
                       cross-references resolve to rendered pages on any
                       static host — and to SITE-ABSOLUTE paths
                       (`/room/x.html`), computed from each file's location,
                       so a page's links survive being served at the wrong
                       URL (hosts without a real 404 fall back to serving
                       some page for unknown routes, and relative links then
                       compound into ever-deeper phantom paths). External
                       (scheme:// or //) targets are never touched. Runs
                       after T2.

Hard guardrails: fenced code blocks (``` / ~~~) and inline code spans are
never modified; YAML frontmatter is preserved byte-for-byte; everything
outside the three transforms is left byte-identical.

Usage:
  vitrine.py CONTENT_DIR

Requires: Python 3, PyYAML.
"""

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path

import yaml

# T2: validator link shadow `^[ID](path)` immediately following a `)`.
SHADOW_RE = re.compile(r'(?<=\))\^\[[^\]\n]*\]\([^()\n]*\)')

# T3: inline Markdown link target `](target.md)` or `](target.md#anchor)`.
MDLINK_RE = re.compile(r'(\]\()([^)\s]+?)\.md(#[^)\s]*)?(\))')

# T3: reference-style link definition `[ref]: target.md`.
MDREFDEF_RE = re.compile(r'(?m)^(\s{0,3}\[[^\]]+\]:\s*)(\S+?)\.md(#\S*)?(\s*)$')

# Inline code spans: a run of backticks, non-backtick content, matching run.
INLINE_CODE_RE = re.compile(r'(?<!`)(`+)(?!`)([^`]|`(?!`))*?\1(?!`)')

# Fence opener/closer.
FENCE_RE = re.compile(r'^(\s{0,3})(`{3,}|~{3,})(.*)$')

EXTERNAL_RE = re.compile(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)')


def is_external(target: str) -> bool:
    return bool(EXTERNAL_RE.match(target))


def absolutize(target: str, base_dir: str) -> str:
    """Resolve a relative link target against the file's site directory
    (e.g. `../decision/DEC-001` from `/entities/meeting`), yielding a
    site-absolute path. Already-absolute targets pass through."""
    if target.startswith('/'):
        return target
    return posixpath.normpath(posixpath.join(base_dir, target))


def transform_plain_text(text: str, base_dir: str, renames: dict) -> str:
    """Apply T2 then T3 to text known to contain no code spans/fences."""
    # T2 first, so the shadow's own `.md` links are gone before T3.
    text = SHADOW_RE.sub('', text)

    def resolve(target):
        # absolutize, then follow any copy-side rename (slug publishing)
        abs_target = absolutize(target, base_dir)
        return renames.get(abs_target, abs_target)

    def link_sub(m):
        pre, target, anchor, post = m.group(1), m.group(2), m.group(3) or '', m.group(4)
        if is_external(target):
            return m.group(0)
        return f'{pre}{resolve(target)}.html{anchor}{post}'

    text = MDLINK_RE.sub(link_sub, text)

    def refdef_sub(m):
        pre, target, anchor, post = m.group(1), m.group(2), m.group(3) or '', m.group(4)
        if is_external(target):
            return m.group(0)
        return f'{pre}{resolve(target)}.html{anchor}{post}'

    return MDREFDEF_RE.sub(refdef_sub, text)


def transform_non_fence_chunk(chunk: str, base_dir: str, renames: dict) -> str:
    """Apply transforms to a chunk outside fenced blocks, skipping inline code."""
    out = []
    pos = 0
    for m in INLINE_CODE_RE.finditer(chunk):
        out.append(transform_plain_text(chunk[pos:m.start()], base_dir, renames))
        out.append(m.group(0))  # inline code: verbatim
        pos = m.end()
    out.append(transform_plain_text(chunk[pos:], base_dir, renames))
    return ''.join(out)


def transform_body(body: str, base_dir: str, renames: dict) -> str:
    """Walk the body line-by-line, leaving fenced code blocks verbatim."""
    out_parts = []
    plain_buf = []
    in_fence = False
    fence_char = ''
    fence_len = 0

    for line in body.splitlines(keepends=True):
        if not in_fence:
            m = FENCE_RE.match(line)
            if m:
                # flush accumulated plain text through the transforms
                out_parts.append(transform_non_fence_chunk(''.join(plain_buf), base_dir, renames))
                plain_buf = []
                out_parts.append(line)  # fence opener: verbatim
                in_fence = True
                fence_char = m.group(2)[0]
                fence_len = len(m.group(2))
            else:
                plain_buf.append(line)
        else:
            out_parts.append(line)  # inside fence: verbatim
            stripped = line.strip()
            if (stripped and stripped[0] == fence_char
                    and len(stripped) >= fence_len
                    and stripped == stripped[0] * len(stripped)):
                in_fence = False
    out_parts.append(transform_non_fence_chunk(''.join(plain_buf), base_dir, renames))
    return ''.join(out_parts)


def split_front_matter(text: str):
    """Return (front_matter_block, body). Frontmatter block kept verbatim
    (including both '---' lines); empty string if none. Mirrors MarkPub's
    own detection: first line exactly '---', then a closing '---' line."""
    lines = text.splitlines(keepends=True)
    if lines and re.match(r'^---\s*$', lines[0]):
        for i, line in enumerate(lines[1:], start=1):
            if re.match(r'^---\s*$', line):
                return ''.join(lines[:i + 1]), ''.join(lines[i + 1:])
    return '', text


def front_matter_data(front_matter_block: str) -> dict:
    """Parse a frontmatter block (as returned by split_front_matter) into a
    dict. Absent, malformed, or non-mapping YAML yields {} — callers never
    see an exception. The one shared frontmatter parser for the toolchain."""
    if not front_matter_block:
        return {}
    inner = ''.join(front_matter_block.splitlines(keepends=True)[1:-1])
    try:
        data = yaml.safe_load(inner)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def get_title(front_matter_block: str):
    """Parse the frontmatter YAML and return a non-empty string title, or None."""
    title = front_matter_data(front_matter_block).get('title')
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def escape_link_label(label: str) -> str:
    """Escape square brackets in a Markdown link label — an unescaped ]
    would end the label early. Shared by every generator that builds
    `[label](target)` links from titles or filenames."""
    return label.replace('[', r'\[').replace(']', r'\]')


def body_starts_with_h1(body: str) -> bool:
    for line in body.splitlines():
        if not line.strip():
            continue
        return bool(re.match(r'^\s{0,3}#\s', line))
    return False


def transform_file(path: Path, content_root: Path, renames: dict) -> bool:
    """Apply T1–T3 to one file in place. Returns True if the file changed."""
    original = path.read_text(encoding='utf-8')
    fm, body = split_front_matter(original)
    # the file's site directory, for T3 absolutization ('/' at the root)
    rel_dir = path.parent.relative_to(content_root).as_posix()
    base_dir = '/' if rel_dir == '.' else f'/{rel_dir}'
    body = transform_body(body, base_dir, renames)  # T2 + T3, code-guarded
    title = get_title(fm)  # T1
    if title and not body_starts_with_h1(body):
        sep = '' if body.startswith('\n') else '\n'
        body = f'# {title}\n{sep}{body}'
    result = fm + body
    if result != original:
        path.write_text(result, encoding='utf-8')
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='vitrine.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged COPY of the content to transform in place (never the source repo)')
    parser.add_argument('--rename-map', metavar='FILE',
                        help='JSON map of copy-side page renames (from rename_pages.py); '
                             'T3 rewrites link targets through it after absolutizing')
    args = parser.parse_args(argv)

    content = Path(args.content_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')
    renames = {}
    if args.rename_map:
        renames = json.loads(Path(args.rename_map).read_text(encoding='utf-8'))

    changed = total = 0
    for md in sorted(content.rglob('*.md')):
        if any(part.startswith('.') for part in md.relative_to(content).parts):
            continue  # leave hidden dirs (.markpub etc.) alone
        total += 1
        if transform_file(md, content, renames):
            changed += 1
    print(f'vitrine: transformed {changed} of {total} Markdown files in {content}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
