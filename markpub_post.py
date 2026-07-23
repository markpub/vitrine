#!/usr/bin/env python3
"""MarkPub-specific post-processing: put human titles where MarkPub keys off
the filename stem.

MarkPub derives a page's display name from its filename stem in three
places that the in-content H1 insertion (vitrine.py T1) cannot reach:

  * the page `<title>` tag  (dolce: `page_title = title ~ ' - ' ~ wiki_title`,
    where `title` is `file.stem` — markpub.py get_page_context)
  * the all-pages.html / recent-pages.html listings
    (markpub.py: `all_pages.append({'title': Path(file).stem, ...})`)
  * the lunr posts list used for search-result display
    (`lunr_posts.append({..., 'title': Path(file).stem})`)

This tool runs AFTER `markpub build`, reads each source page's frontmatter
`title:` from the staged content copy, and rewrites those three spots in the
generated site. It is the one deliberately MarkPub-specific piece of the
chain; vitrine.py itself stays publisher-agnostic.

Usage:
  markpub_post.py CONTENT_DIR SITE_DIR
"""

import argparse
import ast
import html
import json
import re
import sys
from pathlib import Path

# import frontmatter/title helpers from vitrine.py (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vitrine import split_front_matter, get_title  # noqa: E402


def scrub_path(filepath: str) -> str:
    """Mirror markpub.py's scrub_path so our paths match its output paths."""
    return re.sub(r'([ _?\#%"]+)', '_', filepath)


def build_title_map(content: Path):
    """Map site-relative html path -> (stem, human title) for titled pages."""
    mapping = {}
    for md in sorted(content.rglob('*.md')):
        rel = md.relative_to(content)
        if any(part.startswith('.') for part in rel.parts):
            continue
        fm, _body = split_front_matter(md.read_text(encoding='utf-8'))
        title = get_title(fm)
        if title and title != md.stem:
            html_rel = scrub_path('/' + rel.as_posix())[:-3] + '.html'
            mapping[html_rel] = (md.stem, title)
    return mapping


def fix_page_title_tag(site: Path, html_rel: str, stem: str, title: str) -> bool:
    page = site / html_rel.lstrip('/')
    if not page.is_file():
        return False
    text = page.read_text(encoding='utf-8')
    new = text.replace(f'<title>{stem} - ', f'<title>{html.escape(title)} - ', 1)
    if new != text:
        page.write_text(new, encoding='utf-8')
        return True
    return False


def fix_listing(site: Path, listing_name: str, mapping) -> int:
    listing = site / listing_name
    if not listing.is_file():
        return 0
    text = listing.read_text(encoding='utf-8')
    count = 0
    for html_rel, (stem, title) in mapping.items():
        pattern = re.compile(
            r'(<a href="[^"]*' + re.escape(html_rel) + r'">)\s*'
            + re.escape(stem) + r'\s*(</a>)')
        text, n = pattern.subn(r'\g<1>' + html.escape(title) + r'\g<2>', text)
        count += n
    listing.write_text(text, encoding='utf-8')
    return count


def fix_lunr_posts(site: Path, mapping) -> int:
    """Rewrite titles in lunr-posts-<ts>.js (drives search-result display)."""
    count = 0
    for posts_file in site.glob('lunr-posts-*.js'):
        text = posts_file.read_text(encoding='utf-8')
        m = re.match(r'^lunr_posts=\s*(.*)$', text, re.S)
        if not m:
            continue
        try:
            posts = ast.literal_eval(m.group(1).strip())
        except (ValueError, SyntaxError):
            continue
        for post in posts:
            entry = mapping.get(post.get('link', ''))
            if entry and post.get('title') == entry[0]:
                post['title'] = entry[1]
                count += 1
        posts_file.write_text('lunr_posts= ' + json.dumps(posts), encoding='utf-8')
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='markpub_post.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy (source of frontmatter titles)')
    parser.add_argument('site_dir', help='generated MarkPub site to fix up in place')
    args = parser.parse_args(argv)

    content, site = Path(args.content_dir), Path(args.site_dir)
    if not content.is_dir():
        parser.error(f'not a directory: {content}')
    if not site.is_dir():
        parser.error(f'not a directory: {site}')

    mapping = build_title_map(content)
    titles = sum(fix_page_title_tag(site, hr, s, t) for hr, (s, t) in mapping.items())
    listings = sum(fix_listing(site, name, mapping)
                   for name in ('all-pages.html', 'recent-pages.html'))
    lunr = fix_lunr_posts(site, mapping)
    print(f'markpub_post: {len(mapping)} titled pages; '
          f'fixed {titles} <title> tags, {listings} listing entries, {lunr} lunr posts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
