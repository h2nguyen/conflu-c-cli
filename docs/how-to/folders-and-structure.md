# Folders and structure

A space is a tree. Besides pages it holds **folders**, whiteboards, databases and smart links, and a page may sit
below any of them. This guide shows how to find the id of a folder, publish pages below it, make a folder, read what
is in the tree and move a page into a folder, and it names what the CLI does not do.

The commands follow the Confluence Cloud REST API v2 documentation. They are tested against a mock server that
follows the same document, not against a real site, so try a new command with `--dry-run` first.

## Find the id of a folder

A folder has an id like a page. The REST API v2 has no call that lists the folders of a space, so you find one of these ways:

- **The address in the browser.** Open the folder: the address ends in `/folder/7001`. Pass the number, or the whole
  address, to any command that takes a folder: `conflu folder https://example.atlassian.net/wiki/spaces/ENG/folder/7001`.
- **`conflu tree PAGE`.** A folder below a page shows with its type: `Guides  [7001] (folder)`.
- **`conflu folder ID --children`.** Lists what sits directly below a folder, folders included, with their ids.

A folder at the top of a space is not below the home page, so `tree` of the home page will not list it: copy its address.

```bash
conflu tree 123456 --depth 2                       # folders below a page, with their ids
conflu folder 7001 --children --select id,type,title --format tsv
conflu folder 7001 --ancestors                     # the path from the top of the space
```

## Publish below a folder

`--parent` takes the id or the address of a page, a folder, a whiteboard, a database or a smart link of the same
space. The request is the one that always created a page (`POST /api/v2/pages` with a `parentId`); the dry run adds
what the parent is:

```bash
conflu create --space ENG --parent 7001 --title 'Getting started' --file start.md --dry-run
conflu create --space ENG --parent 7001 --title 'Getting started' --file start.md --json
conflu page 20011 --json            # "parentId": "7001", "parentType": "folder"
```

`import-md --parent` and `import-md-dir --parent` do the same for Markdown files, and so does the `parent:` line of
the front matter (it counts when a page is created). `conflu export` writes that line with the id of whatever the
parent is; see [publish Markdown](publish-markdown.md) and [export and sync](export-and-sync.md).

```bash
conflu import-md-dir docs/guides --space ENG --parent 7001 --dry-run
```

A blog post or a comment cannot be a parent: the error says what the id is. An id that does not exist, or that this
account may not see, is "not found" (exit code 4). A parent must be in the space of the new page. A `--parent` or a
`--space` that is given and empty is a mistake (exit code 2, nothing is asked), never the home page or the current
space: leave the option out for those.

## Make a folder

```bash
conflu folder-create --title Guides --space ENG --dry-run
conflu folder-create --title Guides --space ENG --parent 123456 --json     # "folderId": the new id
conflu smartlink-create --url https://example.com/roadmap --title Roadmap --space ENG --parent 7001 --dry-run
```

Confluence does not forbid two folders with one title, and no call lists the folders of a space, so the dry run cannot
say whether the title is taken: look first (`conflu folder ID --children` of the parent) if that matters. Without
`--parent` the request names no parent. A smart link needs an `http` or `https` address (at most 2048 characters, no
user name or password, no blank or control character); it is shown as you gave it.

## Read what is in the tree

| Command | Shows |
| --- | --- |
| `conflu folder ID` | A folder: title, space, status, version, parent. `--children` lists what sits below it, `--ancestors` the path. |
| `conflu whiteboard ID` | The same for a whiteboard. Its drawing cannot be read: the REST API has no call for it. |
| `conflu database ID` | The same for a database, and `--fields`, `--views` or `--entries` (one at a time). |
| `conflu smartlink ID` | The same for a smart link, with the address that it shows. |
| `conflu tree ID` | Everything below a page, a folder, a whiteboard, a database or a smart link. |

A list (`--children`, `--fields`, `--views`, `--entries`) comes in pieces: `--limit N`, `--cursor TOKEN` with the same
limit, or `--all`; `--select` and `--format table|tsv|md` shape it. People stay out: authors, owners and the people in
the cells of a database are hidden until `--with-users`, text and links in a cell have e-mail addresses and personal
links redacted, and `CONFLUENCE_HIDE_USERS=true` refuses `--with-users`.

**A personal space is a person as well.** Confluence keys it by `~` and the account id of its owner, so without
`--with-users` the key is `[hidden]` and an address in it has `[hidden]` in the place of the key (`.../spaces/[hidden]/folder/7001`);
the address of a page in it names the page by its id alone (`.../pages/viewpage.action?pageId=123`). `tree`, `export`,
`folder-create` and `smartlink-create` have no `--with-users`, so they always print `[hidden]`, also for a key that you typed yourself.

The entries of a database come with `columns` that name the fields, and every entry has its value for each field,
keyed by the id of the field. Atlassian marks the entries API experimental, so its shape may change.

`conflu page` of the id of a folder says that it is a folder and names the command: pages and folders have ids of
one sequence, and only Confluence knows which is which.

`conflu export --page ID` accepts a folder as its start: it exports the pages below it (the folder itself is not a
page, and the `notes` of the result say so). Of a personal space the files carry `space: [hidden]`, and `import-md`
takes the space of a new page from `--space` when it reads that line.

## Move a page below a folder

```bash
conflu move 123456 --to 7001 --dry-run
conflu move 123456 --to 7001 --if-version 7
```

The API v2 has no call that moves a page next to another one, but `PUT /api/v2/pages/{id}` takes a new `parentId`.
So a move below a folder (or a whiteboard, a database, a smart link) **saves the page again**, as the next version, with
its title, status and body as they are (mentions and macros included) and a version message `Moved below ...`:

- Only `--position append` is possible, because a folder can only be a parent.
- The dry run prints that request. Without `--with-users` the people and addresses in the body are redacted in the
  copy that is printed (`payloadRedacted` says so), and the address of the page is redacted as every address is (it ends
  at the id when the title in it holds an address, and in a personal space it names the page by its id alone); what is
  sent is the page as it is.
- Confluence merges every such save into an unpublished draft of the page, if somebody has one open, and may replace
  that draft when the two differ much (the description of `updatePage` says so). The CLI cannot see a draft: move a
  page that somebody is editing only after they have published or closed it.
- A page that is below the folder already is left alone (`action: unchanged`).
- Somebody who saves the page in between turns the move into a conflict (exit code 3), and `--if-version` and
  `--if-unchanged-since` guard it like `conflu update`. An empty `--if-unchanged-since` is refused (exit code 1,
  before anything is asked, in a dry run too): it never means "no guard".
- Below, before or after another **page** the move is the v1 call as before; it saves no version. The page is read
  again afterwards: if that read fails the move still counts (exit code 0, a warning, `confirmed` is `null` in the
  JSON), and nobody should repeat it.
- `--position before` and `--position after` are refused (exit code 1, in a dry run too) when the target is a page at
  the top level of its space, the home page included: the description of `movePage` says never to move a page before
  or after one, because the page would land at the top level too, where it does not show in the page tree. Use
  `--position append` to move the page below a parent, or name a target that has a parent.

## What the CLI does not do

- It does not rename, move or delete a folder (the API has no move, and nothing here deletes).
- It does not list the folders of a space, and it cannot read a whiteboard.
- It does not move a page into another space: a page is created, and moved below a folder, within one space.

## Related guides

- [publish-markdown.md](publish-markdown.md)
- [export-and-sync.md](export-and-sync.md)
- [find-information.md](find-information.md)
- [use-with-ai-agents.md](use-with-ai-agents.md)
