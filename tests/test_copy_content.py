#!/usr/bin/env python3
"""Tests for copy_content.py — the staging copy and its ignore-file syntax.

Two of these classes are differential: they check our behavior against the
tools whose behavior we are claiming to reproduce. `GitOracleTest` asks
`git check-ignore` about every fixture path and compares verdicts, which is
what makes "gitignore syntax" a testable claim rather than a docs promise.
`RsyncEquivalenceTest` compares a staged copy against `rsync -a`, the call
this module replaced. Both skip cleanly when the tool is absent, so the
suite never reintroduces the dependency it exists to remove.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copy_content import Ignore, copy_tree  # noqa: E402

HAVE_GIT = shutil.which("git") is not None
HAVE_RSYNC = shutil.which("rsync") is not None

# Patterns covering every construct copy_content.py documents.
PATTERNS = [
    "# a comment",
    "",
    "project/correspondence/",      # anchored, directory only (comroom's real one)
    "*.tmp",                        # basename glob, any depth
    "/root-only.md",                # anchored to the source root
    "drafts/",                      # directory, any depth
    "notes",                        # bare name, any depth, file or directory
    "logs/**/verbose.txt",          # ** spanning segments
    "**/generated",                 # leading **
    "keep/*.md",                    # anchored, one level
    "!keep/important.md",           # negation
    "img?.png",                     # single-character wildcard
    "[abc]-thing.md",               # character class
]

TREE = [
    "root-only.md",
    "sub/root-only.md",
    "project/correspondence/letter.md",
    "project/README.md",
    "a/b/c.tmp",
    "a/b/c.md",
    "drafts/x.md",
    "deep/drafts/y.md",
    "notes",
    "a/notes/inner.md",
    "logs/verbose.txt",
    "logs/one/verbose.txt",
    "logs/one/two/verbose.txt",
    "logs/one/other.txt",
    "generated/out.js",
    "a/b/generated/out.js",
    "keep/important.md",
    "keep/other.md",
    "keep/nested/deep.md",
    "img1.png",
    "img12.png",
    "b-thing.md",
    "d-thing.md",
]


def build_tree(root, paths):
    """Create every path in `paths` as a one-line file under `root`."""
    directories = set()
    for path in paths:
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        for i in range(1, len(path.split("/"))):
            directories.add("/".join(path.split("/")[:i]))
        with open(full, "w", encoding="utf-8") as handle:
            handle.write("x\n")
    return directories


AGED = 1600000000  # a fixed timestamp in the past (2020-09-13), so that
                   # "was the mtime carried over?" cannot accidentally pass
                   # by both sides simply being a few milliseconds old


def age_tree(root):
    """Stamp every directory and regular file in `root` with AGED, deepest first."""
    for dirpath, _, filenames in sorted(os.walk(root), reverse=True):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                os.utime(path, (AGED, AGED))
        os.utime(dirpath, (AGED, AGED))


def walk_relative(root):
    """Every path under `root`, relative and sorted, directories included."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        rel = "" if rel == "." else rel
        for name in list(dirnames) + filenames:
            found.append(f"{rel}/{name}" if rel else name)
    return sorted(found)


class IgnoreSyntaxTest(unittest.TestCase):
    """The documented constructs, asserted directly."""

    def setUp(self):
        self.spec = Ignore(PATTERNS)

    def assertExcluded(self, path, is_dir=False):
        self.assertTrue(self.spec.excludes(path, is_dir), f"expected excluded: {path}")

    def assertKept(self, path, is_dir=False):
        self.assertFalse(self.spec.excludes(path, is_dir), f"expected kept: {path}")

    def test_comments_and_blank_lines_are_not_patterns(self):
        self.assertKept("a comment")
        self.assertKept("")

    def test_leading_slash_anchors_to_the_root(self):
        self.assertExcluded("root-only.md")
        self.assertKept("sub/root-only.md")

    def test_bare_name_matches_at_any_depth(self):
        self.assertExcluded("notes")
        self.assertExcluded("a/notes", is_dir=True)

    def test_trailing_slash_restricts_to_directories(self):
        self.assertExcluded("drafts", is_dir=True)
        self.assertExcluded("deep/drafts", is_dir=True)
        self.assertKept("drafts")           # same name, but a file

    def test_interior_slash_anchors_without_a_leading_one(self):
        self.assertExcluded("project/correspondence", is_dir=True)
        self.assertKept("elsewhere/project/correspondence", is_dir=True)

    def test_star_does_not_cross_a_separator(self):
        self.assertExcluded("keep/other.md")
        self.assertKept("keep/nested/deep.md")

    def test_double_star_spans_segments(self):
        self.assertExcluded("logs/verbose.txt")
        self.assertExcluded("logs/one/two/verbose.txt")
        self.assertKept("logs/one/other.txt")

    def test_leading_double_star_matches_at_any_depth(self):
        self.assertExcluded("generated", is_dir=True)
        self.assertExcluded("a/b/generated", is_dir=True)

    def test_negation_re_includes(self):
        self.assertExcluded("keep/other.md")
        self.assertKept("keep/important.md")

    def test_question_mark_matches_one_character(self):
        self.assertExcluded("img1.png")
        self.assertKept("img12.png")

    def test_character_class(self):
        self.assertExcluded("b-thing.md")
        self.assertKept("d-thing.md")

    def test_last_match_wins(self):
        spec = Ignore(["*.md", "!keep.md", "keep.md"])
        self.assertTrue(spec.excludes("keep.md", False))
        spec = Ignore(["*.md", "keep.md", "!keep.md"])
        self.assertFalse(spec.excludes("keep.md", False))


@unittest.skipUnless(HAVE_GIT, "git not available")
class GitOracleTest(unittest.TestCase):
    """Every verdict compared against git's own gitignore engine."""

    def test_matches_git_check_ignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            directories = build_tree(tmp, TREE)
            with open(os.path.join(tmp, ".gitignore"), "w", encoding="utf-8") as handle:
                handle.write("\n".join(PATTERNS) + "\n")

            spec = Ignore(PATTERNS)
            mismatches = []
            for path in sorted(set(TREE) | directories):
                git_says = subprocess.run(
                    ["git", "-C", tmp, "check-ignore", "-q", path]
                ).returncode == 0
                # A path under an excluded directory stays excluded, which is
                # how the copy behaves (the directory is pruned from the walk).
                parts = path.split("/")
                ancestors = ["/".join(parts[:i]) for i in range(1, len(parts))]
                we_say = (any(spec.excludes(a, True) for a in ancestors)
                          or spec.excludes(path, path in directories))
                if git_says != we_say:
                    mismatches.append(f"{path}: git={git_says} ours={we_say}")

            self.assertEqual([], mismatches)


class CopyFidelityTest(unittest.TestCase):
    """What lands in the staged copy, and what it looks like when it gets there."""

    def stage(self, names=(), patterns=None):
        source = tempfile.mkdtemp()
        dest = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, source, ignore_errors=True)
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        build_tree(source, TREE)
        os.makedirs(os.path.join(source, "an-empty-dir"))
        os.symlink("project/README.md", os.path.join(source, "link-to-file"))
        os.symlink("project", os.path.join(source, "link-to-dir"))
        os.chmod(os.path.join(source, "notes"), 0o755)
        age_tree(source)
        ignore = Ignore(patterns) if patterns is not None else None
        counts = copy_tree(source, dest, set(names), ignore)
        return source, dest, counts

    def test_source_is_never_written_to(self):
        source, dest, _ = self.stage(names=["drafts"])
        before = walk_relative(source)
        copy_tree(source, tempfile.mkdtemp(), {"drafts"}, None)
        self.assertEqual(before, walk_relative(source))

    def test_named_excludes_apply_at_any_depth(self):
        _, dest, _ = self.stage(names=["generated"])
        staged = walk_relative(dest)
        self.assertNotIn("generated", staged)
        self.assertNotIn("a/b/generated", staged)
        self.assertIn("project/README.md", staged)

    def test_ignore_patterns_apply(self):
        _, dest, _ = self.stage(patterns=PATTERNS)
        staged = walk_relative(dest)
        self.assertNotIn("project/correspondence", staged)
        self.assertNotIn("keep/other.md", staged)
        self.assertIn("keep/important.md", staged)   # negation survived
        self.assertIn("project/README.md", staged)

    def test_empty_directories_survive(self):
        _, dest, _ = self.stage()
        self.assertTrue(os.path.isdir(os.path.join(dest, "an-empty-dir")))

    def test_symlinks_are_recreated_not_followed(self):
        _, dest, counts = self.stage()
        link_file = os.path.join(dest, "link-to-file")
        link_dir = os.path.join(dest, "link-to-dir")
        self.assertTrue(os.path.islink(link_file))
        self.assertTrue(os.path.islink(link_dir))
        self.assertEqual("project/README.md", os.readlink(link_file))
        self.assertEqual("project", os.readlink(link_dir))
        self.assertEqual(2, counts[1])

    def test_modes_and_mtimes_are_preserved(self):
        source, dest, _ = self.stage()
        for rel in ["notes", "project/README.md", "a/b/c.md"]:
            src_stat = os.stat(os.path.join(source, rel))
            dst_stat = os.stat(os.path.join(dest, rel))
            self.assertEqual(src_stat.st_mode, dst_stat.st_mode, rel)
            self.assertEqual(src_stat.st_mtime, dst_stat.st_mtime, rel)

    def test_directory_mtimes_are_preserved(self):
        # The source tree is aged to AGED, so a directory that was merely
        # created by the copy (mtime "now") fails this rather than passing
        # by coincidence.
        source, dest, _ = self.stage()
        for rel in ["project", "a/b", "an-empty-dir"]:
            self.assertEqual(AGED, int(os.stat(os.path.join(source, rel)).st_mtime), rel)
            self.assertEqual(AGED, int(os.stat(os.path.join(dest, rel)).st_mtime), rel)


@unittest.skipUnless(HAVE_RSYNC, "rsync not available")
class RsyncEquivalenceTest(unittest.TestCase):
    """The staged copy against `rsync -a`, the call this module replaced."""

    def test_same_paths_modes_and_mtimes(self):
        source = tempfile.mkdtemp()
        via_rsync = tempfile.mkdtemp()
        via_python = tempfile.mkdtemp()
        for path in (source, via_rsync, via_python):
            self.addCleanup(shutil.rmtree, path, ignore_errors=True)

        build_tree(source, TREE)
        os.makedirs(os.path.join(source, "an-empty-dir"))
        os.symlink("project/README.md", os.path.join(source, "link-to-file"))
        os.chmod(os.path.join(source, "notes"), 0o755)
        ignore_file = os.path.join(source, ".vitrineignore")
        with open(ignore_file, "w", encoding="utf-8") as handle:
            handle.write("project/correspondence/\n*.tmp\n")
        age_tree(source)

        subprocess.run(
            ["rsync", "-a", "--exclude", ".vitrineignore",
             "--exclude-from", ignore_file, f"{source}/", f"{via_rsync}/"],
            check=True,
        )
        copy_tree(source, via_python, {".vitrineignore"}, Ignore.from_file(ignore_file))

        self.assertEqual(walk_relative(via_rsync), walk_relative(via_python))
        for rel in walk_relative(via_rsync):
            left = os.lstat(os.path.join(via_rsync, rel))
            right = os.lstat(os.path.join(via_python, rel))
            self.assertEqual(left.st_mode, right.st_mode, rel)
            if os.path.islink(os.path.join(via_rsync, rel)):
                # A symlink's own mtime is set when the link is created and is
                # not carried over by `os.symlink` OR by rsync on macOS, so it
                # is whenever each copy ran. Compare what actually matters.
                self.assertEqual(os.readlink(os.path.join(via_rsync, rel)),
                                 os.readlink(os.path.join(via_python, rel)), rel)
                continue
            # whole seconds: rsync 2.6.9 (macOS 14's system copy) does not
            # carry sub-second mtimes
            self.assertEqual(int(left.st_mtime), int(right.st_mtime), rel)
            self.assertEqual(AGED, int(right.st_mtime), rel)


if __name__ == "__main__":
    unittest.main()
