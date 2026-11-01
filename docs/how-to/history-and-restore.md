# History and restore

A page keeps every version that was saved. This guide shows how to list the versions, read an earlier one, see what changed between two of them and bring one back, and how to read
several pages in one call or name the files of a page. It says what a restore does to the history and what the comparison cannot show.

The commands follow the Confluence Cloud REST API documentation (v2, and v1 for the restore, which v2 does not have). They are tested against a mock server that follows the same documents,
not against a real site, so try a restore with `--dry-run` first.

## The versions of a page

```bash
conflu versions 123456                  # number, when it was saved and the message of each version, newest first
conflu versions 123456 --all --json
```

The number is what the other commands take. Who saved a version is hidden until `--with-users`.

## Read an earlier version

```bash
conflu page 123456 --version 2                  # as it was saved, as Markdown
conflu page 123456 --version 2 --outline        # the headings of that version
conflu page 123456 --version 2 --section Steps --max-chars 3000
conflu page 123456 --version 2 --format storage --body-only --out version-2.xml    # UTF-8, written by the program: Windows PowerShell 5.1 damages what `>` saves
conflu page 123456 --version 2 --json           # version.current is false, currentVersion is the number of the version now
```

An earlier version has the **title, the body and the version of its time**. What belongs to the page and not to one of its versions is the page's now: its labels, its status and its place in the tree.
The text says `Version: 2 (an earlier version; the current one is 3)`, and in JSON `version.current` is `false` and `currentVersion` names the current one; asking for the current version by its
number says `the current version` and `current: true`. `--comments` and `--ancestors` are refused with `--version`, because both are those of now (read them without the option); `--version` is for one page.

A version that the page does not have is "not found" (exit code 4), and the hint says which version the page is at and names `conflu versions PAGE`. A number below 1 is a usage error (exit code 2).

## Compare two versions

```bash
conflu diff 123456                              # the current version against the one before it
conflu diff 123456 --from 2 --to 5 --context 1  # version 2 against version 5, one line of context
conflu diff 123456 --from 3 --json              # version 3 against the current one: added, removed, diff
conflu diff 123456 --max-chars 4000             # a long diff is cut after a whole line, and the answer says how long it was
```

The diff is a **unified diff of the Markdown** that `page` shows for each version, made with the standard library's `difflib`; `--to` names the later version (a number or `current`, the default),
`--from` the earlier one (the version before `--to` by default), and the two may be given in either order. People are hidden as everywhere: a mention reads `@user` and an e-mail address `[email]`,
so the diff names nobody, and the titles and messages of the versions are redacted too.

What the diff cannot show:

- **What Markdown cannot say is not compared.** Macros, layouts and mentions are in the Markdown of neither version, so a change in them is not in the diff. `dropped` (and a line on standard error) names what is
  missing, and `sourceIdentical` says whether the storage format of the two versions is the same too: two versions that read the same but differ in a macro say so instead of showing an empty diff.
- **A change of the title is not in the diff of the body.** `from.title` and `to.title` have both titles.
- A page with one version, or two versions that read the same (or the same version twice), says so and is no failure (exit code 0).
- **Version 1 has nothing before it.** `conflu diff 123456 --to 1` on a page with more versions says so (and `identical` is `false` in JSON: nothing was compared); `--from 1` compares it with the current version.

## Restore a version

```bash
conflu restore 123456 --version 2 --dry-run                          # what would come back, and the request; nothing is sent
conflu restore 123456 --version 2 --message 'Back to the reviewed text' --if-version 5
conflu restore 123456 --version 1 --restore-title --json
```

**A restore makes a new version.** Confluence saves a new version of the page with the content of the old one, so the page is at version 6 after a restore from version 2 of 5, and versions 1 to 5 are all still
there: nothing is lost, and nothing is deleted. To undo a restore, restore the version it covered (`conflu versions PAGE` names it). The message of the new version is `Restored version N` unless you give one
with `--message`. The title of the old version comes back only with `--restore-title`; without it the page keeps the title it has. Confluence may refuse a title that another page of the space has (the mock does, with exit code 6); then nothing is saved.

**The content is restored by Confluence itself, not by the CLI.** The request holds the number of the version and a message and no content, so nothing goes through Markdown: macros, mentions, layouts and
everything else that Markdown cannot say come back exactly as they were. (That is the reason to restore with this command rather than to read an old version and write it back with `update`.)

The rules, all checked before anything is sent:

- The version must exist (otherwise "not found", with the version the page is at) and must not be the current one (usage error, exit code 2: there is nothing to restore).
- The page must be current; a page in the trash or archived is not restored (restore it in Confluence first).
- `--if-version N` refuses (exit code 3) unless the page is at version N now, and `--if-unchanged-since ISO` unless nobody saved after that time. An empty `--if-unchanged-since ''` (or a time that cannot be read) is a mistake and is refused
  before anything is asked or sent (exit code 1, also in a dry run): it never means "no guard". Confluence has no version guard for a restore, so both are a check just
  before the write, not a lock: if somebody saves in the few moments between, the page ends up at a later version, and the answer names the version that the page reached and warns when it is not the next one.
- The dry run reads the page and the version and prints the request and a summary: how many lines the restored text adds to and takes from the Markdown of the current one. It sends nothing.
- After a real run the page is read back, and `versionFrom` and `versionTo` of the answer are the version it was at and the version it is at now. When the read-back fails the restore stands and a warning says so.

## Several pages and the files of a page

```bash
conflu page 123456 654321 789012 --outline --json    # three pages, one request
conflu page 123456 --attachments                     # Attachments: 2 (diagram.png, notes.txt)
```

`conflu page PAGE [PAGE ...]` reads up to 250 pages with one request (`GET /api/v2/pages?id=...`); more ids go in further requests. The pages come in the order they were asked for, each once, one after the other with a rule between them
(or `{count, pages[], errors[]}` in JSON). A page that is not there is a line, or an entry of `errors`, and the exit code is 4; the other pages are still printed. The request for several pages gives no labels, and the answer says so.
`--outline`, `--section`, `--max-chars`, `--format`, `--with-users` and the other options apply to every page; `--version`, `--raw` and `--body-only` are for one page. A `page:KEY/Title` reference is looked up first, one by one.
`--raw` prints Confluence's own JSON of the page, so it is refused together with `--comments`, `--ancestors`, `--attachments` and `--outline` (exit code 2, nothing is sent): they would be asked for and then left out.

`--attachments` adds the files of the page (name, size, type and id in JSON), with one more request for each page. File names are redacted like any text unless you add `--with-users`.

## Which request does what

| Command | Requests |
| --- | --- |
| `page --version N` | `GET /api/v2/pages/{id}` for the page now (without its body), `GET /api/v2/pages/{id}?version=N` for the version |
| `page A B C` | `GET /api/v2/pages?id=A,B,C`, and `GET /api/v2/pages/{id}` for an id that was not in the answer |
| `page --attachments` | `GET /api/v2/pages/{id}/attachments` |
| `diff` | `GET /api/v2/pages/{id}` for the page now, `GET /api/v2/pages/{id}?version=N` for each other version |
| `restore` | `GET /api/v2/pages/{id}` (twice: before, and to read it back), `GET /api/v2/pages/{id}?version=N`, and `POST /rest/api/content/{id}/version` (v1: the v2 document has no call that restores a version) |

## What the CLI does not do

- It does not delete a version: nothing here deletes or redacts content.
- It does not compare structure: macros, layouts and mentions are not in the diff (see above), and the diff is of the reading copy, not of the storage format.
- It does not restore a blog post, a comment or an attachment, and it has no versions of a blog post: [blog posts](blog-posts.md) has what it does.
- It does not lock a page: a restore can be guarded, not made exclusive.

## Related guides

- [find-information.md](find-information.md)
- [markdown-and-storage-format.md](markdown-and-storage-format.md)
- [blog-posts.md](blog-posts.md)
- [use-with-ai-agents.md](use-with-ai-agents.md)
