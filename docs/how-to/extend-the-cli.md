# Extend the CLI

The program is organised so that most changes touch a few files in a predictable order. Read
[the architecture](../architecture.md) first for the layers and the one rule that matters: **dependencies point
inwards**. The domain knows nothing, the application knows the domain, adapters know the application.

## Where does my change go

| I want to ... | Touch |
| --- | --- |
| Add a command or an option | A module in `src/conflu_c_cli/adapters/driving/cli/commands/` (one per feature area), and the use case it calls. |
| Change how a page is read or written | `src/conflu_c_cli/domain/` (rules, payloads) and the use case in `src/conflu_c_cli/application/`. |
| Ask Confluence for something new | The **feature area** it belongs to (below): a method on the area's port, its REST mixin, its fake and its mock routes. |
| Add a setting | One `SettingDef` in `src/conflu_c_cli/application/settings.py` and a field in `Settings`. |
| Change what Confluence's JSON means | `src/conflu_c_cli/adapters/driven/confluence_mapper.py` or `map_<area>.py`. |
| Add another front end | A driving adapter that calls `Application`, wired in `src/conflu_c_cli/bootstrap.py` (`conflu mcp` is one: `adapters/driving/cli/mcp_server.py`). |
| Change a message or an exit code | `src/conflu_c_cli/domain/errors.py` or where the error is raised. |

## Worked example: a read-only command `conflu likes PAGE`

This is an **illustration only**: the command does not exist. It shows the order of the change and the files to touch. The v2 document
has `GET /pages/{id}/likes/count`; read the operation in it before you write the call (`docs/reference/compatibility.md` says where the
documents are).

**1. The port.** In `ports_likes.py` in `application/` (a new area) declare the operation, and add the class to the bases of
`ConfluenceGateway` in `application/ports.py`:

```python
class LikesPort(ABC):
    @abstractmethod
    def count_likes(self, page_id: str) -> int: ...
```

`FakeGateway` and `RestConfluenceGateway` cannot be instantiated now, which is the reminder to implement it in both.

**2. The adapter.** `rest_likes.py` in `adapters/driven/` is a mixin of `RestConfluenceGateway`: it calls the endpoint with
`self._call("GET", f"{V2}/pages/{quote(page_id)}/likes/count")` (`rest_support.py` has `V2`, `V1`, `quote`, `query`), maps the JSON in
`map_likes.py`, and lets the gateway's `_raise_for_status` turn HTTP errors into `NotFoundError`, `AuthError`, and so on. A call to the v1 API
would need an entry in the `V1_CALLS` dict of the module, with the reason why v2 does not do. Import the models and the mapper of the area **inside the
methods** that use them (`from .map_likes import likes_from`), and the types that the signatures only name under `if TYPE_CHECKING:`, so that a command that
never reads the area does not load them (see "What a call loads" below).

**3. The use case.** `likes.py` in `application/` holds the use cases and `build(services)`, which `Application` calls when something first asks for the area:

```python
class CountLikes:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str) -> int:
        return self._gateway.count_likes(parse_page_id(ref))


@dataclass
class LikesUseCases:
    count: CountLikes


def build(services: Services) -> LikesUseCases:
    return LikesUseCases(CountLikes(services.gateway))
```

It validates and delegates. It never prints and never touches HTTP.

**4. Wire it.** Add a property to `Application` in `application/app.py` that builds the area when something first asks for it, with the import inside it,
and the import that its annotation names under `if TYPE_CHECKING:`:

```python
    @cached_property
    def likes(self) -> likes_area.LikesUseCases:
        from . import likes as likes_area

        return likes_area.build(self._services)
```

A use case that is no part of an area is a property of the same kind, built from `self._gateway`, `self.settings` and the other parts that `Application.__init__` keeps.

**5. The command.** `likes.py` in `adapters/driving/cli/commands/` holds a handler and a `Command` in `COMMANDS`; list the module in
`commands/__init__.py` (`MODULE_NAMES`, and the name of the command in `WHERE`: the modules are imported when they are needed, and
`tests/cli/test_registry_lazy.py` fails for a command that the table does not know), and its API in `adapters/driving/cli/apis.py`:

```python
def run_likes(ctx: Context, args: argparse.Namespace) -> int:
    count = ctx.app.likes.count.execute(args.ref)
    ctx.print_json({"pageId": parse_page_id(args.ref), "likes": count}) if ctx.json_mode else ctx.print(str(count))
    return 0

Command(
    name="likes",
    group="Read",
    summary="Count the likes of a page",
    when="Use to see how many people liked a page.",
    args=(Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),),
    examples=(Example("conflu likes 123456"),),
    json_output=True,
    output="pageId and likes.",
    handler=run_likes,
)
```

**6. The tests.** The fake, the mock routes and the sweep line are what keep the call honest:

- `fakes_likes.py` (`FakeLikes`, state set up in `_init_likes`) and `mock_likes.py` (`LikesRoutes`, listed in `mock_extensions.py`), both in
  `tests/support/`: the mock answers HTTP 404 to a call that the matching OpenAPI document does not list.
- `sweep_likes.py` in `tests/support/`: the command lines that the conformance sweep runs (`tests/integration/test_conformance.py`). A command that is
  in no sweep module fails the sweep, and so does a command that changes Confluence and has no line with `--dry-run`. The same lines run again in the
  privacy sweep, so give the lines an id that has people in it (the fake and the mock hold one person, Alex Example). A command that never asks Confluence
  has its line in `tests/support/sweep_local.py`, an option that changes what a command prints in `tests/support/sweep_modes.py`;
  `tests/integration/test_json_sweep.py` runs every line with `CONFLUENCE_OUTPUT=json`, with `--json` and with `CONFLUENCE_JSON_ENVELOPE=1` and names the line whose
  command breaks its JSON promise (the output, the error on stderr, the envelope).
- Tests in `tests/unit/`, `tests/cli/` and `tests/integration/`, and the JSON example in `docs/reference/json-output.md` with its run in
  `jsonruns_likes.py` in `tests/support/`.

Then run the checks:

```bash
python -m unittest discover -s tests -t .
python scripts/generate_docs.py     # the command reference, the README table, the configuration reference, the skill's reference block
python scripts/check_release.py     # version, changelog, generated files, skill and links agree
```

A new command also needs one line in `CHANGELOG.md`, one mention in `skills/conflu-c-cli/SKILL.md`, and a row in the table "Which API each command
uses" of `docs/reference/compatibility.md` (`python -m tests.support.sweep_runner` prints the row).

## The rules every command follows

These are checked by tests where a test can check them.

- **A command that changes Confluence has `--dry-run`**, which shows the payload and sends nothing. Build the payload in one place so the
  preview is exactly what is sent. A write reads its target first and keeps the conflict guards (`--if-version`, `--if-unchanged-since`) where
  Confluence has versions. No command deletes or redacts content.
- **A command that returns data supports `--json`** and documents the shape in `output=`. Add keys, never rename them inside a major version.
- **Every command has examples**, and they must be valid usage. **Every command says when to use it** (`when=`): one or two sentences that tell a
  person or an agent when this is the command to reach for and when another one is better; the text feeds `conflu help`, the catalog
  (`whenToUse`) and the tool descriptions of `conflu commands --format mcp`.
- **A command says what `conflu mcp` needs to know**, on the command and on its arguments (see the comments in `adapters/driving/cli/spec.py`):
  `Command(for_person, local, destructive, idempotent, writes_files, streams)` and `Arg(path=..., at_file=..., overwrites=..., not_a_path=...)`.
  An argument that names a file or a folder says so, a value that may be `@FILE` says so, a flag that replaces what exists says so, and an
  argument that only looks like a path says why it is none. A test fails for an argument that looks like a path and says none of this.
- **A command that prints a list** builds its rows as dicts (the shape of its JSON) and prints through `listing.print_list`, with `SELECT` and
  `FORMAT` in its arguments (`--select a,b.c`, `--format table|tsv|md`), so that every list command behaves the same.
- **A query that people type** (search text, CQL) goes through `_common.query_option`: `@FILE` or `-` reads it from a file or from standard input,
  because Windows PowerShell 5.1 removes the double quotes inside an argument.
- **Text that people supply** is read through `Context.read_input`, `read_stdin` or `LocalFiles.read_text`, which understand UTF-8, UTF-16 and
  Windows-1252, with or without a byte order mark. The readers are bounded (`domain/textio.QUERY_LIMIT`, 1 MiB, and `BODY_LIMIT`, 16 MiB, with
  `check_length`): a new reader asks `Files.read_up_to(path, limit + 1)` and refuses when there is more; it never trusts `Files.size`, because a pipe or a
  device claims none.
- **Errors are `ConfluCliError` subclasses** with a message that says what happened and a `hint` that says what to do. Never print an error from
  a use case, never `sys.exit` below `main`.
- **No I/O in `domain/` or `application/`.** Files, the clock, HTTP and the console are ports or adapters.
- **People stay out of output by default.** Use the privacy helpers in `src/conflu_c_cli/domain/privacy.py`, `ensure_users_allowed` and
  `name_users` in `application/paging.py`, and honour `settings.hide_users`. What Confluence answers is free text, and so is a title that a
  command only echoes: print it through `redact_text`, and the address of a page through `redact_address` (the address ends in the title). The
  request that a dry run prints holds what was read from the page (an append sends the whole body, mentions included): print the copy of
  `hide_people_in_payload`, say `payloadRedacted`, and offer `--with-users` for the exact request. A command that can return people (a raw search, a CQL
  search) goes through `application/search.py`, which drops them. The privacy sweep
  (`tests/integration/test_privacy_sweep.py`) runs every sweep line against a mock that puts an e-mail address into every free text, and fails for a
  command that prints it, or a person, without being asked.
- **Standard library only.** `tests/test_architecture.py` fails on any other import.
- **Results to stdout, messages to stderr**: `ctx.print`, `ctx.print_json`, `ctx.diagnostics`.
- **No secrets in output**, including verbose logging.

## Feature areas

`ConfluenceGateway` is composed of **area ports**, one file per feature area, so that no file grows with every command and so that areas can be built
side by side. For an area `X` (structure, blogposts, history, comments, labels, attachments, access, watches, users, tasks, properties, templates):

| File | Holds |
| --- | --- |
| `application/ports_X.py` | `XPort`, the abstract Confluence operations of the area; `ConfluenceGateway` inherits it. |
| `adapters/driven/rest_X.py` | `RestX`, a mixin of `RestConfluenceGateway` that implements them with `self._call(...)`, and `V1_CALLS`. |
| `adapters/driven/map_X.py` | What Confluence's JSON means for the area. |
| `application/X.py` | The use cases and `build(services)`, which a property of `Application` calls on first use; reached as `app.X.<use case>`. |
| `adapters/driving/cli/commands/X.py` | The `COMMANDS` of the area. |
| `tests/support/fakes_<area>.py`, `mock_<area>.py`, `sweep_<area>.py`, `jsonruns_<area>.py` | `FakeX`, a mixin of `FakeGateway` (state in `_init_X`); `XRoutes`, the routes of the mock; the sweep lines; the runs of the JSON reference. |

Order of work: write the REST method and the fake method first, declare the abstract method in the port last; the gateway cannot be instantiated while
one of the implementations lacks a declared method.

### What a call loads

A start of the program pays for every module that it imports, and on a computer with a virus scanner that is most of its time: once every area was imported by every call,
`conflu version` took a third longer than in 1.0.0. So nothing is imported before it is used. The module of a command is imported when that command runs
(`commands/__init__.py`), a use case is built when something first asks the application for it (`application/app.py`), the code that talks to Confluence (HTTP, TLS and
the REST calls of every area) when a use case first calls it (`_LazyGateway` in `bootstrap.py`), and the models and the mapper of an area where its REST calls are made
(`rest_X.py` imports them inside its methods; a port names the models of its area only under `if TYPE_CHECKING:`). Keep to that for a new area.
`tests/test_startup.py` starts the real program and fails for a command that loads what it does not use, and `tests/test_undefined_names.py` fails for a name that a
function uses and nothing imports (which is what forgetting one of these local imports looks like).

## The target is Confluence Cloud, v2 first, and the tests hold you to it

The two OpenAPI documents of Atlassian are the reference ([compatibility](../reference/compatibility.md) names them and says which version it is written for).

- **v2 (`/api/v2`) is the default.** A call to v1 (`/rest/api`) is allowed only where v2 has no equivalent, and then it stands in the `V1_CALLS` dict of its
  module with the reason, which the page [compatibility](../reference/compatibility.md) repeats. Never call a deprecated operation. Before each feature, read
  both documents again; move a call to v2 as soon as v2 has it.
- `tests/support/confluence_cloud_v2_endpoints.txt` and `confluence_cloud_v1_endpoints.txt` list the operations of the two documents (method and path).
  The mock Confluence answers HTTP 404 to a call that is not in the list and records it (`mock.unknown_endpoints`; `deprecated_endpoints` for a
  deprecated one), and `tests/integration/test_conformance.py` sweeps every command and fails on one. Two addresses are no REST call and are the only
  other ones allowed (`OUTSIDE_THE_REFERENCE` in `tests/support/conformance.py`).
- A new command needs lines in the sweep module of its area, a row in `docs/reference/compatibility.md`, and its entry in `adapters/driving/cli/apis.py` (which API it uses: it
  appears as `REST API:` in `conflu help` and as `api` in `conflu commands --json`; `tests/integration/test_command_apis.py` holds the table to what the sweep recorded). A sweep line is also what checks the parameters of
  the call: the mock answers HTTP 400 to a query parameter, a header or a body property that `confluence_cloud_v2_parameters.txt` or `confluence_cloud_v1_parameters.txt`
  (next to the lists, in `tests/support`) do not give that operation, and the sweep names the command line that sent it. A new option that puts a query parameter into
  a call also needs a line that sends it: the conformance test reads the adapters and names a parameter that no line sends. So does an option of a command: it is named
  by some sweep line (the request of an option is judged by the strict mock, its output read by the privacy sweep), or has its reason in `NOT_SWEPT` of `tests/support/conformance.py`,
  and `tests/integration/test_conformance.py` names the option that is in neither place.

## Add a setting

One entry in `SETTING_DEFS` (`application/settings.py`) with name, attribute, type, default, description and an example, and the attribute on the
`Settings` dataclass. Parsing, `conflu config show`, `conflu doctor` (if you add a check) and `docs/reference/configuration.md` (after
`generate_docs.py`) follow from that.

## Add an adapter

An adapter implements a port from `application/ports.py` (the gateway to Confluence) or from `application/ports_local.py` (what this computer offers: the settings file,
the cache, files, the clock, messages and the documentation) and is wired in `bootstrap.create_application`. Translate the failures of your technology into
domain errors at the boundary. Test it on its own with the real technology (a temporary folder, the mock server) and keep the use cases unchanged: if you
find yourself editing a use case to suit an adapter, the port is wrong. The `Cache` port (`FileCache`, `MemoryCache`) is the smallest example.

## The test helpers

| Helper | Where | Use |
| --- | --- | --- |
| `FakeGateway`, `MemoryFiles`, `MemoryConfigStore`, `MemoryCache`, `FixedClock`, `FakeDocs`, `RecordingDiagnostics`, `build_app` | `tests/support/fakes.py` | Use cases and commands without I/O. `FakeGateway.calls` records every call; `.errors[name]` makes a method fail. |
| `run_cli(*argv, gateway=..., files=..., stdin=...)` | `tests/support/cli.py` | Run the command line in-process; returns `code`, `out`, `err`, `json()`, `error()`. |
| `MockConfluence` | `tests/support/mock_confluence.py` | A Confluence Cloud in a thread with synthetic data. `fail_next(prefix, status, times=...)` injects errors; `.requests` records everything; `.unknown_endpoints`, `.deprecated_endpoints`, `.used_endpoints` and `.outside_calls` say what the documents think of the calls. The routes of a feature area live in `tests/support/mock_<area>.py`. |
| `EndToEnd` | `tests/integration/test_end_to_end.py` | The base of whole-program tests: the real adapters against `MockConfluence`; `self.cli(...)`, `self.sent(...)`. |
| `run_sweeps`, `python -m tests.support.sweep_runner` | `tests/support/sweep_runner.py` | The conformance sweep, and the rows of the table in the compatibility page. `run_sweeps(..., env=..., taint=True)` keeps what every line printed. |
| `MockConfluence.taint`, `taint_payload` | `tests/support/taint.py` | Adds an e-mail address to every free text that the mock answers (and the title to the address of a page): the privacy sweep fails for a command that prints it unredacted. |

## Before you merge

1. `python -m unittest discover -s tests -t .` is green.
2. `python scripts/generate_docs.py` produced no unexpected change; `python scripts/check_release.py` is happy.
3. A line in `CHANGELOG.md` under `## [Unreleased]`.
4. For a release, follow [release a new version](release-process.md).
