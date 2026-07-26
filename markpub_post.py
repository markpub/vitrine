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

It also prunes the infrastructure pages (404, sitemap) from the places
MarkPub lists ordinary pages: the all-pages/recent-pages tables and the
lunr posts file — the latter feeds both search-result display and the
theme's RANDOM PAGE button, so pruning it keeps 'Page not found' out of
the random rotation. The pages stay in the *serialized* lunr index (a
prebuilt artifact this tool does not rewrite), so doSearch in search.html
is patched to drop index hits that no longer have a posts entry — without
that guard, one orphaned hit would break the whole result list. The posts
pruning is therefore applied only when the guard patch takes (a theme
change could stop its pattern matching); if it doesn't, the infra pages
stay listed in search/random — the cosmetic status quo, never a broken
search.

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

# infrastructure pages kept out of listings, search results, and RANDOM PAGE
INFRA_PAGES = ('/404.html', '/sitemap.html')


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


def fix_edit_links(site: Path, renames: dict) -> int:
    """Point Edit buttons of renamed pages back at the REAL source files.

    MarkPub builds edit URLs from the copy's file paths; under slug
    publishing (rename_pages.py) those paths do not exist in the source
    repo. For each renamed page, rewrite the `.../edit/<branch>/<new>.md`
    href back to the source's bare-ID path."""
    count = 0
    for old_abs, new_abs in renames.items():
        page = site / (scrub_path(new_abs).lstrip('/') + '.html')
        if not page.is_file():
            continue
        old_rel, new_rel = old_abs.lstrip('/') + '.md', new_abs.lstrip('/') + '.md'
        text = page.read_text(encoding='utf-8')
        new_text, n = re.subn(
            r'(href="[^"]*?/edit/[^"]*?)' + re.escape(new_rel) + r'"',
            r'\g<1>' + old_rel + r'"', text)
        if n:
            page.write_text(new_text, encoding='utf-8')
            count += n
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


def prune_listing_rows(site: Path, listing_name: str) -> int:
    """Drop the infrastructure pages' rows from a listing table."""
    listing = site / listing_name
    if not listing.is_file():
        return 0
    text = listing.read_text(encoding='utf-8')
    count = 0
    for target in INFRA_PAGES:
        text, n = re.subn(
            r'<tr>\s*<td>\s*<a href="' + re.escape(target) + r'">.*?</tr>\s*',
            '', text, flags=re.S)
        count += n
    if count:
        listing.write_text(text, encoding='utf-8')
    return count


def prune_lunr_posts(site: Path) -> int:
    """Drop the infrastructure pages from lunr-posts-<ts>.js (feeds both
    search-result display and the theme's RANDOM PAGE rotation)."""
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
        kept = [p for p in posts if p.get('link') not in INFRA_PAGES]
        if len(kept) != len(posts):
            posts_file.write_text('lunr_posts= ' + json.dumps(kept),
                                  encoding='utf-8')
            count += len(posts) - len(kept)
    return count


def guard_search_results(site: Path) -> bool:
    """Make doSearch drop index hits with no posts entry: the serialized
    lunr index still knows the pruned pages, and an orphaned hit would
    throw on `element.title` and kill the whole result list."""
    page = site / 'search.html'
    if not page.is_file():
        return False
    text = page.read_text(encoding='utf-8')
    new, n = re.subn(
        r'(index\.search\(searchString\)\.map\(\(item\) => \{\s*'
        r'return lunr_posts\.find\(\(post\) => item\.ref === post\.link\)\s*'
        r'\}\))',
        r'\1.filter((post) => post)', text)
    if n:
        page.write_text(new, encoding='utf-8')
    return bool(n)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='markpub_post.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('content_dir', help='staged content copy (source of frontmatter titles)')
    parser.add_argument('site_dir', help='generated MarkPub site to fix up in place')
    parser.add_argument('--rename-map', metavar='FILE',
                        help='JSON map of copy-side page renames (from rename_pages.py); '
                             'Edit buttons of renamed pages are pointed back at the source files')
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
    edits = 0
    if args.rename_map:
        renames = json.loads(Path(args.rename_map).read_text(encoding='utf-8'))
        edits = fix_edit_links(site, renames)
    rows = sum(prune_listing_rows(site, name)
               for name in ('all-pages.html', 'recent-pages.html'))
    # guard FIRST, and only prune the posts file if the guard took: pruned
    # posts without the guard would make any search hit on an infra page
    # throw and blank that query's whole result list — worse than the
    # cosmetic problem the pruning fixes
    guarded = guard_search_results(site)
    posts = prune_lunr_posts(site) if guarded else 0
    guard_note = ('applied' if guarded
                  else 'NOT applied — lunr posts left unpruned')
    print(f'markpub_post: {len(mapping)} titled pages; '
          f'fixed {titles} <title> tags, {listings} listing entries, {lunr} lunr posts, '
          f'{edits} edit links; pruned {rows} listing rows, {posts} lunr posts '
          f'(infra pages); search guard {guard_note}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
