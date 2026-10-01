# Luxeva CI checks

The workflow runs on pushes, pull requests and manual requests with read-only
repository permissions. GitHub Action references are pinned to commits and
maintained by Dependabot. The HACS and hassfest Actions still obtain their
validator containers from upstream tags; the pins do not freeze those images.

Python syntax, Ruff defect checks, hassfest and HACS file/schema validation are
blocking. Ruff compares finding counts by file, rule and message against the PR
base, ignoring line shifts. Pushes compare against the previous commit. Both
revisions use the same explicit rules, ignore repository Ruff configuration and
scan gitignored Python files too. Existing findings remain visible; new findings
fail CI. Manual runs or new branches without a valid previous commit report the
current baseline.

Mypy begins as a nonblocking diagnostic with missing third-party imports skipped.
It is not a complete Home Assistant type check. There is no runtime test suite
yet; syntax, lint, hassfest and HACS do not replace behavioral tests.

## Analyzer dependencies

`.github/ci/requirements.in` lists the direct analyzer versions. The generated
`requirements.txt` pins every dependency and its allowed artifact hashes for
Python 3.13. CI installs wheels only and verifies their hashes.

To update the lock file, use a local `uv` installation:

```sh
uv pip compile --python-version 3.13 --generate-hashes --only-binary :all: \
  --no-emit-index-url .github/ci/requirements.in -o .github/ci/requirements.txt
```

## HACS publishing requirements

HACS file/schema checks are blocking. Repository publishing checks for license,
description and topics are skipped pending repository owner configuration.
A license must be chosen by the owner; this PR does not assign one.
