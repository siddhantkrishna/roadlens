# Contributing to ROADLENS

Bug reports, fixes, documentation and tests are welcome. Read the
[README](README.md), [security policy](SECURITY.md) and
[license notes](docs/LICENSING.md) first.

## Development setup

On Intel macOS 14 or later with Python 3.11-3.14 and Apple Command Line Tools:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,security,build]'
roadlens fetch-model
QT_QPA_PLATFORM=offscreen python -m pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_release.py
bandit -r src scripts -ll -ii
pip-audit -r requirements-macos-intel.lock --no-deps --disable-pip --timeout 60
```

The model is downloaded only by the explicit fetch command; tests never download
it. Without it, model tests skip. The physical-camera test requires an explicit
`ROADLENS_TEST_CAMERA` device ID and must never run automatically in CI.

## Submit a focused change

1. Create a branch from the current default branch.
2. Read the connected capture/tracking/traffic code before changing contracts.
3. Reuse the existing services and validated scene models. Keep capture and
   inference off the Qt thread and buffers bounded. Keep database connections
   owned by their worker. Never silently switch a selected camera's identity.
4. Add a regression check for nontrivial behavior and run the commands above.
5. Open a pull request describing the problem, behavior, validation and limits.

Use real, licensed public fixtures or clearly identified synthetic test inputs.
Do not claim that mocks or a recorded clip validate physical cameras. Never add
private camera images, device identifiers, credentials, `.env` files, databases,
exports or unreviewed binary assets. The public-asset manifest must match every
intentional binary fixture/screenshot. See [assets/README.md](assets/README.md).

For bug reports, include the ROADLENS version, macOS/Python versions, source kind,
expected behavior and a minimal reproduction using the public fixture. Redact
source paths and device IDs. Share no private recordings or full diagnostics
without reviewing them. Security reports follow [SECURITY.md](SECURITY.md).

## Licensing contributions

By submitting a contribution, you license your original changes under
AGPL-3.0-only, consistent with [LICENSE](LICENSE). You must have the right to
submit it. Preserve third-party notices and disclose any imported code/media and
its license. No copyright assignment or separate CLA is required by this project.
