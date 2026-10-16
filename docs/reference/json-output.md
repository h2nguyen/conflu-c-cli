# JSON output and errors

Every command that returns data has `--json` (or set `CONFLUENCE_OUTPUT=json` for a whole session). The keys are
stable, camelCase and documented here and in the `JSON output:` line of every command in the
[command reference](commands.md). `conflu commands --json` carries the same information for programs.

## Conventions

- **One value on standard output.** A single JSON document. When the output is piped it is one compact line; on a
  terminal it is indented. Progress and warnings never go to standard output; they go to standard error.
- **Errors go to standard error.** With `--json`, or `CONFLUENCE_OUTPUT=json`, a failing command prints one object
  on stderr: `{"error": {...}}`.
- **camelCase keys.** The CLI writes `spaceKey`, `nextCursor`, `minorEdit`, `downloadLink`, and so on.
- **Keys are added, not renamed or removed, within a major version.** A breaking rename needs a new major version.
- **Missing values are `null`.** That is how the CLI represents an absent parent page, author, user, cursor,
  version target or current space.
- **People are hidden unless you ask for them.** `author`, `owner`, comment authors and version authors are `null`
  until `--with-users`, and never shown when `CONFLUENCE_HIDE_USERS=true`. The same holds for the excerpts of
  `conflu search`, which can name mentioned people.
- **Messages stay on stderr.** Even in JSON mode, informational messages and warnings are not mixed into the result.
- **`dropped` and `lossy` are explicit.** The Markdown reading copy can report macros, mentions and
  `redacted-text`, which means the CLI hid e-mail addresses or personal profile links in that Markdown copy.

## Errors

Example, on stderr:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not found: GET /api/v2/pages/999",
    "hint": "Confluence also answers 404 for what the account may not see.",
    "exitCode": 4,
    "details": {
      "status": 404,
      "request": "GET /api/v2/pages/999"
    }
  }
}
```

`code` is one of `USAGE`, `CONFIG`, `INVALID`, `CONFLICT`, `NOT_FOUND`, `AUTH`, `REJECTED`, `UNAVAILABLE`,
`ERROR`. `hint` may be empty. `details` holds structured facts that are useful to a program.

## Page-reading commands

### `conflu page PAGE --json`

```json
{
  "id": "123456",
  "title": "Release notes",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "2001",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "version": {
    "number": 7,
    "created": "2026-10-15T08:00:00.000Z",
    "message": "Added the October notes",
    "minorEdit": false,
    "author": null
  },
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-15T08:00:00.000Z",
  "labels": ["release", "notes"],
  "author": null,
  "owner": null,
  "ancestors": [
    {"id": "2001", "title": "Engineering Home"}
  ],
  "body": {
    "format": "markdown",
    "value": "# Release notes\n\nFirst\n\nSecond",
    "dropped": ["macro:toc", "mention", "redacted-text"],
    "section": null,
    "truncated": false,
    "totalChars": null
  },
  "comments": [
    {
      "id": "4001",
      "kind": "footer",
      "updated": "2026-10-02T10:00:00.000Z",
      "parentId": null,
      "resolution": null,
      "author": null,
      "body": {"format": "markdown", "value": "Looks good.", "dropped": []}
    }
  ]
}
```

`ancestors` appears with `--ancestors`; `comments` appears with `--comments`; `body` is `null` with `--no-body`.

With `--section`, `body.value` is that section only and `body.section` names its heading; with `--max-chars`, `body.truncated` says
that the text was cut and `body.totalChars` is the size of the whole text (of the section, when one was asked for). `body.dropped`
always names what the Markdown cannot say on the whole page, not only in the part that was read.

### `conflu page PAGE --outline --json`

```json
{
  "id": "123456",
  "title": "Release notes",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "2001",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "version": {
    "number": 7,
    "created": "2026-10-15T08:00:00.000Z",
    "message": "Added the October notes",
    "minorEdit": false,
    "author": null
  },
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-15T08:00:00.000Z",
  "labels": ["release", "notes"],
  "author": null,
  "owner": null,
  "body": null,
  "outline": [
    {"index": 1, "level": 1, "title": "Release notes", "chars": 91},
    {"index": 2, "level": 2, "title": "Known issues", "chars": 40}
  ]
}
```

`outline` lists the headings of the Markdown body in reading order. `index` is what `--section N` takes, `chars` the size of the
section with its sub-sections. The body itself is not returned: read the part you need with `--section`.

### `conflu pages --json`

```json
{
  "space": "ENG",
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "pages": [
    {
      "id": "2001",
      "title": "Engineering Home",
      "status": "current",
      "spaceId": "1001",
      "parentId": null,
      "version": 1,
      "updated": "2026-10-01T08:00:00.000Z",
      "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/2001/Engineering+Home"
    }
  ]
}
```

### `conflu tree PAGE --json`

```json
{
  "root": {"id": "2001", "title": "Engineering Home", "spaceKey": "ENG"},
  "depth": 3,
  "count": 3,
  "truncated": false,
  "nodes": [
    {"id": "2003", "title": "Architecture", "type": "page", "parentId": "2001", "depth": 1, "status": "current"},
    {"id": "2004", "title": "ADR 0001", "type": "page", "parentId": "2003", "depth": 2, "status": "current"}
  ]
}
```

### `conflu versions PAGE --json`

```json
{
  "pageId": "123456",
  "title": "Release notes",
  "count": 2,
  "nextCursor": null,
  "versions": [
    {
      "number": 7,
      "created": "2026-10-15T08:00:00.000Z",
      "message": "Added the October notes",
      "minorEdit": false,
      "author": null
    }
  ]
}
```

### `conflu search --json`

```json
{
  "total": 2,
  "count": 2,
  "start": 0,
  "cql": "type = page AND space = \"ENG\" AND text ~ \"retention policy\"",
  "match": "all",
  "relaxed": false,
  "terms": ["retention", "policy"],
  "ignored": [],
  "notes": [],
  "truncated": false,
  "hits": [
    {
      "id": "2002",
      "type": "page",
      "title": "Retention policy",
      "spaceKey": "ENG",
      "path": "Engineering Home > Policies",
      "labels": ["policy"],
      "version": 3,
      "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Retention+policy",
      "excerpt": null,
      "snippet": "Every export is kept for ninety days. The retention policy applies to ...",
      "matched": ["retention", "policy"],
      "lastModified": "2026-10-15T08:00:00.000Z"
    }
  ]
}
```

How the text was searched is in the answer, so that a hit list that looks odd can be understood:

- `terms` are the words and `"phrases"` that went into the query, `ignored` the filler words (English and German) and the words
  beyond the first twelve that were left out. A word in quotes is never left out.
- `match` is `all` (every word occurs), `any` (one is enough) or `cql` (a query written by hand). `relaxed` is `true` when
  no page held all words and the pages that hold some are shown: then `match` is `any`.
- `notes` holds what a person at the terminal is told as well (it also goes to standard error): filler left out, the search relaxed,
  or, when nothing was found, what to try (the language of the pages, fewer words, a wildcard).
- `path` is the chain of parent pages from the top (or `null`), `labels` the page's labels, `version` its current version.
- `snippet` and `matched` are `null` and `[]` unless `--snippets N` was given. Then the first N hits that are pages carry the passage
  around the words (cut from the page as `conflu page` shows it, so people are hidden as there) and the words the page holds. A hit
  without any word in the page gets the beginning of the page.

`excerpt` is `null` unless you add `--with-users`: the search index writes the name of a mentioned person into the
excerpt as plain text, which cannot be told from any other word. `--with-users` is refused under
`CONFLUENCE_HIDE_USERS=true`. `title` is the title as written (`Q&A`), not as the search API escapes it (`Q&amp;A`).

### `conflu export --json`

```json
{
  "directory": "mirror/eng",
  "space": "ENG",
  "root": null,
  "format": "markdown",
  "dryRun": false,
  "count": 2,
  "indexFile": "mirror/eng/index.json",
  "truncated": false,
  "notes": [],
  "pages": [
    {
      "id": "2002",
      "title": "Release notes",
      "parentId": "2001",
      "path": "Engineering Home",
      "file": "release-notes-2002.md",
      "version": 3,
      "updated": "2026-10-10T09:00:00.000Z",
      "lossy": ["macro:toc", "mention", "redacted-text"]
    }
  ]
}
```

## Page-part commands

### `conflu comments PAGE --json`

```json
{
  "pageId": "123456",
  "count": 2,
  "comments": [
    {
      "id": "4001",
      "kind": "footer",
      "updated": "2026-10-02T10:00:00.000Z",
      "parentId": null,
      "resolution": null,
      "author": null,
      "body": {"format": "markdown", "value": "Looks good.", "dropped": []}
    },
    {
      "id": "4002",
      "kind": "footer",
      "updated": "2026-10-02T11:00:00.000Z",
      "parentId": "4001",
      "resolution": null,
      "author": null,
      "body": {"format": "markdown", "value": "Thanks!", "dropped": []}
    }
  ]
}
```

### `conflu labels PAGE --json`

```json
{
  "pageId": "123456",
  "labels": [
    {"name": "release", "prefix": "global"},
    {"name": "notes", "prefix": "global"}
  ]
}
```

### `conflu attachments PAGE --json`

```json
{
  "pageId": "123456",
  "count": 1,
  "nextCursor": null,
  "attachments": [
    {
      "id": "att5001",
      "title": "diagram.png",
      "mediaType": "image/png",
      "size": 10,
      "version": 1,
      "created": "2026-10-04T08:00:00.000Z",
      "pageId": "123456",
      "downloadLink": "/download/attachments/123456/diagram.png?version=1&api=v2",
      "comment": null
    }
  ]
}
```

### `conflu download ... --json`

```json
{
  "dryRun": false,
  "count": 2,
  "files": [
    {"attachmentId": "att5001", "name": "diagram.png", "path": "out/diagram.png", "size": 10, "action": "downloaded"},
    {"attachmentId": "att5002", "name": "notes.txt", "path": "out/notes.txt", "size": 12, "action": "downloaded"}
  ]
}
```

## Write commands

### `conflu update PAGE --json`

```json
{
  "action": "updated",
  "dryRun": true,
  "pageId": "123456",
  "title": "Release notes",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "versionFrom": 7,
  "versionTo": 8,
  "lost": [],
  "labels": [],
  "payload": {
    "id": "123456",
    "status": "current",
    "title": "Release notes",
    "body": {"representation": "storage", "value": "<p>Added.</p>"},
    "version": {"number": 8, "message": "Added the October notes"}
  }
}
```

`action` may also be `unchanged`.

### `conflu move PAGE --json`

```json
{
  "action": "moved",
  "dryRun": true,
  "pageId": "123456",
  "title": "Release notes",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "versionFrom": 7,
  "versionTo": 7,
  "lost": [],
  "labels": [],
  "payload": {"pageId": "123456", "position": "before", "targetId": "654321"}
}
```

### `conflu comment PAGE --json`

```json
{
  "pageId": "123456",
  "dryRun": false,
  "commentId": "4009",
  "payload": {
    "pageId": "123456",
    "body": {"representation": "storage", "value": "<p>Reviewed.</p>"},
    "parentCommentId": "4001"
  }
}
```

### `conflu label PAGE --json`

```json
{
  "pageId": "123456",
  "dryRun": false,
  "added": ["reviewed"],
  "removed": ["draft"],
  "labels": ["release", "reviewed"]
}
```

### `conflu attach PAGE FILE... --json`

```json
{
  "pageId": "123456",
  "dryRun": false,
  "files": [
    {
      "path": "docs/diagram.png",
      "name": "diagram.png",
      "size": 10,
      "action": "uploaded",
      "attachmentId": "att5001",
      "version": 2
    }
  ]
}
```

### `conflu create --json`

```json
{
  "action": "created",
  "dryRun": false,
  "pageId": "20001",
  "title": "Monthly checklist",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/20001/Monthly+checklist",
  "versionFrom": null,
  "versionTo": 1,
  "lost": [],
  "labels": ["operations", "checklist"],
  "payload": {
    "spaceId": "1001",
    "status": "current",
    "title": "Monthly checklist",
    "parentId": "123456",
    "body": {"representation": "storage", "value": "<p>Run the checks.</p>"}
  }
}
```

### `conflu import-md FILE --json`

```json
{
  "file": "docs/release-notes.md",
  "action": "updated",
  "pageId": "123456",
  "title": "Release notes",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "dryRun": false,
  "message": null,
  "lost": [],
  "labels": ["release"],
  "payload": {
    "id": "123456",
    "status": "current",
    "title": "Release notes",
    "body": {"representation": "storage", "value": "<p>Updated text.</p>"},
    "version": {"number": 8, "message": "Imported from release-notes.md"}
  }
}
```

`action` may be `created`, `updated` or `unchanged`. `unchanged` is what you get when the imported Markdown is
exactly what the current page already shows as Markdown and the front matter names no label the page lacks. A label
that is new counts as a change: the action is then `updated`, and `labels` names the labels the import added (in a dry
run, the labels it would add).

### `conflu import-md-dir DIR --json`

```json
{
  "dryRun": false,
  "created": 1,
  "updated": 1,
  "unchanged": 2,
  "failed": 0,
  "outcomes": [
    {
      "file": "docs/overview.md",
      "action": "created",
      "pageId": "20011",
      "title": "Overview",
      "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/20011/Overview",
      "dryRun": false,
      "message": null,
      "lost": [],
      "labels": [],
      "payload": {
        "spaceId": "1001",
        "status": "current",
        "title": "Overview",
        "parentId": "123456",
        "body": {"representation": "storage", "value": "<p>Overview text.</p>"}
      }
    }
  ]
}
```

## Space commands

### `conflu spaces --json`

```json
{
  "count": 2,
  "nextCursor": null,
  "truncated": false,
  "spaces": [
    {
      "id": "1001",
      "key": "ENG",
      "name": "Engineering",
      "type": "global",
      "status": "current",
      "homepageId": "2001",
      "description": "Engineering documentation",
      "created": "2026-09-01T08:00:00.000Z",
      "url": "https://example.atlassian.net/wiki/spaces/ENG"
    }
  ]
}
```

### `conflu space [KEY] --json`

```json
{
  "id": "1001",
  "key": "ENG",
  "name": "Engineering",
  "type": "global",
  "status": "current",
  "homepageId": "2001",
  "description": "Engineering documentation",
  "created": "2026-09-01T08:00:00.000Z",
  "url": "https://example.atlassian.net/wiki/spaces/ENG"
}
```

## Setup and information commands

### `conflu setup-token --json`

```json
{"saved": true, "file": "C:/Users/example/.config/conflu-c-cli/config"}
```

### `conflu remove-token --json`

```json
{"removed": true, "file": "C:/Users/example/.config/conflu-c-cli/config"}
```

### `conflu use KEY --json`

```json
{"space": "ENG", "name": "Engineering"}
```

### `conflu current --json`

```json
{"space": "ENG"}
```

When no current space is set the JSON becomes `{"space": null}` and the exit code is 1.

### `conflu clear-space --json`

```json
{"cleared": true}
```

### `conflu config show --json`

```json
{
  "file": "C:/Users/example/.config/conflu-c-cli/config",
  "settings": [
    {
      "name": "CONFLUENCE_BASE_URL",
      "value": "https://example.atlassian.net/wiki",
      "source": "config file",
      "description": "Address of the Confluence Cloud site, ending in /wiki. The /wiki is added when it is left out of an atlassian.net address.",
      "secret": false
    },
    {
      "name": "CONFLUENCE_API_TOKEN",
      "value": "******** (17 characters)",
      "source": "config file",
      "description": "API token of that account. Save it with `conflu setup-token`; it is never printed.",
      "secret": true
    }
  ]
}
```

### `conflu ping --json`

```json
{
  "ok": true,
  "baseUrl": "https://example.atlassian.net/wiki",
  "user": null
}
```

With `--quiet` or `CONFLUENCE_HIDE_USERS=true`, `user` is `null`; otherwise it is
`{"accountId", "displayName"}`.

### `conflu doctor --json`

```json
{
  "ok": true,
  "checks": [
    {"name": "runtime", "status": "ok", "detail": "conflu-c-cli 1.0.0 on Python 3.13.3", "hint": ""},
    {"name": "base url", "status": "ok", "detail": "https", "hint": ""},
    {"name": "space", "status": "warn", "detail": "no current space", "hint": "Run `conflu use KEY` to avoid typing --space."}
  ]
}
```

### `conflu commands --json`

```json
{
  "version": "1.0.0",
  "commands": [
    {
      "name": "page",
      "group": "Read",
      "summary": "Show one page",
      "description": "Shows the title, space, version, labels and the body.",
      "whenToUse": "Use to read one page whose id, address or title you know. Start with --outline and read only the --section you need.",
      "usage": "conflu page PAGE [--format markdown|text|storage] [--no-body] [--comments] [--ancestors] [--with-users] [--raw] [--json]",
      "arguments": [
        {
          "names": ["ref"],
          "positional": true,
          "kind": "str",
          "required": true,
          "default": null,
          "choices": [],
          "help": "Page id, or the address of the page as copied from the browser."
        }
      ],
      "supportsJson": true,
      "changesData": false,
      "jsonOutput": "id, title, status, spaceId, spaceKey, parentId, url, version{number,created,message,minorEdit,author}, created, updated, labels[], author and owner (null unless --with-users), ancestors[{id,title}] (with --ancestors), body{format,value,dropped[]} (null with --no-body), comments[] (with --comments).",
      "examples": [{"command": "conflu page 123456", "note": "the page as Markdown"}],
      "notes": [
        "The Markdown is a reading copy: macros, layouts, mentions, links between pages and the like cannot be shown in it. Both the text and the JSON name what is missing (`dropped`)."
      ],
      "aliases": []
    }
  ],
  "exitCodes": [
    {"code": 0, "names": "OK", "meaning": "The command succeeded (also for a dry run)."}
  ],
  "settings": [
    {
      "name": "CONFLUENCE_BASE_URL",
      "kind": "str",
      "default": "",
      "secret": false,
      "personal": false,
      "description": "Address of the Confluence Cloud site, ending in /wiki. The /wiki is added when it is left out of an atlassian.net address."
    }
  ]
}
```

### `conflu commands --format mcp`

```json
{
  "tools": [
    {
      "name": "conflu_page",
      "title": "Show one page",
      "description": "Show one page.\n\nWhen to use: Use to read one page whose id, address or title you know. ...\n\nReturns JSON: id, title, ...",
      "inputSchema": {
        "type": "object",
        "properties": {
          "page": {"type": "string", "description": "Page id, the address of the page as copied from the browser, or a `page:KEY/Title` reference."}
        },
        "required": ["page"],
        "additionalProperties": false
      },
      "annotations": {"title": "Show one page", "readOnlyHint": true, "openWorldHint": true},
      "_meta": {
        "conflu": {
          "command": ["conflu", "page"],
          "arguments": [{"property": "page", "positional": true, "flag": null, "type": "string"}],
          "alwaysAppend": ["--json"],
          "examples": ["conflu page 123456"]
        }
      }
    }
  ],
  "_meta": {
    "conflu": {
      "version": "1.0.0",
      "only": "read",
      "invoke": "Run the command: `conflu NAME`, then the positional arguments in the order of `arguments`, ...",
      "exitCodes": [{"code": 0, "names": "OK", "meaning": "The command succeeded (also for a dry run)."}]
    }
  }
}
```

The shape is that of an MCP `tools/list` answer, so that the tools can be handed to a tool-calling model or to an MCP server that wraps
the CLI. `--only read` (the default) lists the commands that change nothing, `--only write` the others, `--only all` both.

- **Which commands.** Commands for the person (the token, the settings, the default space, help and the raw `api`) are never listed.
- **`inputSchema`** is JSON Schema: an option `--if-version` is the property `ifVersion`, a positional `PAGE` is `page`, a flag is a
  `boolean`, an option that may be repeated is an `array` of strings, a choice has an `enum`. `required` lists the arguments the command
  insists on.
- **`annotations`** follow MCP: `readOnlyHint`; for a tool that changes Confluence also `destructiveHint` (it replaces, moves or removes)
  and `idempotentHint` (the same call again changes nothing more); `openWorldHint` is `false` for the commands that never ask Confluence.
- **`_meta.conflu`** turns a call into a command line: `command`, then the positional `arguments` in order, then every other property
  as its `flag` (a `boolean` only when true, an `array` as the flag repeated; the `array` of a positional argument, such as the files of
  `conflu attach`, is passed item by item, in order), then `alwaysAppend`. The result is JSON on standard
  output; a failure is a non-zero exit code and JSON on standard error. `examples` are command lines that work.
- **The texts** speak of properties and tools (`dryRun`, `conflu_page`), not of flags and commands.

### `conflu version --json`

```json
{
  "name": "conflu-c-cli",
  "version": "1.0.0",
  "python": "3.13.3",
  "platform": "win32"
}
```

### `conflu how-to --json`

Without a topic:

```json
[
  {"topic": "readme", "title": "Overview, install and the first commands"},
  {"topic": "daily-workflow", "title": "Daily workflow"}
]
```

With a topic:

```json
{
  "topic": "daily-workflow",
  "text": "# Daily workflow\n\nThis is a small set of commands that covers most work with Confluence Cloud. ..."
}
```

### `conflu skill --json`

Show:

```json
{
  "name": "conflu-c-cli",
  "text": "---\nname: conflu-c-cli\ndescription: ...\n---\n# Working with Confluence through the conflu CLI\n..."
}
```

Install:

```json
{
  "path": ".github/skills/conflu-c-cli/SKILL.md",
  "action": "installed",
  "dryRun": false
}
```

### `conflu api ... --json`

`conflu api` prints Confluence's response unchanged, apart from the normal privacy scrubbing when
`CONFLUENCE_HIDE_USERS=true`. A possible response is therefore whatever that endpoint returns, for example:

```json
{
  "ok": true,
  "user": {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Documentation Reviewer"}
}
```
