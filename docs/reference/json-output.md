# JSON output and errors

Every command that returns data has `--json` (or set `CONFLUENCE_OUTPUT=json` for a whole session). The keys are
stable, camelCase and documented here and in the `JSON output:` line of every command in the
[command reference](commands.md). `conflu commands --json` carries the same information for programs.

## Conventions

- **One value on standard output.** A single JSON document. When the output is piped it is one compact line; on a
  terminal it is indented (`--raw` too). Progress and warnings never go to standard output; they go to standard error.
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
- **A file that the program writes is told in one line.** `--out FILE` of `page`, `blogpost` and `template` (with `--body-only`) and of `convert` writes the text that the
  command would have printed into a file, as UTF-8 (a shell's `>` damages it in Windows PowerShell 5.1), and answers `Wrote N bytes to FILE`; with `--json` that is the
  object `{"file": "page.xml", "bytes": 1234}` (shown below for each command). `convert` has no JSON, so its line is text.
- **`dropped` and `lossy` are explicit.** The Markdown reading copy names what it cannot carry: macros (`macro:NAME`), mentions (`mention`), links whose target Markdown has no address
  for (`link:page`, `link:attachment`, `link:anchor`, `link:blogpost`, `link:space`, `link:shortcut`, `link:content`, `link:NAME`), anchors (`anchor`), the hint of a template
  (`placeholder`), layouts, some tables and some formatting, and `redacted-text`, which means the CLI hid e-mail addresses or personal profile links in that Markdown copy. The same
  names are the `lost` of a replacement from Markdown that was forced, and without `--force` the replacement is refused for them. Formatting that is only how the page looks
  (indentation, the width and layout of a table ...) has no name; the guide [Markdown and storage format](../how-to/markdown-and-storage-format.md#what-markdown-cannot-say) says
  what every name means and which formatting is not named.

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

The words of the server in `message` have no e-mail addresses (`[email]`), no links to people (`[personal link]`) and no account ids (`[account id]`),
whatever the policy. A refusal that has no status of its own (a 400, for example) also has `details.confluence`, the answer of the server with its text
redacted in the same way; under `CONFLUENCE_HIDE_USERS=true` (the agent profile sets it) it is left out. A bug (an unexpected error) is reported like any other
failure: with JSON asked for (`--json`, `CONFLUENCE_OUTPUT=json`, the agent profile), the last line of standard error is the error object with `code` `ERROR` and a
message that starts with `unexpected`.

## The envelope: `--json-envelope`

Some agent tools report the exit code as 1 for every command, or drop standard error, so that a failure cannot be told from a result.
`--json-envelope` (or `CONFLUENCE_JSON_ENVELOPE=1` in the environment, also `true`, `yes` or `on`, for a whole session) makes **every**
command print exactly one JSON object on standard output, whatever happens. A result is `ok` with its `data`:

```json
{"ok": true, "data": {"id": "123456", "title": "Release notes"}}
```

A failure is `ok: false` with the same `error` object as above:

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "Not found: GET /api/v2/pages/999", "hint": "", "exitCode": 4, "details": {"status": 404}}}
```

- A command that supports `--json` prints its JSON as `data` (the envelope implies `--json`). A command without JSON (`convert`,
  `changelog`), and a mode without it (`page --body-only`), prints `{"text": "..."}` as `data`; with `--out` the answer of `page`, `blogpost` and `template` is the object
  `{"file", "bytes"}`, and that of `convert` is its one line as `text`.
- The exit code of the process and standard error stay as they are: an error is still printed there too, as text or with `--json`
  as JSON. The envelope is added, nothing is taken away.
- A command that answers and still asks for a non-zero exit code (`current` without a current space, `doctor` with a failed
  check) has `"ok": false`, its `data` and an `error` with `"code": "EXIT"`. A bug is `"code": "ERROR"` with the message
  `unexpected ...`.
- What a command printed before it failed is not part of the envelope. `--help`, and a command that talks on standard input and
  output itself (a server), are not wrapped.
- Without the switch nothing changes.

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
  "parentType": "page",
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

`ancestors` appears with `--ancestors`; `comments` appears with `--comments`; `body` is `null` with `--no-body`. `attachments` and `attachmentTotal` appear with
`--attachments`, `version.current` and `currentVersion` with `--version N`, and for several pages the document is `{count, pages[], errors[]}`: the sections
[earlier versions, differences and restoring](#earlier-versions-differences-and-restoring) below show each.

With `--section`, `body.value` is that section only and `body.section` names its heading; with `--max-chars`, `body.truncated` says
that the text was cut and `body.totalChars` is the size of the whole text (of the section, when one was asked for). `body.dropped`
always names what the Markdown cannot say on the whole page, not only in the part that was read. A link to a page in a personal space (its key is the account id of its owner)
is written `page:[hidden]/Title`, and in `--format storage` the key is `[hidden]` in `ri:space-key`, unless `--with-users`; storage format that was read that way is refused when it is written back.

### `conflu page PAGE --outline --json`

```json
{
  "id": "123456",
  "title": "Release notes",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "2001",
  "parentType": "page",
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

`space` is `[hidden]` when the space is a personal space (also for the `--space ~KEY` that you typed): its key is the account id of its owner, and `pages` has no `--with-users`. `spaceId` stays, as it names nobody.

### `conflu tree PAGE --json`

```json
{
  "root": {"id": "2001", "title": "Engineering Home", "type": "page", "spaceKey": "ENG"},
  "depth": 3,
  "count": 3,
  "truncated": false,
  "nodes": [
    {"id": "2003", "title": "Architecture", "type": "page", "parentId": "2001", "depth": 1, "status": "current"},
    {"id": "2004", "title": "ADR 0001", "type": "page", "parentId": "2003", "depth": 2, "status": "current"}
  ]
}
```

`root.type` is `page`, or `folder`, `whiteboard`, `database` or `embed` (a smart link) when the tree starts at one of those; the same words are the `type` of the nodes.
`root.spaceKey` is `[hidden]` when the tree is in a personal space, whose key is the account id of its owner (`tree` has no `--with-users`).

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

A search can find people and spaces (`--cql 'type = user ...'`, `--type any`). Without `--with-users` no hit about a person is listed (nor is an item of `--raw`
that is a person), a hit about a personal space has the key `[hidden]`, the name `[personal space]` and no address, and `notes` says how many hits were left out and never who.
`total` counts what Confluence found (people included), `count` the hits that are listed; when every hit was a person, `hits` is empty. No key of the answer names a person.
`cql` is the query that ran, with the key of a personal space in it (`--space ~KEY`, or a query that you wrote) shown as `[hidden]` unless `--with-users`: what was sent is the query itself.

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

`space` is `[hidden]` for a personal space (also for `--space ~KEY`, which you typed yourself): its key is the account id of its owner, and `export` has no
`--with-users`. The files and `index.json` say the same: the `space:` line and the `space` of the index are `[hidden]`, and the `url:` line of a file in such a
space names the page by its id alone (`.../pages/viewpage.action?pageId=ID`). A file with a `page_id` is imported by that id; for a new page, `import-md`
ignores a `space: [hidden]` line and takes the space of `--space`, or of the current space.

## Page-part commands

### `conflu comments PAGE --json`

```json
{
  "pageId": "123456",
  "total": 3,
  "count": 2,
  "since": "2026-10-01T00:00:00+00:00",
  "comments": [
    {
      "id": "4001",
      "kind": "footer",
      "updated": "2026-10-02T10:00:00.000Z",
      "parentId": null,
      "resolution": null,
      "author": null,
      "authorRef": "a-97d57512",
      "byMe": true,
      "body": {"format": "markdown", "value": "Looks good.", "dropped": []}
    },
    {
      "id": "4002",
      "kind": "footer",
      "updated": "2026-10-02T11:00:00.000Z",
      "parentId": "4001",
      "resolution": null,
      "author": null,
      "authorRef": "a-97d57512",
      "byMe": true,
      "body": {"format": "markdown", "value": "Thanks!", "dropped": []}
    }
  ]
}
```

The comments come as conversations, each first comment followed by its answers; `--inline` adds the inline comments and `--resolution STATE` lists the inline ones in that state.
`total` is what the page has of the kind that was asked for, `count` what is printed after `--since` and `--last` chose among them (`since` is the moment `--since` named, `null`
without it). `updated` is when the current version of a comment was saved: when it was written, unless somebody changed it, and that is the time those two options use.

`author` is a person, so it is `null` unless you add `--with-users` (then `{"accountId", "displayName", "email"}`). `authorRef` is not a person: it is `a-` and eight hexadecimal digits of an
HMAC-SHA-256 of the site address and the account id, keyed with your API token, so the comments of one person can be told apart while names are hidden. It is the same in every command that
runs with the same token and differs with another token; without a token to key it, it is `null` and never an unkeyed hash. `byMe` says whether the user of the token wrote the comment
(`null` when that could not be read: it takes one more request, `GET /rest/api/user/current`, and only when there are comments). `--select a,b.c` keeps only those (dotted) keys of every comment.

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

The labels of a page, whole. With `--space KEY` the answer is that of [`conflu labels --space KEY --json`](#conflu-labels---space-key---json).

### `conflu attachments PAGE --json`

```json
{
  "pageId": "123456",
  "blogPostId": null,
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
      "updated": "2026-10-04T08:00:00.000Z",
      "pageId": "123456",
      "blogPostId": null,
      "downloadLink": "/download/attachments/123456/diagram.png?version=1&api=v2",
      "comment": null
    }
  ]
}
```

A blog post works as a page does: for its id `pageId` is `null` and `blogPostId` holds the id, and so it does in every attachment. `created` is when the file was first attached, `updated` when its
current version was saved. `title`, `comment` and `mediaType` are redacted like any text (an e-mail address or a personal link in them is replaced), and `downloadLink`, which ends in the name, ends at the id
when the name holds an address, unless you add `--with-users`. `--select a,b.c` keeps only those (dotted) keys of every attachment.

### `conflu download ... --json`

```json
{
  "dryRun": false,
  "count": 2,
  "files": [
    {"attachmentId": "att5001", "name": "diagram.png", "path": "out/diagram.png", "size": 10, "version": 1, "action": "downloaded"},
    {"attachmentId": "att5002", "name": "notes.txt", "path": "out/notes.txt", "size": 12, "version": 1, "action": "downloaded"}
  ]
}
```

`version` is the version of the file that was saved: the newest one, or the one that `--version N` asked for. `name` is the name the attachment has in Confluence, redacted like any text (an e-mail address or a
personal link in it is replaced: `alex@example.com-cv.pdf` is `[email]`) unless you add `--with-users`; `path` is where the file went. **The file is saved under the name that is printed**, made safe for a file
system (no folder or drive, none of the characters that Windows refuses, no device name, a `_` in front of a name that starts with a dot, at most 200 bytes), so `path` always names the file that is on disk and
`name` is that name before it was made safe. When a run that saves several files stops after it wrote some, the error has `details.written` (`attachmentId`, `path`, `size` of each) and `details.failed`.

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
  },
  "payloadRedacted": false
}
```

`action` may also be `unchanged`. `title` and `url` come from Confluence and are redacted unless you add `--with-users`: an e-mail address in the title
is replaced, and the address of the page then ends at its id. An append or a prepend sends the whole body, so `payload` is shown without the people
(mentions) and the e-mail addresses and personal links that the body holds, and `payloadRedacted` is `true`; what is sent is unchanged, and
`--with-users` (refused when `CONFLUENCE_HIDE_USERS=true`) prints the exact request.

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
  "payload": {"pageId": "123456", "position": "before", "targetId": "654321"},
  "payloadRedacted": false,
  "target": {"id": "654321", "type": "page", "title": "Engineering Home"},
  "confirmed": null,
  "message": null
}
```

`target` is what the page was moved to: a page, or a folder, a whiteboard, a database or a smart link (`type` says which). `action` may also be
`unchanged`, for a page that is below the folder already. Below a folder the move is a save of the page, so `versionTo` is `versionFrom` plus one
and `payload` is the whole request, body included; `payloadRedacted` is `true` when that body is shown without the people and addresses that it
holds (see `conflu move PAGE --to FOLDER --json`). The `url` is redacted like the address of any page unless you add `--with-users`: it ends at the id
when the title in it holds an address that the title itself hides, and a page in a personal space has the address that names it by its id alone
(`.../pages/viewpage.action?pageId=123456`), because the key of a personal space is the account id of its owner.

`confirmed` says whether the page, as Confluence answered after the move (a move below a page reads it again, a move below a folder takes the answer of the
save), is below the new parent: `true`, or `false` when it is not (the answer was accepted and nothing moved). It is `null` for a dry run, for `action: unchanged`
and when the page could not be read again after the move. That last case is no failure: the move was made, the command still ends with exit code 0, and `message`
(`null` otherwise) and a warning on stderr say what happened and how to look. A move is never repeated because the check after it failed.

### `conflu comment PAGE --json`

```json
{
  "pageId": "123456",
  "dryRun": false,
  "commentId": "4009",
  "payload": {
    "parentCommentId": "4001",
    "body": {"representation": "storage", "value": "<p>Reviewed.</p>"}
  }
}
```

Adding a comment: `commentId` is `null` in a dry run, and `payload` is exactly what is sent: `pageId` and `body` for a comment on the page, `parentCommentId` and `body` for an
answer (`--reply-to`), because the Confluence document says not to give the page for an answer. The other modes of `conflu comment` have their own shapes:
[`--get`](#conflu-comment-page---get-id---json), [`--edit`](#conflu-comment-page---edit-id---json) and [`--resolve` and `--reopen`](#conflu-comment-page---resolve-id---json).

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
  "comment": "October version",
  "minorEdit": false,
  "files": [
    {
      "path": "docs/diagram.png",
      "name": "diagram.png",
      "size": 10,
      "action": "uploaded",
      "attachmentId": "att5001",
      "version": 2,
      "replaces": "att5001",
      "versionFrom": 1,
      "versionTo": 2
    }
  ]
}
```

A file whose name the page has already becomes a new version of that attachment: `replaces` is its id, `versionFrom` the version it was at when the command read the page and `versionTo` the version it
becomes. For a file that is new `replaces` and `versionFrom` are `null` and `versionTo` is 1. `--dry-run` reads the same things and sends nothing: `action` is `would upload`, `attachmentId` and `version` are
`null`. `comment` and `minorEdit` are what the upload sends with every file. When the token may not read the attachments of the page (HTTP 403) and no guard
needs them, the files are sent anyway after a warning on standard error, and `replaces`, `versionFrom` and, before the upload, `versionTo` are `null` (the text shows `?`): nothing is
claimed that was not read. Any other failure of that read (the server is down, the credentials are wrong, a proxy answered) stops the command, in a dry run as well. When a run that attaches several files stops after it uploaded some, nothing is printed on standard output; the error (on standard error, with `--json` as
`{"error": {...}}`) has `details.uploaded` (`path`, `name`, `size`, `attachmentId`, `version` of each file that went), `details.failed` (`path` and `name` of the file that stopped the run) and what the error had of its own,
and its message and hint name the files that went and those that are left. The guard `--if-unchanged-since ''` (empty) is an error that names the option, never "no guard".

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
  "parentId": "123456",
  "parentType": "page",
  "parent": {"id": "123456", "type": "page", "title": "Release notes"},
  "payload": {
    "spaceId": "1001",
    "status": "current",
    "title": "Monthly checklist",
    "parentId": "123456",
    "body": {"representation": "storage", "value": "<p>Run the checks.</p>"}
  }
}
```

`parentType` says what the page is (or in a dry run would be) created below: `page`, `folder`, `whiteboard`, `database` or `embed` (a smart
link); `parent` has its id, type and title (with e-mail addresses and personal links redacted). Both are `null` without `--parent`, when
Confluence puts the page below the home page of the space. `payload` is what is sent: `parentId` is the only place where it names the parent.

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
  "parentType": null,
  "parent": null,
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
run, the labels it would add). `parentType` and `parent` (`id`, `type`, `title`) say what a page that is created sits below, as for
`conflu create`; they are `null` for a page that is updated or created without a parent.

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
      "parentType": "page",
      "parent": {"id": "123456", "type": "page", "title": "Release notes"},
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

A **personal space** is named after its owner and keyed by the owner's account id, so it is a person in the output of these commands. Without `--with-users` it comes out
as an entry with `key` `[hidden]`, `name` `[personal space]`, and an empty `description` and `url` (a space is personal when its `type` is `personal` or its key starts with `~`);
`id`, `type`, `status`, `homepageId` and `created` stay, because they name nobody. The keys of the answer do not change, and `count`, `nextCursor` and `truncated` count the masked
entries like any other. `--with-users`, which `spaces` and `space` have and which is refused when `CONFLUENCE_HIDE_USERS=true`, shows the space as Confluence answers it. Any other
space keeps its key, and the e-mail addresses and personal links in its name and description are redacted (unless `--with-users`).

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

`--search` looks at what is printed, so it cannot find a person's space by the name of the person: `conflu spaces --search alex` lists no personal space, and with `--with-users` it does.

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

For a personal space (without `--with-users`) the same keys come back with `key` `[hidden]`, `name` `[personal space]` and an empty `description` and `url`.

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

For a personal space the answer is `{"space": "[hidden]", "name": "[personal space]"}`: the key that was typed is what is saved in the settings, and `conflu current` prints it as `[hidden]` as well.

### `conflu current --json`

```json
{"space": "ENG"}
```

When no current space is set the JSON becomes `{"space": null}` and the exit code is 1. The key of a personal space is `[hidden]` (the setting keeps the real key).

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

### `conflu config path --json`

```json
{"file": "/home/example/.config/conflu-c-cli/config"}
```

### `conflu config set NAME VALUE --json`

```json
{"saved": "CONFLUENCE_SPACE", "file": "/home/example/.config/conflu-c-cli/config"}
```

`saved` is the name of the setting that was written: the answer never holds the value, and no secret is set this way (the token is saved by `setup-token`).

### `conflu config unset NAME --json`

```json
{"name": "CONFLUENCE_SPACE", "removed": true, "file": "/home/example/.config/conflu-c-cli/config"}
```

`removed` is `false` when the setting was not in the file; the exit code is 0 either way.

All four actions of `config` answer in JSON whenever JSON is on: with `--json`, with `--json-envelope` (the object is the `data`), with `CONFLUENCE_OUTPUT=json` and in the agent profile.
Without JSON they print the text that they always did (`conflu config path` prints just the path).

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
    {"name": "runtime", "status": "ok", "detail": "conflu-c-cli 1.1.0 on Python 3.13.3", "hint": ""},
    {"name": "base url", "status": "ok", "detail": "https", "hint": ""},
    {"name": "space", "status": "warn", "detail": "no current space", "hint": "Run `conflu use KEY` to avoid typing --space."}
  ],
  "cached": false,
  "cachedAt": null
}
```

`cached` is `true` when the online checks (`connection`, `spaces`, `api`, `space`) come from an earlier successful run that was not older than
`--cached AGE`; nothing was asked of Confluence then, and `cachedAt` holds the time of that run (`2026-10-15T08:00:00+00:00`). With `--quick` there is
no `space` check. The check `launcher` is there when the program knows how it was started; a `warn` of it is advice, not a failure.

### `conflu setup --json`

```json
{
  "current": "https://example.atlassian.net/wiki",
  "cloudId": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "gatewayAddress": "https://api.atlassian.com/ex/confluence/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "written": true,
  "dryRun": false,
  "changed": true
}
```

`current` is `CONFLUENCE_BASE_URL` as it is now, a user name or password in it replaced by `********`. `written` is `true` when the configuration file
was changed. `changed` is `true` when the address is not the gateway address yet: it is `true` in a dry run and without an answer of yes (nothing is
written then), and `false` when the address already is the gateway address.

### `conflu commands --json`

```json
{
  "version": "1.1.0",
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
      "api": "v2",
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

`api` is the REST API of Confluence Cloud that the command uses: `v2`, `v1` (only where v2 has no call, with the reason on the [compatibility](compatibility.md) page), `v2+v1`,
`none` (it works on this computer), `named` (`conflu api`: a path that starts with `api/` is v2, one that starts with `rest/` is v1) or `tools` (`conflu mcp`: every tool uses the API of
its command). `conflu help COMMAND` says the same in its line `REST API:`.

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
      "version": "1.1.0",
      "only": "read",
      "invoke": "Run the command: `conflu NAME`, then the positional arguments in the order of `arguments`, ...",
      "exitCodes": [{"code": 0, "names": "OK", "meaning": "The command succeeded (also for a dry run)."}]
    }
  }
}
```

The shape is that of an MCP `tools/list` answer, so that the tools can be handed to a tool-calling model or to an MCP server that wraps
the CLI (`conflu mcp` is one). `--only read` (the default) lists the commands that change nothing and write no file, `--only write` the others
(the commands that change Confluence, and `export` and `download`, which write files on this computer and change nothing in Confluence),
`--only all` both. `--group NAME` (repeat it; the case does not matter; an unknown group is exit code 2) lists only the tools of those groups,
with the text of the whole set, and adds `groups` (the groups asked for) to `_meta.conflu` of the answer.

- **Which commands.** Commands for the person (the token, the settings, the default space, help and the raw `api`) are never listed.
- **`inputSchema`** is JSON Schema: an option `--if-version` is the property `ifVersion`, a positional `PAGE` is `page`, a flag is a
  `boolean`, an option that may be repeated is an `array` of strings, a choice has an `enum`. `required` lists the arguments the command
  insists on.
- **`annotations`** follow MCP: `readOnlyHint`; for a tool that changes Confluence also `destructiveHint` (it replaces, moves or removes)
  and `idempotentHint` (the same call again changes nothing more); a tool that writes files has `readOnlyHint: false`, `destructiveHint: true`
  and `idempotentHint: true`; `openWorldHint` is `false` for the commands that never ask Confluence.
- **`_meta.conflu`** turns a call into a command line: `command`, then the positional `arguments` in order, then every other property
  as its `flag` (a `boolean` only when true, an `array` as the flag repeated; the `array` of a positional argument, such as the files of
  `conflu attach`, is passed item by item, in order), then `alwaysAppend`. The result is JSON on standard
  output; a failure is a non-zero exit code and JSON on standard error. `examples` are command lines that work. The `tools/list` answer of
  `conflu mcp` has the same shape with a lean `_meta.conflu` of `command` and `alwaysAppend` only (the argument table and the examples stay here),
  and the result of its `tools/call` is `{content: [{type: "text", text}], isError}`: the text is what the command printed with `--json`, or on
  failure `{"error": {code, message, hint, exitCode, details}}` ([MCP server](../how-to/mcp-server.md)).
- **The texts** speak of properties and tools (`dryRun`, `conflu_page`), not of flags and commands.

### `conflu version --json`

```json
{
  "name": "conflu-c-cli",
  "version": "1.1.0",
  "python": "3.13.3",
  "platform": "win32",
  "confluenceCloud": {
    "default": "v2",
    "documentsRead": "2026-10-30",
    "apis": {
      "v2": {"base": "/wiki/api/v2", "version": "2.0.0", "guide": "https://developer.atlassian.com/cloud/confluence/rest/v2/intro/"},
      "v1": {"base": "/wiki/rest/api", "version": "1.0.0", "guide": "https://developer.atlassian.com/cloud/confluence/rest/v1/intro/"}
    }
  }
}
```

`confluenceCloud` names the two REST APIs that the CLI is written for (v2 is the default, v1 is used only where v2 has no equivalent), the
version that each OpenAPI document states, and the day the documents were read. [Compatibility](compatibility.md) says how that is checked.

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
`CONFLUENCE_HIDE_USERS=true`. With `--json` that is one compact line when piped and indented on a terminal; without it the
response is always indented. A possible response is therefore whatever that endpoint returns, for example:

```json
{
  "ok": true,
  "user": {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Documentation Reviewer"}
}
```

### `conflu api ... --dry-run --json`

`conflu api METHOD PATH ... --write --dry-run --json` prints the request as one JSON object, and nothing else on standard output:

```json
{"dryRun": true, "method": "PUT", "path": "/api/v2/pages/123456/title", "query": {}, "body": {"status": "current", "title": "Release notes"}}
```

`path` is the path without its query. `query` holds the query string as an object, whether it was written into the path or given as
`--param KEY=VALUE`: a name that occurs once has its value as a string, a name that occurs twice has a list of strings. A request without
a body (a `GET`) has `"body": null`:

```json
{"dryRun": true, "method": "GET", "path": "/rest/api/search", "query": {"cql": "type = page", "limit": "5"}, "body": null}
```

Without `--json` the dry run is the text `Dry run: PUT /api/v2/pages/123456/title; nothing was sent`, followed by the body.

## Folders, whiteboards, databases and smart links

`folder`, `whiteboard`, `database` and `smartlink` show one item of the tree of a space with the same keys; `folder-create` and `smartlink-create`
make one. `type` is what Confluence calls the kind: `folder`, `whiteboard`, `database` or `embed` (a smart link). `author`, `owner` and the author of
the version are `null` until `--with-users`. A list (`--children`; of a database also `--fields`, `--views`, `--entries`) is asked for one at a time and
adds `count`, `nextCursor` (`null` on the last page) and `truncated` next to the list, where `--select` keeps only some keys of every item.

### `conflu folder ID --json`

```json
{
  "id": "7001",
  "type": "folder",
  "title": "Guides",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": null,
  "parentType": null,
  "position": 0,
  "url": "https://example.atlassian.net/wiki/spaces/ENG/folder/7001",
  "version": {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": false, "author": null},
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-01T08:00:00.000Z",
  "author": null,
  "owner": null,
  "ancestors": [{"id": "2001", "type": "page", "title": "Engineering Home"}],
  "count": 2,
  "nextCursor": null,
  "truncated": false,
  "children": [
    {"id": "7011", "type": "folder", "title": "Runbooks", "status": "current", "position": 0},
    {"id": "20011", "type": "page", "title": "Getting started", "status": "current", "position": 1}
  ]
}
```

`parentId` and `parentType` are `null` for an item at the top of the space. `ancestors` (with `--ancestors`) runs from the top of the tree down to the
parent; `children` (with `--children`) is what sits directly below, in the order of the tree. In a personal space, whose key is the account id of its
owner, `spaceKey` is `[hidden]` and the `url` has `[hidden]` in the place of the key (`.../spaces/[hidden]/folder/7001`) unless you add `--with-users`.

### `conflu whiteboard ID --json`

```json
{
  "id": "7021",
  "type": "whiteboard",
  "title": "Architecture sketch",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "7001",
  "parentType": "folder",
  "position": 1,
  "url": "https://example.atlassian.net/wiki/spaces/ENG/whiteboard/7021",
  "version": {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": false, "author": null},
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-01T08:00:00.000Z",
  "author": null,
  "owner": null,
  "ancestors": [{"id": "7001", "type": "folder", "title": "Guides"}]
}
```

The REST API has no call that returns what a whiteboard shows, so there is no content here.

### `conflu database ID --json`

```json
{
  "id": "7041",
  "type": "database",
  "title": "Services",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "7001",
  "parentType": "folder",
  "position": 2,
  "url": "https://example.atlassian.net/wiki/spaces/ENG/database/7041",
  "version": {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": false, "author": null},
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-01T08:00:00.000Z",
  "author": null,
  "owner": null,
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "columns": [
    {"id": "name", "name": "Name", "type": "text"},
    {"id": "tier", "name": "Tier", "type": "select"},
    {"id": "owner", "name": "Owner", "type": "user"},
    {"id": "active", "name": "Active", "type": "checkbox"},
    {"id": "docs", "name": "Docs", "type": "hyperlink"}
  ],
  "entries": [
    {
      "id": "7051",
      "values": {
        "name": "Billing",
        "tier": ["Gold"],
        "owner": ["[hidden]"],
        "active": true,
        "docs": [{"url": "https://example.com/billing", "label": "Billing docs"}]
      }
    }
  ]
}
```

`--entries` gives every entry with the value of each field, keyed by the id of the field; `columns` names the fields. A cell is `null` when nothing is set.
Text and the label and address of a link have e-mail addresses and personal links redacted; the people in a cell are `[hidden]`, one marker each, and
with `--with-users` they are objects with `accountId`, `displayName` and `email`. A select field is the list of the chosen labels, a checkbox is `true` or
`false`, a number or a date is the text that Confluence gives. A field that Confluence derives from other content has no value. The cursor belongs to
the `--limit` that made it. `--fields` and `--views` have `fields[]` and `views[]` in the place of `columns` and `entries`:

```json
{
  "id": "7041",
  "type": "database",
  "title": "Services",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "7001",
  "parentType": "folder",
  "position": 2,
  "url": "https://example.atlassian.net/wiki/spaces/ENG/database/7041",
  "version": {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": false, "author": null},
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-01T08:00:00.000Z",
  "author": null,
  "owner": null,
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "fields": [
    {"id": "name", "name": "Name", "type": "text", "description": "What the service is called", "options": []},
    {"id": "tier", "name": "Tier", "type": "select", "description": null, "options": ["Gold", "Silver", "Bronze"]}
  ]
}
```

`views[]` has `id`, `name` and `type` (`table`, `gallery`, `board`, `calendar` or `timeline`).

### `conflu smartlink ID --json`

```json
{
  "id": "7061",
  "type": "embed",
  "title": "Roadmap",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "7001",
  "parentType": "folder",
  "position": 3,
  "url": "https://example.atlassian.net/wiki/spaces/ENG/embed/7061",
  "version": {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": false, "author": null},
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-01T08:00:00.000Z",
  "author": null,
  "owner": null,
  "embedUrl": "https://example.com/roadmap",
  "ancestors": [{"id": "7001", "type": "folder", "title": "Guides"}]
}
```

`embedUrl` is the address that the smart link shows, `null` when it shows none; a personal link is redacted unless `--with-users`.

### `conflu folder-create --json`

```json
{
  "action": "created",
  "dryRun": false,
  "folderId": "7090",
  "title": "Runbooks 2026",
  "spaceKey": "ENG",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/folder/7090",
  "parentId": "7001",
  "parentType": "folder",
  "parent": {"id": "7001", "type": "folder", "title": "Guides"},
  "payload": {"spaceId": "1001", "title": "Runbooks 2026", "parentId": "7001"}
}
```

In a dry run `folderId` and `url` are `null`; without `--parent`, `parentId`, `parentType` and `parent` are `null` and `payload` has no `parentId`.
`payload` is exactly what is sent. Confluence does not forbid two folders with one title, and the dry run cannot know whether the title is taken.
In a personal space (`--space ~KEY`, a key that you typed yourself) `spaceKey` is `[hidden]` and the `url` has `[hidden]` in the place of the key: these commands
have no `--with-users`, and the key is the account id of the owner.

### `conflu smartlink-create --json`

```json
{
  "action": "created",
  "dryRun": true,
  "smartlinkId": null,
  "title": "Roadmap 2026",
  "spaceKey": "ENG",
  "url": null,
  "embedUrl": "https://example.com/roadmap",
  "parentId": null,
  "parentType": null,
  "parent": null,
  "payload": {"spaceId": "1001", "title": "Roadmap 2026", "embedUrl": "https://example.com/roadmap"}
}
```

`embedUrl` is the address as it was given. After a real run `smartlinkId` and `url` are set; `parentId`, `parentType` and `parent` are as in `conflu folder-create`.

### `conflu move PAGE --to FOLDER --json`

Below a folder, a whiteboard, a database or a smart link a page is moved by saving it again with a new parent: the next version, the body as it is. `payload`
is that whole request, and `versionTo` is `versionFrom` plus one (in a dry run too, because that is the version the move would save). The body may hold
mentions and addresses of people: without `--with-users` the printed `payload` has the account ids blanked and the addresses redacted in the body and the
title, and `payloadRedacted` says so (`true`); what is sent is always the page as it is. With `--with-users` the payload is shown exactly (refused when
`CONFLUENCE_HIDE_USERS=true`). Without `--with-users` the `url` is redacted like the address of any page (see `conflu move PAGE --json`). Confluence
merges the save into an unpublished draft of the page, if somebody has one, and may replace that draft; nothing in the answer can tell that there is one.

```json
{
  "action": "moved",
  "dryRun": true,
  "pageId": "2005",
  "title": "Plain page",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/2005/Plain+page",
  "versionFrom": 1,
  "versionTo": 2,
  "lost": [],
  "labels": [],
  "payload": {
    "id": "2005",
    "status": "current",
    "title": "Plain page",
    "parentId": "7001",
    "body": {"representation": "storage", "value": "<p>Just a paragraph &amp; text.</p>"},
    "version": {"number": 2, "message": "Moved below Guides"}
  },
  "payloadRedacted": false,
  "target": {"id": "7001", "type": "folder", "title": "Guides"},
  "confirmed": null,
  "message": null
}
```

<!-- json:structure -->
## Blog posts

A blog post is read, listed, created and changed like a page, and its JSON has the keys of the page's, with `blogpostId` where a page has `pageId`. A blog post has no
parent, no ancestors and no owner, and its title need not be unique. People stay hidden as everywhere: the title and the address are redacted (an address
that ends in a title with an e-mail address in it ends at the id instead), and `author` is `null` until `--with-users`.

### `conflu blogposts --json`

```json
{
  "space": "ENG",
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "blogposts": [
    {
      "id": "7101",
      "title": "Release 2026.10 is out",
      "status": "current",
      "spaceId": "1001",
      "version": 3,
      "created": "2026-10-12T09:00:00.000Z",
      "updated": "2026-10-14T09:00:00.000Z",
      "url": "https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out"
    }
  ]
}
```

`space` is `null` for a list of the whole site, and `[hidden]` for a personal space (also for the `--space ~KEY` that you typed): its key is the account id of its owner. `nextCursor` is `null` on the last part. `--select a,b.c` keeps only those keys of every blog post.

### `conflu blogpost ID --json`

```json
{
  "id": "7101",
  "title": "Release 2026.10 is out",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out",
  "version": {
    "number": 3,
    "created": "2026-10-14T09:00:00.000Z",
    "message": "Added the known issues",
    "minorEdit": false,
    "author": null
  },
  "created": "2026-10-12T09:00:00.000Z",
  "updated": "2026-10-14T09:00:00.000Z",
  "labels": ["release", "news"],
  "author": null,
  "body": {
    "format": "markdown",
    "value": "# Release 2026.10\n\nThanks to @user.\n\n## Known issues\n\nNone so far.",
    "dropped": ["mention"],
    "section": null,
    "truncated": false,
    "totalChars": null
  },
  "comments": [
    {
      "id": "7151",
      "kind": "footer",
      "updated": "2026-10-13T10:00:00.000Z",
      "parentId": null,
      "resolution": null,
      "author": null,
      "body": {"format": "markdown", "value": "Great news.", "dropped": []}
    }
  ]
}
```

`comments` appears with `--comments`: the footer comments first, then the inline ones, each conversation as its first comment followed by its replies (`parentId` names
the comment that a reply answers; `resolution` is set on inline comments). `body` is `null` with `--no-body`, and `--section` and `--max-chars` work as they do for `conflu page`.

### `conflu blogpost ID --outline --json`

```json
{
  "id": "7101",
  "title": "Release 2026.10 is out",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out",
  "version": {
    "number": 3,
    "created": "2026-10-14T09:00:00.000Z",
    "message": "Added the known issues",
    "minorEdit": false,
    "author": null
  },
  "created": "2026-10-12T09:00:00.000Z",
  "updated": "2026-10-14T09:00:00.000Z",
  "labels": ["release", "news"],
  "author": null,
  "body": null,
  "outline": [
    {"index": 1, "level": 1, "title": "Release 2026.10", "chars": 170},
    {"index": 2, "level": 2, "title": "Known issues", "chars": 64}
  ]
}
```

### `conflu blogpost-create --json`

```json
{
  "action": "created",
  "dryRun": false,
  "blogpostId": "7110",
  "title": "Release 2026.11 is out",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/blog/2026/11/15/7110/Release+2026.11+is+out",
  "versionFrom": null,
  "versionTo": 1,
  "lost": [],
  "labels": ["release", "news"],
  "payload": {
    "spaceId": "1001",
    "status": "current",
    "title": "Release 2026.11 is out",
    "body": {"representation": "storage", "value": "<p>The November release is out.</p>"}
  }
}
```

In a dry run `blogpostId` and `url` are `null` and nothing was sent; `payload` is what a real run sends. The labels are added with a second request: when that fails the blog post is
there, and the error names its id.

### `conflu blogpost-update --json`

```json
{
  "action": "updated",
  "dryRun": true,
  "blogpostId": "7101",
  "title": "Release 2026.10 is out",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out",
  "versionFrom": 3,
  "versionTo": 4,
  "lost": [],
  "labels": [],
  "payload": {
    "id": "7101",
    "status": "current",
    "title": "Release 2026.10 is out!",
    "body": {"representation": "storage", "value": "<h1>Release 2026.10</h1><p>Thanks to <ac:link><ri:user ri:account-id=\"hidden\" /></ac:link>.</p>"},
    "version": {"number": 4}
  },
  "payloadRedacted": true
}
```

`action` is `unchanged` (and `payload` `null`) when the title and the body are already as asked. `payload` always holds the whole body, also for a change of the title, because the API has no
call for the title only. The body may hold mentions and addresses of people: without `--with-users` the printed `payload` has the account ids blanked and the addresses redacted
in the body and the title, and `payloadRedacted` says so (`true`); the request that is sent has them, so that mentions survive. With `--with-users` the payload is shown exactly
(refused when `CONFLUENCE_HIDE_USERS=true`). `lost` names what a replacement from Markdown dropped (only with `--force`).

### `conflu blogpost ID --body-only --out FILE --json`

The body of the blog post goes into the file as UTF-8, exactly the text that `--body-only` would have printed (people hidden unless `--with-users`), and the answer is this object
instead of the text: `file` is the path as it was given and `bytes` the size of the file. A file that exists is not replaced without `--force`, and `--out` needs `--body-only`.

```json
{
  "file": "post.xml",
  "bytes": 376
}
```

<!-- json:blogposts -->
## Earlier versions, differences and restoring

### `conflu page PAGE --version N --json`

An earlier version of one page, as it was saved: the title, the body and the version of that time. What belongs to the page and not to a version (labels, status, the parent) is
the page's now. The keys are those of `conflu page PAGE --json`, with `version.current` (`false` unless `N` is the current version) and `currentVersion` (the number of the current one).
There are no `ancestors` and no `comments` with `--version`: both are those of now, so the options are refused together.

```json
{
  "id": "123456",
  "title": "Release notes",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "2001",
  "parentType": "page",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "version": {
    "number": 2,
    "created": "2026-10-05T10:00:00.000Z",
    "message": "",
    "minorEdit": false,
    "author": null,
    "current": false
  },
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-05T10:00:00.000Z",
  "labels": ["release", "notes"],
  "author": null,
  "owner": null,
  "currentVersion": 3,
  "body": {
    "format": "markdown",
    "value": "# Release notes\n\nContact @user.\n\n- First",
    "dropped": ["mention"],
    "section": null,
    "truncated": false,
    "totalChars": null
  }
}
```

A version that the page does not have is a not-found error (exit code 4) whose hint names the version the page is at and `conflu versions PAGE`.

### `conflu page PAGE... --json`

Several pages in one call, read with one request. `count` is the number of pages in `pages[]`, which come in the order they were asked for, each page once. A page that is not there (or whose
`--section` it lacks) is an entry of `errors[]` with `ref` as it was given and the `code` of the error, the exit code is that of the first one (4 for a page that is not found), and the pages that
were found are still printed. The request for several pages gives no labels: `labels` is `null` in every page, and `conflu page PAGE` for one page has them. Every other key is as for one page,
and options such as `--outline`, `--max-chars` and `--attachments` apply to every page. `--version` and `--raw` are for one page. `hint` may be empty.

```json
{
  "count": 1,
  "pages": [
    {
      "id": "123456",
      "title": "Release notes",
      "status": "current",
      "spaceId": "1001",
      "spaceKey": "ENG",
      "parentId": "2001",
      "parentType": "page",
      "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
      "version": {
        "number": 3,
        "created": "2026-10-10T09:00:00.000Z",
        "message": "Added the October notes",
        "minorEdit": false,
        "author": null
      },
      "created": "2026-10-01T08:00:00.000Z",
      "updated": "2026-10-10T09:00:00.000Z",
      "labels": null,
      "author": null,
      "owner": null,
      "body": null,
      "outline": [
        {"index": 1, "level": 1, "title": "Release notes", "chars": 69}
      ]
    }
  ],
  "errors": [
    {
      "ref": "999",
      "code": "NOT_FOUND",
      "message": "Not found: GET /api/v2/pages/999",
      "hint": "Confluence also answers 404 for what the account may not see."
    }
  ]
}
```

### `conflu page PAGE --attachments --json`

The files attached to the page, with one more request: `attachments[]` (the name in `title`, its type and size in bytes) and `attachmentTotal`. File names and types are redacted like any text unless
`--with-users` is given: a name or a type can hold an e-mail address. Without the option neither key is printed.

```json
{
  "id": "123456",
  "title": "Release notes",
  "status": "current",
  "spaceId": "1001",
  "spaceKey": "ENG",
  "parentId": "2001",
  "parentType": "page",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "version": {
    "number": 3,
    "created": "2026-10-10T09:00:00.000Z",
    "message": "Added the October notes",
    "minorEdit": false,
    "author": null
  },
  "created": "2026-10-01T08:00:00.000Z",
  "updated": "2026-10-10T09:00:00.000Z",
  "labels": ["release", "notes"],
  "author": null,
  "owner": null,
  "body": {
    "format": "markdown",
    "value": "# Release notes\n\nFirst",
    "dropped": [],
    "section": null,
    "truncated": false,
    "totalChars": null
  },
  "attachments": [
    {"id": "att5001", "title": "diagram.png", "mediaType": "image/png", "size": 10},
    {"id": "att5002", "title": "notes.txt", "mediaType": "text/plain", "size": 12}
  ],
  "attachmentTotal": 2
}
```

### `conflu diff PAGE --json`

A unified diff of the Markdown of two versions: by default the current version against the one before it. The Markdown is the reading copy that hides people (a mention is `@user`, an
e-mail address `[email]`), so the diff names nobody. `from` and `to` describe the two versions (`message` and `title` are redacted; `current` says whether it is the current version of the page);
`from` is `null` when there is nothing to compare: for a page with one version, and for `--to 1` on a page with more (version 1 has nothing before it; `--from 1` compares it with the current version). `identical` says that the Markdown of the two reads the same, and `sourceIdentical` that their storage format is the same
too: versions that differ only in what Markdown cannot say (`dropped`: macros, mentions, layouts) are identical here and not in `sourceIdentical`. `added` and `removed` count lines. `truncated` and
`totalChars` tell that `--max-chars` cut the diff (and how long it was). `note` is `null` or the sentence that the text prints in the place of a diff ("Page 123456 has one version only: there
is nothing to compare." or "Version 1 is the first version of page 123456: nothing came before it, so there is nothing to compare. ..."); `diff` is empty then. `identical` is `false` for the second
sentence, because nothing was compared.

```json
{
  "pageId": "123456",
  "title": "Release notes",
  "from": {
    "number": 2,
    "created": "2026-10-05T10:00:00.000Z",
    "message": "",
    "title": "Release notes",
    "current": false
  },
  "to": {
    "number": 3,
    "created": "2026-10-10T09:00:00.000Z",
    "message": "Added the October notes",
    "title": "Release notes",
    "current": true
  },
  "identical": false,
  "added": 2,
  "removed": 1,
  "truncated": false,
  "totalChars": null,
  "dropped": ["macro:toc", "mention", "redacted-text"],
  "sourceIdentical": false,
  "note": null,
  "diff": "--- version 2\t2026-10-05T10:00:00.000Z\n+++ version 3 (current)\t2026-10-10T09:00:00.000Z\n@@ -1,5 +1,6 @@\n # Release notes\n \n-Contact @user.\n+Contact @user or write to [email].\n \n - First\n+- Second"
}
```

### `conflu restore PAGE --json`

Restoring makes a NEW version of the page with the body (and with `--restore-title` the title) of an earlier one; the versions in between stay in the history. `restoredVersion` is the version that
was brought back, `versionFrom` the version the page was at, and `versionTo` the version that the restore made (in a dry run the one it would make; after a real run the one the page is at
when it was read back, which is a later one if somebody saved meanwhile). `added` and `removed` count the lines that the restored Markdown adds to and takes from the current one. `payload` is
the request that is sent: it names the version and holds no content, since Confluence makes the new version itself, so mentions and macros come back as they were.

```json
{
  "action": "restored",
  "dryRun": true,
  "pageId": "123456",
  "title": "Release notes",
  "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
  "restoredVersion": 1,
  "versionFrom": 3,
  "versionTo": 4,
  "added": 1,
  "removed": 4,
  "payload": {
    "operationKey": "restore",
    "params": {"versionNumber": 1, "message": "Restored version 1", "restoreTitle": false}
  }
}
```

### `conflu page PAGE --body-only --out FILE --json`

The body of the page (or of the version that `--version` names) goes into the file as UTF-8, exactly the text that `--body-only` would have printed (people hidden unless `--with-users`), and the answer
is this object instead of the text: `file` is the path as it was given and `bytes` the size of the file. A file that exists is not replaced without `--force`, never the settings file of the CLI, and
`--out` needs `--body-only`. It writes a file on this computer and changes nothing in Confluence.

```json
{
  "file": "page.xml",
  "bytes": 209
}
```

<!-- json:history -->

### `conflu comment PAGE --get ID --json`

```json
{
  "pageId": "123456",
  "id": "4003",
  "kind": "inline",
  "updated": "2026-10-03T09:00:00.000Z",
  "version": 1,
  "parentId": null,
  "resolution": "open",
  "author": null,
  "authorRef": "a-97d57512",
  "byMe": true,
  "body": {"format": "markdown", "value": "Check this phrase.", "dropped": []}
}
```

One comment, the keys of `conflu comments PAGE --json` and `version`: the number that `--if-version` of a change compares. The comment must belong to `PAGE`; a comment of another page is "not found" (exit code 4), like
one that does not exist. Its `kind` is found by asking the footer comments first and, when Confluence answers 404, the inline comments. `--format markdown|text|storage` is the format of `body.value`;
`--with-users` fills `author` and shows mentions, as in `conflu comments`.

### `conflu comment PAGE --edit ID --json`

```json
{
  "action": "updated",
  "dryRun": true,
  "pageId": "123456",
  "commentId": "4001",
  "kind": "footer",
  "versionFrom": 1,
  "versionTo": 2,
  "updated": "2026-10-02T10:00:00.000Z",
  "resolution": null,
  "byMe": true,
  "diff": "--- current\n+++ new\n@@ -1 +1 @@\n-Looks good.\n+Looks good to me.",
  "lost": [],
  "warnings": [],
  "payload": {
    "version": {"number": 2},
    "body": {"representation": "storage", "value": "<p>Looks good to me.</p>"}
  },
  "payloadRedacted": false
}
```

Replaces the text of a comment; the comment is read first, and a comment is never deleted. `action` is `updated`, or `unchanged` when the new text is the comment's own: nothing is sent, `payload` and `diff` are `null` and
`versionTo` is `versionFrom`. `versionTo` is the version that the change saves (the current one plus one), in a dry run too. `updated` is when the comment was saved last: by this change after a real run, else as it is now.
`resolution` is the state of an inline comment, which a change of its text keeps (`null` for a footer comment); the payload of an inline comment carries it as `resolved`. `byMe` is filled in a dry run only: whether you wrote the
comment, because Confluence refuses a change of somebody else's text (exit code 5; `warnings` says so before). `diff` is a unified diff of the old and the new text as Markdown with people hidden, `lost[]` what a replacement from
Markdown drops from the old text (only with `--force`: mentions and macros), `warnings[]` what to know before the real run. `payload` is exactly what is sent, the same in the dry run and in the real run; `payloadRedacted` is `false`
for an edit: the text in it is the one that you gave. A comment that has moved on since you read it is exit code 3 (`--if-version`, `--if-unchanged-since`, or Confluence's own answer HTTP 409).

### `conflu comment PAGE --resolve ID --json`

```json
{
  "action": "resolved",
  "dryRun": true,
  "pageId": "123456",
  "commentId": "4003",
  "kind": "inline",
  "versionFrom": 1,
  "versionTo": 2,
  "updated": "2026-10-03T09:00:00.000Z",
  "resolution": "resolved",
  "byMe": null,
  "diff": null,
  "lost": [],
  "warnings": [],
  "payload": {
    "version": {"number": 2},
    "body": {"representation": "storage", "value": "<p>Check this phrase.</p>"},
    "resolved": true
  },
  "payloadRedacted": false
}
```

`--resolve` and `--reopen` print this shape; `action` is `resolved` or `reopened`, or `unchanged` when the comment is in that state already (nothing is sent). Only an inline comment can be resolved: a footer comment is a usage
error (exit code 2), a dangling one (the text it was made on is gone) is refused. The change saves the comment's own text again with `resolved` true or false, so `payload.body` is the text of the comment as Confluence has it: the
printed `payload` leaves out the people and addresses in it, and `payloadRedacted` is `true` then (what is sent is the comment as it is); `--with-users` prints it as it is (refused when `CONFLUENCE_HIDE_USERS=true`). `byMe` and
`diff` are `null`, `updated` is as above, and `resolution` is the state that the change gives (or that the comment has, when nothing changes). The guards of `--edit` apply too.

<!-- json:comments -->

### `conflu labels --space KEY --json`

```json
{
  "space": "ENG",
  "spaceId": "1001",
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "labels": [
    {"name": "adr", "prefix": "global"},
    {"name": "notes", "prefix": "global"}
  ]
}
```

The labels that the content of a space (pages, blog posts) carries, by name, not the labels of the space itself. `space` is `[hidden]` for a personal space (also for the `--space ~KEY` that you typed): its key is the account id of its owner; `spaceId` stays. One piece at a time (`--limit`, default 25, `--cursor` with the `nextCursor` of the piece before) or all of them
(`--all`; then `nextCursor` is `null` and `truncated` is `true` when the list was cut at 20000 labels). `nextCursor` is `null` on the last piece. `--select name` keeps only those (dotted) keys of every label. The labels of one
page are `conflu labels PAGE --json`.

<!-- json:labels -->
## Attachments: one file, its versions, and the text of a document

### `conflu attachment ID --json`

```json
{
  "id": "att5101",
  "title": "plan.txt",
  "mediaType": "text/plain",
  "size": 59,
  "version": 3,
  "created": "2026-10-05T09:00:00.000Z",
  "updated": "2026-10-09T14:00:00.000Z",
  "pageId": "123456",
  "blogPostId": null,
  "downloadLink": "/download/attachments/123456/plan.txt?version=3&api=v2",
  "comment": "The plan for the October release",
  "versions": [
    {"number": 3, "created": "2026-10-09T14:00:00.000Z", "message": "", "minorEdit": true, "size": 59, "author": null},
    {"number": 2, "created": "2026-10-07T09:30:00.000Z", "message": "Added the contact", "minorEdit": false, "size": 63, "author": null}
  ],
  "nextCursor": "2",
  "labels": [
    {"name": "draft", "prefix": "global"},
    {"name": "plan", "prefix": "global"}
  ]
}
```

The properties of one attachment are those of an item of [`conflu attachments`](#conflu-attachments-page---json); `downloadLink` is the address as Confluence gives it, relative to the wiki, and
nothing the CLI fetches from. `versions` and `nextCursor` appear with `--versions` (newest first; `--limit`, `--cursor` and `--all` page through them), `labels` with `--labels`. The answer that lists
the versions has no size, so it is asked for with one request for each of the first 50 versions listed: `size` is `null` for the others, and where a version cannot be read. `author` is a person, so it is `null`
unless you add `--with-users` (then `{"accountId", "displayName", "email"}`); the same option shows `title`, `comment`, `mediaType` and `downloadLink` as they are, where they are otherwise redacted like any text.
`--select a,b.c` and `--format` work on the list of `--versions` (or of `--labels` when only that was asked for). As text they print one list, so with `--versions` and `--labels` together they are refused (exit code 2)
unless `--json` is given: then `--select` trims the versions and `labels` stays as it is.

### `conflu download ... --text --json`

```json
{
  "dryRun": false,
  "count": 1,
  "files": [
    {
      "attachmentId": "att5102",
      "name": "spec.docx",
      "mediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "size": 455,
      "version": 1,
      "kind": "document",
      "action": "read",
      "text": "# Specification\nThe scope is small. Questions go to [email].\n## Goals\n- faster\n- simpler\nOwner | Release Team",
      "truncated": false,
      "totalChars": 109,
      "hint": null
    }
  ]
}
```

With `--text` nothing is saved: the text of every file is printed instead. `kind` is `text` for a text file (by its type and its name), `document` for a Word, Excel or PowerPoint file, and `other` for
anything else, which has no `text`, only its properties and a `hint` that points to the plain `download`. `action` is `read`; `not text` for a file that could not be read as text (its `hint` says why:
damaged, protected with a password, refused as unsafe, binary where the type said text, or empty); `would read` and `too large` with `--dry-run`. `text` is `null` where there is none. `totalChars` is the
length of the whole text, after the e-mail addresses, the mentions and the characters that a terminal would obey were taken out; `truncated` says that `text` was cut, at the end of a paragraph, after `--max-chars`
characters (20000 by default). `--version N` reads that version of one attachment. `name` is redacted unless you add `--with-users`, like the text. A file that arrives longer than `--max-bytes` (25 MiB by default)
is refused, whatever Confluence listed as its size, and nothing of it is decoded.

<!-- json:attachments -->
## What you may do, who may see content, who may use a space

`conflu permissions`, `conflu restrictions` and `conflu space-access` only read. `target` says what an answer is about: `id` and `type` (what Confluence calls
it: `page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed` for a smart link, `footer-comment`, `inline-comment`, `attachment`, `custom` for custom
content, or `space`) and, for a space only, `key` and `title`; the others are `null`. A personal space is named after its owner, so without `--with-users`
(`space-access` only; `permissions` has no such option) its `key` is `[hidden]` and its `title` `[personal space]`, as in `conflu spaces`.

No account id, group id or name of a person is in an answer unless `--with-users` was given (and it is refused when `CONFLUENCE_HIDE_USERS=true`): then
`createdBy`, `permissions` and `principals` are `null` and `usersShown` is `false`, and the counts are all that is said about who. `count` is the number of
principals in this answer (`null` without `--with-users`), `nextCursor` is `null` on the last piece of the list, and a cursor is a position in a list that
is sorted the same way every time. `notes` are sentences that qualify the answer. `--select` keeps only some keys of every principal.

### `conflu permissions [ID] --json`

What the account of the token may do with content (`ID`), or with `--space` in a space. `operations` is what is allowed, in a fixed order (by operation, then by
what it is done to), and `can` says yes or no for `read`, `update` and `delete` and for every other operation that is allowed. `create` can be allowed for
a comment and an attachment and not for a page: `targetType` says what an operation is done to.

```json
{
  "target": {"id": "123456", "type": "page", "key": null, "title": null},
  "operations": [
    {"operation": "archive", "targetType": "page"},
    {"operation": "copy", "targetType": "page"},
    {"operation": "create", "targetType": "attachment"},
    {"operation": "create", "targetType": "comment"},
    {"operation": "delete", "targetType": "page"},
    {"operation": "read", "targetType": "page"},
    {"operation": "restrict_content", "targetType": "page"},
    {"operation": "update", "targetType": "page"}
  ],
  "can": {"read": true, "update": true, "delete": true, "archive": true, "copy": true, "create": true, "restrict_content": true}
}
```

With `--only read,update,create` (here in a space) `operations` keeps those and `can` answers for exactly those names, in the order given; `update` is `false` here and has
no entry in `operations`, because it is not allowed:

```json
{
  "target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"},
  "operations": [
    {"operation": "create", "targetType": "attachment"},
    {"operation": "create", "targetType": "blogpost"},
    {"operation": "create", "targetType": "comment"},
    {"operation": "create", "targetType": "page"},
    {"operation": "read", "targetType": "space"}
  ],
  "can": {"read": true, "update": false, "create": true}
}
```

### `conflu restrictions ID --json`

The restriction that is set on the content itself, and its direct permissions: `state` is `OPEN`, `EDIT_RESTRICTED` or `VIEW_RESTRICTED`, `meaning` says in words what the
document says it means (`null` for a state that the CLI does not know), `createdAt` is when it was set (`null` for `OPEN`) and `createdBy` the account id of who set it
(only with `--with-users`). `counts` is how many users and groups hold `read` and `update`, over all the direct permissions, and `total` how many there are. `truncated`
is `true` when the lists were cut at their limit, 20000 entries, and the counts are of what was read. A restriction that a parent sets is not in these calls (a note says so).

```json
{
  "target": {"id": "123456", "type": "page", "key": null, "title": null},
  "state": "VIEW_RESTRICTED",
  "meaning": "Viewing and editing are restricted to the users and groups that are granted it.",
  "createdAt": "2026-10-03T09:00:00.000Z",
  "createdBy": null,
  "counts": {"read": {"user": 2, "group": 1}, "update": {"user": 1, "group": 1}},
  "total": 5,
  "usersShown": false,
  "count": null,
  "nextCursor": null,
  "truncated": false,
  "permissions": null,
  "notes": ["Only what is set on the content itself is shown: a restriction that a parent page or folder sets is not in these calls, so OPEN does not mean that everybody may read it."]
}
```

With `--with-users` (here with `--limit 2`) `createdBy` and the principals are there, sorted by operation, kind and id. A principal is a user (`principalId` is an account id) or a
group (a group id; it is not named):

```json
{
  "target": {"id": "123456", "type": "page", "key": null, "title": null},
  "state": "VIEW_RESTRICTED",
  "meaning": "Viewing and editing are restricted to the users and groups that are granted it.",
  "createdAt": "2026-10-03T09:00:00.000Z",
  "createdBy": "5b10ac8d82e05b22cc7d4ef5",
  "counts": {"read": {"user": 2, "group": 1}, "update": {"user": 1, "group": 1}},
  "total": 5,
  "usersShown": true,
  "count": 2,
  "nextCursor": "2",
  "truncated": false,
  "permissions": [
    {
      "operation": "read",
      "principalType": "group",
      "principalId": "00000000-0000-4000-8000-0000000000a1",
      "createdAt": "2026-10-03T09:00:00.000Z",
      "createdBy": "5b10ac8d82e05b22cc7d4ef5"
    },
    {
      "operation": "read",
      "principalType": "user",
      "principalId": "5b10ac8d82e05b22cc7d4ef5",
      "createdAt": "2026-10-03T09:00:00.000Z",
      "createdBy": "5b10ac8d82e05b22cc7d4ef5"
    }
  ],
  "notes": ["Only what is set on the content itself is shown: a restriction that a parent page or folder sets is not in these calls, so OPEN does not mean that everybody may read it."]
}
```

### `conflu space-access [SPACE] --json`

How a space gives access. `mode` is the role mode of the site (`PRE_ROLES`, `ROLES_TRANSITION` or `ROLES`; `null` when the site reports none) and `models` says which of
`permissions` and `roles` were read. `permissionCounts` says how many users, groups and roles hold each operation on each kind of thing, `roleCounts` how many users, groups
and access classes (audiences that are no single person) have each role, with its name; each of the two is `null` (and so is its total) when its model was not read. A role
that cannot be named is shown by its id. `total` is the assignments of the models that were read.

```json
{
  "target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"},
  "mode": "ROLES_TRANSITION",
  "models": ["permissions", "roles"],
  "permissionTotal": 7,
  "permissionCounts": [
    {"operation": "administer", "targetType": "space", "user": 1, "group": 0, "role": 0},
    {"operation": "create", "targetType": "comment", "user": 0, "group": 1, "role": 0},
    {"operation": "create", "targetType": "page", "user": 1, "group": 1, "role": 0},
    {"operation": "read", "targetType": "space", "user": 2, "group": 1, "role": 0}
  ],
  "roleTotal": 5,
  "roleCounts": [
    {"roleId": "00000000-0000-4000-8000-0000000000b1", "name": "Admin", "type": "SYSTEM", "user": 1, "group": 0, "accessClass": 0},
    {"roleId": "00000000-0000-4000-8000-0000000000b2", "name": "Contributor", "type": "SYSTEM", "user": 0, "group": 1, "accessClass": 0},
    {"roleId": "00000000-0000-4000-8000-0000000000b3", "name": "Viewer", "type": "SYSTEM", "user": 1, "group": 1, "accessClass": 1}
  ],
  "usersShown": false,
  "total": 12,
  "count": null,
  "nextCursor": null,
  "truncated": false,
  "principals": null,
  "notes": ["The site is moving from permissions to roles (ROLES_TRANSITION): both are shown."]
}
```

With `--with-users` (here with `--limit 3`) `principals` lists who holds what, permission assignments first and then role assignments. `principalType` is `user`, `group`, `role` or
`access_class`. A row of the permission model has `operation` and `targetType`, one of the role model has `roleId` and `roleName`; the keys that do not apply are `null`.

```json
{
  "target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"},
  "mode": "ROLES_TRANSITION",
  "models": ["permissions", "roles"],
  "permissionTotal": 7,
  "permissionCounts": [{"operation": "administer", "targetType": "space", "user": 1, "group": 0, "role": 0}],
  "roleTotal": 5,
  "roleCounts": [{"roleId": "00000000-0000-4000-8000-0000000000b1", "name": "Admin", "type": "SYSTEM", "user": 1, "group": 0, "accessClass": 0}],
  "usersShown": true,
  "total": 12,
  "count": 3,
  "nextCursor": "3",
  "truncated": false,
  "principals": [
    {
      "model": "permissions",
      "principalType": "user",
      "principalId": "5b10ac8d82e05b22cc7d4ef5",
      "operation": "administer",
      "targetType": "space",
      "roleId": null,
      "roleName": null
    }
  ],
  "notes": ["The site is moving from permissions to roles (ROLES_TRANSITION): both are shown."]
}
```

<!-- json:access -->

### `conflu watching --json`

Whether the account of the token watches a page, a blog post or other content (named by its id), or a space (named by its key). `target.type` is what
Confluence calls the content (`page`, `blogpost`, `folder` ...) or `space`; `key` and `title` are set for a space only, as `conflu spaces` prints them. The title is
redacted like every title. A personal space is named after its owner and keyed by the owner's account id, so its `key` is `[hidden]` and its `title` `[personal space]`
(`conflu watching` has no `--with-users`; the call still names the real key). Only your own watch is shown: no person is in the answer.

```json
{
  "target": {"id": "2002", "type": "page", "key": null, "title": null},
  "watching": false
}
```

```json
{
  "target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"},
  "watching": true
}
```

### `conflu watch --json`

`action` is `watched` or `unwatched` (what was done, or in a dry run what would be done), or `unchanged` when the watch is as asked already and nothing was
sent. `wasWatching` is the state before; `watching` is the state after, as Confluence says it when the status is read again (`null` when that read failed;
in a dry run, and when `unchanged`, the state as it is). `confirmed` says that the status read back is the one asked for: `null` when nothing was written
or the read failed, `false` when Confluence still shows the old state. In both of those cases the change was made, the exit code is 0, `message` says what to
check (`conflu watching ...`) and standard error has the same text as a warning; `message` is `null` otherwise. `call` is the REST call that is sent, or in a
dry run would be, written as the compatibility page writes it (`null` when `unchanged`): `POST` starts watching, `DELETE` stops, and only your own watch is
ever the target.

```json
{
  "action": "watched",
  "dryRun": true,
  "target": {"id": "2002", "type": "page", "key": null, "title": null},
  "wasWatching": false,
  "watching": false,
  "confirmed": null,
  "call": "POST /rest/api/user/watch/content/{contentId}",
  "message": null
}
```

```json
{
  "action": "watched",
  "dryRun": false,
  "target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"},
  "wasWatching": false,
  "watching": true,
  "confirmed": true,
  "call": "POST /rest/api/user/watch/space/{spaceKey}",
  "message": null
}
```

<!-- json:watches -->

### `conflu users search TEXT --json`

The people whose name holds the text, found with the older API's user search (the API v2 has none). Both `users` actions are refused without `--with-users` and always
under `CONFLUENCE_HIDE_USERS=true`: this is the one command where people are the point. `query` is the words as they were normalised, `cql` the query that was sent:
the text sits in one CQL string with its double quote and backslash escaped, so it stays a text. `total` is how many people Confluence says fit, `count` how many
are in `users`, `start` the index of the first, `nextStart` where the next request goes on (`null` on the last one, and with `--all`), `truncated` that `--all` stopped
at its limit (5000). A person is `accountId`, `displayName` (the public name when the person hides their name), `email` (only when Confluence returns one: it depends on
the privacy setting of the person) and `accountType` (`atlassian`, `app` ...); `null` is what Confluence does not say. With `--select` only those (dotted) keys of every person.

```json
{
  "query": "alex",
  "cql": "user.fullname ~ \"alex\"",
  "total": 1,
  "count": 1,
  "start": 0,
  "nextStart": null,
  "truncated": false,
  "users": [
    {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Alex Example", "email": "alex@example.com", "accountType": "atlassian"}
  ]
}
```

### `conflu users lookup ACCOUNT_ID --json`

The people behind up to 250 account ids, in the order asked, with the bulk lookup of API v2. `requested` is how many different ids were asked for, `notFound` the ids that
Confluence did not describe (unknown, or not a person that this account may look up): that is no error, and the exit code is 0. `users` is as for `search`.

```json
{
  "requested": 2,
  "count": 1,
  "notFound": ["0000000000000000000000ff"],
  "users": [
    {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Alex Example", "email": "alex@example.com", "accountType": "atlassian"}
  ]
}
```

<!-- json:users -->

### `conflu tasks --json`

The tasks (the checkboxes) that are written into pages and blog posts, a piece at a time or all of them. `space` is the key when `--space` was given (`[hidden]` for a personal space, whose key is the account id of its owner, unless you add `--with-users`), else `null`; `count` is how many
tasks are in this answer, `nextCursor` where the next request goes on (`null` on the last piece, and with `--all`), `truncated` that `--all` stopped at its limit. A task has `id`, `localId` (its
number inside its page or blog post), `status` (`complete` or `incomplete`), `pageId` and `blogPostId` (one of the two is `null`), `spaceId`, `text` (the text of the task as plain text: a
mention is `@user`, an address is redacted), the times `dueAt`, `createdAt`, `updatedAt` and `completedAt` (`null` when it has none, a task without a due date is in no range of `--due-after` and
`--due-before`), and the people `assignedTo`, `createdBy` and `completedBy`. A person is `null` unless you add `--with-users`; then it is `{accountId, displayName, email}`, with the name and the
address empty when Confluence does not describe the person. With `--select` only those (dotted) keys of every task. `--task ID`, given once for each task (at most 250), keeps only the tasks with those ids: the
answer has this shape too, and an id that no task has, or that the other filters do not let through, is just not in `tasks` (`count` is smaller): that is how one task is read without `conflu task`.

```json
{
  "space": null,
  "count": 1,
  "nextCursor": null,
  "truncated": false,
  "tasks": [
    {
      "id": "7203", "localId": "1", "status": "incomplete", "pageId": "2003", "blogPostId": null, "spaceId": "1001", "text": "Write ADR 0002",
      "dueAt": "2026-11-05T00:00:00.000Z", "createdAt": "2026-10-03T10:00:00.000Z", "updatedAt": "2026-10-03T10:00:00.000Z", "completedAt": null,
      "assignedTo": null, "createdBy": null, "completedBy": null
    }
  ]
}
```

```json
{
  "space": null,
  "count": 1,
  "nextCursor": "1",
  "truncated": false,
  "tasks": [
    {
      "id": "7201", "localId": "1", "status": "incomplete", "pageId": "2002", "blogPostId": null, "spaceId": "1001", "text": "Check the numbers with @<5b10ac8d82e05b22cc7d4ef5>",
      "dueAt": "2026-10-20T00:00:00.000Z", "createdAt": "2026-10-02T09:00:00.000Z", "updatedAt": "2026-10-02T09:00:00.000Z", "completedAt": null,
      "assignedTo": {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Alex Example", "email": "alex@example.com"},
      "createdBy": {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Alex Example", "email": "alex@example.com"},
      "completedBy": null
    }
  ]
}
```

```json
{
  "space": null,
  "count": 1,
  "nextCursor": null,
  "truncated": false,
  "tasks": [
    {
      "id": "7205", "localId": "1", "status": "incomplete", "pageId": null, "blogPostId": "7290", "spaceId": "1001", "text": "Announce the release",
      "dueAt": "2026-10-25T00:00:00.000Z", "createdAt": "2026-10-05T08:00:00.000Z", "updatedAt": "2026-10-05T08:00:00.000Z", "completedAt": null,
      "assignedTo": null, "createdBy": null, "completedBy": null
    }
  ]
}
```

### `conflu task ID --json`

Without `--complete` and `--reopen` the task as `conflu tasks` shows one (the three people are always `null` here). With one of them the change: `action` is `completed`, `reopened` or
`unchanged` (the task is in that state already and nothing was sent), `dryRun` says that nothing was sent (a dry run reads the task and shows what would be sent), `taskId`, `statusFrom` (what
the task was) and `statusTo` (what was asked for), `readBack` that the task was read again after the change, `notes`, `payload` (exactly what is sent: the status and nothing else; `null` when
nothing is), `task`, the task as Confluence holds it after the change (before it, in a dry run and when `unchanged`), `confirmed` and `message`.

`confirmed` says whether the read after the change shows the state that was asked for: `true`, or `false` when it shows the other one (Confluence accepted the call and the task did not change,
or somebody changed it again). It is `null` for a dry run, for `action: unchanged` and when that read failed (`readBack` is `false` then). Neither of the last two cases is a failure of the
command: the change was sent, the exit code is 0, `message` (`null` otherwise) and a warning on stderr say what to check (`conflu task ID --json`, `status`), and `notes` holds the same text. The text
form never says `Completed` or `Reopened` when `confirmed` is `false`: it says that Confluence accepted the request and still shows the old state. A change is never repeated because the check after it
failed.

```json
{
  "id": "7203", "localId": "1", "status": "incomplete", "pageId": "2003", "blogPostId": null, "spaceId": "1001", "text": "Write ADR 0002",
  "dueAt": "2026-11-05T00:00:00.000Z", "createdAt": "2026-10-03T10:00:00.000Z", "updatedAt": "2026-10-03T10:00:00.000Z", "completedAt": null,
  "assignedTo": null, "createdBy": null, "completedBy": null
}
```

```json
{
  "action": "completed",
  "dryRun": true,
  "taskId": "7203",
  "statusFrom": "incomplete",
  "statusTo": "complete",
  "readBack": false,
  "notes": [],
  "payload": {"status": "complete"},
  "task": {
    "id": "7203", "localId": "1", "status": "incomplete", "pageId": "2003", "blogPostId": null, "spaceId": "1001", "text": "Write ADR 0002",
    "dueAt": "2026-11-05T00:00:00.000Z", "createdAt": "2026-10-03T10:00:00.000Z", "updatedAt": "2026-10-03T10:00:00.000Z", "completedAt": null,
    "assignedTo": null, "createdBy": null, "completedBy": null
  },
  "confirmed": null,
  "message": null
}
```

```json
{
  "action": "completed",
  "dryRun": false,
  "taskId": "7203",
  "statusFrom": "incomplete",
  "statusTo": "complete",
  "readBack": true,
  "notes": [],
  "payload": {"status": "complete"},
  "task": {
    "id": "7203", "localId": "1", "status": "complete", "pageId": "2003", "blogPostId": null, "spaceId": "1001", "text": "Write ADR 0002",
    "dueAt": "2026-11-05T00:00:00.000Z", "createdAt": "2026-10-03T10:00:00.000Z", "updatedAt": "2026-10-15T08:00:00.000Z", "completedAt": "2026-10-15T08:00:00.000Z",
    "assignedTo": null, "createdBy": null, "completedBy": null
  },
  "confirmed": true,
  "message": null
}
```

A server that answers the call with success and does not change the task (the exit code is 0, and the text form says that Confluence still shows the old state):

```json
{
  "action": "completed",
  "dryRun": false,
  "taskId": "7203",
  "statusFrom": "incomplete",
  "statusTo": "complete",
  "readBack": true,
  "notes": ["Confluence accepted the change, but it holds task 7203 as incomplete, not as complete. Somebody may have changed it again; check it with `conflu task 7203 --json` (status)."],
  "payload": {"status": "complete"},
  "task": {
    "id": "7203", "localId": "1", "status": "incomplete", "pageId": "2003", "blogPostId": null, "spaceId": "1001", "text": "Write ADR 0002",
    "dueAt": "2026-11-05T00:00:00.000Z", "createdAt": "2026-10-03T10:00:00.000Z", "updatedAt": "2026-10-03T10:00:00.000Z", "completedAt": null,
    "assignedTo": null, "createdBy": null, "completedBy": null
  },
  "confirmed": false,
  "message": "Confluence accepted the change, but it holds task 7203 as incomplete, not as complete. Somebody may have changed it again; check it with `conflu task 7203 --json` (status)."
}
```

<!-- json:tasks -->

### `conflu properties ID --json`

The content properties of a page, a blog post, a folder, a whiteboard, a database, a smart link, an attachment (its id starts with `att`) or a comment. `target` is the content: its `id` and
its `type`, which is what Confluence calls it (`page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed`, `attachment`, `footer-comment` or `inline-comment`); `count` is how many
properties are in this answer and `nextCursor` where the next request goes on (`null` on the last piece, and with `--all`), `truncated` that `--all` stopped at its limit. A property is `id`, `key`, `version`, `updatedAt` (when that version
was saved) and `value`, which is any JSON: an object, a list, a text, a number, `true`, `false` or `null`. People are hidden in the value, in the key too (a user object becomes
`{"hidden": true}`, an account id or an address becomes a marker) unless you add `--with-users`. A text that holds JSON (an app that stores `JSON.stringify(state)` stores a text) is read as JSON, up to
1,000,000 characters and also when it was encoded up to four times, so that the user objects in it are hidden like the others: it is then shown as compact JSON (`{"reviewer":{"hidden":true}}`), and as it is
when nothing in it was hidden; a text that is not JSON, or is longer, is read by the rules for texts only. A value longer than `--max-chars` characters as compact JSON (2000 unless you say another number,
0 cuts nothing) is the beginning of that text instead, followed by `[value cut]`: `truncated` is `true` and `totalChars` is the size of the whole text (`null` otherwise). `property-set` refuses that
text, so read a value that you want to change with `--max-chars 0` (and `--with-users` when it holds people).

```json
{
  "target": {"id": "2002", "type": "page"},
  "count": 1,
  "nextCursor": null,
  "truncated": false,
  "properties": [
    {
      "id": "7303",
      "key": "team.review",
      "version": 3,
      "updatedAt": "2026-10-10T09:00:00.000Z",
      "value": {"status": "open", "reviewer": {"hidden": true}, "owners": ["[hidden]"], "note": "Ask [email]"},
      "truncated": false,
      "totalChars": null
    }
  ]
}
```

```json
{
  "target": {"id": "2003", "type": "page"},
  "count": 1,
  "nextCursor": null,
  "truncated": false,
  "properties": [
    {
      "id": "7304",
      "key": "inventory",
      "version": 1,
      "updatedAt": "2026-10-01T08:00:00.000Z",
      "value": "{\"items\":[\"item-000\",\"item-001\",\"item-002\",\"item-003\",\"item-[value cut]",
      "truncated": true,
      "totalChars": 4411
    }
  ]
}
```

### `conflu property-set ID --json`

`action` is `created` (the key was new), `updated` (the next version was saved) or `unchanged` (the property holds that value already and nothing was sent); `dryRun` says that nothing
was sent. `target` is the content as for `properties`, `key`, `propertyId` (`null` in a dry run of a creation, and when Confluence's answer to the creation names no id: the text form then says `Created the property KEY on ...` without an id), `versionFrom` (the version it had; `null` for a creation) and `versionTo` (the
version it has now, or in a dry run would have), `value` (the value that was set, as it was given), `current` (what Confluence held before, without people; `null` for a creation), `payload`
(exactly what is sent, which is what a dry run shows; `null` when nothing is sent) and `notes` (what the command did not do, such as a `--message` for a property that is new).
A new value that is a copy of what `properties` showed is not an answer: it is refused with exit code 1, the error `INVALID`, and `details.markers` names what it holds (`details` also has `id` and `key`). These
are the stand-ins for people, where the property holds people (`[hidden]`, `[email]`, `[personal link]`, `[personal space]`, `{"hidden": true}`, `[nested too deeply to show]`, and an attribute whose value was
blanked in a text that is storage format, such as `ri:account-id="hidden"`, `data-userkey="hidden"` or `ri:space-key="[hidden]"`), and `[value cut]`, the end of a value that was cut at `--max-chars`, which is refused
for a property that is new as well. A text that `properties` showed in a changed form with no stand-in in it (an address without its title) is refused too, and `details.texts` shows it instead of `details.markers`.
A number too large to be a number (`1e999`) is a usage error, exit code 2: JSON has no infinity. To write a value that was read, read it whole and real first: `conflu properties ID --key KEY --with-users --max-chars 0 --json`.

```json
{
  "action": "updated",
  "dryRun": true,
  "target": {"id": "2002", "type": "page"},
  "key": "team.review",
  "propertyId": "7303",
  "versionFrom": 3,
  "versionTo": 4,
  "value": {"status": "closed"},
  "current": {"status": "open", "reviewer": {"hidden": true}, "owners": ["[hidden]"], "note": "Ask [email]"},
  "payload": {"key": "team.review", "value": {"status": "closed"}, "version": {"number": 4}},
  "notes": []
}
```

```json
{
  "action": "created",
  "dryRun": false,
  "target": {"id": "2002", "type": "page"},
  "key": "reviewed.by",
  "propertyId": "7313",
  "versionFrom": null,
  "versionTo": 1,
  "value": "the team",
  "current": null,
  "payload": {"key": "reviewed.by", "value": "the team"},
  "notes": []
}
```

<!-- json:properties -->

### `conflu templates --json`

The page templates of a space (`space` is its key, `[hidden]` for a personal space: its key is the account id of its owner), or the global ones (`space` is `null`), or with `--blueprints` the templates that blueprints provide (`blueprints` is `true`). `count` is how many
templates are in this answer, `start` the index of the first one, `nextStart` where the next request goes on (`null` on the last piece, and with `--all`), `truncated` that `--all` stopped at
its limit. A template is `id`, `name`, `type` (`page` or `blueprint`), `description`, `spaceKey` (`null` for a global template, `[hidden]` in a personal space), `labels` (names) and `blueprint` (what the template references, as
Confluence says it; `null` when it says nothing). Names, descriptions and labels are redacted like every title. With `--select` only those (dotted) keys of every template.

```json
{
  "space": "ENG",
  "blueprints": false,
  "count": 2,
  "start": 0,
  "nextStart": 2,
  "truncated": false,
  "templates": [
    {"id": "7404", "name": "Decision record", "type": "page", "description": "ADR style", "spaceKey": "ENG", "labels": ["adr"], "blueprint": null},
    {"id": "7403", "name": "Incident report", "type": "page", "description": "", "spaceKey": "ENG", "labels": [], "blueprint": null}
  ]
}
```

```json
{
  "space": null,
  "blueprints": true,
  "count": 2,
  "start": 0,
  "nextStart": null,
  "truncated": false,
  "templates": [
    {
      "id": "7406", "name": "Meeting notes", "type": "blueprint", "description": "Agenda, notes and actions", "spaceKey": null, "labels": ["meeting"],
      "blueprint": "com.atlassian.confluence.plugins.confluence-business-blueprints:meeting-notes-blueprint"
    },
    {
      "id": "7407", "name": "Product requirements", "type": "blueprint", "description": "What and why", "spaceKey": null, "labels": [],
      "blueprint": "com.atlassian.confluence.plugins.confluence-software-blueprints:requirements-blueprint"
    }
  ]
}
```

### `conflu template ID --json`

One template: the fields of a template in the list, `variables` (the names that the template declares with `<at:var>` elements, in the order of their first appearance, each once: the
Markdown copy of a body cannot show them, so they are read from the storage format), `variablesComplete` (`false` when the body holds more such tags than are read, or longer ones, so that
the list may be incomplete) and `body` as `conflu page` shows one: `format`, `value` and `dropped` (what the format could not say). People are hidden in the body, and so is the key of a personal space: `spaceKey` is `[hidden]` for a template of one, and a link in the body to a page in one is `page:[hidden]/Title` (`ri:space-key="[hidden]"` in `--format storage`).

```json
{
  "id": "7402",
  "name": "Release checklist",
  "type": "page",
  "description": "Steps for every release",
  "spaceKey": "ENG",
  "labels": ["release", "checklist"],
  "blueprint": null,
  "variables": ["version"],
  "variablesComplete": true,
  "body": {"format": "markdown", "value": "## Release\n\n- Update the notes\n- Tag", "dropped": ["html:at:var"]}
}
```

### `conflu template ID --body-only --out FILE --json`

The body of the template goes into the file as UTF-8, exactly the text that `--body-only` would have printed, and the answer is this object instead of the text: `file` is the path as it was given and
`bytes` the size of the file. With `--format storage` the file holds the source as Confluence keeps it (the variables included), to start a page from. A file that exists is not replaced without
`--force`, and `--out` needs `--body-only`.

```json
{
  "file": "body.xml",
  "bytes": 121
}
```

<!-- json:templates -->
