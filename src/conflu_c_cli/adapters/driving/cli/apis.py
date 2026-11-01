"""Which Confluence Cloud REST API each command uses: the table behind the line `REST API:` of `conflu help COMMAND`, the key `api` of `conflu commands --json`
and the command reference. v2 is the default; v1 is used only where v2 has no equivalent, and each such call has its reason in `conflu how-to compatibility`.

`tests/integration/test_command_apis.py` holds this table to the calls that the sweep of every command recorded, so it cannot drift from what the commands send:
a new command needs its entry here, and a command that starts to use another API fails the test until the entry says so."""
from __future__ import annotations

V2 = "v2"
V1 = "v1"
BOTH = "v2+v1"
NONE = "none"  # it works on this computer
NAMED = "named"  # `conflu api`: the path says
TOOLS = "tools"  # `conflu mcp`: every tool uses the API of its command

API_OF: dict[str, str] = {
    "page": V2,
    "pages": V2,
    "versions": V2,
    "search": BOTH,
    "export": V2,
    "tree": V2,
    "diff": V2,
    "comments": BOTH,
    "labels": V2,
    "attachments": V2,
    "attachment": V2,
    "download": BOTH,
    "move": BOTH,
    "restore": BOTH,
    "comment": BOTH,
    "label": BOTH,
    "attach": BOTH,
    "update": V2,
    "create": BOTH,
    "import-md": V2,
    "import-md-dir": V2,
    "folder": V2,
    "whiteboard": V2,
    "database": V2,
    "smartlink": V2,
    "folder-create": V2,
    "smartlink-create": V2,
    "blogposts": V2,
    "blogpost": V2,
    "blogpost-create": BOTH,
    "blogpost-update": V2,
    "permissions": V2,
    "restrictions": V2,
    "space-access": V2,
    "watching": BOTH,
    "watch": BOTH,
    "users": BOTH,
    "tasks": BOTH,
    "task": V2,
    "properties": V2,
    "property-set": V2,
    "templates": BOTH,
    "template": V1,
    "spaces": V2,
    "space": V2,
    "setup-token": NONE,
    "remove-token": NONE,
    "use": V2,
    "current": NONE,
    "clear-space": NONE,
    "config": NONE,
    "ping": V1,
    "doctor": BOTH,
    "setup": NONE,
    "help": NONE,
    "commands": NONE,
    "version": NONE,
    "changelog": NONE,
    "how-to": NONE,
    "skill": NONE,
    "convert": NONE,
    "api": NAMED,
    "mcp": TOOLS,
}

_SAYS = {
    V2: "v2 (/wiki/api/v2).",
    BOTH: "v2 (/wiki/api/v2), and v1 (/wiki/rest/api) for what v2 cannot do: the reasons are in `conflu how-to compatibility`.",
    V1: "v1 (/wiki/rest/api), because v2 has no call for it: the reason is in `conflu how-to compatibility`.",
    NONE: "none, it works on this computer.",
    NAMED: "the one that PATH names: a path that starts with api/ is v2, one that starts with rest/ is v1.",
    TOOLS: "none of its own: every tool it serves uses the API of its command.",
}
_EXCEPTIONS = {
    "setup": "none of the two: --discover reads the public tenant information of your site, which is no REST call.",
    "use": "v2 (/wiki/api/v2): the key is looked up among the spaces.",
}


def api_of(name: str) -> str:
    """`v2`, `v1`, `v2+v1`, `none`, `named` or `tools`; empty for a command that the table does not know."""
    return API_OF.get(name, "")


def api_line(name: str) -> str:
    """The sentence for `REST API: ...` in the help and in the reference; empty for a command that the table does not know."""
    return _EXCEPTIONS.get(name) or _SAYS.get(api_of(name), "")
