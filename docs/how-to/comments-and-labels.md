# Comments and labels

Comments are the discussion on a page: **footer comments** at the bottom, and **inline comments** that are made on a piece of text and can be resolved.
This guide shows how to read them, how to pick the recent or the open ones, how to tell the authors apart while names stay hidden, how to change a comment
that you wrote, how to resolve an inline comment, and how to see which labels a space uses. It names what the CLI does not do.

The commands follow the Confluence Cloud REST API v2 documentation. They are tested against a mock server that follows the same document, not against a
real site, so try a command that changes a comment with `--dry-run` first.

## Read the comments of a page

```bash
conflu comments 123456                     # the footer comments, each conversation as its first comment and the answers
conflu comments 123456 --inline            # also the comments made on a piece of text
conflu comments 123456 --inline --json
```

Every comment has a line with its id, its kind, its state (an inline comment: `[open]`), the time it was saved, whom it answers and who wrote it, and below it
its text. An answer is indented below the comment it answers. The text is Markdown (`--format text` or `--format storage` change that), and mentions and
addresses of people are hidden, see the next part.

### Who wrote it

Names, account ids, e-mail addresses and personal links stay out of the output unless you add `--with-users`, and `CONFLUENCE_HIDE_USERS=true` refuses
`--with-users`. A link in a comment to a page in a personal space, which is keyed by the account id of its owner, reads `page:[hidden]/Title`. The authors can still be told apart:

- **`authorRef`** is a pseudonym of the author: `a-` and eight hexadecimal digits. It is made from the address of the site and the account id with a key
  that only you have, your API token, so it is the same in every command that runs with your token, nobody else can work out the account behind it or compute it
  for an account id that they know, and another token gives other values. Without a token there is none (`null`): an unkeyed hash could be worked out from
  an id. It is not a person, so it is shown under `CONFLUENCE_HIDE_USERS=true` too.
- **`byMe`** says whether the user of the token wrote the comment, and the text marks your own comments with `(you)`. It takes one more request
  (`GET /rest/api/user/current`, a v1 call: v2 has none for the user of a token), and only when there are comments; when that read fails the comment says
  `null` and a warning says why.
- With **`--with-users`** the name stands in the text instead of the pseudonym, and `author` in the JSON is filled.

### Pick the recent ones

```bash
conflu comments 123456 --inline --since 2d             # saved in the last two days (12h, 1w, 30m ...)
conflu comments 123456 --since 2026-10-15              # since a date, or an ISO 8601 time: 2026-10-15T08:00:00Z
conflu comments 123456 --inline --last 3               # the three newest
conflu comments 123456 --since 1w --last 3 --json      # the newest three of the last week
```

The time of a comment is when its current version was saved, which is when it was written unless somebody changed it, so an edited comment is recent again. A date, or a time
without an offset, is UTC. `--last` looks at what `--since` lets through. The JSON says `total` (what the page has of that kind) and `count` (what is printed), and `since` (the moment that
`--since` named). A value that is no time, such as `yesterday` or an empty one, is a usage error (exit code 2); so is `--last 0`.

### Open and resolved discussions

```bash
conflu comments 123456 --resolution open       # inline comments that nobody has resolved, with their answers
conflu comments 123456 --resolution resolved
```

`--resolution` is the filter of Confluence for inline comments: `open`, `resolved`, `reopened` (resolved once and opened again) and `dangling` (the text on the
page that the comment was made on is gone). The footer comments have no state and are left out. `open` and `reopened` are two states; ask for both with two runs.

### As a table, or only some keys

`--format` is the format of the comment text, so the layout of the list is `--list-format table|tsv|md`:

```bash
conflu comments 123456 --inline --list-format tsv --select id,kind,updated,byMe
conflu comments 123456 --inline --select id,authorRef,body.value --json
```

## Read one comment

```bash
conflu comment 123456 --get 4001
conflu comment 123456 --get 4001 --json            # with its version
```

The comment must be one of that page: a comment of another page is "not found" (exit code 4), like one that does not exist. The CLI does not know whether an
id is a footer or an inline comment; it asks for a footer comment first and, when Confluence answers 404, for an inline one. `--get` shows the `version` of the
comment, which is what the guard `--if-version` of a change compares. `--with-users` and `--format markdown|text|storage` work as in `conflu comments`.

## Change the text of a comment

Confluence lets a person change the text of their own comments. Read it, preview the change, then make it:

```bash
conflu comment 123456 --get 4001
conflu comment 123456 --edit 4001 --text 'Fixed in 2.1.' --dry-run          # the diff and the request, nothing is sent
conflu comment 123456 --edit 4001 --file new.md --if-version 1              # refused when the comment is no longer at version 1
```

- The comment is **read first**. The dry run shows a unified diff of the old and the new text (as Markdown, with people hidden) and the request that a real run
  sends; a real run sends exactly that. An inline comment keeps its state: the request carries `resolved` as it is.
- A text that is the comment's own is `unchanged`, and nothing is sent.
- `--if-version N` and `--if-unchanged-since ISO` refuse the change (exit code 3, nothing written) when the comment is at another version, or was saved after that
  time. Both are checked again just before the write. The version number that the change sends is the current one plus one, so Confluence itself refuses
  (HTTP 409, exit code 3) when somebody saved in between.
- The text is Markdown unless `--format storage`. A text that holds `[email]` or `[personal link]` is refused: that is what a reading shows in place of
  an address or a profile link, and sending it would overwrite the real one. Storage format whose mentions were hidden by a reading is refused too. Replacing
  a comment that holds a mention or a macro with Markdown is refused, because Markdown cannot say it; write storage format, or add `--force` to replace it anyway.
  An empty text is refused: a comment is never deleted or emptied.
- Somebody else's comment is refused by Confluence (HTTP 403, exit code 5, with its own message and a hint); the dry run warns before. The earlier versions of a
  comment stay in Confluence.

## Resolve an inline comment

```bash
conflu comment 123456 --resolve 4003 --dry-run
conflu comment 123456 --resolve 4003
conflu comment 123456 --reopen 4003
conflu comment 123456 --resolve 4003 --dry-run --with-users     # the request exactly as it is, with the people in the text
```

Only an inline comment can be resolved: for a footer comment the command is a usage error (exit code 2) that says to answer it with `--reply-to` instead. A comment
that is in the state already is `unchanged`; a dangling one is refused. The change sends the comment's own text back with `resolved` true or false, so the text is not
changed; the account needs the permission to add comments in the space, and what Confluence refuses is shown as it comes (HTTP 403 or 404 with a hint). The printed
request leaves out the people and addresses in that text (`payloadRedacted`) unless you add `--with-users`, which `CONFLUENCE_HIDE_USERS=true` refuses; what is sent is
always the comment as it is. `--if-version` and `--if-unchanged-since` guard it as they guard a change of the text.

## Add a comment

```bash
conflu comment 123456 --text 'Reviewed, no findings.' --dry-run
conflu comment 123456 --file review.md
conflu comment 123456 --text 'Agreed.' --reply-to 4001
```

Adding a comment: a footer comment on the page, or an answer to a comment with `--reply-to`. Everyone who sees the page sees the comment: add one only when you are
asked, and preview it first. `--get`, `--edit`, `--resolve`, `--reopen` and adding exclude each other, and an option that belongs to some of them is refused for the
others, with a usage error that names the clash.

An answer names its parent comment and not the page, because the Confluence document says not to give the page for an answer: `--reply-to ID` reads that comment first, sends only
`parentCommentId` and `body`, and refuses a parent that is not a comment of that page (exit code 4, "No comment ID on page PAGE", also in a dry run, which reads the parent
and sends nothing). The dry run prints the request exactly as it would be sent.

An option that is given with an empty value, such as `--reply-to "$ID"` where the shell variable is empty, is an error that names the option, and nothing is read or sent,
also in a dry run: it never means "not given", which would post a comment of its own where an answer was meant. That holds for `--reply-to`, `--get`, `--edit`, `--resolve`,
`--reopen`, `--since`, `--resolution`, `--if-unchanged-since` and `--file`.

## The labels used in a space

```bash
conflu labels --space ENG                          # a piece of the list, by name
conflu labels --space ENG --all --select name --format tsv
conflu labels --space ENG --limit 100 --cursor TOKEN --json
conflu labels 123456                               # the labels of one page, as before
```

`conflu labels --space KEY` lists the labels that the content of the space carries (pages and blog posts), each once, by name. It is the call
`GET /api/v2/spaces/{id}/content/labels`; `GET /api/v2/spaces/{id}/labels` is the labels of the space itself, which is another thing. The list comes in pieces of
`--limit` (25 by default, at most 250); the text prints how to go on (`--cursor TOKEN` with the `nextCursor` of the JSON), or use `--all`, which stops at 20000 labels
and says so. Name a page or a space, not both: the current space of `conflu use` is not assumed here. The JSON repeats the `space` that was listed, as `[hidden]` when it is a personal space (its key is
the account id of its owner).

The labels come as Confluence gives them, and the CLI asks for no prefix. Atlassian's description of the call names the prefixes `my` and `team` for its filter, and the
tests of this CLI cannot show what a real site answers for the labels that everybody uses (prefix `global`): if a label that you expect is missing, tell the maintainers.

- To find the **pages that carry a label**, use `conflu search --label NAME`, see [find information](find-information.md).
- To **add or remove** labels of a page: `conflu label 123456 --add reviewed --remove draft --dry-run`. That is the v1 API, because v2 can read labels and not change them.
  An `--add` or `--remove` that is given and names no label (`--add ""`, from an empty shell variable) is an error that names the option, and nothing is read or sent: it never means "not given".

## Exit codes

| Code | When |
| --- | --- |
| 0 | It worked, also a dry run and a change that was not needed (`unchanged`). |
| 1 | Bad input: an id that is no number, a text that is refused, an empty text, an id or a guard that is given empty, a dangling comment, `--with-users` under `CONFLUENCE_HIDE_USERS=true`. |
| 2 | The command line is wrong: modes that clash, an option for the wrong mode, a value that is no time or state (an empty one too), `--resolve` of a footer comment. |
| 3 | The comment moved on: `--if-version`, `--if-unchanged-since`, or HTTP 409 from Confluence. |
| 4 | No such page, comment or space. A comment of another page counts as none. |
| 5 | Confluence refused: somebody else's comment (HTTP 403), or the credentials. |

## What the CLI does not do

- It never deletes a comment, and it never empties one.
- It does not change the text of somebody else's comment: Confluence refuses it.
- It does not create inline comments; only footer comments are added.
- It does not reach the comments of a blog post, an attachment or a whiteboard with these commands: `conflu comment` takes a page.
- It does not search comments by their text, and it cannot list the labels of a space with the number of pages that carry each.

## Related guides

- [find-information.md](find-information.md)
- [markdown-and-storage-format.md](markdown-and-storage-format.md)
- [use-with-ai-agents.md](use-with-ai-agents.md)
- [daily-workflow.md](daily-workflow.md)
