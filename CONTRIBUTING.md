# Contributing to conflu-c-cli

Thank you for taking the time to contribute. Bug reports, questions, documentation fixes, tests and code are all
welcome, and a small contribution is as valuable as a big one.

Everyone who takes part follows the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security problem, read
[SECURITY.md](SECURITY.md) first: do not open a public issue for it.

## What the project is for

conflu-c-cli is a command line client for **Confluence Cloud**, for people at a terminal and for programs and AI
agents. It stays small on purpose:

- **Standard library only.** No third-party package, in the program or in its tools. A test enforces it.
- **Safe by default.** Every command that changes Confluence has `--dry-run`, and `conflu update` has conflict guards.
- **Private by default.** People, e-mail addresses and personal links stay out of the output unless asked for.
- **A stable interface.** Within a major version, commands, options, settings, JSON keys and exit codes are
  added, not renamed or removed (see [the release process](docs/how-to/release-process.md)).
- **Confluence Cloud only.**

A change that fits these points is easy to accept. A change that adds a dependency, weakens a default, breaks
the interface or targets another product will most likely be declined, kindly and with a reason. If you are not
sure, open an issue and ask before you write the code.

## Ways to help

- **Report a bug or ask a question.** [Open an issue](https://github.com/h2nguyen/conflu-c-cli/issues/new/choose) and
  pick a form. Say which version you run (`conflu version`), your operating system and Python, the command you ran
  and what you expected. `conflu doctor` shows the state of your setup with the secrets masked.
- **Never post secrets or real content.** Remove tokens, e-mail addresses, the name of your site and the text of your
  pages from anything you share. Replace them with placeholders such as `example.atlassian.net` and `ENG`.
- **Suggest a feature.** Describe the problem first, then the idea. What you want to do matters more than how.
- **Improve the documentation.** The guides are in [docs/](docs/). A confusing sentence is a bug.
- **Fix something.** Look for issues labelled `good first issue` or `help wanted`, or fix what you found yourself.

## Set up

You need Python 3.10 or newer and Git. There is nothing to install:

```bash
git clone https://github.com/h2nguyen/conflu-c-cli.git
cd conflu-c-cli
python conflu.py version            # run the program from the clone
python -m unittest discover -s tests -t .
```

The tests need no network and no credentials. The integration tests run the real HTTP code against a mock
Confluence Cloud server in `tests/support/mock_confluence.py`. To run one test module:
`python -m unittest tests.unit.test_domain`.

Before you open a pull request, run all three checks:

```bash
python -m unittest discover -s tests -t .
python scripts/generate_docs.py     # rewrites docs/reference/*.md and the command table in README.md
python scripts/check_release.py     # version, changelog, generated files, skill and links agree
```

The files that `scripts/generate_docs.py` writes are generated from the command descriptions: change the
description in the code, not the generated file.

## How the code is organised

The program follows the hexagonal (ports and adapters) pattern: dependencies point inwards, the domain and the
application do no input or output, and only `src/conflu_c_cli/bootstrap.py` knows both sides. Tests read the
imports and fail on a violation (`tests/test_architecture.py`). Start with [the architecture](docs/architecture.md)
and [the guide to extending the CLI](docs/how-to/extend-the-cli.md); the second one walks through a new command.

A few rules that save a review round:

- A command is one declarative description (`spec.Command`). Help, the parser, `conflu commands --json` and the
  generated reference all come from it.
- Every command that changes Confluence has `--dry-run`, and a command that returns data documents its JSON.
- The skill in `skills/conflu-c-cli/SKILL.md` names every command; add a new one there.
- Use only Python 3.10 syntax and library. `tests/test_python_compat.py` checks it.
- Match the surrounding code: type hints, and short docstrings that explain why, not what.

## Tests and test data

A change that alters behaviour comes with a test. Unit tests use the fakes in `tests/support/fakes.py`, command line
tests use `run_cli`, and tests of HTTP behaviour use the mock server.

Use synthetic data in tests, documentation and examples: `example.atlassian.net`, the space `ENG`,
`alex@example.com`. Never commit a token, a real site name, real page content or personal data.

## Pull requests

1. Fork the repository, and create a branch from `main`.
2. Keep the change focused: one topic per pull request. Several small pull requests are easier to review than one big one.
3. Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) when a user can notice the change.
4. Update the documentation that the change touches, and run the three checks above.
5. Open the pull request and fill in the template. The CI workflow runs the tests and the release check on Linux,
   Windows and macOS; all checks must pass before a maintainer merges.

This is a project maintained in spare time. A maintainer reads every issue and pull request and replies as soon as
possible, usually within about a week. If nothing has happened after that, a polite reminder is welcome. A
maintainer may ask for changes or decline a contribution; the reason will be given.

## License of your contribution

By contributing you agree that your contribution is licensed under the project's [MIT License](LICENSE), the
same as the rest of the code. There is no contributor license agreement to sign.
