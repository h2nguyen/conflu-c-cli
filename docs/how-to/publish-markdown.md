# Publish Markdown pages

`conflu import-md` publishes one Markdown file, and `conflu import-md-dir` does the same for every `*.md` file in
one folder. This guide covers the file format, the precedence rules, safe re-runs and the cases where Markdown is
not rich enough.

## The file format

A Markdown file may start with a front matter block of `key: value` lines between `---` markers:

```text
---
title: Release notes 2026.10
space: ENG
parent: 123456
page_id: 123456
labels: release, notes
message: Imported from release-notes.md
---
# Optional heading

Body text.
```

The import reads these front matter keys:

- `title`
- `space`
- `parent`
- `page_id`
- `labels`
- `message`

Aliases such as `id`, `confluence_id`, `space_key`, `parent_id` and `label` are accepted and normalised. Any other
key is ignored, which is how the `version`, `updated`, `url` and `lossy` lines that `conflu export` writes pass
through an import without harm.

The file may be UTF-8 (with or without a byte order mark), UTF-16 (what Windows PowerShell 5.1 writes with `>` and
`Out-File`) or Windows-1252; a byte order mark is dropped and a line end of Windows is fine. A file with NUL characters
(a picture) is refused with "is not text".

## Where the title comes from

The title is chosen in this order:

1. `title:` in the front matter
2. the first level-1 heading at the start of the body (`# Heading`)

When the first heading becomes the title, it is removed from the body before the body is converted and sent.
If the file has neither a title nor a `page_id`, the import is refused.

A title that holds `[email]` or `[personal link]` is refused too: that is what `conflu export` writes in place of an e-mail
address or a personal link, and the page must not be renamed to it. Take the `title:` line out of the file and the page keeps
its own title.

## Space and parent precedence

The page location is chosen in this order:

- `space:` in the front matter
- `--space KEY`
- the current space saved by `conflu use KEY`

For the parent page:

- `parent:` in the front matter
- `--parent ID`

The front matter wins over the command line. `parent:` is optional; without it a newly created page goes below
the home page of the chosen space. The parent may be a page, a folder, a whiteboard, a database or a smart link of
the same space, given as an id or as the address in the browser, and `conflu export` writes the id of whatever the
parent is. A parent only counts when a page is created: an update leaves a page where it is
([folders and structure](folders-and-structure.md)).

## Update by `page_id`, else by title

`conflu import-md` decides what to do this way:

1. If the front matter has `page_id`, it updates that page.
2. Otherwise it looks in the target space for a **current** page with the same title.
3. If such a page exists, it updates it.
4. Otherwise it creates a new page.

That makes re-runs stable: the first run can create the page, later runs find it again by title, and exported
files find it again by `page_id`.

## Labels and version message

`labels:` is a comma-separated list. On import they are **added only**; labels not named in the file are left as
they are on the page. A label the page does not have yet counts as a change: an import whose text is unchanged is then
reported as `updated`, and the dry run lists the labels it would add (`labels` in the JSON). A label Confluence
would refuse (it has a space, for example) is refused before anything is written.

`message:` becomes the version message when the import updates an existing page. Without it the CLI uses
`Imported from FILE.md`.

## Dry runs

Both commands support `--dry-run`:

```bash
conflu import-md notes.md --space ENG --dry-run
conflu import-md-dir docs/confluence --space ENG --dry-run
```

A dry run reads the file, resolves the target page, converts the Markdown, proves that the space or page exists,
and prints exactly what would be sent. It writes nothing to Confluence.

## Re-running an import

Re-runs are meant to be safe:

- If the file still says exactly what the page says, the result is `unchanged`.
- If the file changed, the page is updated.
- If the page does not exist yet, it is created.
- `import-md-dir` processes files in name order and stops at the first failure unless you add
  `--continue-on-error`.

An unedited mirror written by `conflu export` is therefore a no-op when you feed it back to
`conflu import-md-dir`, even for pages whose Markdown export carries `lossy` markers because the original page had
macros, mentions or `redacted-text`.

What the import does not look at is whether the page changed in Confluence after the file was written: the `version` line of an
exported file is information, not a guard. See [export and sync](export-and-sync.md) for what that means and for a safe routine.

## The lossy guard and `--force`

Markdown cannot express every Confluence storage-format construct. When an import would **replace** a page body
that contains things the CLI's Markdown view cannot say, the update is refused and names the missing constructs
under `lost`. That list can include `redacted-text` when the existing page body contains e-mail addresses or
personal profile links that the Markdown copy hides as `[email]` or `[personal link]` unless `--with-users`.

The guard is conservative but not wasteful: if the Markdown you are importing is exactly what the current page
already shows as Markdown, the result is `unchanged` and no new version is created.

Use `--force` only when you accept that loss:

```bash
conflu import-md release-notes.md --force
```

Safer alternatives:

- add text with `conflu update PAGE --append` or `--prepend`
- edit storage format explicitly with `conflu update PAGE --format storage ...`
- inspect the page first with `conflu page PAGE --json` and look at `body.dropped`

In practice that means:

- an **unedited** export can be re-imported as a no-op
- an **edited** file for a page with `lost` constructs is refused without `--force`

## Images and attachments

A Markdown image such as:

```markdown
![Deployment diagram](diagram.png)
```

becomes a reference to an attachment named `diagram.png`. `import-md` does **not** upload the file for you.
Upload it separately with `conflu attach`:

```bash
conflu attach 123456 diagram.png
```

The same applies to links to local files by name.

## Alerts and raw HTML

The Markdown converter recognises GitHub-style alerts and turns them into Confluence macros:

- `> [!NOTE]` becomes an info macro
- `> [!TIP]` becomes a tip macro
- `> [!IMPORTANT]` becomes a note macro
- `> [!WARNING]` and `> [!CAUTION]` become a warning macro

Raw HTML is **not** interpreted as HTML. It is shown as text.

## One file versus one folder

Use `conflu import-md` when you already know the file you want to publish. Use `conflu import-md-dir` when you
want a repeatable batch from one folder. The folder command reads only files whose names match `*.md`; it does
not recurse into subfolders.

## Related guides

- [daily-workflow.md](daily-workflow.md)
- [export-and-sync.md](export-and-sync.md)
- [markdown-and-storage-format.md](markdown-and-storage-format.md)
