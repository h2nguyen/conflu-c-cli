# conflu-c-cli

![CI status](https://github.com/h2nguyen/conflu-c-cli/actions/workflows/ci.yml/badge.svg)

A command line client for **Confluence Cloud**. It reads pages, page trees, versions, comments, labels,
attachments and spaces; searches with text or CQL; exports a local mirror; publishes Markdown; and updates
pages, comments, labels and attachments with dry runs and conflict guards. People use it in a terminal,
programs and AI agents use it through `--json`, documented exit codes and the shipped skill.

Version 1.0.0, released under the [MIT License](LICENSE). It is written in Python with the **standard
library only**: Python 3.10 or newer is the only requirement. No pip, no curl, no jq, no PowerShell script.

> **An independent project.** conflu-c-cli is not affiliated with, endorsed by or sponsored by Atlassian.
> Confluence and Atlassian are trademarks of Atlassian.

## Why this design

- **Nothing to install but Python.** One process and one reused HTTPS connection per command; no other
  program is started.
- **Safe by default.** Reading is free. Every command that changes Confluence has `--dry-run`, which shows
  exactly what would be sent. `conflu update` can also be guarded with `--if-version` and
  `--if-unchanged-since`. Publishing a folder (`import-md-dir`) has no such guard: it is one-way, and the
  [export and sync guide](docs/how-to/export-and-sync.md) says what it does and does not do.
- **Built for programs and AI agents.** `--json` on every command that returns data, stable
  [exit codes](docs/reference/exit-codes.md), errors as JSON on stderr, and `conflu commands --json`, which
  describes the whole CLI. A ready-made [skill](skills/conflu-c-cli/SKILL.md) teaches an agent to use it.
- **Friendly to people.** Help with examples for every command, did-you-mean for typos, and `conflu doctor`,
  which checks the setup step by step and says how to fix what is wrong.
- **Private by default.** People are hidden unless you ask for them with `--with-users`, and mentions,
  e-mail addresses and personal links are removed from text, and search excerpts, which can carry names, are left
  out. `CONFLUENCE_HIDE_USERS=true` makes that policy strict.
- **Easy to extend.** Hexagonal architecture with the rules enforced by tests, one declarative place per
  command, and a [guide to extending it](docs/how-to/extend-the-cli.md).

## Install

You need Python 3.10 or newer (`python --version`) and Git. In Git Bash, PowerShell, cmd or any other shell:

```bash
git clone https://github.com/h2nguyen/conflu-c-cli.git
cd conflu-c-cli
python install.py --dry-run    # shows what would happen
python install.py
```

Without Git, download the source archive of a release from the
[releases page](https://github.com/h2nguyen/conflu-c-cli/releases) and run the two `python install.py` commands
in the unpacked folder.

The installer copies the program to your local profile (`%LOCALAPPDATA%\conflu-c-cli` on Windows,
`~/.local/share/conflu-c-cli` elsewhere) and writes the launchers `conflu` (Git Bash, Linux, macOS) and
`conflu.cmd` (cmd and PowerShell) to `~/bin`. Your configuration stays where it is. Details, updating and
uninstalling: [install and update](docs/how-to/install-and-update.md).

## First steps

```bash
conflu config set CONFLUENCE_BASE_URL https://example.atlassian.net/wiki
conflu config set CONFLUENCE_EMAIL user@example.com
conflu setup-token
conflu use ENG
conflu doctor
```

More on the settings: [configure the connection](docs/how-to/configure.md).

## A tour

```bash
conflu page 123456 --comments
conflu search 'retention policy' --space ENG --json
conflu update 123456 --file notes.md --append --if-version 7 --dry-run
conflu export --space ENG --out tmp/eng
conflu import-md examples/page.md --space ENG --dry-run
conflu attachments 123456
conflu download 123456 --name diagram.png --out tmp
```

The [daily workflow](docs/how-to/daily-workflow.md) shows more recipes.

## For programs and AI agents

```bash
conflu commands --json             # every command, argument, example, output shape and exit code
conflu commands --format mcp       # the read-only commands as tool descriptions (the shape of an MCP tools/list answer)
conflu search "how do I ...?" --space KEY --snippets 5 --json   # a question: path, labels, version and the passage around the words
conflu page 123456 --outline       # the headings; then --section TITLE reads one part
conflu page 123456 --json          # one compact JSON line when piped
conflu skill install               # copies the skill into .github/skills for GitHub Copilot
```

Read [use the CLI with AI agents](docs/how-to/use-with-ai-agents.md) and the
[JSON output reference](docs/reference/json-output.md).

## Commands

The full text of every command, with examples, is available offline: `conflu help COMMAND`. The same text
is in the [command reference](docs/reference/commands.md).

<!-- commands:start -->

**Read**

| Command | What it does |
| --- | --- |
| `conflu page` | Show one page |
| `conflu pages` | List the pages of a space |
| `conflu tree` | Show the pages below a page |
| `conflu versions` | List the saved versions of a page |
| `conflu search` | Search pages with text or CQL |
| `conflu export` | Export a space or a page tree to Markdown files |
| `conflu comments` | Show the comments of a page |
| `conflu labels` | List the labels of a page |
| `conflu attachments` | List the files attached to a page |
| `conflu download` | Download attachments of a page |

**Work on a page**

| Command | What it does |
| --- | --- |
| `conflu update` | Change the title or the body of a page |
| `conflu move` | Move a page below, before or after another page |
| `conflu comment` | Add a comment to a page |
| `conflu label` | Add or remove labels of a page |
| `conflu attach` | Attach files to a page |

**Create and import**

| Command | What it does |
| --- | --- |
| `conflu create` | Create one page |
| `conflu import-md` | Create or update a page from a Markdown file |
| `conflu import-md-dir` | Publish all Markdown files of a folder |

**Spaces**

| Command | What it does |
| --- | --- |
| `conflu spaces` | List the spaces you can see |
| `conflu space` | Show one space |

**Setup and information**

| Command | What it does |
| --- | --- |
| `conflu setup-token` | Save the API token |
| `conflu remove-token` | Remove the stored token |
| `conflu use` | Select the current space |
| `conflu current` | Print the current space |
| `conflu clear-space` | Forget the current space |
| `conflu config` | Show or change the settings |
| `conflu ping` | Check the connection and the credentials |
| `conflu doctor` | Check the setup and say how to fix it |
| `conflu help` | Show the commands, or the help of one command |
| `conflu commands` | List every command, for programs |
| `conflu version` | Show the version |
| `conflu changelog` | Show the release history |
| `conflu how-to` | Read the guides that ship with the CLI |
| `conflu skill` | Show or install the AI agent skill |

**Tools**

| Command | What it does |
| --- | --- |
| `conflu convert` | Convert Markdown to storage format, or back |
| `conflu api` | Call any Confluence REST endpoint |

<!-- commands:end -->

## Documentation

| Topic | Where |
| --- | --- |
| Install, update, uninstall | [docs/how-to/install-and-update.md](docs/how-to/install-and-update.md) |
| Configure the connection | [docs/how-to/configure.md](docs/how-to/configure.md) |
| Daily workflow | [docs/how-to/daily-workflow.md](docs/how-to/daily-workflow.md) |
| Use with AI agents | [docs/how-to/use-with-ai-agents.md](docs/how-to/use-with-ai-agents.md) |
| Publish Markdown pages | [docs/how-to/publish-markdown.md](docs/how-to/publish-markdown.md) |
| Find information: search, read in parts, follow links, tool descriptions for agents | [docs/how-to/find-information.md](docs/how-to/find-information.md) |
| Export a local mirror and sync it back | [docs/how-to/export-and-sync.md](docs/how-to/export-and-sync.md) |
| Markdown and storage format | [docs/how-to/markdown-and-storage-format.md](docs/how-to/markdown-and-storage-format.md) |
| Extend the CLI | [docs/how-to/extend-the-cli.md](docs/how-to/extend-the-cli.md) |
| Troubleshooting | [docs/how-to/troubleshooting.md](docs/how-to/troubleshooting.md) |
| Release a new version | [docs/how-to/release-process.md](docs/how-to/release-process.md) |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Reference: commands | [docs/reference/commands.md](docs/reference/commands.md) |
| Reference: configuration | [docs/reference/configuration.md](docs/reference/configuration.md) |
| Reference: exit codes | [docs/reference/exit-codes.md](docs/reference/exit-codes.md) |
| Reference: JSON output | [docs/reference/json-output.md](docs/reference/json-output.md) |
| Release history | [CHANGELOG.md](CHANGELOG.md) |

All of it ships with the CLI and reads offline: `conflu how-to`, `conflu how-to TOPIC`, `conflu changelog`
and `conflu skill`.

## Limits and notes

- **Confluence Cloud only.** The CLI expects a Cloud address such as `https://example.atlassian.net/wiki`.
- **HTTPS by default.** Plain http is accepted only for localhost, or when `CONFLUENCE_ALLOW_HTTP=true`.
- **TLS on managed Windows laptops.** Python 3.13 enables strict X.509 checks that many TLS-inspecting company
  proxies fail (`Missing Authority Key Identifier`). `CONFLUENCE_TLS_STRICT` is therefore **off by default**:
  the certificate chain and the host name are still always verified. Turn it on only when you want Python's
  stricter behaviour.
- **No explicit proxy support.** Transparent inspection works when the certificates are trusted; `HTTP_PROXY`
  and `HTTPS_PROXY` are not supported by this CLI.
- **No cache.** Every command reads fresh data from Confluence.
- **Downloads are kept in memory.** The download limit is 512 MiB per file.
- **Tested against a mock server, and read-only against a real site.** The CLI was built against Atlassian's
  published API descriptions. The test suite runs against a mock Confluence Cloud server, and the read commands
  were also checked, read-only, against a real Confluence Cloud site. Commands that change Confluence are covered
  by the mock server tests: try them with `--dry-run` first. `conflu doctor` is the check against your own site.

## Examples

Sample Markdown files for `conflu import-md` and `conflu import-md-dir` are in [examples/](examples/).

## Getting help

- Run `conflu help` or `conflu help COMMAND`, read the [troubleshooting guide](docs/how-to/troubleshooting.md), or
  run `conflu doctor`, which checks your setup and says how to fix what is wrong.
- A bug or an idea? [Open an issue](https://github.com/h2nguyen/conflu-c-cli/issues/new/choose); the forms ask for
  what is needed. Never post tokens, site names or page content: replace them with placeholders.
- A security problem? Do not open an issue: follow [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome: bug reports, documentation, tests and code. Read [CONTRIBUTING.md](CONTRIBUTING.md)
first. It explains what the project is for, how to run the checks and what a pull request needs. Everyone who
takes part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

conflu-c-cli is released under the [MIT License](LICENSE).
