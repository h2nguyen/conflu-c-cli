# Architecture

conflu-c-cli follows the hexagonal (ports and adapters) pattern. The rules and use cases sit in the middle and
know nothing about HTTP, files or the terminal; everything that touches the outside world is an adapter that
plugs into a port. That is what makes the program easy to extend and to test, and tests enforce the rules.

```text
                    driving side                                         driven side
        (who asks the application to act)                  (what the application needs from outside)

   +--------------------------+                                   +-------------------------------+
   |  command line adapter    |                                   |  RestConfluenceGateway (HTTP) |
   |  adapters/driving/cli    |                                   |  FileConfigStore      (file)  |
   |  parse, call, print      |                                   |  LocalFiles, LocalDocs        |
   +------------+-------------+                                   |  SystemClock                  |
                |                                                 +---------------+---------------+
                | calls use cases                                                 ^ implements ports
                v                                                                 |
        +------------------------------------------------------------------------------------+
        |  application   use cases (ViewPage, SearchContent, UpdatePage, ImportMarkdown, ...) |
        |                ports: ConfluenceGateway, ConfigStore, Files, Clock, Docs, ...       |
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
| Application | `src/conflu_c_cli/application/` | The use cases, the **ports** (abstract interfaces), the settings definitions. | The domain and the application. |
| Driven adapters | `src/conflu_c_cli/adapters/driven/` | Implementations of the ports: HTTP transport and Confluence REST gateway, config file, files, docs, clock. | Domain, application, `version`. Never a driving adapter. |
| Driving adapter | `src/conflu_c_cli/adapters/driving/cli/` | The command line: command descriptions, parser, help, output formatting, `main`. | Domain, application, `version`. Never a driven adapter. |
| Composition root | `src/conflu_c_cli/bootstrap.py` | Wiring: settings from file and environment, real adapters, `main()`. | Everything. Nothing imports it except the entry points. |

Everything uses the standard library only. `tests/test_architecture.py` reads the imports of every module and
fails on a violation: an inner layer reaching outwards, I/O in the domain or application, a third-party import,
a command module that is not registered, or a port without a real adapter or a test double. There is **no cache
port** in this project.

## Ports

| Port | What the application needs | Real adapter | Test double |
| --- | --- | --- | --- |
| `ConfluenceGateway` | Everything Confluence: current user, spaces, pages, trees, versions, comments, labels, attachments, search, raw requests. | `RestConfluenceGateway` over `HttpTransport` | `FakeGateway` |
| `ConfigStore` | Persistent `KEY=value` settings. | `FileConfigStore` | `MemoryConfigStore` |
| `Files` | Read, write, list, join, name. | `LocalFiles` | `MemoryFiles` |
| `Clock` | The current time. | `SystemClock` | `FixedClock` |
| `Docs` | The documentation and skill that ship with the CLI. | `LocalDocs` | `FakeDocs` |
| `Diagnostics` | Progress and warnings for the person at the terminal. | `StderrDiagnostics` | `RecordingDiagnostics` |

Integration tests add one more helper outside the port table: `tests/support/mock_confluence.py` is a mock
Confluence Cloud HTTP server behind the real HTTP adapter.

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
description feeds the argument parser, `conflu help`, `conflu commands --json` and the generated
`docs/reference/commands.md`, so they cannot disagree. `registry.all_commands()` collects the `COMMANDS` of the
modules listed in `commands/__init__.py`.

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

## Decisions and trade-offs

- **Python standard library only.** Installation is just Python plus the source tree. The tests fail on a third-party import.
- **Confluence Cloud only.** The settings, URL rules, authentication and REST mapping all target Cloud addresses.
- **API v2 first, with a small v1 surface where Cloud still needs it.** Pages, spaces, comments, versions and most
  attachment reads go through `/api/v2`. CQL search, the current user, adding or removing labels, uploading
  attachments and moving a page use `/rest/api` because those operations are not all available the same way in v2.
- **Cursor pagination hidden behind `Chunk` and `fetch_all`.** The gateway returns one page plus a cursor; the use
  cases decide whether to fetch one page or all of them.
- **No cache.** Every command reads fresh data. The code stays smaller and avoids stale content, at the price of
  more API calls.
- **TLS is strict enough for Cloud, but not stricter than many company proxies allow by default.** The certificate
  chain and the host name are always verified. `CONFLUENCE_CA_BUNDLE` adds authorities to the system store (a private CA, or a public one the system lacks). `CONFLUENCE_TLS_STRICT`
  turns on Python's stricter X.509 checks; it is off by default because many TLS-inspecting company proxies fail
  them. `CONFLUENCE_INSECURE` exists only as a diagnostic.
- **Markdown/storage-format conversion stays pure domain code.** The CLI treats those conversions as business rules,
  not as I/O; the commands reuse the same converters everywhere.
- **Privacy by default.** Names, account ids, e-mail addresses and personal links are hidden unless `--with-users`
  is allowed and requested.
- **No general delete surface.** `conflu api` deliberately exposes only `GET`, `POST` and `PUT`. The CLI offers no
  general-purpose delete command.

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

## What this architecture buys

- One declarative place per command.
- One place per concern: HTTP in adapters, privacy in the domain, orchestration in use cases.
- Dry runs that show the exact payload that a real run sends.
- Readable offline docs (`conflu how-to`, `conflu skill`, `conflu changelog`).
- Safe defaults for privacy, TLS and stale writes, while still leaving an escape hatch with `conflu api`.
