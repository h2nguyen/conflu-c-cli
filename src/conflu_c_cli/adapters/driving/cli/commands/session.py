"""Commands for the setup and the connection: setup-token, remove-token, use, current, clear-space, config, ping, doctor."""
from __future__ import annotations

import argparse
import getpass

from .....domain.errors import ConfigError, UsageError
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example

GROUP = "Setup and information"

OK, WARN, FAIL = "ok", "warn", "fail"  # the statuses of a doctor check
_MARK = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}


# -- token ---------------------------------------------------------------------------------------


def _warn_if_overridden(ctx: Context, name: str) -> None:
    """The environment wins over the file: a change to the file does nothing while the variable is set."""
    if ctx.environ.get(name):
        ctx.diagnostics.warn(f"{name} is also set in the environment, which overrides the configuration file; the change has no effect while it is set.")


def run_setup_token(ctx: Context, args: argparse.Namespace) -> int:
    if args.stdin:
        token = ctx.read_stdin()
    elif ctx.stdin.isatty():
        token = getpass.getpass("Enter the Confluence API token. Input will not be displayed: ")
    else:
        ctx.diagnostics.warn(
            "Standard input is not a terminal, so the token may be visible while you type. "
            "Hide it with `winpty conflu setup-token`, or pipe it in with --stdin."
        )
        token = ctx.stdin.readline()
    ctx.app.config.save_token(token)
    _warn_if_overridden(ctx, "CONFLUENCE_API_TOKEN")
    path = ctx.app.config.path
    ctx.print_json({"saved": True, "file": path}) if ctx.json_mode else ctx.print(f"Token saved to {path}")
    return 0


def run_remove_token(ctx: Context, args: argparse.Namespace) -> int:
    removed = ctx.app.config.remove_token()
    _warn_if_overridden(ctx, "CONFLUENCE_API_TOKEN")
    path = ctx.app.config.path
    if ctx.json_mode:
        ctx.print_json({"removed": removed, "file": path})
    else:
        ctx.print(f"Token removed from {path}" if removed else "No token was stored.")
    return 0


# -- space ---------------------------------------------------------------------------------------


def run_use(ctx: Context, args: argparse.Namespace) -> int:
    space = ctx.app.config.select_space(args.key)
    _warn_if_overridden(ctx, "CONFLUENCE_SPACE")
    if ctx.json_mode:
        ctx.print_json({"space": space.key, "name": space.name})
    else:
        ctx.print(f"Current space: {space.key}" + (f" ({space.name})" if space.name else ""))
    return 0


def run_current(ctx: Context, args: argparse.Namespace) -> int:
    key = ctx.app.config.current_space()
    if ctx.json_mode:
        ctx.print_json({"space": key or None})
        return 0 if key else 1
    if not key:
        ctx.diagnostics.info("No current space. Run `conflu use SPACE_KEY`.")
        return 1
    ctx.print(key)
    return 0


def run_clear_space(ctx: Context, args: argparse.Namespace) -> int:
    cleared = ctx.app.config.clear_space()
    _warn_if_overridden(ctx, "CONFLUENCE_SPACE")
    if ctx.json_mode:
        ctx.print_json({"cleared": cleared})
    else:
        ctx.print("The current space was cleared." if cleared else "No current space was set.")
    return 0


# -- config --------------------------------------------------------------------------------------


def run_config(ctx: Context, args: argparse.Namespace) -> int:
    action = args.action or "show"
    service = ctx.app.config
    if action == "path":
        ctx.print(service.path)
        return 0
    if action == "show":
        entries = service.entries()
        if ctx.json_mode:
            ctx.print_json({"file": service.path, "settings": entries})
        else:
            ctx.print(f"Configuration file: {service.path}\n")
            ctx.print(table(["SETTING", "VALUE", "SOURCE"], [(entry.name, entry.value, entry.source) for entry in entries]))
        return 0
    if not args.name:
        raise UsageError(f"`conflu config {action}` needs a setting name.", hint="List the names with `conflu config show`.")
    if action == "set":
        if args.value is None:
            raise UsageError(f"`conflu config set {args.name}` needs a value.")
        service.set_value(args.name, args.value)
        _warn_if_overridden(ctx, args.name)
        ctx.print(f"{args.name} saved to {service.path}")
    else:
        removed = service.unset_value(args.name)
        _warn_if_overridden(ctx, args.name)
        ctx.print(f"{args.name} removed from {service.path}" if removed else f"{args.name} was not set in {service.path}")
    return 0


# -- ping and doctor -----------------------------------------------------------------------------


def run_ping(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.ping.execute(quiet=args.quiet)
    address = ctx.app.settings.wiki_url
    if ctx.json_mode:
        user = result.user
        ctx.print_json(
            {
                "ok": result.ok,
                "baseUrl": address,
                "user": None if user is None else {"accountId": user.account_id, "displayName": user.display_name},
            }
        )
    elif args.quiet:
        ctx.print("OK")  # a script can compare the output with OK
    elif result.user is None:
        ctx.print(f"OK: connected to {address}")
    else:
        ctx.print(f"OK: connected to {address} as {result.user.display_name or result.user.account_id}")
    return 0


def run_doctor(ctx: Context, args: argparse.Namespace) -> int:
    try:
        checks = ctx.app.doctor.execute()
    except ConfigError as error:  # the settings cannot even be read: that is the finding
        broken = [{"name": "configuration", "status": FAIL, "detail": error.message, "hint": error.hint}]
        if ctx.explicit_json:
            ctx.print_json({"ok": False, "checks": broken})
        else:
            ctx.print(f"{_MARK[FAIL]} configuration  {error.message}" + (f"\n{' ' * 15}Hint: {error.hint}" if error.hint else ""))
        return 1
    failed = any(check.status == FAIL for check in checks)
    if ctx.json_mode:
        ctx.print_json({"ok": not failed, "checks": checks})
    else:
        width = max(len(check.name) for check in checks)
        for check in checks:
            ctx.print(f"{_MARK[check.status]} {check.name.ljust(width)}  {check.detail}")
            if check.hint and check.status != OK:
                ctx.print(f"{' ' * (len(_MARK[check.status]) + 1 + width + 2)}Hint: {check.hint}")
    return 1 if failed else 0


COMMANDS = (
    Command(
        name="setup-token",
        group=GROUP,
        summary="Save the API token",
        when="For the person, once: saves the API token. Never run it for somebody else and never ask for a token.",
        description="Asks for the Confluence API token without showing it and saves it in the configuration file "
        "(~/.config/conflu-c-cli/config, or the file named by CONFLUENCE_CONFIG_FILE) with restricted permissions. "
        "Create the token at https://id.atlassian.com/manage-profile/security/api-tokens. The token is never printed and never accepted "
        "as a command line argument, so it does not end up in the shell history. The e-mail address of the account is a setting: "
        "`conflu config set CONFLUENCE_EMAIL user@example.com`.",
        args=(Arg(("--stdin",), "Read the token from standard input (for scripts and agents).", kind="flag"),),
        examples=(
            Example("conflu setup-token"),
            Example("printf '%s' \"$TOKEN\" | conflu setup-token --stdin", "non-interactive"),
        ),
        writes=True,
        json_output=True,
        output="saved, file.",
        handler=run_setup_token,
    ),
    Command(
        name="remove-token",
        group=GROUP,
        summary="Remove the stored token",
        when="For the person: removes the stored token.",
        description="Removes the token from the configuration file. Other settings stay.",
        examples=(Example("conflu remove-token"),),
        writes=True,
        json_output=True,
        output="removed, file.",
        handler=run_remove_token,
    ),
    Command(
        name="use",
        group=GROUP,
        summary="Select the current space",
        when="Use to select the default space, so that --space can be left out.",
        description="Checks that you can access the space and saves it as the current space (CONFLUENCE_SPACE), "
        "so that --space can be left out.",
        args=(Arg(("key",), "Space key.", required=True, metavar="SPACE_KEY"),),
        examples=(Example("conflu use ENG"),),
        writes=True,
        json_output=True,
        output="space, name.",
        handler=run_use,
    ),
    Command(
        name="current",
        group=GROUP,
        summary="Print the current space",
        when="Use to see which space is the default.",
        description="Prints the space key set with `conflu use`. Exit code 1 and no output when none is set.",
        examples=(Example("conflu current"),),
        json_output=True,
        output="space (null when none).",
        handler=run_current,
    ),
    Command(
        name="clear-space",
        group=GROUP,
        summary="Forget the current space",
        when="Use to forget the default space.",
        examples=(Example("conflu clear-space"),),
        writes=True,
        json_output=True,
        output="cleared.",
        handler=run_clear_space,
    ),
    Command(
        name="config",
        group=GROUP,
        summary="Show or change the settings",
        when="Use to show or change the settings; a secret is never printed.",
        description="`show` lists every setting with its value and where it comes from (environment, config file or default); the token "
        "is masked and the e-mail address shortened. `set NAME VALUE` and `unset NAME` change the configuration file. "
        "The environment overrides the file. The token is set with `conflu setup-token` only.",
        args=(
            Arg(("action",), "show (default), path, set or unset.", kind="choice", choices=("show", "path", "set", "unset")),
            Arg(("name",), "Setting name, for example CONFLUENCE_BASE_URL."),
            Arg(("value",), "New value for `set`."),
        ),
        examples=(
            Example("conflu config show"),
            Example("conflu config set CONFLUENCE_BASE_URL https://example.atlassian.net/wiki"),
            Example("conflu config set CONFLUENCE_EMAIL user@example.com"),
            Example("conflu config set CONFLUENCE_HIDE_USERS true"),
            Example("conflu config unset CONFLUENCE_CA_BUNDLE"),
        ),
        writes=True,
        json_output=True,
        output="file, settings[{name,value,source,description,secret}].",
        handler=run_config,
    ),
    Command(
        name="ping",
        group=GROUP,
        summary="Check the connection and the credentials",
        when="Use to test the connection with one request.",
        description="Calls Confluence once. Prints who the token belongs to, unless --quiet (which prints just OK) or CONFLUENCE_HIDE_USERS=true.",
        args=(Arg(("--quiet",), "Print only OK, not who you are.", kind="flag"),),
        examples=(Example("conflu ping --quiet"),),
        json_output=True,
        output="ok, baseUrl, user{accountId,displayName} (null when hidden).",
        handler=run_ping,
    ),
    Command(
        name="doctor",
        group=GROUP,
        summary="Check the setup and say how to fix it",
        when="Use first in a session: it checks the setup and the connection and says how to fix what is wrong.",
        description="Checks the configuration, the credentials, TLS, the connection, whether spaces can be read and the current space, "
        "and says how to fix what is wrong. Exit code 1 when a check failed.",
        examples=(Example("conflu doctor"), Example("conflu doctor --json")),
        json_output=True,
        output="ok and checks[{name,status,detail,hint}] with status ok, warn or fail.",
        handler=run_doctor,
    ),
)
