# Blog posts

A blog post is content like a page, kept in a collection of its own: it has no parent, it is not in `pages`, `tree` or `export`, and its title need not be
unique. This guide shows how to find a blog post, read it, publish one and change one, what stays hidden, and what the CLI does not do with blog posts.

The commands follow the Confluence Cloud REST API v2 documentation. They are tested against a mock server that follows the same document, not against a real
site, so try a write with `--dry-run` first.

## Find a blog post

```bash
conflu blogposts --space ENG                                      # the current space (conflu use KEY) when --space is left out
conflu blogposts --space ENG --sort created-date --desc --limit 10  # the latest ones
conflu blogposts --space ENG --title 'Release 2026.10 is out'     # exactly this title
conflu blogposts --all --select id,title,created --format tsv     # the whole site, as TSV
conflu search 'release highlights' --type blogpost --space ENG    # words inside blog posts
```

The list has the id, title, status, version and dates of each blog post (`--json` has the keys of the [reference](../reference/json-output.md#conflu-blogposts---json)).
Without `--space` and without a current space the blog posts of the whole site are listed. An empty `--space ''` (or `--title ''`) is a mistake and is refused (exit code 2), never "not given". `--status` is `current` (the default), `trashed` or `deleted`: a blog post is never
archived. A list comes in pieces: `--limit N` (1 to 250), `--cursor TOKEN` with the same limit, or `--all`; `--select` and `--format table|tsv|md` shape it.

The address of a blog post in the browser has its id (`.../blog/2026/10/15/123456/Release+2026.10`): pass the number or the whole address to `blogpost`. Pages, folders and blog
posts have ids of one sequence, so an id says nothing about its kind; Confluence says when it is asked, and the CLI asks only when a blog post was not found.

## Read one

```bash
conflu blogpost 123456                           # as Markdown, with its labels
conflu blogpost 123456 --outline                 # the headings with the size of each section
conflu blogpost 123456 --section 'Known issues' --max-chars 3000
conflu blogpost 123456 --comments --json         # the footer and the inline comments, each conversation with its replies
conflu blogpost 123456 --format storage --body-only --out post.xml    # the source into a file that the program writes as UTF-8, not with `>`
```

It shows what `page` shows: title, space, status, version, labels, dates and the body, converted from Confluence's storage format to Markdown (`--format text` or `storage` for the others).
`--outline`, `--section`, `--max-chars`, `--no-body`, `--body-only` and `--raw` work as they do for a page (`--raw` prints Confluence's own JSON, so it is refused together with `--comments`, which would be asked for and then left out), and `--comments` adds the footer comments first and then the inline ones, each conversation as its
first comment followed by its replies. The Markdown is a reading copy: what it cannot say (macros, mentions, layouts) is named in `dropped`. A blog post that is read costs two requests (the blog post and
its labels), and more only for comments or `--with-users`.

An id that is a page, a folder or another kind of content is "not found" (exit code 4), and the hint says what it is and which command shows it: `2002 is a page, not a blog post.` / `Use `conflu page 2002`.`

## Publish one

```bash
conflu blogpost-create --space ENG --title 'Release 2026.11 is out' --file post.md --labels release,news --dry-run
conflu blogpost-create --space ENG --title 'Release 2026.11 is out' --file post.md --labels release,news --json   # "blogpostId": the new id
conflu blogpost-create --title 'Weekly update' --body 'Nothing to report.'                                      # in the current space
```

The body is Markdown (converted to storage format), or storage format with `--format storage`; `--file -` reads it from standard input. A blog post without a body is fine. The dry run asks for the space,
proves that it exists and prints the payload that a real run sends (`POST /api/v2/blogposts`); nothing is created. The labels are added with a second request, the call that is keyed by the id of any content
(`POST /rest/api/content/{id}/label`, v1: the v2 document has no call that adds a label). When that request fails the blog post is there, and the error says so and names its id.

**A blog post may share its title with another one**: Confluence does not forbid it, so the CLI looks for no other blog post with the title and does not stop you. Look first (`conflu blogposts --title ...`)
if two with one title would be a mistake.

## Change one

```bash
conflu blogpost-update 123456 --title 'Release 2026.10 is out!' --dry-run
conflu blogpost-update 123456 --file addendum.md --append --message 'Added the known issues' --if-version 3
conflu blogpost-update 123456 --file post.xml --format storage --dry-run
```

- The text **replaces** the body, or is put behind it (`--append`) or in front of it (`--prepend`); the last two keep everything that is there. Prefer them.
- **Replacing a body with Markdown is refused when the blog post holds what Markdown cannot say** (macros, mentions, layouts ...), because that would drop it: the error names what would be lost. Add text with
  `--append`, give the body in storage format, or replace it anyway with `--force`.
- **The API has no call for the title only.** A change of the title sends the whole body along, as it is; the body is read first, in the same request that the guards use.
- The new version number is the current one plus one, so Confluence itself refuses a write when somebody saved in between (exit code 3). `--if-version N` refuses unless the blog post is at that version now, and
  `--if-unchanged-since ISO` unless nobody saved after that time (exit code 3 too); both are checked in a dry run as well. An empty `--if-unchanged-since ''` or a time that cannot be read is refused before anything is sent (exit code 1): it never means "no guard". A title and a body that are as asked already are `unchanged`: nothing is sent.
- A blog post in the trash is not changed (restore it in Confluence first). An empty file is refused rather than clearing the body; to clear it on purpose give `--body ''`.

## What stays hidden

People stay out of the output as everywhere in the CLI: `author` and the people in a version or a comment are `null` until `--with-users`, mentions read as `@user`, e-mail addresses as `[email]` and personal
links are redacted, in the Markdown and in the titles. The address of a blog post ends with its title, and a title can hold an e-mail address (as `%40`): then the address that is printed ends at the id,
which opens the same blog post. `CONFLUENCE_HIDE_USERS=true` refuses `--with-users`. The key of a personal space is the account id of its owner, so `blogposts --space ~KEY` lists it as `[hidden]`, and a
link in the Markdown to a page in it reads `page:[hidden]/Title`.

The payload of `blogpost-update` holds the whole body, and the body may hold mentions. Without `--with-users` the payload that is **printed** (dry run or not) has the account ids blanked and the addresses redacted,
and `payloadRedacted` says so; the request that is **sent** is the body as it is, so mentions survive. With `--with-users` the payload is shown exactly. A body read without people (`blogpost --format storage`)
has its mentions blanked and is refused by `blogpost-update` and `blogpost-create`, so a copy cannot damage a blog post.

## Which request does what

| Command | Requests |
| --- | --- |
| `blogposts` | `GET /api/v2/spaces` (the key to the id), `GET /api/v2/spaces/{id}/blogposts` or `GET /api/v2/blogposts` |
| `blogpost` | `GET /api/v2/blogposts/{id}`, `GET /api/v2/blogposts/{id}/labels`; with `--comments` the footer and inline comments and their replies |
| `blogpost-create` | `GET /api/v2/spaces`, `POST /api/v2/blogposts`, and with labels `POST /rest/api/content/{id}/label` (v1) |
| `blogpost-update` | `GET /api/v2/blogposts/{id}`, `PUT /api/v2/blogposts/{id}` |

## What the CLI does not do

- It does not delete, trash or restore a blog post, and it does not change the labels of one that exists (`conflu label` works on pages); labels are added when a blog post is created.
- It has no versions of a blog post: `page --version`, `diff` and `restore` are for pages ([history and restore](history-and-restore.md)).
- It does not move a blog post, and a blog post has no parent: it is not below a page or a folder, and it is not in `conflu tree` or `conflu export`.
- It does not write comments on a blog post: `blogpost --comments` reads them, and the comment commands are the place for the rest.

## Related guides

- [find-information.md](find-information.md)
- [history-and-restore.md](history-and-restore.md)
- [markdown-and-storage-format.md](markdown-and-storage-format.md)
- [folders-and-structure.md](folders-and-structure.md)
