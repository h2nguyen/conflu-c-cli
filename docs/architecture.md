# Architecture

conflu-c-cli follows the hexagonal (ports and adapters) pattern. The rules and use cases sit in the middle and
know nothing about HTTP, files or the terminal; everything that touches the outside world is an adapter that
plugs into a port. That is what makes the program easy to extend and to test, and tests enforce the rules.

```text
                    driving side                                         driven side
        (who asks the application to act)                  (what the application needs from outside)

   +--------------------------+                                   +-------------------------------+
   |  command line adapter    |                                   |  RestConfluenceGateway (HTTP) |
   |  adapters/driving/cli    |                                   |  FileConfigStore, FileCache   |
   |  parse, call, print      |                                   |  LocalFiles, LocalDocs        |
   |  MCP server (same folder)|                                   |  SystemClock                  |
   +------------+-------------+                                   +---------------+---------------+
                |                                                                 ^ implements ports
                | calls use cases                                                 |
                v                                                                 |
        +------------------------------------------------------------------------------------+
        |  application   use cases (ViewPage, SearchContent, UpdatePage, ImportMarkdown, ...) |
        |                ports: ConfluenceGateway (+ per area), ConfigStore, Cache, Files,    |
        |                       Clock, Docs, Diagnostics                                      |
        |  +--------------------------------------------------------------------------------+ |
        |  |  domain   Page, Space, CQL, front matter, privacy, payloads, naming, errors   | |
        |  +--------------------------------------------------------------------------------+ |
        +------------------------------------------------------------------------------------+

   bootstrap.py is the composition root: the only module that knows both sides. It reads the
   settings, builds the real adapters and hands the application to the command line.
```

## The layers and what they may import

| Layer | Folder | Holds | May import |
| --- | --- | --- | --- |
| Domain | `src/conflu_c_cli/domain/` | Pure rules and data: the model, page ids and space keys, front matter, privacy, payload builders, naming, error types with their exit codes, and the Markdown/storage-format converters. | The domain and the standard library, but nothing that does I/O. |
| Application | `src/conflu_c_cli/application/` | The use cases (one module per area), the **ports** (abstract interfaces: `ports.py` for the gateway to Confluence, `ports_<area>.py` for each feature area, `ports_local.py` for what this computer offers), the settings definitions. | The domain and the application. |
| Driven adapters | `src/conflu_c_cli/adapters/driven/` | Implementations of the ports: HTTP transport, the Confluence REST gateway (the core in `confluence_rest.py`, one mixin `rest_<area>.py` and one mapper `map_<area>.py` per area), config file, cache file, files, docs, clock. | Domain, application, `version`. Never a driving adapter. |
| Driving adapter | `src/conflu_c_cli/adapters/driving/cli/` | The command line: command descriptions, parser, help, output formatting, `main`; and the MCP server (`mcp_server.py`, `mcp_calls.py`, `mcp_paths.py`), which runs the same commands. | Domain, application, `version`. Never a driven adapter. |
| Composition root | `src/conflu_c_cli/bootstrap.py` | Wiring: settings from file and environment, real adapters, `main()`. | Everything. Nothing imports it except the entry points. |

Everything uses the standard library only. `tests/test_architecture.py` reads the imports of every module and
fails on a violation: an inner layer reaching outwards, I/O in the domain or application, a third-party import,
a command module that is not registered, or a port without a real adapter or a test double. Confluence **content is
never cached**; the one `Cache` port holds only the answer of `conflu doctor` (see below).

## Ports

| Port | What the application needs | Real adapter | Test double |
| --- | --- | --- | --- |
| `ConfluenceGateway` | Everything Confluence: current user, spaces, pages, trees, versions, search, raw requests (the core), plus one small port per feature area that the gateway inherits: `StructurePort`, `BlogpostsPort`, `HistoryPort`, `CommentsPort`, `LabelsPort`, `AttachmentsPort`, `AccessPort`, `WatchesPort`, `UsersPort`, `TasksPort`, `PropertiesPort`, `TemplatesPort`, `SetupPort` (`ports_<area>.py`). | `RestConfluenceGateway` over `HttpTransport`, assembled from the core and the `rest_<area>.py` mixins | `FakeGateway`, assembled from `tests/support/fakes_<area>.py` |
| `ConfigStore` | Persistent `KEY=value` settings. | `FileConfigStore` | `MemoryConfigStore` |
| `Cache` | A small file that remembers the result of the last `doctor` run, so that `doctor --cached` can answer without a network call. Never page content. | `FileCache` | `MemoryCache` |
| `Files` | Read, write, list, join, name. | `LocalFiles` | `MemoryFiles` |
| `Clock` | The current time. | `SystemClock` | `FixedClock` |
| `Docs` | The documentation and skill that ship with the CLI. | `LocalDocs` | `FakeDocs` |
| `Diagnostics` | Progress and warnings for the person at the terminal. | `StderrDiagnostics` | `RecordingDiagnostics` |

The six ports below the gateway are in `ports_local.py`: they need nothing of what Confluence holds, so the command line can use them without loading the
models of every feature area (`ports.py` names them again, so that `from .ports import Files` works).
Integration tests add one more helper outside the port table: `tests/support/mock_confluence.py` is a mock
Confluence Cloud HTTP server behind the real HTTP adapter. It serves the routes of every area
(`tests/support/mock_<area>.py`), and it answers **404 and writes down** every path that neither OpenAPI document lists,
so that a call to an invented or deprecated endpoint fails a test (see "Which API version a call uses").

## Feature areas

A feature area (folders and structure, blog posts, history, comments, labels, attachments, access, watches, users,
tasks, properties, templates) is a slice of the same shape, so that an area can grow without touching the others:

| Piece | Where |
| --- | --- |
| The rules and the data | `domain/<area>.py` |
| The port | `application/ports_<area>.py`, inherited by `ConfluenceGateway` |
| The use cases, reached as `app.<area>.<use case>` | `application/<area>.py` (`<Area>UseCases`, built from `Services`) |
| The REST calls and the reason for each v1 call | `adapters/driven/rest_<area>.py` (a mixin of `RestConfluenceGateway`, with `V1_CALLS`), `map_<area>.py` |
| The commands | `adapters/driving/cli/commands/<area>.py` |
| The test double and the mock routes | `tests/support/fakes_<area>.py`, `tests/support/mock_<area>.py` |
| The compatibility sweep and the examples of the JSON reference | `tests/support/sweep_<area>.py`, `tests/support/jsonruns_<area>.py` |

[Extend the CLI](how-to/extend-the-cli.md) walks through adding a command with these pieces.

## Which API version a call uses, and how that is enforced

Confluence Cloud has two REST APIs. v2 (`/wiki/api/v2`, cursor pagination) is the default for everything it can
do. v1 (`/wiki/rest/api`) is used only where v2 has no equivalent, and each such call is written down once with its
reason in `V1_CALLS` of the area's REST module and on [the compatibility page](reference/compatibility.md).
Three tests hold that together: the list of documented v2 and v1 operations
(`tests/support/confluence_cloud_v2_endpoints.txt`, `confluence_cloud_v1_endpoints.txt`, taken from the two
published OpenAPI documents), the mock server that refuses a path outside both lists, and a sweep that runs every
command against the mock and compares what it sent with the compatibility page. A deprecated operation, a v1 call
without a reason, or a command without a row on the page fails the build.

## What a start loads

A call to `conflu` is short, so what it imports is most of its time, and on a computer with a virus scanner every file that Python opens costs. Nothing is imported
before it is used. `conflu version` loads the command line framework and nothing else. A command imports its own module (`commands/__init__.py`). The application
(`application/app.py`) builds a use case, and imports its module, when something first asks for it. The gateway to Confluence (`_LazyGateway` in `bootstrap.py`) loads the
HTTP, TLS and REST code when a use case first calls it, so `conflu config show` never does. And a REST mixin imports the models and the mapper of its area inside its
methods, so `conflu page` does not load those of access, tasks or templates. `tests/test_startup.py` starts the real program and fails for a command that loads what it does
not use; `tests/test_undefined_names.py` fails for a function that uses a name that nothing imports, which is what a forgotten local import looks like.

## The MCP server

`conflu mcp` is a second driving adapter next to the command line (`adapters/driving/cli/mcp_server.py`,
`mcp_calls.py`, `mcp_paths.py`). It speaks MCP on standard input and output, turns a tool call into the command line of the
same command, runs it in process through `main.run` with a fresh application, and returns the JSON the command printed.
Everything it knows about a command comes from the declarations on the command, so a new command is
offered without a line of MCP code. It is read-only by default, offers commands that write files only with
`--allow-files` and commands that change Confluence only with `--allow-write`, and applies a path policy to every
file argument. [MCP server](how-to/mcp-server.md) describes what it does and refuses.

## One command, from the keyboard to Confluence

`conflu update 123456 --file notes.md --append`:

1. `main.run` reads the arguments, finds the command in the registry and builds an argparse parser from its
   description (`spec.Command`). `--help` is answered before parsing, so help never needs valid arguments.
2. The handler in `adapters/driving/cli/commands/changes.py` gets a `Context`: the streams, the output mode and a
   lazy `Application`. It reads `notes.md`, converts Markdown to storage format, and calls
   `ctx.app.update_page.execute(...)`.
3. `UpdatePage` (application) reads the current page through `ConfluenceGateway`, checks the guards
   (`--if-version`, `--if-unchanged-since`), combines the new body with the old one for `--append`, and returns
   the exact payload for a dry run or hands that same payload to the gateway for a real write.
4. `RestConfluenceGateway` turns the call into HTTPS on `HttpTransport` (keep-alive connection, retries for reads,
   TLS handling), maps the status to a domain error (`ConflictError`, `NotFoundError`, ...) and the JSON to domain
   objects.
5. The handler prints the result as text or JSON. A `ConfluCliError` anywhere on the way ends in `main.run`,
   which prints it (as JSON on stderr with `--json`) and returns the exit code the error carries.

## The command framework

A command is data: `spec.Command` holds the name, group, summary, description, arguments, examples, notes,
whether it writes, whether it supports `--json` and what the JSON holds, and the handler. That single
description feeds the argument parser, `conflu help`, `conflu help --brief`, `conflu commands --json` and
`--format mcp`, the MCP server and the generated `docs/reference/commands.md`, so they cannot disagree.
`registry.all_commands()` collects the `COMMANDS` of the modules listed in `commands/__init__.py`; `registry.find_command()` imports only the module of the
command that runs (a table `WHERE` says which, and a test holds it to what the modules declare), so that a call does not pay for the other nineteen.

A command also says what a program that runs it for a model must know, as data on the command and on its
arguments (`Command(for_person, local, destructive, idempotent, writes_files)`, `Arg(path, at_file, overwrites,
not_a_path)`): whether it only works on the person's own setup, whether it removes or overwrites anything, whether
it writes files on this computer, which arguments name a path, and which values may be `@FILE`. The MCP server
and `conflu commands --format mcp` read these declarations; a test walks over every command and refuses an argument
that looks like a path and does not say what it is.

Quality rules are tests (`tests/cli/test_framework.py`): every command has examples and they parse, every
argument has help text, a command that returns data documents its JSON, and every command that changes
Confluence through the network has `--dry-run`.

## Errors and exit codes

`domain/errors.py` defines `ConfluCliError` and its subclasses. Each carries a `code`, an `exit_code`, a human
`message`, a `hint` (what to do) and `details` (structured facts). Adapters translate their failures into these
(an HTTP 404 becomes `NotFoundError`); the application raises them for rule violations; only `main.run` turns
them into output. The table of exit codes is in the same file and generates the reference and the catalog.

## Output

Results go to standard output, progress and warnings to standard error through `Diagnostics`. JSON is produced
from dataclasses by `render.to_jsonable` (camelCase keys); output that must keep a particular shape is built
explicitly by the command handlers. On a terminal JSON is indented; when piped it is one compact line. A broken
pipe (`| head`) ends quietly with exit code 141.

## Settings

`application/settings.py` lists every setting once (`SettingDef`): name, type, default, meaning, whether it is
secret or personal. Parsing, `conflu config show`, `conflu doctor` and the generated configuration reference all
read that list. `bootstrap.effective_values` overlays the environment on the config file; the result is the
immutable `Settings` object handed to the application.

The settings are read once, when the application is made. When they cannot be read, the application is made with `UnreadableSettings` (in
`application/settings.py`): it lets the commands that mend the configuration run (`config set|unset|path`, `setup-token`, `remove-token`, `clear-space`) and
makes every other command fail with the original error, so that a damaged file never leads to a default that is more permissive (a privacy policy that cannot
be read is not "off"). `HttpTransport` bounds an answer by size (`limit`), by time (a deadline of `CONFLUENCE_MAX_TIME` from the end of the request) and by
gzip members (16), and every answer that cannot be read is an `UnavailableError` (exit code 7) that blames the answer. What the server says in an error is free
text like a page title: it goes through `domain/errortext.py`, which adds the account id to what `redact_text` removes. It is a separate function because a page
body is not searched for ids (a run of 24 hexadecimal digits is as often a hash).

## Decisions and trade-offs

- **Python standard library only.** Installation is just Python plus the source tree. The tests fail on a third-party import.
- **Confluence Cloud only.** The settings, URL rules, authentication and REST mapping all target Cloud addresses.
- **API v2 first; v1 only with a reason that a test holds.** Everything v2 can do goes through `/api/v2`. The calls to
  `/rest/api` are few, each has its reason in `V1_CALLS` and on the compatibility page, and the build fails when the
  two disagree or when a call is not in the published API documents.
- **Cursor pagination hidden behind `Chunk` and `fetch_all`.** The gateway returns one page plus a cursor; the use
  cases decide whether to fetch one page or all of them.
- **No content cache.** Every command reads fresh data. The code stays smaller and avoids stale content, at the price of
  more API calls. The one thing the CLI remembers between runs is the result of the last `conflu doctor`, in the `Cache`
  port, and it is read back only when `conflu doctor --cached` asks for it.
- **TLS is strict enough for Cloud, but not stricter than many company proxies allow by default.** The certificate
  chain and the host name are always verified. `CONFLUENCE_CA_BUNDLE` adds authorities to the system store (a private CA, or a public one the system lacks). `CONFLUENCE_TLS_STRICT`
  turns on Python's stricter X.509 checks; it is off by default because many TLS-inspecting company proxies fail
  them. `CONFLUENCE_INSECURE` exists only as a diagnostic.
- **Markdown/storage-format conversion stays pure domain code.** The CLI treats those conversions as business rules,
  not as I/O; the commands reuse the same converters everywhere.
- **Privacy by default.** Names, account ids, e-mail addresses and personal links are hidden unless `--with-users`
  is allowed and requested. `CONFLUENCE_PROFILE=agent` makes the safe choices for a program that runs the CLI
  (people hidden, no prompts, JSON), and `conflu doctor --strict-privacy` checks that nothing weakens that.
- **No general delete surface.** `conflu api` deliberately exposes only `GET`, `POST` and `PUT`. The CLI offers no
  general-purpose delete command, no command that redacts content, and no command that changes who may read or
  edit content. The two removals it has are small ones: `conflu label --remove` takes a label off a page and `conflu watch --remove` takes your own watch off.

## Testing

| Level | Where | What it uses |
| --- | --- | --- |
| Domain | `tests/unit/test_domain.py`, `tests/unit/test_converters.py`, `tests/unit/test_settings.py` | Plain functions and data. |
| Application | `tests/unit/test_application_read.py`, `tests/unit/test_application_write.py` | `FakeGateway`, `MemoryFiles`, `MemoryConfigStore`, `FixedClock`, `FakeDocs`, `RecordingDiagnostics`. |
| CLI | `tests/cli/test_framework.py`, `tests/cli/test_commands.py` | `run_cli(...)` plus the in-memory fakes. |
| HTTP and adapters | `tests/integration/test_http_and_gateway.py`, `tests/integration/test_adapters.py` | `MockConfluence`, real URL parsing, TLS handling and file adapters. |
| End to end | `tests/integration/test_end_to_end.py` | The real child process against the mock server. |
| Release consistency | `tests/test_release.py` | Version files, generated docs, links, the skill, every command line and repository path the documents show, and hidden characters. |
| Architecture rules | `tests/test_architecture.py` | The imports and the structure of every module. |
| Installer | `tests/test_installer.py` | The real installer, into a temporary folder. |
| Python 3.10 | `tests/test_python_compat.py` | The syntax and the library names of the whole tree, because the tests may run on a newer Python. |
| JSON reference | `tests/integration/test_json_reference.py` | Every example of the JSON reference against what the command prints. |
| JSON promise | `tests/integration/test_json_sweep.py`, `tests/support/json_sweep.py` | Every sweep line with `CONFLUENCE_OUTPUT=json`, with `--json` and with the envelope: one JSON value on standard output, a JSON error on standard error, one object in the envelope, and the same exit code under every switch. |
| API compatibility | `tests/integration/test_conformance.py`, `tests/support/sweeps*.py` | The endpoint lists, the mock's refusal of an undocumented call, and the sweep that runs every command and compares the calls with `docs/reference/compatibility.md`. |
| Privacy | `tests/integration/test_privacy_sweep.py`, `tests/support/taint.py` | The same sweep against a mock that puts an e-mail address into every free text and the title into every page address: no command may print it, or a person, unless asked, and a refused `--with-users` prints nothing. |
| Feature areas | `tests/unit/test_<area>_*.py`, `tests/cli/test_<area>_commands.py`, `tests/integration/test_<area>_flow.py` | The same three levels for each area: domain and use cases against the fake, the commands, and the requests that really go to the mock. |
| MCP server | `tests/cli/test_mcp_server.py`, `tests/integration/test_mcp_process.py` | The protocol, the tool selection, the path policy and the classification of every command; a real server process over pipes. |

## What this architecture buys

- One declarative place per command.
- One place per concern: HTTP in adapters, privacy in the domain, orchestration in use cases.
- Dry runs that show the exact payload that a real run sends.
- Readable offline docs (`conflu how-to`, `conflu skill`, `conflu changelog`).
- Safe defaults for privacy, TLS and stale writes, while still leaving an escape hatch with `conflu api`.
