# Security policy

ROADLENS is an early-stage local desktop application. Security fixes target the
latest source revision. There is no paid support or security-response SLA.

## Report a vulnerability privately

Use this repository's **Security → Advisories → Report a vulnerability** when
GitHub private vulnerability reporting is enabled. If that option is absent,
ask a maintainer in a public issue to provide a private reporting channel;
include no exploit, credentials, video, device ID or sensitive log contents.
Do not post sensitive findings in public issues or pull requests.

Maintainers must enable private vulnerability reporting, secret scanning and
push protection in GitHub settings before the first public push. The intended repository is [siddhantkrishna/roadlens](https://github.com/siddhantkrishna/roadlens);
no private reporting email is invented.

## Threat model and data handling

- Inference, previews and analytics run locally. There is no web server,
  telemetry, cloud inference or application account. `fetch-model` explicitly
  downloads a pinned ONNX file over HTTPS and verifies SHA-256.
- Treat imported videos, ONNX models, scene/configuration files and databases as
  untrusted. Use trusted sources and current dependencies. Native codec/model
  parsers execute in this user's process; process isolation is not a sandbox.
- Do not run as root. macOS controls camera permissions. Device IDs, source paths,
  scene geometry, logs, counts and trajectories can be sensitive even without
  stored camera frames. SQLite and exports are not encrypted at rest.
- Camera frames stay in memory unless the user explicitly exports a snapshot.
  Exclusion zones affect analytics; they do not redact the live image or an
  explicitly saved snapshot. Recorded video is read from the user's selected file.
- Tracking IDs are temporary, source-local observations. Do not use ROADLENS to
  make identity, enforcement, safety-critical or legally consequential decisions.

## Local release checks

```sh
python -m pip install -e '.[dev,security]'
python scripts/check_release.py
bandit -r src scripts -ll -ii
pip-audit -r requirements-macos-intel.lock --no-deps --disable-pip --timeout 60
python -m pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
python -m pip check
```

`check_release.py` examines the actual Git release candidates, including staged
files and non-ignored new files. Stage or restore tracked changes first: the
gate rejects a mismatch between staged and working bytes. It rejects private-file types, symlinks,
unreviewed assets, personal home paths and secret-detector findings. It scans
secret patterns locally with verification network calls disabled; neither raw
secrets nor match values are printed. Known public binary assets require exact
hashes in `docs/public-assets.json`. Only exact reviewed public SHA-256 values
are exempt from the entropy detector; other credential rules remain enabled. Findings block the check; it creates no
allowlist baseline of secret values.

Bandit is gated at medium severity/confidence. Its generic low-severity warnings
about importing subprocess and using argument lists are reviewed, not evidence
of command injection: ROADLENS never invokes a shell. The single dynamic SQL
identifier is explicitly whitelisted before interpolation. Do not add broad
security suppressions or dependency advisory ignores to make CI green.

Dependency auditing uses public vulnerability databases. An unavailable service
or unresolved advisory is a failed gate, not a successful audit. It covers known
advisories, not all possible defects. Native Objective-C, codecs and dependencies
also require review; automated Python checks do not certify them as secure.

## Before publishing

Follow [the release checklist](docs/RELEASING.md). `.gitignore` cannot remove a
secret already committed in history. Revoke exposed credentials first, clean
history and re-run scans. Never attach an existing local `.app`, database, log,
private recording or `artifacts/` directory to a public release.
