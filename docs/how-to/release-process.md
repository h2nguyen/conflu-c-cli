# Release a new version

The version lives in two files that must agree, `VERSION` and `src/conflu_c_cli/version.py`, and in the
changelog. `scripts/check_release.py` checks that they do, together with the documentation. The project follows
semantic versioning: `MAJOR.MINOR.PATCH`.

| Change | Bump |
| --- | --- |
| A removed or renamed command, option, setting, JSON key or exit code; a changed meaning | MAJOR |
| A new command, option, setting or JSON key; a new feature that keeps everything working | MINOR |
| A fix that changes no interface | PATCH |

## Steps

1. **Branch and work** from `main` and open a pull request (see [CONTRIBUTING.md](../../CONTRIBUTING.md)); add a
   line under `## [Unreleased]` in `CHANGELOG.md` for every change a user can notice (`Added`, `Changed`,
   `Fixed`, `Security`).
2. **Choose the version** with the table above.
3. **Edit the version in both places**: `VERSION` (one line, no `v`) and `src/conflu_c_cli/version.py`
   (`__version__`).
4. **Close the changelog entry**: rename `## [Unreleased]` content into a new heading
   `## [x.y.z] - YYYY-MM-DD` above the older entries, and leave an empty `## [Unreleased]` section on top.
5. **Regenerate the documentation**: `python scripts/generate_docs.py` (the command reference and the command table
   in the README embed the version and the command descriptions).
6. **Run the checks**:

   ```bash
   python -m unittest discover -s tests -t .
   python scripts/check_release.py
   ```

   `check_release.py` fails when the version files disagree, when the newest changelog entry is not the current
   version or is out of order, when a generated file is out of date, when the skill does not mention a command,
   when a link in the documentation leads nowhere, and when a community file (license, contributing guide, code
   of conduct, security policy, pull request template, issue forms) is missing.
7. **Install and try it**: `python install.py --dry-run`, then `python install.py`, then `conflu version` and
   `conflu doctor`.
8. **Merge, tag and publish.** Merge the pull request into `main` once the checks of the CI workflow pass. Then
   tag the merge commit with `v` and the version, push the tag, and create a GitHub release from that tag with
   the new changelog entry as its notes:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "conflu-c-cli X.Y.Z"
   git push origin vX.Y.Z
   ```

   The release gives everybody a source archive to install from.

## What is in a release

Everything the installer copies: the package, `docs/`, `skills/`, `examples/`, `README.md`, `CHANGELOG.md`,
`LICENSE`, `VERSION`, `conflu.py` and `install.py`. `conflu version`, `conflu changelog` and `conflu how-to` read
the installed copies, so a release is complete only when those files are current.

## Rules for the changelog

- Write for the person who updates: what they can now do, what changed for them, what they must change.
- Name the commands and settings in backticks and give the exit code or JSON key when it matters.
- Do not describe the implementation unless it changes what a user sees (requirements, speed, safety).
- Be honest about test scope: say what was verified against the mock server, what against a real Confluence
  Cloud site, and that `conflu doctor` is the check against the reader's own site.
