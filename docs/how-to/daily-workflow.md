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
- `--body-only` prints the body and nothing else, so it can go into a file: `conflu page 123456 --format storage --with-users --body-only > page.xml`
  keeps the page exactly as Confluence stores it, ready for `conflu update 123456 --file page.xml --format storage --dry-run`.

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
