# Preparing a public release

The validation commands below do not push or publish. The final source-only
publication commands require the repository owner’s authorization. ROADLENS currently prepares a **source release**, not a cleared binary
release. See the [licensing gate](LICENSING.md) before distributing an app/model.

## 1. Review the source payload

Read README, LICENSE, NOTICE, THIRD_PARTY, SECURITY and public media provenance.
Confirm the right to publish every source contribution and fixture. The three
screenshots must show only the documented public Intel clip and no personal
paths, camera images, identifiers or diagnostics. The manifest's exact hashes
protect reviewed assets from accidental replacement; they do not establish
copyright ownership by themselves.

```sh
git status --short
# Stage only reviewed source files before the final gate.
git ls-files --cached --others --exclude-standard
python scripts/check_release.py
```

The gate rejects differences between the index and working copy, so an unreviewed
staged file cannot be hidden behind sanitized working bytes. Stage or restore
tracked changes before checking the release. It includes already tracked files even when `.gitignore` would now ignore
them. It rejects private file types, unexpected paths, symlinks, home-directory
paths and detected secrets. Its only entropy exceptions are exact reviewed
public checksums; it does not blanket-ignore source files or credential rules.
Changes to `docs/public-assets.json` and the release policy require human review.
Review Git history too: ignoring a file does not remove it from earlier commits.

## 2. Run validation on the exact candidate

```sh
python -m pip install -r requirements-macos-intel.lock
python -m pip install -r requirements-security.lock
python -m pip install --no-deps -e .
roadlens fetch-model
QT_QPA_PLATFORM=offscreen python -m pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
bandit -r src scripts -ll -ii
pip-audit -r requirements-macos-intel.lock --no-deps --disable-pip --timeout 60
python -m pip check
python scripts/check_release.py
python -m build
```

Review the sdist/wheel contents for unintended files and correct license metadata.
A missing model means inference tests were skipped; do not report them as passed.
Physical-camera tests are opt-in. Dependency auditing requires current network
advisory data; network failures and advisories fail the release gate. Save local
reports under ignored `artifacts/`, not in public source. The checked-in CI uses
an explicit Intel runner and commit-pinned Actions with read-only permissions;
it has no publishing job or deployment token.

## 3. Create a local, reviewed source artifact

```sh
python scripts/check_release.py --archive artifacts/roadlens-0.1.0-source.tar.gz
tar -tzf artifacts/roadlens-0.1.0-source.tar.gz
```

This archive contains only the approved Git candidates. It includes public test
fixtures and reviewed screenshots, excludes weights/apps/databases/private files,
and omits local owner names and timestamps in archive member metadata. Creating
it is not permission to publish. Re-run the gate and regenerate the archive if
any candidate changes after review. Do not upload the entire checkout directory.

## 4. Configure GitHub before the first public push

The repository owner must choose/create the repository and verify ownership and
visibility. Enable private vulnerability reporting, secret scanning and push
protection; configure branch protection/rulesets and require the CI checks once
available. GitHub settings and hosted Actions cannot be verified from an
unpublished local repository. No badges or successful hosted runs are invented.

Review the remote URL before adding it; do not embed access tokens in URLs. Use
GitHub's normal SSH/credential-manager authentication. Inspect the final staged
diff and history, and re-run the checks. **Do not push while any gate is failed,
unreviewed or explicitly marked pending.** A separate, explicit publishing action
is still needed after local preparation; these scripts never push for you.

## Binary releases remain a separate gate

Resolve the pinned model export's preferred-source/export provenance, satisfy
AGPL/Qt/native-library corresponding-source and notice requirements, and publish
matching source/build instructions beside the binary. Rebuild from the exact
release revision; do not reuse a previously generated local app. Sign/notarize as
appropriate and test a clean installation and physical-camera permissions on the
target Mac. Only then review which binary artifacts may be uploaded. Publishing
source alone does not retroactively clear a model or binary for redistribution.


## Authorized source publication

The intended remote is `https://github.com/siddhantkrishna/roadlens`. Inspect an
existing remote and its branches first; never replace it or force-push. With a
reviewed staged tree, passing gates, and write permission to the intended account:

```sh
git diff --cached --check
python scripts/check_release.py
git commit -m "Release verified ROADLENS source"
# Only if origin is absent:
git remote add origin https://github.com/siddhantkrishna/roadlens.git
# Only after verifying this is the intended repository and main is compatible:
git push -u origin main
```

If the repository does not yet exist, its authorized owner can create it using
`gh repo create siddhantkrishna/roadlens --public` before pushing. Authenticate
through `gh auth login` or an existing credential manager; never put a token in
the remote URL. If remote main already exists, fetch and inspect it, preserve
its history and integrate without force. Observe the real Actions result after
pushing and repair failures before announcing a passing hosted build.
