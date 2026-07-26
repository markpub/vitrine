#!/usr/bin/env python3
"""Stage a copy of a source repo for publishing — step 1 of the Vitrine chain.

    copy_content.py [--exclude NAME]... [--ignore-file PATH] <source> <dest>

Copies <source> into <dest>, skipping excluded names and any path matched by
an ignore file. The source is only ever read.

This replaces the `rsync -a --exclude ...` call the stage used to shell out to.
rsync was doing exactly one job here — a recursive copy with an exclude list —
and paying for it with a system-binary dependency that is not the same program
everywhere: macOS 14 ships rsync 2.6.9 (2006), macOS 15 ships openrsync, and
Homebrew installs rsync 3.x, each with its own filter-rule handling. Doing the
copy in Python removes the dependency (nothing outside the standard library is
used) and makes the ignore-file syntax exactly what the docs claim it is.

Ignore-file syntax (gitignore rules, per gitignore(5)):

  * blank lines and lines whose first non-space character is `#` are skipped
  * `!pattern` re-includes a path an earlier pattern excluded
  * a trailing `/` restricts the pattern to directories
  * a leading `/`, or any `/` inside the pattern, anchors it to the source root;
    a pattern with no `/` matches at any depth
  * `*` matches within one path segment, `?` matches one character, `[abc]` and
    `[!abc]` are character classes, and `**` spans segments
  * the LAST matching pattern decides
  * a path under an excluded directory stays excluded — a negation cannot reach
    back into a directory that was already pruned, same as git

Metadata handling matches `rsync -a` for the cases a content repo has: file
mode and mtime are preserved, symlinks are recreated as symlinks, and empty
directories survive the copy.
"""

import argparse
import os
import re
import shutil
import sys


# ---------------------------------------------------------------- pattern

def _translate(pat):
    """Translate one gitignore glob into regex source (unanchored)."""
    out = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            j = i
            while j < n and pat[j] == "*":
                j += 1
            doubled = (j - i) >= 2
            at_segment_start = i == 0 or pat[i - 1] == "/"
            at_segment_end = j >= n or pat[j] == "/"
            if doubled and at_segment_start and at_segment_end:
                if j >= n:
                    out.append(".*")          # trailing `**` — everything below
                else:
                    out.append("(?:.*/)?")    # `**/` — any number of directories
                    j += 1                    # consume the separator
            else:
                out.append("[^/]*")
            i = j
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:                        # unterminated class — literal `[`
                out.append(re.escape(c))
                i += 1
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j + 1
        elif c == "\\" and i + 1 < n:         # escaped metacharacter
            out.append(re.escape(pat[i + 1]))
            i += 2
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


class _Rule:
    def __init__(self, line):
        self.negate = line.startswith("!")
        pat = line[1:] if self.negate else line
        self.dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        if pat.startswith("/"):
            anchored, pat = True, pat.lstrip("/")
        else:
            anchored = "/" in pat
        prefix = "" if anchored else "(?:.*/)?"
        self.regex = re.compile("^" + prefix + _translate(pat) + "$")

    def matches(self, relpath, is_dir):
        if self.dir_only and not is_dir:
            return False
        return self.regex.match(relpath) is not None


class Ignore:
    """The rules from one ignore file; last match wins, as in gitignore."""

    def __init__(self, lines):
        self.rules = []
        for raw in lines:
            line = raw.rstrip("\n").rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            self.rules.append(_Rule(line))

    def excludes(self, relpath, is_dir):
        verdict = False
        for rule in self.rules:
            if rule.matches(relpath, is_dir):
                verdict = not rule.negate
        return verdict

    @classmethod
    def from_file(cls, path):
        with open(path, encoding="utf-8") as handle:
            return cls(handle.readlines())


# ------------------------------------------------------------------- copy

def _clone_symlink(source, dest):
    if os.path.lexists(dest):
        os.remove(dest)
    os.symlink(os.readlink(source), dest)


def copy_tree(source, dest, names, ignore):
    """Copy `source` into `dest`. Returns (files, symlinks, skipped)."""
    files = symlinks = skipped = 0
    directories = []

    def excluded(name, relpath, is_dir):
        return name in names or (ignore is not None and ignore.excludes(relpath, is_dir))

    for root, dirnames, filenames in os.walk(source):
        relroot = os.path.relpath(root, source)
        relroot = "" if relroot == "." else relroot
        os.makedirs(os.path.join(dest, relroot) if relroot else dest, exist_ok=True)
        directories.append(relroot)

        kept = []
        for name in sorted(dirnames):
            relpath = f"{relroot}/{name}" if relroot else name
            if excluded(name, relpath, True):
                skipped += 1
                continue
            if os.path.islink(os.path.join(root, name)):
                # a symlinked directory: recreate the link, never descend
                _clone_symlink(os.path.join(root, name), os.path.join(dest, relpath))
                symlinks += 1
                continue
            kept.append(name)
        dirnames[:] = kept                     # prune the walk in place

        for name in sorted(filenames):
            relpath = f"{relroot}/{name}" if relroot else name
            if excluded(name, relpath, False):
                skipped += 1
                continue
            src_path = os.path.join(root, name)
            dst_path = os.path.join(dest, relpath)
            if os.path.islink(src_path):
                _clone_symlink(src_path, dst_path)
                symlinks += 1
            else:
                shutil.copy2(src_path, dst_path)
                files += 1

    # Directory mode and mtime last, deepest first: writing into a directory
    # updates its mtime, so a parent has to be stamped after its children.
    for relroot in sorted(directories, reverse=True):
        shutil.copystat(os.path.join(source, relroot) if relroot else source,
                        os.path.join(dest, relroot) if relroot else dest)

    return files, symlinks, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME",
                        help="skip any file or directory with this name, at any depth")
    parser.add_argument("--ignore-file", metavar="PATH",
                        help="gitignore-syntax file of additional paths to skip")
    parser.add_argument("source")
    parser.add_argument("dest")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        parser.error(f"source is not a directory: {args.source}")

    ignore = None
    if args.ignore_file:
        if not os.path.isfile(args.ignore_file):
            parser.error(f"ignore file not found: {args.ignore_file}")
        ignore = Ignore.from_file(args.ignore_file)

    files, symlinks, skipped = copy_tree(args.source, args.dest,
                                         set(args.exclude), ignore)
    summary = f"copy_content: staged {files} files"
    if symlinks:
        summary += f", {symlinks} symlinks"
    print(f"{summary}; skipped {skipped} excluded paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
