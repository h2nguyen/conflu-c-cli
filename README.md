# conflu-c-cli

![CI status](https://github.com/h2nguyen/conflu-c-cli/actions/workflows/ci.yml/badge.svg)

A command line client for **Confluence Cloud**. It reads pages, page trees, folders, blog posts, versions, comments, labels,
attachments, tasks, properties, templates and spaces; searches with text or CQL; exports a local mirror; publishes Markdown; and updates
pages, blog posts, comments, labels, attachments, tasks and properties with dry runs and conflict guards. People use it in a terminal,
programs and AI agents use it through `--json`, documented exit codes, the shipped skill and a built-in MCP server (read-only by default).

Version 1.1.0, released under the [MIT License](LICENSE). It is written in Python with the **standard
library only**: Python 3.10 or newer is the only requirement. No pip, no curl, no jq, no PowerShell script.

> **An independent project.** conflu-c-cli is not affiliated with, endorsed by or sponsored by Atlassian.
> Confluence and Atlassian are trademarks of Atlassian.

## Why this design

- **Nothing to install but Python.** One process and one reused HTTPS connection per command; no other
  program is started.
- **Safe by default.** Reading is free. Every command that changes Confluence has `--dry-run`, which shows
  what would be sent (the people that a page body mentions stay out of the preview unless you ask with `--with-users`).
  `conflu update` can also be guarded with `--if-version` and
  `--if-unchanged-since`. Publishing a folder (`import-md-dir`) has no such guard: it is one-way, and the
  [export and sync guide](docs/how-to/export-and-sync.md) says what it does and does not do.
- **Built for programs and AI agents.** `--json` on every command that returns data, stable
  [exit codes](docs/reference/exit-codes.md), errors as JSON on stderr (or `--json-envelope`: one JSON object whatever happens),
  `--select` to keep only the fields a program needs, `conflu help --brief`, and `conflu commands --json`, which
  describes the whole CLI. A ready-made [skill](skills/conflu-c-cli/SKILL.md) teaches an agent to use it, and
  `conflu mcp` is a local [MCP server](docs/how-to/mcp-server.md) that offers the commands as tools, read-only by default.
- **Friendly to people.** Help with examples for every command, did-you-mean for typos, and `conflu doctor`,
  which checks the setup step by step and says how to fix what is wrong. It also tells you when `conflu` is not found on
  the PATH, and `conflu doctor --quick --cached 10m` is cheap enough to run at the start of every session.
- **Private by default.** People are hidden unless you ask for them with `--with-users`, and mentions,
  e-mail addresses and personal links are removed from text, and search excerpts, which can carry names, are left
  out. `CONFLUENCE_HIDE_USERS=true` makes that policy strict. Two commands print what Confluence answers, unless the policy is strict:
  `conflu ping` (who the token belongs to) and `conflu api` (the raw answer).
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
`conflu.cmd` (cmd and PowerShell) to `~/bin`. When that folder is not on your PATH, the installer prints the exact command for a folder that
is, and that already holds the launcher of the sibling `jira` CLI. Your configuration stays where it is. Details, updating and
uninstalling: [install and update](docs/how-to/install-and-update.md).

## First steps

```bash
conflu config set CONFLUENCE_BASE_URL https://example.atlassian.net/wiki
conflu config set CONFLUENCE_EMAIL user@example.com
conflu setup-token
conflu use ENG
conflu doctor
```

More on the settings: [configure the connection](docs/how-to/configure.md). On the custom domain of your site API tokens are
refused: `conflu setup --discover` finds the gateway address that works
([the site address](docs/how-to/configure.md#the-site-address)).

## A tour

```bash
conflu page 123456 --comments
conflu search 'retention policy' --space ENG --json
conflu update 123456 --file notes.md --append --if-version 7 --dry-run
conflu export --space ENG --out tmp/eng
conflu import-md examples/page.md --space ENG --dry-run
conflu attachments 123456
conflu download 123456 --name diagram.png --out tmp
conflu diff 123456 --from 6                          # what the last edit changed
conflu restore 123456 --version 6 --dry-run          # bring an earlier version back as a new one
conflu folder 7001 --children                        # what sits directly below a folder
conflu create --title 'Guides' --parent 7001 --file guide.md --dry-run
conflu comments 123456 --inline --resolution open
conflu permissions 123456 --only update              # may my account change this page?
```

The [daily workflow](docs/how-to/daily-workflow.md) shows more recipes. The samples in [examples/](examples/) publish below the home page of the space; a
`parent:` line in the front matter, or `--parent ID`, publishes below a page or a folder.

## For programs and AI agents

```bash
conflu help --brief                # every command with its main options in about 3 KB
conflu commands --json             # every command, argument, example, output shape and exit code
conflu commands --format mcp       # the read-only commands as tool descriptions (the shape of an MCP tools/list answer)
conflu mcp                         # the same tools served over MCP, read-only unless the person adds --allow-write or --allow-files
conflu doctor --quick --cached 10m --json   # the setup in two requests at most, none when a run of the last ten minutes is reused
conflu search "how do I ...?" --space KEY --snippets 5 --json   # a question: path, labels, version and the passage around the words
conflu pages --space ENG --all --select id,title,version --json # only the keys a program needs
conflu page 123456 --outline       # the headings; then --section TITLE reads one part
conflu page 123456 --json          # one compact JSON line when piped
conflu skill install               # copies the skill into .github/skills for GitHub Copilot
```

Read [use the CLI with AI agents](docs/how-to/use-with-ai-agents.md), the [MCP server](docs/how-to/mcp-server.md) and the
[JSON output reference](docs/reference/json-output.md). `CONFLUENCE_PROFILE=agent` sets the safe choices for a program in one go.

## Supported API versions

conflu-c-cli is written for **Confluence Cloud**. It uses the REST API **v2** (`/wiki/api/v2`) wherever v2 has the feature, and the
REST API **v1** (`/wiki/rest/api`) only where v2 has no equivalent: CQL search, the search for people, the user who owns the token, adding and
removing labels, restoring an older version, watching pages and spaces, uploading and downloading the file of an attachment, reading templates,
and moving a page before or after another page. Each call to v1 has its reason in the
[compatibility page](docs/reference/compatibility.md), which also names the calls of every command and links to the two official guides
([v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/), [v1](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/)).
`conflu help COMMAND` names the API of a command in its line `REST API:`.

The CLI is written against the two OpenAPI documents of Atlassian as they were on 2026-10-30, and the tests hold it to them: the mock
server answers HTTP 404 to a call that the matching document does not list and HTTP 400 to a request whose query parameters, headers or body
properties the document does not know, a sweep of every command fails on either, and no call to a deprecated operation is made. All of that
ran against the mock, not against a real site. `conflu version --json` names the versions (`confluenceCloud`), and `conflu doctor` checks
that both APIs answer on your site (`api`).

## Commands

The full text of every command, with examples, is available offline: `conflu help COMMAND`. The same text
is in the [command reference](docs/reference/commands.md).

<!-- commands:start -->

**Read**

| Command | What it does |
| --- | --- |
| `conflu page` | Show one page |
| `conflu pages` | List the pages of a space |
| `conflu versions` | List the saved versions of a page |
| `conflu search` | Search pages with text or CQL |
| `conflu export` | Export a space or a page tree to Markdown files |
| `conflu tree` | Show what is below a page or a folder |
| `conflu diff` | Show what changed between two versions of a page |
| `conflu comments` | Show the comments of a page |
| `conflu labels` | List the labels of a page or of a space |
| `conflu attachments` | List the files attached to a page or a blog post |
| `conflu attachment` | Show one attachment, with its versions and labels |
| `conflu download` | Save attachments, or read their text |

**Work on a page**

| Command | What it does |
| --- | --- |
| `conflu move` | Move a page below, before or after another page, or below a folder |
| `conflu restore` | Bring an earlier version of a page back |
| `conflu comment` | Add, read or change a comment |
| `conflu label` | Add or remove labels of a page |
| `conflu attach` | Attach files to a page |
| `conflu update` | Change the title or the body of a page |

**Create and import**

| Command | What it does |
| --- | --- |
| `conflu create` | Create one page |
| `conflu import-md` | Create or update a page from a Markdown file |
| `conflu import-md-dir` | Publish all Markdown files of a folder |

**Structure**

| Command | What it does |
| --- | --- |
| `conflu folder` | Show one folder |
| `conflu whiteboard` | Show one whiteboard |
| `conflu database` | Show one database |
| `conflu smartlink` | Show one smart link |
| `conflu folder-create` | Create a folder |
| `conflu smartlink-create` | Create a smart link |

**Blog posts**

| Command | What it does |
| --- | --- |
| `conflu blogposts` | List the blog posts of a space |
| `conflu blogpost` | Show one blog post |
| `conflu blogpost-create` | Create one blog post |
| `conflu blogpost-update` | Change the title or the body of a blog post |

**Access and people**

| Command | What it does |
| --- | --- |
| `conflu permissions` | Show what your account may do with content or in a space |
| `conflu restrictions` | Show the restriction on content and who is granted access |
| `conflu space-access` | Show who may use a space |
| `conflu watching` | Show whether you watch a page or a space |
| `conflu watch` | Start or stop watching a page or a space |
| `conflu users` | Search for people by name, or look up account ids |

**Tasks and properties**

| Command | What it does |
| --- | --- |
| `conflu tasks` | List the tasks that are written into pages |
| `conflu task` | Show a task, or complete or reopen it |
| `conflu properties` | Show the content properties of a page or other content |
| `conflu property-set` | Create or update a content property |

**Spaces**

| Command | What it does |
| --- | --- |
| `conflu templates` | List the page templates of a space |
| `conflu template` | Show a template with its body and its variables |
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
| `conflu setup` | Find the gateway address of the site |
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
| `conflu mcp` | Run a local MCP server for AI tools |

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
| Folders, whiteboards, databases and smart links: read them, publish below one, move a page into one | [docs/how-to/folders-and-structure.md](docs/how-to/folders-and-structure.md) |
| Blog posts: find, read, publish and change | [docs/how-to/blog-posts.md](docs/how-to/blog-posts.md) |
| History and restore: earlier versions, differences, several pages in one call | [docs/how-to/history-and-restore.md](docs/how-to/history-and-restore.md) |
| Access and restrictions: what your account may do, who may see or edit content, who may use a space | [docs/how-to/access-and-restrictions.md](docs/how-to/access-and-restrictions.md) |
| Comments and labels: read, filter, change and resolve comments; the labels of a space | [docs/how-to/comments-and-labels.md](docs/how-to/comments-and-labels.md) |
| Attachments: list, look at, save, read and add | [docs/how-to/attachments.md](docs/how-to/attachments.md) |
| Watch a page or a space, find a person | [docs/how-to/watches-and-users.md](docs/how-to/watches-and-users.md) |
| Tasks, content properties and page templates: list and complete tasks, read and set properties, read templates | [docs/how-to/tasks-properties-and-templates.md](docs/how-to/tasks-properties-and-templates.md) |
| MCP server: offer the commands to an AI client as tools, read-only by default | [docs/how-to/mcp-server.md](docs/how-to/mcp-server.md) |
| Markdown and storage format | [docs/how-to/markdown-and-storage-format.md](docs/how-to/markdown-and-storage-format.md) |
| Extend the CLI | [docs/how-to/extend-the-cli.md](docs/how-to/extend-the-cli.md) |
| Troubleshooting | [docs/how-to/troubleshooting.md](docs/how-to/troubleshooting.md) |
| Release a new version | [docs/how-to/release-process.md](docs/how-to/release-process.md) |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Reference: commands | [docs/reference/commands.md](docs/reference/commands.md) |
| Reference: configuration | [docs/reference/configuration.md](docs/reference/configuration.md) |
| Reference: exit codes | [docs/reference/exit-codes.md](docs/reference/exit-codes.md) |
| Reference: JSON output | [docs/reference/json-output.md](docs/reference/json-output.md) |
| Reference: compatibility with Confluence Cloud (API v2 and v1) | [docs/reference/compatibility.md](docs/reference/compatibility.md) |
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
- **No cache of your content.** Every command reads fresh data from Confluence. The one thing the CLI remembers is the result of the
  online checks of the last successful `conflu doctor`, in a small file in `~/.cache/conflu-c-cli`, and only `conflu doctor --cached AGE` uses it.
- **Downloads are kept in memory.** The download limit is 512 MiB per file.
- **Tested against a mock server.** The CLI was built against Atlassian's published API descriptions. The test suite runs against a mock
  Confluence Cloud server, and the read commands of version 1.0.0 were also checked, read-only, against a real Confluence Cloud site. What was
  added in 1.1.0 (folders, blog posts, history, comments, labels, attachments, access, watches, users, tasks, properties, templates and the
  MCP server) was tested against the mock server only. Commands that change Confluence are covered by the mock server tests: try them with
  `--dry-run` first. `conflu doctor` is the check against your own site.

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
