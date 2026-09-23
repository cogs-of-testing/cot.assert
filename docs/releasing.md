# Releasing

Versions come from git tags (hatch-vcs). Pushing a `v*` tag runs
`.github/workflows/release.yml`, which tests, builds, smoke-tests the wheel
on Python 3, CPython 2.7 and PyPy2.7, and publishes to PyPI through trusted
publishing.

## Once: trusted publisher

On PyPI, add a pending publisher for the project `cot-assert`:

| field | value |
|---|---|
| owner | `cogs-of-testing` |
| repository | `cot.assert` |
| workflow | `release.yml` |
| environment | `pypi` |

GitHub creates the `pypi` environment on the first run that uses it.
Protection rules on it (required reviewers, tag-only deployments) are
optional.

## Each release

1. Update `CHANGELOG.md` on `main`.
2. Tag the commit on `main` and push the tag:

       git tag v0.1.0
       git push origin v0.1.0
