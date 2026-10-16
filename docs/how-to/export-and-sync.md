# Export a local mirror and sync it back

`conflu export` writes pages from Confluence Cloud into a folder you can review, diff, hand to another tool, or
re-import later with `conflu import-md` or `conflu import-md-dir`.

## Is there a `sync` command?

No. There are two one-way commands, and it helps to know exactly what each does:

| Direction | Command | What it does |
| --- | --- | --- |
| Confluence to a folder | `conflu export` | Writes one Markdown file per page, with the page id, version and time in the front matter. |
| A folder to Confluence | `conflu import-md-dir` | Updates the page named by `page_id` (or finds it by title, or creates it). A file that says what the page says is `unchanged`. |

What the pair does **not** do, so that nothing surprises you:

- **No check against changes made in Confluence after the export.** The `version` and `updated` lines are information; the import does
  not compare them. It replaces the body of the page as it is now. If a colleague edited a page since your export, your import
  overwrites that edit (Confluence keeps it in the page history). To be safe, keep the folder in Git: commit your work,
  run `conflu export --space KEY --out DIR --force`, and read `git diff`, which shows what changed in Confluence, before you import. Without Git, export into a second folder and run `git diff --no-index --stat FIRST SECOND`, which compares any two folders.
- **No deletions** in either direction: a page you delete in Confluence stays in the folder, a file you delete stays a page.
- **No moves.** `parent:` is used when a page is created, not to move one. Use `conflu move`.
- **Labels are added**, never removed. **The folder is flat** and the import reads only the `*.md` files of one folder.
- **A title is kept as it is**, spacing included. A title that holds an e-mail address or a personal link is written with the
  placeholder `[email]` or `[personal link]`, and the import refuses to rename a page to it: take the `title:` line out of that file.

`conflu import-md-dir DIR --dry-run` shows what an import would do (`created`, `updated`, `unchanged`, `failed`) and sends nothing.

## Export a whole space or one page tree

A whole space:

```bash
conflu export --space ENG --out mirror/eng
```

The current space, if you already selected one:

```bash
conflu use ENG
conflu export --out mirror/eng
```

One page and everything below it:

```bash
conflu export --page 123456 --out mirror/guide
```

The page-tree export follows descendants up to 10 levels deep. If the tree is deeper, the export finishes with a
note that pages below that level were left out.

## What gets written

An export writes:

- one file per page
- `index.json`

Markdown is the default. File names are derived from the page title and always include the page id, for example
`release-notes-2002.md`.

A Markdown file starts with front matter that `conflu import-md` understands again:

```text
---
title: Release notes
page_id: 2002
space: ENG
parent: 2001
version: 3
updated: 2026-10-10T09:00:00.000Z
url: https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Release+notes
lossy: macro:toc, mention, redacted-text
---
```

The body follows after that front matter.

Every file also has a `path:` line (the parent pages, within what was exported) and every entry of `index.json` a `path`, so that a file search over the mirror
shows where a hit lives; the import ignores the line. To search the code and the pages together see [find information](find-information.md#4-a-local-mirror-to-search-the-code-and-the-pages-together).

`index.json` contains the export time, the space key, the root page (when there is one), the format and one entry
per exported page (`id`, `title`, `parentId`, `file`, `version`, `updated`, `lossy`).

## The `lossy` marker

When you export as Markdown, some Confluence constructs cannot be expressed exactly. The CLI does not hide that:
it writes the missing constructs under `lossy` in the front matter and in `index.json`.

That is why a Markdown export is best thought of as a **local mirror for reading and controlled editing**, not as a
byte-for-byte backup of storage format. For the page source as Confluence keeps it, export storage format instead.
`redacted-text` is part of that honesty: it tells you that the Markdown copy hid e-mail addresses or personal
profile links.

## Storage format export

```bash
conflu export --space ENG --format storage --out mirror/storage
```

This writes `.xml` files instead of `.md`. Use it when you need Confluence's storage format for inspection or for
careful storage-format edits. The same `index.json` is written alongside the files.

## No personal data

Exports are privacy-safe by default:

- people are not written
- mention account ids are blanked in storage-format reads without `--with-users`
- e-mail addresses and personal links in text are redacted

That makes a mirror safer to hand to another tool or keep in a repository, but it also means it is not a full
forensic copy of what a privileged user may see in the browser.

## Re-importing an export

A mirror written by `conflu export` is meant to feed `conflu import-md` or `conflu import-md-dir` later.
Typical flow:

```bash
conflu export --space ENG --out mirror/eng
conflu import-md-dir mirror/eng --dry-run
conflu import-md-dir mirror/eng
```

Re-import behaviour:

- unchanged files report `unchanged`
- edited files update their pages
- front matter with `page_id` points at the original page directly
- labels are not removed by import; named labels are added

An important consequence of the no-op rule: an **unedited** export can be fed straight back into
`conflu import-md-dir` without creating new versions or failing, even for pages whose export lists `lossy`
constructs. Only an **edited** file for such a page is refused without `--force`.

## What a local mirror is good for

A local mirror is useful for:

- offline reading on a laptop
- code review style diffs of page content
- feeding another program or an AI agent without live API access
- careful, repeatable bulk edits through `conflu import-md-dir`
- keeping documentation content in version control while Confluence remains the live system

## The limits of a local mirror

A local mirror is **not**:

- a live view of Confluence
- a permission mirror
- a complete representation of every macro or layout when you export Markdown
- a recursive folder export beyond 10 levels of descendants for `--page`

`conflu export` also refuses to overwrite files unless you add `--force`, so repeated exports to the same folder
are explicit.

## A practical sync loop

1. `conflu export --space ENG --out mirror/eng`
2. Review or edit selected Markdown files.
3. `conflu import-md-dir mirror/eng --dry-run`
4. Inspect the reported `created`, `updated`, `unchanged` and `failed` counts.
5. Run `conflu import-md-dir mirror/eng`
6. Read back the changed pages with `conflu page PAGE --json`

For the converter rules behind the mirror, read [markdown-and-storage-format.md](markdown-and-storage-format.md).
