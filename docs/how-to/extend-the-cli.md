# Extend the CLI

The program is organised so that most changes touch a few files in a predictable order. Read
[the architecture](../architecture.md) first for the layers and the one rule that matters: **dependencies point
inwards**. The domain knows nothing, the application knows the domain, adapters know the application.

## Where does my change go

| I want to ... | Touch |
| --- | --- |
| Add a command or an option | A module in `src/conflu_c_cli/adapters/driving/cli/commands/`, and the use case it calls. |
| Change how a page is read or written | `src/conflu_c_cli/domain/` (rules, payloads) and the use case in `src/conflu_c_cli/application/`. |
| Ask Confluence for something new | A method on the `ConfluenceGateway` port, its implementation in `src/conflu_c_cli/adapters/driven/confluence_rest.py`, and the fake in `tests/support/fakes.py`. |
| Add a setting | One `SettingDef` in `src/conflu_c_cli/application/settings.py` and a field in `Settings`. |
| Change what Confluence's JSON means | `src/conflu_c_cli/adapters/driven/confluence_mapper.py`. |
| Add another front end | A second driving adapter that calls `Application`, wired in `src/conflu_c_cli/bootstrap.py`. |
| Change a message or an exit code | `src/conflu_c_cli/domain/errors.py` or where the error is raised. |

## Worked example: a read-only command `conflu restrictions PAGE`

This is an **illustration only**. The command does not exist in the program today; it shows the order of the
change and the files to touch.

**1. The port.** In `src/conflu_c_cli/application/ports.py` add to `ConfluenceGateway`:

```python
    @abstractmethod
    def list_restrictions(self, page_id: str) -> list[dict[str, str]]: ...
```

The test double `FakeGateway` now fails to instantiate (an abstract method is missing), which is the reminder to
implement it in `tests/support/fakes.py` too.

**2. The adapter.** In `src/conflu_c_cli/adapters/driven/confluence_rest.py` add a method that calls the right
Cloud endpoint, maps the JSON to plain data, and lets `_raise_for_status` translate HTTP errors into
`NotFoundError`, `AuthError`, `RejectedError`, and so on.

**3. The use case.** Add a small application class, for example in `src/conflu_c_cli/application/pages.py` or a
new module:

```python
class ListRestrictions:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str) -> list[dict[str, str]]:
        return self._gateway.list_restrictions(parse_page_id(ref))
```

It validates and delegates. It never prints and never touches HTTP.

**4. Wire it.** In `src/conflu_c_cli/application/app.py` add the field to `Application` and instantiate it in
`Application.create(...)`.

**5. The command.** In one of the command modules under
`src/conflu_c_cli/adapters/driving/cli/commands/` add a handler and a `Command` to `COMMANDS`:

```python
def run_restrictions(ctx: Context, args: argparse.Namespace) -> int:
    rows = ctx.app.list_restrictions.execute(args.ref)
    if ctx.json_mode:
        ctx.print_json({"pageId": parse_page_id(args.ref), "restrictions": rows})
    else:
        ctx.print(table(["OPERATION", "SUBJECT"], [(row["operation"], row["subject"]) for row in rows]))
    return 0

Command(
    name="restrictions",
    group="Read",
    summary="Show the restrictions of a page",
    args=(Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),),
    examples=(Example("conflu restrictions 123456"),),
    json_output=True,
    output="pageId and restrictions[]: operation, subject.",
    handler=run_restrictions,
)
```

If you create a new module, add it to `src/conflu_c_cli/adapters/driving/cli/commands/__init__.py`.

**6. The checks.** Add tests in `tests/unit/`, `tests/cli/test_commands.py` and, if the REST mapping is
non-trivial, in `tests/integration/test_http_and_gateway.py`. Then regenerate the generated reference and run the
suite:

```bash
python scripts/generate_docs.py
python -m unittest discover -s tests -t .
python scripts/check_release.py
```

A new command also needs one line in `CHANGELOG.md` and one mention in `skills/conflu-c-cli/SKILL.md`.

## The rules every command follows

These are checked by tests where a test can check them.

- **A command that changes Confluence has `--dry-run`**, which shows the payload and sends nothing. Build the
  payload in one place so the preview is exactly what is sent.
- **A command that returns data supports `--json`** and documents the shape in `output=`. Add keys, never rename
  them inside a major version.
- **Every command has examples**, and they must be valid usage.
- **Errors are `ConfluCliError` subclasses** with a message that says what happened and a `hint` that says what to
  do. Never print an error from a use case, never `sys.exit` below `main`.
- **No I/O in `domain/` or `application/`.** Files, the clock, HTTP and the console are ports or adapters.
- **People stay out of output by default.** Use the privacy helpers in `src/conflu_c_cli/domain/privacy.py`, and
  honour `settings.hide_users`.
- **Standard library only.** `tests/test_architecture.py` fails on any other import.
- **Results to stdout, messages to stderr**: `ctx.print`, `ctx.print_json`, `ctx.diagnostics`.
- **No secrets in output**, including verbose logging.

## Add a setting

Add one entry to `SETTING_DEFS` in `src/conflu_c_cli/application/settings.py` with name, attribute, type,
default, description and an example, and the attribute on the `Settings` dataclass. Parsing,
`conflu config show`, `conflu doctor` (if you add a check) and `docs/reference/configuration.md` (after
`python scripts/generate_docs.py`) follow from that.

## Add an adapter

An adapter implements a port from `src/conflu_c_cli/application/ports.py` and is wired in
`src/conflu_c_cli/bootstrap.py`. Translate the failures of your technology into domain errors at the boundary.
Test it on its own with the real technology (a temporary folder, the mock server) and keep the use cases
unchanged: if you find yourself editing a use case to suit an adapter, the port is wrong.
