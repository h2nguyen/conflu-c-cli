"""`conflu setup`: the setting up that needs a look at the site. Today: `--discover`, the address of the Atlassian gateway."""
from __future__ import annotations

import argparse

from .....application.tenant import TenantProposal
from .....domain.errors import UsageError
from ..runtime import Context
from ..spec import Arg, Command, Example

GROUP = "Setup and information"

TOKENS = "https://id.atlassian.com/manage-profile/security/api-tokens"


def _confirm(ctx: Context, proposal: TenantProposal) -> bool:
    """The question goes to standard error and the answer comes from standard input, so that a result on standard output stays a result."""
    ctx.err.write(f"Set CONFLUENCE_BASE_URL to {proposal.gateway_address}? [y/N] ")
    ctx.err.flush()
    return ctx.stdin.readline().strip().lower() in ("y", "yes")


def _site_note(site: str) -> str:
    if site.endswith(".atlassian.net"):
        return f"The site address ({site}) works too, with an API token without scopes; the gateway address is for a token with scopes."
    return f"{site} is a custom domain, and API tokens are not accepted on a custom domain: the gateway address is the way to use one."


def _say_what_was_found(ctx: Context, proposal: TenantProposal) -> None:
    ctx.print(f"Site: {proposal.site}, cloud id {proposal.cloud_id}")
    ctx.print(f"Gateway address: {proposal.gateway_address}")


def run_setup(ctx: Context, args: argparse.Namespace) -> int:
    if not args.discover:
        raise UsageError(
            "`conflu setup` has to be told what to set up.",
            hint="There is one thing today: `conflu setup --discover` finds the gateway address of your site. See `conflu help setup`.",
        )
    discovery = ctx.app.discover_tenant
    proposal = discovery.propose()
    changed = not proposal.already
    written = False
    if changed and not args.dry_run:
        written = args.yes or (ctx.stdin.isatty() and _confirm(ctx, proposal))
    if written:
        discovery.apply(proposal)
        if ctx.environ.get("CONFLUENCE_BASE_URL"):
            ctx.diagnostics.warn("CONFLUENCE_BASE_URL is also set in the environment, which overrides the configuration file; the change has no effect while it is set.")
    if ctx.json_mode:
        ctx.print_json(
            {
                "current": proposal.current,
                "cloudId": proposal.cloud_id,
                "gatewayAddress": proposal.gateway_address,
                "written": written,
                "dryRun": args.dry_run,
                "changed": changed,
            }
        )
        return 0
    if proposal.already:
        ctx.print(f"CONFLUENCE_BASE_URL is the gateway address already ({proposal.gateway_address}). Nothing was written.")
        return 0
    _say_what_was_found(ctx, proposal)
    if written:
        ctx.print(f"CONFLUENCE_BASE_URL saved to {ctx.app.config.path}.")
        ctx.print("Use it with an API token with scopes: a token without scopes works on the site address, not on this one.")
        ctx.print(f"Create the token at {TOKENS}, save it with `conflu setup-token`, then run `conflu doctor`.")
    elif args.dry_run:
        ctx.print(f"Would set CONFLUENCE_BASE_URL to {proposal.gateway_address} (it is {proposal.current} now). Dry run: nothing was written.")
        ctx.print(_site_note(proposal.site))
    else:
        terminal = ctx.stdin.isatty()  # then the person was asked and said no
        ctx.print("Nothing was written." if terminal else "Nothing was written. To use that address, run:")
        if not terminal:
            ctx.print(f"  conflu config set CONFLUENCE_BASE_URL {proposal.gateway_address}")
            ctx.print("or run `conflu setup --discover --yes`.")
        ctx.print(_site_note(proposal.site))
    return 0


COMMANDS = (
    Command(
        name="setup",
        group=GROUP,
        summary="Find the gateway address of the site",
        when="For the person, once: when API tokens are refused on the address of the site (a custom domain), or to move to the gateway address "
        "that tokens with scopes use. It changes the local configuration only, never Confluence.",
        description="`--discover` reads the public tenant information of the site that CONFLUENCE_BASE_URL names (`/_edge/tenant_info`, for example "
        "`https://SITE.atlassian.net/_edge/tenant_info`: at the root of that host and of no other, with no credential, and a redirect is not followed) and "
        "proposes the gateway address `https://api.atlassian.com/ex/confluence/CLOUD_ID`. On a terminal it asks before it saves the address as "
        "CONFLUENCE_BASE_URL; --yes saves it without asking; without a terminal and without --yes it only prints the proposal and the `conflu config set` "
        "command that applies it. --dry-run says what would be saved and saves nothing. The gateway address belongs with an API token with scopes; a "
        "token without scopes works on the site address (SITE.atlassian.net), so an atlassian.net address does not have to change.",
        args=(
            Arg(("--discover",), "Find the cloud id of the site and propose the gateway address.", kind="flag"),
            Arg(("--yes",), "Save the address without asking.", kind="flag"),
            Arg(("--dry-run",), "Say what would be saved and save nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu setup --discover"),
            Example("conflu setup --discover --dry-run"),
            Example("conflu setup --discover --yes --json", "for a script: no question, JSON result"),
        ),
        writes=True,
        json_output=True,
        output="current (CONFLUENCE_BASE_URL now, without a user name or password), cloudId, gatewayAddress, written (the configuration file was changed), "
        "dryRun, changed (the address is not the gateway address yet, so there is something to change; false when it already is).",
        for_person=True,
        handler=run_setup,
    ),
)
