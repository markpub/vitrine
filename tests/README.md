# Tests

Run them from the repository root:

```
python3 -m unittest discover -s tests
```

Add `-v` to see each test named. There is nothing to install.

## Conventions

**Standard library only.** Tests use `unittest`, never pytest or any other third-party runner. Vitrine's own rule is that it depends on nothing outside the standard library except `markpub` and `pyyaml`; a test suite that needed a pip install to run would quietly undo that for every contributor and every CI image.

**One `test_<module>.py` per module**, in this directory. Each one puts the repository root on `sys.path` itself, so discovery works from the root with no packaging, no `conftest`, and no `PYTHONPATH` to remember.

**Fixtures are built, not committed.** Tests construct their trees under `tempfile.TemporaryDirectory()` or `mkdtemp()` and clean up after themselves. Nothing in the repository is written to, and no test needs a real content repo to be present.

**Differential tests skip rather than fail.** Where a test compares Vitrine against an external tool — `git check-ignore` as the oracle for gitignore syntax, `rsync -a` as the reference for the copy it replaced — it is guarded with `@unittest.skipUnless(shutil.which("tool"), ...)`. The suite has to pass on a machine that has neither, or it would reintroduce the dependencies these tests exist to check us against.

**Assert the value, not just the agreement.** A test that compares two freshly-created trees can pass because both sides are equally wrong — two directories created seconds apart both look "recent." Where a test checks that something was *carried over*, it stamps the source with a fixed past value (`AGED`) and asserts that exact value on both sides, so a copy that merely made a new directory fails.

**Check that a new test can fail.** Before trusting one, break the code it covers and confirm it goes red. `test_directory_mtimes_are_preserved` passed against a build with the directory restamping deleted outright until it was rewritten to the rule above; it was testing nothing.
