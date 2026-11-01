"""Commands that run the CLI for another program: `conflu mcp`. Add a `Command` to COMMANDS: the module is already registered."""
from __future__ import annotations

import argparse

from ..runtime import Context
from ..spec import Arg, Command, Example

GROUP = "Tools"


def run_mcp(ctx: Context, args: argparse.Namespace) -> int:
    from ..mcp_server import ServerOptions, serve  # the server imports the registry, which imports this module

    options = ServerOptions(
        allow_write=args.allow_write,
        allow_files=args.allow_files,
        show_users=args.show_users,
        groups=tuple(args.group or ()),
        verbose=bool(getattr(args, "verbose", False)),
    )
    return serve(ctx, options)


COMMANDS = (
    Command(
        name="mcp",
        group=GROUP,
        summary="Run a local MCP server for AI tools",
        when="Use to give an MCP client such as VS Code the read-only commands as tools, with no shell and no new process per call; "
        "the client starts it from its MCP configuration. An agent that has a shell runs the commands directly instead.",
        description="Starts an MCP server on standard input and output: the commands of `conflu commands --format mcp` become tools that "
        "run inside this process, so a call needs no shell, and each call builds its own application, as a run of `conflu` would. "
        "It speaks JSON-RPC, one message per line, "
        "and writes nothing else to standard output; its own messages go to standard error, and the end of the input stops it. "
        "Tools that change Confluence are not offered unless --allow-write, tools that write files (download, export) not unless "
        "--allow-files, and people stay out unless --show-users. Every path in a call must lie below the folder the server was "
        "started in; the settings file and the cache folder are never reachable.",
        args=(
            Arg(
                ("--allow-write",),
                "Also offer the commands that change Confluence (each has dryRun). Without it they are not offered and a call of one is refused. "
                "It does not offer the tools that write files.",
                kind="flag",
            ),
            Arg(
                ("--allow-files",),
                "Also offer the commands that write local files: download and export. A call may write only below the folder the "
                "server was started in, never into a hidden folder, never over an existing file, download only below "
                "tmp/conflu-attachments, and there is no force. It does not offer the tools that change Confluence.",
                kind="flag",
            ),
            Arg(
                ("--show-users",),
                "Allow the option that shows people (withUsers). Without it a call that sets it is refused; "
                "CONFLUENCE_HIDE_USERS=true refuses it anyway.",
                kind="flag",
            ),
            Arg(
                ("--group",),
                "Offer only the commands of this group of `conflu help` (Read, Work on a page, ...); the case does not matter. "
                "Repeat it for several groups. A client that loads every tool into a model spends context on all of them: take the groups it needs.",
                kind="repeat",
                metavar="NAME",
            ),
        ),
        examples=(
            Example("conflu mcp", "what an MCP client starts: the read-only tools"),
            Example("conflu mcp --allow-write", "also the tools that change Confluence"),
            Example("conflu mcp --allow-files", "also download and export, writing below the working folder"),
            Example("conflu mcp --group Read --group Spaces", "only the commands of two groups"),
        ),
        notes=(
            'VS Code, in .vscode/mcp.json: {"servers": {"conflu": {"type": "stdio", "command": "conflu", "args": ["mcp"]}}}. '
            'Add "--allow-write", "--allow-files" or "--group", "Read" to args as needed.',
            'Another client: the same command and arguments in its MCP settings, often under a top-level "mcpServers" object: '
            '{"mcpServers": {"conflu": {"command": "conflu", "args": ["mcp"]}}}.',
            "If the client does not find `conflu` on its PATH, start the program itself. "
            'In a console: python "%LOCALAPPDATA%\\conflu-c-cli\\conflu.py" mcp. '
            'In the settings of the client: "command": "python" and "args": [the same path, "mcp"]; '
            "VS Code writes ${env:LOCALAPPDATA} for the folder.",
            "The working folder is the boundary of every path in a call (file, out, dir, ...): start the server in "
            'the project folder ("cwd": "${workspaceFolder}" in VS Code). Paths outside it, `..` escapes, network and device paths, '
            "the settings file and the cache folder are refused with an error that says what is allowed.",
            "The settings file and the token are read again for each call: `conflu config set` works at the next call. The environment of "
            "the server is read once when it starts: restart it after changing CONFLUENCE_BASE_URL, CONFLUENCE_PROFILE or another variable. "
            "`CONFLUENCE_PROFILE=agent` in the environment of the server keeps people out of the answers, as it does for every command "
            "(`conflu how-to use-with-ai-agents`). More: `conflu how-to mcp-server`.",
        ),
        needs_app=False,
        streams=True,
        for_person=True,
        handler=run_mcp,
    ),
)
