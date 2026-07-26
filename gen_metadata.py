#!/usr/bin/env python3
"""Publish selected frontmatter metadata as a bullet list on each record page.

MarkPub drops YAML frontmatter from the rendered page, so a record's dates,
participants, status and references are invisible on the site. This tool
renders the *relevant* fields — declared per entity type in the content
repo's `.vitrine.yaml` — as a Markdown bullet list at the top of the body,
on the staged copy only (the source repo is never touched).

Config (`.vitrine.yaml` at the source root, same travel-with-the-content
pattern as `.vitrineignore`):

  metadata:
    _default: none            # types without an entry: none | all | [fields]
    decision: [id, meeting, status]
    meeting:  [id, date, participants, artifacts]

The listed order is the display order. `title` and `slug` are never
published (the title is the page's H1; the slug is the URL). With no config
file, or no `metadata:` section, nothing changes.

Value rendering:
  * a value matching a record ID that exists in the copy becomes a link to
    that record, labeled with the record's title (falling back to the ID);
    targets are emitted as `/path/ID.md`, so the later vitrine.py transform
    absolutizes them and follows any slug renames
  * `http(s)://` values become autolinks
  * lists of scalars are comma-joined, each item rendered by the rules above
  * mappings (nested YAML) become an indented sub-list of `key: value`
    bullets, recursing for deeper nesting; in a list that holds a mapping,
    each mapping item becomes one bullet carrying its first scalar pair,
    with the remaining pairs nested beneath it
  * everything else is printed as-is

Runs BEFORE rename_pages.py (record files still carry their bare-ID names,
so ID -> file resolution is direct) and before vitrine.py (whose T1 inserts
the H1 title above the metadata block).

Usage:
  gen_metadata.py --config SOURCE/.vitrine.yaml CONTENT_DIR
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

import yaml

# sibling-module helpers (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vitrine import escape_link_label, front_matter_data, split_front_matter  # noqa: E402

ID_RE = re.compile(r'^[A-Z][A-Z0-9]*-\d+$')
URL_RE = re.compile(r'^https?://\S+$')

NEVER_PUBLISHED = {'title', 'slug'}


def parse_front_matter(md: Path):
    """Return (front-matter block, parsed dict or {}, body)."""
    fm, body = split_front_matter(md.read_text(encoding='utf-8'))
    return fm, front_matter_data(fm), body


def build_record_index(content: Path):
    """Map record ID -> (site-absolute .md path, title-or-ID label)."""
    index = {}
    for md in sorted(content.rglob('*.md')):
        rel = md.relative_to(content)
        if any(part.startswith('.') for part in rel.parts):
            continue
        if not ID_RE.match(md.stem):
            continue
        _fm, data, _body = parse_front_matter(md)
        title = data.get('title')
        label = title.strip() if isinstance(title, str) and title.strip() else md.stem
        index[md.stem] = ('/' + rel.as_posix(), label)
    return index


def render_value(value, records: dict, self_id) -> str:
    if isinstance(value, list):
        return ', '.join(render_value(v, records, self_id) for v in value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    text = str(value).strip()
    # a record's reference to ITSELF (its own id field) stays plain text
    if text in records and text != self_id:
        path, label = records[text]
        return f'[{escape_link_label(label)}]({path})'
    if URL_RE.match(text):
        return f'<{text}>'
    return text


def validate_config(config: dict) -> dict:
    """Warn (stderr) about misshapen metadata specs and coerce them to
    'none', preserving the silent-nothing behavior but making it visible.
    A valid spec is none, 'none', 'all', or a list of field names — a bare
    scalar like `decision: id` is the classic mistake (meant `[id]`)."""
    out = {}
    for entity, spec in config.items():
        if spec in (None, 'none', 'all') or isinstance(spec, list):
            out[entity] = spec
        else:
            # the did-you-mean hint only makes sense for a bare field name
            hint = f' (did you mean [{spec}]?)' if isinstance(spec, str) else ''
            print(f"gen_metadata: WARNING: metadata spec for '{entity}' is "
                  f"{spec!r}; expected 'none', 'all', or a list of field "
                  f"names{hint} — publishing no fields for this type",
                  file=sys.stderr)
            out[entity] = 'none'
    return out


def fields_for(entity: str, config: dict):
    """The field list to publish for this entity type, or None for none."""
    spec = config.get(entity, config.get('_default', 'none'))
    if spec in (None, 'none'):
        return None
    if spec == 'all':
        return 'all'
    if isinstance(spec, list):
        return [f for f in spec if f not in NEVER_PUBLISHED]
    return None


def is_nested(value) -> bool:
    """True when a value needs a sub-list (a mapping, or a list holding one)
    rather than an inline rendering."""
    if isinstance(value, dict):
        return True
    return isinstance(value, list) and any(is_nested(v) for v in value)


def render_nested(value, records: dict, self_id, depth: int) -> list:
    """Indented sub-bullet lines for a mapping, or for a list that holds one."""
    pad = '  ' * depth
    lines = []
    if isinstance(value, dict):
        for key, v in value.items():
            if v in (None, '', [], {}):
                continue
            if is_nested(v):
                sub = render_nested(v, records, self_id, depth + 1)
                if sub:
                    lines.append(f'{pad}- {key}:')
                    lines.extend(sub)
            else:
                lines.append(f'{pad}- {key}: {render_value(v, records, self_id)}')
    else:
        for v in value:
            if v in (None, '', [], {}):
                continue
            if is_nested(v):
                if isinstance(v, dict):
                    # rotate a scalar pair to the front so it can ride the
                    # dash line: a nested first pair would visually swallow
                    # the sibling pairs that follow it
                    items = list(v.items())
                    i = next((i for i, (_k, x) in enumerate(items)
                              if x not in (None, '', [], {})
                              and not is_nested(x)), None)
                    if i is not None and i > 0:
                        items.insert(0, items.pop(i))
                        v = dict(items)
                sub = render_nested(v, records, self_id, depth + 1)
                if sub:
                    # the item's first pair rides on the dash line: a bare '-'
                    # under a paragraph line is a setext underline to
                    # CommonMark, so the field label would render as an <h2>
                    first = sub[0].lstrip()
                    lines.append(f'{pad}- {first[2:]}')
                    lines.extend(sub[1:])
            else:
                lines.append(f'{pad}- {render_value(v, records, self_id)}')
    return lines


def metadata_block(data: dict, spec, records: dict) -> str:
    if spec == 'all':
        names = [k for k in data if k not in NEVER_PUBLISHED]
    else:
        names = [f for f in spec if f in data]
    self_id = data.get('id')
    lines = []
    for name in names:
        value = data.get(name)
        if value in (None, '', [], {}):
            continue
        if is_nested(value):
            sub = render_nested(value, records, self_id, 1)
            if sub:
                lines.append(f'- **{name}:**')
                lines.extend(sub)
        else:
            lines.append(f'- **{name}:** {render_value(value, records, self_id)}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='gen_metadata.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy to render metadata into (never the source repo)')
    parser.add_argument('--config', metavar='FILE',
                        help='path to the source repo\'s .vitrine.yaml (absent or empty: no-op)')
    args = parser.parse_args(argv)

    content = Path(args.content_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')

    config = {}
    if args.config and Path(args.config).is_file():
        loaded = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
        if isinstance(loaded, dict) and isinstance(loaded.get('metadata'), dict):
            config = validate_config(loaded['metadata'])
    if not config:
        print('gen_metadata: no metadata config; nothing to do')
        return 0

    records = build_record_index(content)
    done = 0
    for md in sorted(content.rglob('*.md')):
        rel = md.relative_to(content)
        if any(part.startswith('.') for part in rel.parts):
            continue
        fm, data, body = parse_front_matter(md)
        entity = data.get('entity')
        if not isinstance(entity, str):
            continue
        spec = fields_for(entity, config)
        if spec is None:
            continue
        block = metadata_block(data, spec, records)
        if not block:
            continue
        md.write_text(f'{fm}{block}\n\n{body.lstrip()}'
                      if body.strip() else f'{fm}{block}\n', encoding='utf-8')
        done += 1
    print(f'gen_metadata: rendered metadata on {done} record pages')
    return 0


if __name__ == '__main__':
    sys.exit(main())
