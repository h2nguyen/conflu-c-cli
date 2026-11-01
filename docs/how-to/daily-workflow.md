# Daily workflow

This is a small set of commands that covers most work with Confluence Cloud: read, search, change one page
safely, publish Markdown, and keep a local mirror.

## Start from a known space

```bash
conflu use ENG
conflu current
conflu doctor
```

`conflu use` saves the current space so you can leave out `--space` on later commands. `conflu doctor` is worth
running after a fresh install or a network change.

## Read a page before you change it

```bash
conflu page 123456
conflu page 123456 --outline
conflu page 123456 --section Steps
conflu page 123456 --comments --ancestors --json
conflu versions 123456 --with-users
```

What to look at:

- `conflu page` shows the current version, the labels and the body.
- `--comments` adds the footer comments; `conflu comments 123456 --inline` adds inline comments too.
- `--ancestors` prints the path so you can see where the page lives.
- `conflu versions` gives you the version numbers that `conflu update --if-version N` can guard on.
- `--body-only` prints the body and nothing else, and with `--out FILE` the program writes it into a file itself, as UTF-8:
  `conflu page 123456 --format storage --with-users --body-only --out page.xml` keeps the page exactly as Confluence stores it, ready for
  `conflu update 123456 --file page.xml --format storage --dry-run`. Do not save it with `>`: Windows PowerShell 5.1 re-encodes what `>` writes and damages every character that is
  not ASCII (see [troubleshooting](troubleshooting.md#saving-output-with--in-windows-powershell-51)). `--out` does not replace a file that is there without `--force`.

If `conflu page` mentions `dropped`, the page holds constructs that Markdown cannot express in its reading copy.
That list can include macros, mentions and `redacted-text` when the Markdown view had to hide e-mail addresses or
personal profile links. For a body replacement prefer `--append`, `--prepend` or `--format storage`, and read
[markdown-and-storage-format.md](markdown-and-storage-format.md) before you overwrite it.

## Find the right page

```bash
conflu pages --space ENG --sort modified-date --desc --limit 50
conflu search 'retention policy' --space ENG --label adr
conflu tree 123456 --depth 3
```

Use cases:

- `conflu pages` is a directory listing.
- `conflu search` is for words, questions and CQL (`--cql`) across the site or one space. Each hit shows where it lives; `--snippets 5` shows the
  passage around your words for the first five (the excerpts of the search index can name people, so they are left out). See
  [find information](find-information.md).
- `conflu tree` helps before you move or export a branch of the page tree.

## Change one page safely

For a title change:

```bash
conflu update 123456 --title 'Release notes 2026.10' --if-version 7 --dry-run
conflu update 123456 --title 'Release notes 2026.10' --if-version 7
```

For a body update that keeps the current content and adds more text:

```bash
conflu update 123456 --file notes.md --append --message 'Added the October notes' --if-version 7 --dry-run
conflu update 123456 --file notes.md --append --message 'Added the October notes' --if-version 7
```

For a full replacement from Markdown, only when the page is simple enough or when you explicitly accept the loss:

```bash
conflu update 123456 --file page.md --if-unchanged-since 2026-10-15T08:00:00Z --dry-run
conflu update 123456 --file page.md --if-unchanged-since 2026-10-15T08:00:00Z
```

Rules of thumb:

- Always dry-run first.
- Prefer `--append` or `--prepend` to a full replacement.
- A full Markdown replacement is refused when the current page holds constructs listed under `dropped`,
  including `redacted-text`, unless you add `--force`.
- Use `--if-version` when you just read the version number.
- Use `--if-unchanged-since` when you read the page earlier and kept the timestamp.
- Exit code 3 means the page changed before your write reached Confluence; read it again.

## Check before you write, and undo an edit

```bash
conflu permissions 123456 --only update          # may my account change this page at all?
conflu restrictions 123456                       # is it restricted, and how many users and groups hold read and update?
conflu versions 123456                           # the saved versions
conflu diff 123456 --from 6 --to 7               # what the last edit changed, as a unified diff of the Markdown
conflu restore 123456 --version 6 --dry-run      # bring version 6 back as a new version, nothing is lost
conflu restore 123456 --version 6 --if-version 7
```

`conflu permissions`, `conflu restrictions` and `conflu space-access` only read: nothing here changes who may see
or edit content. A restore saves the old content as the next version, so the edit you undo stays in the history
([history and restore](history-and-restore.md), [access and restrictions](access-and-restrictions.md)).

## Folders and blog posts

```bash
conflu folder 7001 --children                    # what sits directly below a folder (its id is in the address in the browser)
conflu create --space ENG --title 'Guides' --parent 7001 --file guide.md --dry-run
conflu move 123456 --to 7001 --dry-run           # a page into a folder: it saves a new version
conflu blogposts --space ENG                     # the blog posts of a space
conflu blogpost 7101 --outline
```

A page, a folder, a whiteboard, a database and a smart link share one tree and one sequence of ids, so an id alone
does not say which it is; `conflu folder`, `conflu whiteboard`, `conflu database` and `conflu smartlink` show the
others ([folders and structure](folders-and-structure.md), [blog posts](blog-posts.md)).

## Work around one page

```bash
conflu labels 123456
conflu label 123456 --add reviewed,adr --dry-run
conflu comment 123456 --file review.md --dry-run
conflu attach 123456 diagram.png notes.pdf --comment 'October version' --dry-run
conflu move 123456 --to 654321 --position before --dry-run
```

`conflu label`, `conflu comment`, `conflu attach` and `conflu move` all have the same safe pattern: preview,
run, then read back with `conflu page`, `conflu comments` or `conflu attachments`.

## Review the discussion on a page

```bash
conflu comments 123456 --inline --resolution open       # what is still open
conflu comments 123456 --since 2d --last 5              # what was said lately
conflu comment 123456 --text 'Done, see version 8.' --reply-to 4001 --dry-run
conflu comment 123456 --edit 4005 --text 'A better wording.' --dry-run     # your own comment; the dry run shows a diff
conflu comment 123456 --resolve 4003 --dry-run                              # close an inline discussion
```

Comments carry `authorRef`, a stable pseudonym of the author, and `byMe`, so the discussion can be followed without a single name
([comments and labels](comments-and-labels.md)).

## Publish Markdown from files

```bash
conflu import-md examples/page.md --space ENG --dry-run
conflu import-md examples/page.md --space ENG
conflu import-md-dir examples/pages --space ENG --dry-run
```

`conflu import-md` and `conflu import-md-dir` are for page content that belongs in files. The guide
[publish Markdown pages](publish-markdown.md) explains the front matter, re-runs, the no-op behaviour for
unchanged exports, and the lossy guard.

## Export a local mirror

```bash
conflu export --space ENG --out mirror/eng
conflu export --page 123456 --out mirror/guide --dry-run
```

This writes one file per page plus `index.json`, with no personal data. Use it for offline review, AI-agent
input, bulk edits with `conflu import-md-dir`, or a human-readable snapshot. The guide
[export a local mirror and sync it back](export-and-sync.md) covers the workflow and the limits. There is no `sync` command: the import does not notice changes made in Confluence after the
export, so read that guide before you import a folder that you exported earlier.

## When the built-in commands stop short

```bash
conflu api GET api/v2/pages/123456
conflu api GET 'rest/api/search?cql=type=page AND space="ENG"'
```

Use `conflu api` only when a named command does not cover the case yet. `GET` is free. `POST` and `PUT` need
`--write`, and a dry run is available for both.
