# Changelog

All notable changes to conflu-c-cli are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html): `MAJOR.MINOR.PATCH`.

## [Unreleased]

## [1.1.0] - 2026-11-01

Everything below was run against the bundled mock Confluence Cloud server and in-memory fakes only; no real site was used. Use `--dry-run` first,
and `conflu doctor` as the check against your own site.

### Added

- **The supported API versions are stated and checked.** The CLI is written for the Confluence Cloud REST API **v2** as the default and for **v1**
  only where v2 has no equivalent ([compatibility](docs/reference/compatibility.md)). The operations of both OpenAPI documents (252 and 130, read
  on 2026-10-30 and again on 2026-11-01 without a difference, the deprecated ones marked) sit in `tests/support`, the mock server answers HTTP 404 to a call that the matching document does not
  list and records it (also a call to a deprecated operation), and a sweep of every command proves that each one sends documented calls only, that
  every call to v1 has its reason, and that the compatibility page names exactly the calls that each command made.
- `conflu version --json` has the new key `confluenceCloud`: the two REST APIs the CLI is written for, their base paths, the version each document
  states and the day they were read. `conflu doctor` has the new check `api`, which says whether v2 and v1 both answered on your site (`warn`, with a
  hint, when only one did, which is what a Data Center address looks like).
- **A search text needs no quotes, and a file or a pipe can carry it.** `conflu search story points reference --space ENG` takes several words. The text and `--cql` can
  come from a file or from standard input (`conflu search '@query.txt'`, `conflu search --cql -`), the form that survives Windows PowerShell 5.1, which removes double quotes
  inside an argument. `--phrase 'exact words'` (repeat it) adds an exact phrase without a double quote to type.
- **`conflu api` can preview and build a query.** `conflu api ... --write --dry-run --json` prints the request as one JSON object (`dryRun`, `method`, `path`, `query`, `body`);
  `--param KEY=VALUE` (repeat it) adds URL-encoded query parameters, so no `&` has to survive cmd.exe or PowerShell; a real call with `--json` prints Confluence's answer as JSON.
- **`--json-envelope`** on every command (or `CONFLUENCE_JSON_ENVELOPE=1`): exactly one JSON object on standard output, `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`,
  whatever happens, for a tool that drops standard error or reports every exit code as 1. The exit code and standard error stay as they are.
- **`--select a,b.c` and `--format table|tsv|md`** on `pages`, `spaces`, `versions`, `search`, `labels`, `attachments` and `tree`; `--select` and `--list-format` on `comments`
  (its `--format` is the format of the comment text). Keep only some keys of every item in the JSON, or print the list as a table, TSV or Markdown.
- **`conflu help --brief`** lists every command with its arguments and main options in one short text, in at most 4 KB when the CLI has about 70 commands. The skill carries
  the arguments and all options of `page`, `search`, `update`, `create`, `comment` and `api`, generated from the same command descriptions.
- **The profile `CONFLUENCE_PROFILE=agent`** for a program that runs the CLI: people hidden, JSON the default, no informational messages on standard error.
  `conflu config show` lists what the profile sets (the source is `profile`).
- **`conflu doctor` is cheap enough to run at the start of every session.** `--quick` asks Confluence at most twice (who the token belongs to, and the list of spaces) and leaves
  out the check of the current space. `--cached AGE` (`30s`, `10m`, `2h`, `1d`; a bare number counts in minutes) answers from the online checks of the last successful run that
  is not older, asks Confluence nothing and says when that run was (`cached` and `cachedAt` in the JSON). A run in which a check failed is never reused. That is the one thing the
  CLI remembers between two runs: a small file in `~/.cache/conflu-c-cli` (`XDG_CACHE_HOME` first) that holds the checks and no token, no e-mail address and no person;
  `python install.py --uninstall --purge` deletes it. Nothing you read from Confluence is cached.
- **`conflu doctor --strict-privacy`** fails (exit code 1) whenever people can still be shown, with the settings that fix it. The `privacy` check says when the profile is what
  hides them, and warns when the profile is on but `CONFLUENCE_HIDE_USERS` was set to `false`.
- **`conflu doctor` checks the launcher.** The new check `launcher` says where `conflu` is found on the PATH of the shell, or warns (no failure) that it is not, how this run was
  started and the exact `python install.py --bin-dir DIR` command. When its folder is not on the PATH, the installer now prints the exact command for a folder that is on the PATH,
  that you can write to and that already holds the launcher of the sibling `jira` CLI.
- **`conflu setup --discover`** (for the person) finds the gateway address of your site. It asks the host named by `CONFLUENCE_BASE_URL` for its public tenant information
  (`/_edge/tenant_info`, with no credential and without following a redirect) and proposes `https://api.atlassian.com/ex/confluence/CLOUD_ID`, the address that API tokens with
  scopes use and the way out on a custom domain, where API tokens are refused. On a terminal it asks before it saves, `--yes` saves without asking, `--dry-run` writes nothing, and
  without a terminal it prints the `conflu config set` command. A token without scopes works on the site address.
- **Pages can be published below a folder.** `conflu create --parent`, `conflu import-md --parent`, `conflu import-md-dir --parent` and the `parent:` line
  of a Markdown file take the id or the address of a page, a folder, a whiteboard, a database or a smart link of the same space, and the dry run says what
  the parent is (`parentType`, and `parent` with its id, type and title, next to the unchanged `payload`). A page asked for first costs no more than it did;
  for any other id one request says what it is. `conflu page ID --json` shows the folder as the parent. A blog post or a comment is refused with a message that
  says what the id is; an id that does not exist is "not found" (exit code 4), also when the request that says what an id is fails: that answer only explains a 404 and never replaces it
  (the same holds for `tree`, `export --page` and `move`).
- **`conflu tree` and `conflu export --page` start at a folder** (or a whiteboard, a database, a smart link), not only at a page: the JSON of `tree` has
  `root.type`, and an export of a folder writes the pages below it (the `notes` of the result say that a folder is not a page; the front matter has the id of
  the folder as `parent`, and the `path` names it). A folder id given to `conflu page` says that it is a folder.
- **`conflu move PAGE --to FOLDER`** puts a page below a folder, a whiteboard, a database or a smart link. The API v2 has no move call; it does let `PUT /pages/{id}`
  name a new parent, so the page is saved again, as the next version, with its body untouched and the message `Moved below ...`. The dry run shows that request and
  says that it saves a new version; a page that is below the folder already is `unchanged`; only `--position append` is possible. `move` also has `--if-version` and
  `--if-unchanged-since` now (for either kind of target), and its JSON has `target` and `payloadRedacted`: the printed request has the people and addresses of the page
  body redacted unless you add `--with-users`. A folder cannot be moved: the API has no call for it. A move below or next to another page is the v1 call that it was.
  Confluence merges the save of a move below a folder into an unpublished draft of the page, if somebody has one open, and may replace that draft: the dry run says so, and the CLI cannot see a draft.
- **New commands to read the structure**, group `Structure`: `conflu folder ID [--children] [--ancestors]`, `conflu whiteboard ID`, `conflu database ID [--fields | --views | --entries]`
  and `conflu smartlink ID`, with `--limit`, `--cursor`, `--all`, `--select` and `--format` for the lists, people only with `--with-users`, and titles, text in a cell
  and personal links redacted otherwise. The entries of a database come with the fields that name their cells (Atlassian marks that API experimental); a whiteboard
  has no content that the REST API returns, and `conflu whiteboard` says so.
- **New commands to create structure**: `conflu folder-create --title T [--space KEY] [--parent ID]` and `conflu smartlink-create --url URL --title T`, both with `--dry-run`, and the
  new id in the result. Confluence allows two folders with one title and no call lists the folders of a space, so the dry run cannot say whether a title is taken. The address of a smart link
  must be http or https, without credentials and at most 2048 characters. The guide [folders and structure](docs/how-to/folders-and-structure.md) has the whole story.
- **`conflu mcp [--allow-write] [--allow-files] [--show-users] [--group NAME]`: a local MCP server** on standard input and output, for an MCP client such as GitHub Copilot in VS Code
  (`.vscode/mcp.json`: `"type": "stdio", "command": "conflu", "args": ["mcp"], "cwd": "${workspaceFolder}"`; the guide [use the CLI as an MCP server](docs/how-to/mcp-server.md) also covers another
  client and what to do when the launcher is not on the `PATH`). JSON-RPC 2.0, one message per line, protocol versions 2025-06-18, 2025-03-26 and 2024-11-05, standard library only. The commands that
  `conflu commands --format mcp` describes are the tools (`conflu_page`, `conflu_search`, ...): a call runs inside the server process, with no shell and a new application for every call (the settings
  file and the token are read again, and what a run asks of Confluence is asked again), and answers with what the command prints with `--json`. The tools that change Confluence are offered only with
  `--allow-write`, the two that write files (`download` and `export`) only with `--allow-files`, and a path in a call must lie below the folder the server was started in. A failure is `isError: true` and
  the error object (`code`, `message`, `hint`, `exitCode`, `details`), and a result over 100,000 characters is cut with a note. `--group` keeps only the commands of some groups of `conflu help`; `mcp`
  itself, the commands for the person and `api` are never offered. It was run against the bundled mock server only, as a child process over pipes in the tests: no MCP client such as VS Code was at hand
  and no real Confluence site was used. Nothing else in the CLI depends on it.
- **`conflu commands --format mcp --group NAME`** (repeat it) lists only the tools of some groups of `conflu help`, and `_meta.conflu.groups` names them. The whole set is a lot of text for the context
  of a model, so the guide states three numbers that a test holds: 7,000 characters for one tool, 2,800 for a tool on average over a set, and 40,000 for all the tools of one group. Over `conflu mcp`
  the listing leaves out the argument table and the examples of `_meta.conflu`, which a program that builds a command line itself needs (`conflu commands --format mcp` has them): they were a quarter of it.
- **What the CLI sends is checked down to the parameters, and four things were put right.** Next to the lists of operations, the test suite now holds what each
  operation of the two OpenAPI documents says about its query parameters (the required ones, the documented maximum of `limit`), its required headers and the top-level
  properties of its request body (`tests/support/confluence_cloud_v2_parameters.txt` and `confluence_cloud_v1_parameters.txt`, written by `scripts/update_endpoint_lists.py`
  from the same two documents). The mock Confluence answers HTTP 400 to a request that does not fit (`strict_parameters`, which the sweep of every command turns on), and the
  sweep names the command line that sent it. Reading every REST call against the documents found four things that no test of the mock could see: `conflu comment PAGE --reply-to ID`
  no longer names the page next to the parent comment (the document says not to; the parent is read first and must be a comment of that page, else "not found"); `conflu page`
  shows every label of a page and not only the first 50 that the answer holds (when the request for the rest fails, the 50 are shown and a warning says so); `conflu move PAGE --to PAGE --position before|after` is refused when the target is a page at the
  top level of its space, where the document says never to move a page before or after one; and the ancestors of an item are asked for again, as the document says, when one
  call does not hold them all. A second pass found two more: `conflu attachment ID --labels` asked for the labels with `att5101` where the v2 document types that one id as a number
  (it sends `5101` now), and the labels of a search hit were lost when the answer holds them as a plain list, which the v1 document allows. The test suite also reads the REST
  adapters for the query parameters they can send and fails for one that no line of the sweep sends, and the same for the options of every command: each is named by some
  sweep line (so that the strict mock judges its request and the privacy sweep reads its output, also the file that `--out` writes) or has its reason in a short table. All of this ran against the bundled mock only.
- **Blog posts.** The new group `Blog posts` has four commands: `conflu blogposts [--space KEY] [--title TEXT] [--status current|trashed|deleted] [--sort ...] [--all]` lists the blog posts of
  a space (or of the site), `conflu blogpost ID` reads one by its id or by the address copied from the browser (with its labels; `--comments` adds the footer and the inline comments with their
  replies; `--outline`, `--section`, `--max-chars`, `--no-body`, `--body-only`, `--format` and `--raw` work as they do for `page`), `conflu blogpost-create --title T [--space KEY] [--file F | --body TEXT]
  [--labels a,b]` publishes one, and `conflu blogpost-update ID [--title T] [--file F | --body TEXT] [--append | --prepend]` changes its title or its body. Both writers have `--dry-run`, which shows
  the payload and sends nothing; the update has `--if-version` and `--if-unchanged-since` (exit code 3 when somebody saved meanwhile; an empty or unreadable time is refused with exit code 1, never taken for "no guard"), `--message`, and refuses to replace a body with Markdown that
  would lose what Markdown cannot say (macros, mentions) unless `--force`. A blog post may share its title with another one, so a creation looks for no title; the API has no call for the title only, so a change
  of the title sends the body along as it is. People stay hidden: titles and addresses are redacted, and the payload that `blogpost-update` prints has the people in the body blanked unless you add
  `--with-users` (`payloadRedacted` in its JSON says so; what is sent always has them, so mentions survive). The guide [blog posts](docs/how-to/blog-posts.md) has the whole story.
- **Earlier versions of a page.** `conflu page PAGE --version N` reads that version as it was saved (its title, its body and its version; the labels, the status and the place in the tree are those of the page now),
  and says in the text and in the JSON (`version.current`, `currentVersion`) that it is not the current one. The outline, the section, `--max-chars`, `--format`, `--raw` and `--attachments` work on it;
  `--comments` and `--ancestors` are refused with it, because they are those of now. A version the page does not have is "not found", with the version it is at and `conflu versions PAGE` in the hint.
  `--raw` prints Confluence's own JSON, so it is refused (exit code 2, nothing is sent) with `--comments`, `--ancestors`, `--attachments` and `--outline`, which it would leave out.
- **`conflu page PAGE [PAGE ...]` reads several pages with one request** (at most 250 ids at a time, the pages one after the other with a rule between them, or `{count, pages[], errors[]}` in JSON). A page that is
  not there is a line (an entry of `errors`) and exit code 4, and the other pages are still printed; the request for several pages gives no labels, which the answer says. `--outline`, `--section` and the
  other options apply to every page; `--version` and `--raw` are for one page.
- **`conflu page PAGE --attachments`** adds the files of the page: `Attachments: 2 (diagram.png, notes.txt)` in the text, `attachments[]` and `attachmentTotal` in the JSON, one more request. File names are redacted
  like any text unless you add `--with-users`.
- **`conflu diff PAGE [--from N] [--to N|current] [--context LINES] [--max-chars N]`** shows what an edit changed: a unified diff of the Markdown of two versions (the current one against the one before it by default),
  with the people hidden (`@user`, `[email]`), `added` and `removed` counts and, in `dropped`, what Markdown cannot show (macros, mentions), which is not compared. A page with one version, or two that read the same, says so and is no failure;
  `--to 1` on a page with more versions says that nothing came before version 1 (`identical` is false then).
- **`conflu restore PAGE --version N [--message TEXT] [--restore-title] [--dry-run]`** brings an earlier version back as a NEW version of the page, with `--if-version` and `--if-unchanged-since` (exit code 3). Nothing is lost:
  the history keeps every version, and Confluence itself restores the content, so macros and mentions come back as they were and nothing goes through Markdown. The dry run reads the page and the version and shows the
  request and how many lines the restore adds and takes. It is the v1 call `POST /rest/api/content/{id}/version`, because the API v2 has no restore (the reason is on the [compatibility page](docs/reference/compatibility.md)).
  The guide [history and restore](docs/how-to/history-and-restore.md) shows how to read, compare and restore.
- **`conflu page`, `versions`, `diff`, `restore`, `labels`, `label`, `comments`, `comment` and `update` say what an id is when it is no page** (a folder, a whiteboard, a database, a smart link, a blog post): the same "not found" (exit code 4) with a hint such as
  "7001 is a folder, not a page: use `conflu folder 7001`". `conflu page PAGE --ancestors` shows the title of a folder in the path, which Confluence leaves out of the answer. The address that `conflu restore` and the blog post commands print ends at the
  id when the title holds an e-mail address, which the title itself hides.
- **Comments: read one, correct one, resolve one.** `conflu comment PAGE --get ID` shows one comment with its version and whether it is yours. `--edit ID` replaces the text of a comment (`--text` or `--file`; Markdown, or
  `--format storage`) after reading it: the dry run shows a diff of the old and the new text and the request that a real run sends, a text that is the comment's own sends nothing, and `--if-version` and
  `--if-unchanged-since` refuse (exit code 3) a comment that moved on and are checked again just before the write. A new text is refused when it holds `[email]` or `[personal link]` (what a reading shows in place of an
  address or a profile link, which would overwrite the real one), when it holds mentions that a reading blanked, or when it replaces through Markdown a comment that holds a mention or a macro (`--force` allows that); somebody
  else's comment is Confluence's HTTP 403, exit code 5, with a hint. `--resolve ID` and `--reopen ID` resolve an inline comment and open it again (the comment's own text goes back with `resolved`; a footer comment is a usage
  error, a dangling one is refused), with `--dry-run` and the same guards; the request that is printed leaves out the people and addresses in that text unless you add `--with-users` (`payloadRedacted` says so), and what is sent
  is always the comment as it is. The modes exclude each other, nothing deletes or empties a comment, and all of it was run against the bundled mock server only. An empty value for `--reply-to`, `--get`, `--edit`,
  `--resolve`, `--reopen`, `--since`, `--resolution`, `--if-unchanged-since` or `--file` is an error that names the option (nothing is read or sent, also in a dry run); an empty `--reply-to` used to post a comment of its own.
  The guide [comments and labels](docs/how-to/comments-and-labels.md) has the whole story.
- **`conflu comments PAGE` picks the comments you want and tells the authors apart without names.** `--since 2d|12h|1w|DATE|ISO` and `--last N` keep the recent comments (by the time a comment was last saved, which is when it
  was written unless somebody changed it), `--resolution open|resolved|reopened|dangling` the inline comments in that state (the filter of the API v2). Every comment has `authorRef`, a stable pseudonym of its author (`a-` and
  eight hexadecimal digits of an HMAC-SHA-256 of the site and the account id, keyed with your API token: the same in every command with the same token, `null` without a token, never an unkeyed hash), and `byMe`, whether the
  user of the token wrote it (one more request, only when there are comments; `null` when it fails). The header line of a comment now ends with the pseudonym, or with the name under `--with-users`, and with `(you)` for
  your own. The JSON has the new keys `total`, `since`, `authorRef` and `byMe` next to the old ones. The pseudonym is no person, so `CONFLUENCE_HIDE_USERS=true` still refuses `--with-users` and still shows it.
- **The labels used in a space: `conflu labels --space KEY [--limit N] [--cursor TOKEN] [--all]`** lists the labels that the pages and blog posts of the space carry (`GET /api/v2/spaces/{id}/content/labels`: by name, a piece at
  a time or all of them), with `--select` and `--format`. `conflu labels PAGE` is as it was; a page or a space has to be named, not both, and the current space of `conflu use` is not assumed. `conflu search --label NAME` finds the
  pages that carry a label. Run against the bundled mock server only: Atlassian's description of the call names the prefixes `my` and `team` for its filter, and what a real site answers for the labels that everybody uses
  has not been seen. `conflu label PAGE --add ""` (or `--remove ""`, or a value that holds only commas) is an error that names the option, where it used to be skipped as if it were not given; nothing is read or sent.
- **Look at one attachment: `conflu attachment ID [--versions] [--labels] [--limit N] [--cursor TOKEN] [--all] [--with-users] [--select a,b.c] [--format table|tsv|md]`.** It shows the type, size, version, when the file was
  first attached and when its current version was saved, the page or the blog post that holds it, the comment, and the download address as Confluence gives it (shown, never fetched). `--versions` lists the versions, newest
  first, a page at a time, with what each one said and how large it was (the list has no size, so it is asked for with one request each for the first 50, and the note says so); `--labels` adds the labels. Who saved a version
  comes only with `--with-users`, and a name, a comment or a message with an e-mail address in it is shown redacted without it. `CONFLUENCE_HIDE_USERS=true` refuses `--with-users`. Run against the bundled mock server only.
- **Files of blog posts, and any version of a file.** `conflu attachments BLOGPOST` and `conflu download BLOGPOST --name FILE` / `--all` work when the id is a blog post: a page is asked for first, and only when Confluence says that
  there is none is the id asked what it is (the answer of an id that is a folder or nothing says so). `conflu download ID --version N` (or one `--name` with it) saves that version of one attachment, judged by its own size;
  a version that is not there is exit code 4 with the command that lists them. `--max-bytes N` refuses a file whose listed size is over N before anything is fetched (without it only the 512 MiB cap of the transport applies, as before).
  `conflu attachments` lists `updated` and `blogPostId` too and shows names, comments and download addresses without e-mail addresses unless you add `--with-users`.
- **Read what a file says without saving it: `conflu download ... --text [--max-chars N] [--with-users] [--version N]`.** It prints the text of text files (by media type and by extension; UTF-8, UTF-16 or Windows-1252) and of
  Word, Excel and PowerPoint files (`docx`, `xlsx`, `pptx`), read with the standard library only and with the limits of a reader that does not trust the file: a bounded archive (no ZIP64, no encrypted or bzip2 or LZMA part),
  no document type or entity, bounded parts, tags, names, attributes and text. A picture, a PDF or any other type prints its properties and a hint that points to the plain `download`; a file that is damaged, protected with a
  password, refused as unsafe or binary is an entry with a `hint` that names the kind of the failure and never the content, not a failure of the run. The text is cut at the end of a paragraph after `--max-chars` (20000) and
  says so (`truncated`, `totalChars`), e-mail addresses and mentions are replaced unless you add `--with-users`, and terminal controls, invisible format characters and tag characters are taken out of what is printed. Nothing is
  written (`--out` and `--force` are a usage error with it); a file over 25 MiB is refused unless `--max-bytes` says otherwise. Run against the bundled mock server only.
- **`conflu download` writes more carefully.** Nothing is written into the folder that holds the configuration of the CLI, with `--force` or without, in a dry run too (exit code 2): an attachment named `config` could
  have replaced the token and the address it goes to. The folders are compared by where they are, so `..`, a relative path, a link or another case of a name do not help. A file that appears while a download runs is left as
  it is, a name is cut at 200 bytes (a longer one made a run stop half way), the names of more Windows devices are refused, and a run that fails after it wrote some files says which. The folder the files go into is now declared
  for programs that run the command (`conflu mcp`) as one that files named by strangers are written below, and `download` as a command that writes files.
- **`conflu attach` reads before it writes, guards and refuses what must not be published.** It asks the page for the attachment of each file name, so the dry run (and the real run) says which file becomes a new version of
  which attachment and from which version to which (`replaces`, `versionFrom`, `versionTo`); `--if-version N` (0 says: new) and `--if-unchanged-since TIME` refuse with exit code 3 when that attachment is not as you read it, in a
  dry run too. A file that is the configuration of the CLI (found by its place: a link, `..` or another case do not help) or whose bytes hold the API token (as it is, as the `Authorization` header that carries it, in UTF-8 or
  UTF-16, searched piece by piece) is refused with exit code 2 and nothing sent, in a dry run too; so are two files of one name, and a file that is too large to be searched. A blog post is told apart from a page. The comment goes
  as UTF-8 text, as Atlassian asks, so that one in any language arrives as written. Run against the bundled mock server only.
- **What your account may do: `conflu permissions [ID] [--space KEY] [--only NAME,NAME]`** (new group `Access and people`). It asks Confluence what the account of your token may do with a page, blog post, folder,
  whiteboard, database, smart link, comment or attachment (an id or the address copied from the browser; one request says what the id is), or with `--space` (or the current space) in a space: `yes` or `no` for read,
  update and delete, and every other operation that is allowed, with what it is done to (`create` can be allowed for a comment and not for a page). `--only update,delete` asks about those names, and a name
  that is no operation is refused before anything is asked. The key of a space given as an id is told to use `--space`. It is about your own account only.
- **Who may see or edit content: `conflu restrictions ID [--with-users] [--limit N] [--cursor TOKEN] [--all] [--select a,b.c] [--format table|tsv|md]`.** It shows the restriction that is set on a page, blog post,
  folder, whiteboard or database (`OPEN`, `EDIT_RESTRICTED`, `VIEW_RESTRICTED`, with what each means) and how many users and groups hold read and update; the counts are of all the direct permissions. Who they are
  (account ids of users, ids of groups) and who set the restriction come only with `--with-users`, one piece at a time. A restriction that a parent page or folder sets is not in the REST calls, so `OPEN` does not
  mean that everybody may read it: the answer says so. A smart link, a comment and an attachment have no restriction of their own, and the command says that.
- **Who may use a space: `conflu space-access [SPACE] [--with-users] [--limit N] [--cursor TOKEN] [--all] [--select a,b.c] [--format table|tsv|md]`.** It asks the site for its role mode (`PRE_ROLES`, `ROLES_TRANSITION`,
  `ROLES`), then reads the permission assignments, the role assignments (with the names of the roles) or both, and counts users, groups, roles and access classes per operation or per role; a site that reports no
  mode is asked for both, and one without space roles shows its permissions. Who holds what comes only with `--with-users`.
- **These three only read, and keep people out.** No command changes a restriction, a permission or a role: that stays with the web interface, or `conflu api ... --write`, which previews with `--dry-run`. Without
  `--with-users` there is no account id, group id, display name or e-mail address in an answer, an address in the name of a space or a role is redacted, a personal space comes out as `[hidden]` and `[personal space]`, and
  `CONFLUENCE_HIDE_USERS=true` refuses `--with-users`. They call the REST API v2 only, and were run against the bundled mock server only. The guide [access and restrictions](docs/how-to/access-and-restrictions.md)
  has the whole story.
- **Your own watch: `conflu watching [PAGE] [--space KEY]` and `conflu watch [PAGE] [--space KEY] [--remove] [--dry-run]`** (group `Access and people`). `watching` says whether you watch a page, a blog post or
  other content (an id or the address copied from the browser) or a space (its key); without either it asks about the current space. `watch` starts watching, or with `--remove` stops, and names what it changes: the
  current space is not assumed for a change. It reads the status first, so a watch that is as asked is `unchanged` and nothing is sent; the dry run reads and sends nothing and names the call; after a change the status
  is read again, and if that read fails the change still counts as made (exit code 0, `confirmed` is `null`, a warning says how to check). Only your own watch is ever read or changed: no option names another person.
  A space is named as `conflu spaces` names it: its title is redacted like every title, and a personal space (it is named after its owner and keyed by the owner's account id) comes out as `[hidden]` and
  `[personal space]`, while the call still names the real key.
  `--remove` takes your watch off and removes no content; with `conflu label --remove` it is the one command that sends a `DELETE`. The API v2 has no watches, so these are v1 calls, each with its reason on the
  compatibility page. They were run against the bundled mock server only. The guide [watches and users](docs/how-to/watches-and-users.md) has the whole story.
- **Find a person: `conflu users search NAME --with-users [--limit N] [--start N] [--all]` and `conflu users lookup ACCOUNT_ID... --with-users`.** `search` finds the people whose name holds the text (the older API's user
  search; the API v2 has none), `lookup` shows the people behind up to 250 account ids (the v2 bulk lookup; an id that Confluence does not describe is listed as `notFound`). Each person is the account id, the display
  name, the e-mail address only when Confluence returns one, and the account type. People are the point here, so both are refused without `--with-users` and always under `CONFLUENCE_HIDE_USERS=true` (which the
  `agent` profile sets), and nothing is sent in either case. A name with a double quote or a backslash is escaped in the CQL and stays a text; the name or the ids may come from a file (`'@name.txt'`) or from standard
  input, which survives Windows PowerShell 5.1. `--select`, `--format` and `--json` work as for the other lists. They were run against the bundled mock server only. See [watches and users](docs/how-to/watches-and-users.md).
- **Tasks: `conflu tasks [--space KEY] [--page ID] [--task ID]... [--status incomplete|complete] [--mine] [--created-by-me] [--due-before DAY] [--due-after DAY] [--limit N] [--cursor TOKEN] [--all] [--with-users] [--select a,b.c] [--format table|tsv|md]`**
  (group `Tasks and properties`) lists the checkboxes that are written into pages and blog posts (`GET /api/v2/tasks`) across the site, or narrowed by every filter that the call has: a space (its key), a page or a
  blog post (an id or the address copied from the browser: it is asked what it is first), the tasks with some ids (`--task ID`, given again for each task, at most 250: it reads one task without `conflu task`, which can also
  change it, so a read-only agent can; an id that no task has is just not in the list), a status, the tasks assigned to you (`--mine`) or created by you (`--created-by-me`: one more request finds out who the token
  belongs to, and that account id is never printed), and a range of due days (a day is `YYYY-MM-DD`, counted from 00:00 UTC, both ends in; a task without a due date is in no range; a date that is no day is a usage
  error). The text of a task is plain text without mentions and addresses, and who created, was assigned and completed it is shown only with `--with-users` (which `CONFLUENCE_HIDE_USERS=true` refuses).
  **`conflu task ID [--complete | --reopen] [--dry-run]`** shows a task, or ticks it off or unticks it: the task is read first (a task that is as asked is `unchanged` and nothing is sent), the status is the one thing that the call
  changes and the one thing that is sent, and the task is read again afterwards (if that read fails the change still counts as made: exit code 0, `readBack` is `false`, a warning says so). The dry run reads and sends nothing.
  Nothing creates, edits or deletes a task. They were run against the bundled mock server only. The guide [tasks, properties and templates](docs/how-to/tasks-properties-and-templates.md) has the whole story.
- **Content properties: `conflu properties ID [--key KEY] [--max-chars N] [--with-users] [--limit N] [--cursor TOKEN] [--all]` and `conflu property-set ID --key KEY (--value JSON | --file FILE) [--message TEXT] [--if-version N] [--dry-run]`.**
  `properties` shows what is kept under keys on a page, a blog post, a folder, a whiteboard, a database, a smart link, an attachment (its id starts with `att`) or a comment: the id is asked what it is, and each kind
  has its own collection in the API v2. A value is any JSON, shown as compact JSON and cut at `--max-chars` (2000; `truncated` and `totalChars` say so, a cut value ends in `[value cut]`, and `--max-chars 0` cuts nothing); people (user objects, account ids, addresses, profile links) are
  hidden in the value and in the key unless you add `--with-users`; a value nested too deeply is shown as such, and one that nests beyond what the program can read is an error with a reason (exit code 7) instead of
  a crash. `property-set` creates the property when the key is new and otherwise saves the next version of it (the current one plus one), after reading it: the same value is `unchanged` and nothing is sent, the dry run
  shows the value that is there (without people), the new one and the exact payload, and `--if-version N` (0: it must not exist yet) refuses with exit code 3 before anything is sent, as does Confluence's own HTTP 409
  when somebody saves in between. A new value that is a copy of what `properties` showed is refused with exit code 1 and `details.markers` (or `details.texts`), also in a dry run, because saving it would overwrite what the
  property holds: a value with the stand-ins for its people (`[hidden]`, `[email]`, `[personal link]`, `[personal space]`, `{"hidden": true}`, `[nested too deeply to show]`, or an attribute that was blanked in storage format,
  such as `ri:account-id="hidden"` or `data-userkey="hidden"`), a text that was shown changed (an address without its title), or `[value cut]`, the end of a value that was cut at `--max-chars` (for a new property too).
  Read the whole real value with `--with-users --max-chars 0`, change what you need and write that. The value must be valid JSON of at most 32 KiB and 100 levels, with finite numbers (`1e999` is refused: JSON has no infinity;
  a bare word is a usage error with the hint for Windows PowerShell 5.1: use `--file`, or `--file -`), the key holds
  letters, digits and `_ . : -`. Apps keep their settings in properties, so changing one can change what an app does: there is no undo, and **no command deletes a property**. They were run against the bundled mock server only.
- **Templates: `conflu templates [--space KEY] [--blueprints] [--limit N] [--start N] [--all] [--select a,b.c] [--format table|tsv|md]` and `conflu template ID [--format markdown|text|storage] [--body-only]`.**
  `templates` lists the page templates of a space (without `--space` the global ones; the key is asked for first, so `eng` works and a space that is not there is "not found"), or with `--blueprints` the templates that
  blueprints provide. `template` shows one with what it is, **the variables that it declares** (the `<at:var>` elements that the Markdown copy cannot show, listed from the storage format, each once, and not those in a comment or a CDATA section, which are text; a body of broken tags
  is read in a moment and says that the list may be incomplete) and its body converted like the body of a page, with the people hidden; `--body-only` prints the body alone, for a file. The older REST API (v1) is the only one
  that has templates, so the three calls are v1 calls with their reason on the compatibility page. The API cannot make a page from a template and nothing here does: save the body (`--format storage --body-only`)
  and create the page from the file (`conflu create --file F --format storage`), unless it holds a mention, which comes out blanked and is refused. Confluence answers HTTP 403 for a template that does not exist as
  well as for one that may not be seen; the message says that without repeating Confluence's words. They were run against the bundled mock server only.
- **`--out FILE` saves a body as UTF-8, and the guides no longer say `>`.** `conflu page PAGE --body-only --out FILE`, `conflu blogpost ID --body-only --out FILE`, `conflu template ID --body-only --out FILE` and
  `conflu convert [FILE] --out FILE` write the text that the command would have printed into a file themselves, as UTF-8 without a byte-order mark and with plain line ends, and answer in one line
  (`Wrote N bytes to FILE`; `{"file", "bytes"}` with `--json`; `convert` has no JSON). The old recipe, `conflu page ID --format storage --with-users --body-only > page.xml` and then
  `conflu update ID --file page.xml --format storage`, damaged every character that is not ASCII in Windows PowerShell 5.1 (`Grüße` was saved as `Gr├╝├ƒe`, because `>` decodes the UTF-8 output with the code
  page of the console and stores UTF-16) and wrote the damage back with nothing to warn. A file that exists is not replaced without `--force`, and never the settings file of the CLI, a file in its folder or a file that
  holds the token (not even with `--force`); a folder that is missing is made; the path is judged before Confluence is asked for anything; `page`, `blogpost` and `template` need `--body-only`; what is written is what
  would have been printed, so people stay out unless you add `--with-users`. The commands still only read: `--out` changes nothing in Confluence. Over `conflu mcp` the option is not offered (the text is in the
  result). `conflu convert --source storage` prints the Markdown without the redaction of `page`, because it converts what it is given (its help and the guide said that it prints "the Markdown that `page` shows").
  Run against the bundled mock server and in a child process only, never a real site.
- **Every command names the REST API it uses.** `conflu help COMMAND` has the line `REST API:` (v2; v1 only where v2 has no call; both; or none for a command that works on this computer),
  `conflu commands --json` has the key `api`, and the command reference says it. The table behind it (`src/conflu_c_cli/adapters/driving/cli/apis.py`) is held by a test to what the sweep of
  every command recorded, so it cannot drift from the calls that the commands send.
- A test runs every command line of the sweep three times, with `CONFLUENCE_OUTPUT=json`, with `--json` and with the envelope, and fails, naming the line, when a command that declares JSON
  prints anything but one JSON value, when a failure is not a JSON error on standard error, or when the envelope is not one object.

### Changed

- `conflu download` asks for the file with the documented v1 call (`GET /rest/api/content/{id}/child/attachment/{attachmentId}/download`), built from
  the ids, and no longer follows the `downloadLink` that an answer carries (it is a web address, not a call of either document, and an address that
  came out of an answer is not what the credentials should be sent to). The link is used only for an attachment whose page is not known.
- Text files and standard input are read in whatever encoding Windows wrote: UTF-8 with or without a byte order mark, UTF-16 (what PowerShell 5.1 writes with `>` and `Out-File`),
  UTF-32 or Windows-1252; the settings file too. A byte order mark never reaches a page, a title, a comment or the token, and line ends are plain newlines. A file with NUL
  characters (a picture) is refused with "is not text" instead of being sent as garbage.
- The first argument of `conflu search` is now several words (`conflu commands --json`: kind `words`; its `--phrase` is kind `repeat`). `conflu commands --format mcp` does not offer
  the list format to a model (its calls always ask for JSON).
- A usage error says which command has an option the command lacks, and, for a search text whose double quotes PowerShell 5.1 removed, what to do instead.
- The help of every command lists `--json-envelope`; `conflu help` names `conflu help --brief`.
- `python install.py --uninstall --purge` also deletes the cache file of the program, and its folder when nothing else is in it.
- `conflu attachments --json` has `blogPostId` (at the top and per attachment) and `updated`; `conflu download --json` has `version` per file; `conflu attach --json`
  has `comment`, `minorEdit` and per file `replaces`, `versionFrom` and `versionTo`. `conflu attach` reads the attachments of the page once, for all its files, before it
  writes (a dry run no longer reads the page itself; when the token may not read them (HTTP 403) the files are sent anyway after a warning, unless a guard needs the read, and the
  output says that it does not know which of them replace a file; any other failure of the read stops the command), its text starts with `Dry run: nothing was sent.` and shows `REPLACES` and `VERSION 3 -> 4`, two files of one name in one call are
  refused, and `conflu attachments` shows names and comments without e-mail addresses unless you add `--with-users`.
- **`conflu commands --format mcp --only read` (the default) no longer lists `export` and `download`, and `--only write` lists them besides the commands that change Confluence.** They
  change nothing in Confluence, but they write files on this computer, so they are not read-only: their annotations are `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: true`; `--only all`
  is unchanged. Over `conflu mcp` their descriptions say what they are there (nothing is replaced, a file that exists stops them, and the property `force`, which every command that overrides has, is marked
  "Refused over MCP"); `conflu commands --format mcp` still prints the description for any other client. The text of a tool names properties and tools, not flags and commands, also for a flag that stands in a
  longer span of code (`--format storage` is `format storage` there).
- **A search text that starts with `@` is a file only when that file exists.** `conflu search '@alex'` and `'@example.com'` are searched for as they were in 1.0.0, with a warning that says so (a
  mistyped file name looks the same), and `conflu search '@query.txt'` reads the file when it is there, with a note that says so; to search for the text itself put a space in front of it or use
  `--phrase`. `--cql @FILE` and `-` always read a file or standard input. A name that the file system refuses, such as `@` and 300 letters, is no file either.
- `--raw` of `page`, `blogpost` and `search`, and `conflu api --json`, print one compact line when they are piped (indented only on a terminal), like every other JSON output.
- `conflu commands --format mcp`: the property `page` of `conflu_page` is an array of strings now (several pages in one call).
- Start-up: a call loads only the code it uses (the module of its command, the use cases it needs, the code that talks to Confluence and the models of the area it reads) instead
  of the whole program, so the 27 new commands cost nothing to the commands that do not use them. On a Windows computer with a virus scanner (Python 3.13; medians of 11 runs against the
  bundled mock server; 1.0.0, then this release) `conflu version` takes 255 and 185 ms, `conflu config show` 289 and 218 ms, `conflu current` 280 and 219 ms, `conflu pages` 334 and 318 ms,
  `conflu search` 317 and 315 ms and `conflu page` 318 and 327 ms (the best of the runs are 311 and 309 ms): a command that asks Confluence takes as long as before, and one that does not is a quarter quicker.
- CI: the time limit of a test job is 20 minutes (the suite has grown from 939 to about 5,200 tests), like the sibling CLI.
- `.gitattributes`: `*.txt text eol=lf` (the endpoint and parameter lists are compared byte for byte).
- Exit code 7 also covers HTTP 429 after the retries; `docs/reference/exit-codes.md` says so and names 130 (interrupted) and 141 (the reader of the output went away).
- The samples in `examples/` no longer carry `parent: 123456`: they are published below the home page of the space. A `parent:` line or `--parent` publishes below a page or a folder.
- The guides on installing and on AI agents say that an installed skill is a copy: after an update, `conflu skill install --dir DIR --force` brings it to the version of the program.

### Fixed

- A base URL that holds a user name or a password (also a password with a `/`, `?` or `#` in it) is no longer printed by `conflu config show`, `conflu doctor`, `conflu ping` or in an
  error text; `conflu config set` refuses it without repeating it.
- `127.example.com` is no longer taken for an address on this computer; only `localhost` and the loopback addresses are.
- `CONFLUENCE_CONNECT_TIMEOUT` and `CONFLUENCE_MAX_TIME` are refused above 86400 seconds: a larger value made the socket layer fail with an `OverflowError`.
- A `Retry-After: nan` (or `inf`) from a server no longer crashes the wait before a retry; the usual wait is used.
- A request address that holds a space or a control character is a usage error (exit code 2) that sends nothing and tries nothing again, instead of "Cannot reach Confluence" after
  the retries.
- A base URL with an IPv6 address and no port (`http://[::1]/wiki`) is no longer read as a host with a port.
- `conflu update --file` with an empty file or an empty pipe is refused instead of clearing the body of the page (an editor that saved nothing, a pipe that failed); to clear it on purpose
  give `--body ''`.
- A download of an attachment whose name was longer than a file system takes stopped half way: names are cut at 200 bytes now. The comment of `conflu attach` could be read
  in another encoding by Confluence: it is sent as UTF-8 text. A file that appeared while a download ran could be replaced: it is checked again just before the write.
- **A file or a pipe that does not end no longer makes a command read for ever.** `conflu search --cql @FILE` believed the size that the file says, and a device or a pipe
  says 0; `--file`, `convert`, `api --data-file`, `import-md` and standard input had no limit at all. A search text or a query is read up to 1 MiB and any other text up to
  16 MiB, one byte beyond the limit and no further, and a longer one is refused (exit code 2) with a message that names the limit.
- **An empty value is no longer taken for "not given" by `conflu move`, `create`, `folder-create`, `smartlink-create`, `import-md` and `import-md-dir`.** `move --if-unchanged-since ''`
  removed the guard, and `--parent ''` or `--space ''` put the new page, folder or smart link at the default place or into the current space. An empty `--if-unchanged-since` is
  refused now (exit code 1, before anything is asked, in a dry run too), and an empty `--space` or `--parent` is a usage error (exit code 2: "The space is empty." / "The parent is
  empty."), also for `import-md-dir` as a whole: nothing is asked or made. Leave the option out for the default.
- **`conflu move PAGE --to PAGE` no longer fails after the page was moved.** The page is read again after the move, and when that read failed the command ended with exit code 7 and
  no output, although the move was made, so somebody would repeat it. It ends with exit code 0 now, prints what it knows and warns on stderr; the JSON of `move` has `confirmed`
  (the page is below its new parent: `true`, `false` when it is not, `null` when nothing was moved or it could not be read back) and `message`.
- **A value with a line break no longer locks you out of the configuration.** `conflu config set CONFLUENCE_SPACE $'ENG\nX'`, or the text of a certificate pasted into
  `CONFLUENCE_CA_BUNDLE`, wrote a line that cannot be read, and after that every command failed with "CONFLUENCE_SPACE has unbalanced quotes", `conflu config set` and
  `config unset` (the commands that the hint named) too: only editing the file by hand helped. A value with a control character, a line separator or a paragraph separator
  is refused now (exit code 1; the message names the setting and says what to do; the file is left as it was). The file is read at `\n`, `\r\n` and `\r` only, and a line that
  cannot be read is named by its number and its file, with the command that mends it. `config set`, `config unset`, `config path`, `setup-token`, `remove-token` and
  `clear-space` work on such a file; every other command refuses it, as before, and asks nothing of Confluence.
- **An answer that cannot be used is exit code 7 with a message that blames the answer, not an "unexpected" error and not your address.** A redirect whose `Location` no parser
  takes (`http://[`), a download that is redirected to an address with a space, a letter that no address can hold or a port that is no number (nothing is sent to it), a `totalSize`,
  `start` or `limit` that is no number, a search that answers something other than an object, a link to the next piece of a list that cannot be read, a `Content-Length` of
  thousands of digits and tenant information that nests 60 000 deep ended as exit code 1 or 2, as an unexpected error or as "Cannot reach Confluence" after the retries.
- **`CONFLUENCE_MAX_TIME` is the time for a whole answer now.** It was the time to wait for the next bytes, so a server that sent one byte every few seconds kept a command
  waiting for hours. The time is counted from the end of the request (a slow upload has not used it up); an answer that is not in by then is cut off ("the time allowed for it
  (CONFLUENCE_MAX_TIME) was up") and a read is asked for again, as after any network error. The default is 120 seconds: a big download over a slow link needs more
  (`conflu config set CONFLUENCE_MAX_TIME 600`, which the hint suggests). A gzip answer of more than 16 members is refused as an answer that could not be read.
- **`conflu attach` no longer loses its guard, and says which files went when a later one fails.** `attach --if-unchanged-since ''` (the value of a variable that is not set) removed
  the guard, so the file was uploaded over an attachment that had changed; it is an error that names the option now (exit code 1, before anything is asked, in a dry run too).
  When `attach A B` failed on `B` after `A` had gone, the error did not mention `A`, which was on the page already, and running the command again made another version of it:
  the error now keeps its kind and its exit code and says how many files went and which (`details.uploaded`), and the hint names the files that are left. The type of an attachment
  is redacted in `conflu page --attachments` and in the hint of `download --text`, as it is in `attachments`, and `conflu attachment ID --versions --labels` with `--select` or
  `--format` as text is refused (exit code 2) instead of printing the versions and dropping the labels without a word.
- **The words of a refusal no longer name people.** Confluence explains a refusal in a sentence (`No user found for alex@example.com (accountId 5b10ac8d82e05b22cc7d4ef5)`), and
  the explanation was printed as it came: in the message of every error that has one (400, 403, 404, 409, 5xx) and in `details.confluence`. `CONFLUENCE_HIDE_USERS=true` replaced
  the e-mail address and left the account id in the sentence. The explanation has no e-mail address (`[email]`), no link to a person (`[personal link]`) and no account id
  (`[account id]`: 24 hexadecimal digits, or the older number, colon and UUID) now, whatever the policy, also when `--with-users` was given (an error has no such option);
  page texts are not scanned for account ids, where a run of 24 hexadecimal digits is as often a hash. The answer is kept in `details.confluence` (the error of a refusal that has
  no status of its own, a 400 for example) only when people may be shown, and with its text redacted in the same way; under `CONFLUENCE_HIDE_USERS=true` and the agent profile it is
  left out. The address that a redirect leads to is redacted too, and an answer that is nested too deeply to be scrubbed (about 490 levels) is exit code 7 ("a body that nests
  arrays or objects too deeply to be read") instead of an unexpected error.
- **`conflu config path`, `set` and `unset` answer in JSON when JSON is on** (`--json`, `--json-envelope`, `CONFLUENCE_OUTPUT=json`, the agent profile), as `config show` does, and not in
  plain text: `{"file"}`, `{"saved": NAME, "file"}` (the name, never the value) and `{"name", "removed", "file"}`; without JSON the text is what it was.
- **`conflu export` and `conflu tree` no longer take an empty value for "not given".** `export --page ''` exported the whole current space, `export --space ''` the current space, and `export --out ''` wrote
  its files (and an `index.json`) into the folder that you are in; `tree PAGE --space ''` looked a `page:Title` up in the current space. `--page`, `--space` and `--out` of `export` and `--space` of `tree`
  are usage errors now (exit code 2: "The page is empty.", "The space is empty.", "The output folder is empty."): nothing is asked, nothing is written, a dry run too. Leave the option out
  for the default. An empty root of `tree` was refused before ("Invalid id", exit code 1) and still is.
- **`conflu mcp` served no path where the system names no home folder.** Without `USERPROFILE` (and `HOMEDRIVE` with `HOMEPATH`) on Windows, or with an account database that has no
  home for the user, `~` stayed `~`; the server read it as a folder in the working folder, took the working folder for the home folder and refused every call that named a path as "too
  wide". A home folder that is not an absolute path is none now, and every other rule still holds.
- **A path of more than 4,096 characters, or one that the system cannot look at, is a refusal with its reason in `conflu mcp`**, no longer an internal error (`-32603`) of the request.
- **An answer that cannot be read is no longer taken for an empty one.** A content property that holds an integer of more than 4,300 digits (the decoder will not turn it into one), the page
  of a proxy or a captive portal that answers HTTP 200, and an empty body to a read were all read as "nothing": `conflu properties` printed `No properties` with exit code 0 (and
  `property-set` went to the creation branch), `tasks` printed `No tasks.`, `search` `Nothing found.`, `page` a blank page, and `ping` and `doctor` said that the connection was fine.
  Such an answer is exit code 7 now, "with something that is not JSON (text/html)", "with a number that is too long to be read" or "with an empty body", for every command and for
  `conflu api`; a refusal is still what its status says whatever its body is, and a write may still answer with no content (HTTP 204). A version, a size or a depth that an answer
  holds and that is no number (a word, a list, `true`, infinity) is the same error, and no longer a 0 or a 1. So is JSON of another kind than the call needs (`[]`, `null`, a number: every call that
  reads or makes something needs an object) and an empty body where there should be data: a property that the page of a proxy "created" (`property-set` said `Created the property ...`), a task
  that it "completed" and a list that came as `[]` were reported as done or as empty. A call that ignores its answer (`label --remove`, `watch`, `move`) still takes no content and any JSON, and
  `conflu api` any JSON, but none of them takes a page of HTML for an answer. When such a page answers a write (`comment`, `attach`, `update --append`, `blogpost-create`, `property-set`, `task`,
  `api POST` and `PUT`), the hint says that the change may have been made all the same and to look at the result before repeating it; the hint of a read says to try again.
- **`update --file`, `import-md` and `import-md-dir` no longer take away, without a word, what the Markdown copy of a page cannot carry.** The reading copy (`page`, `export`, `convert --source storage`)
  named macros, mentions and some other things, but not a link to a blog post, to a space, to a shortcut (a Jira issue key) or to content by its id (it showed the text of the link, or nothing),
  not a named anchor (`<a name="top">`), not the grey hint of a template (`<ac:placeholder>`), not a table caption and not markup inside inline code: `body.dropped` and `lossy` were empty,
  `update --dry-run` said `lost: []`, and the real run replaced the body and the links were gone. They are named now (`link:blogpost`, `link:space`, `link:shortcut`, `link:content`, `link:NAME` for
  any other target, `anchor`, `placeholder`, `html:caption`, `formatting:inline-code`; `link:anchor` also when a link to a page or an attachment goes to an anchor in it) in `body.dropped`, `lossy`,
  `lost` and the note of `convert`, and a Markdown that would replace such a page is refused without `--force`. Formatting that is only how the page looks (indentation, the width and layout of a table,
  classes, the numbers of tasks) is still not named; the guide [Markdown and storage format](docs/how-to/markdown-and-storage-format.md) says so. Two more losses of the same kind are gone: a
  `<div>` or `<section>` around several paragraphs ran them together into one line of words, and a table of one column, which `conflu page` writes as a pipe table, was read back as a paragraph of pipes
  (it is a table now, and a backslash before a backslash in a table cell is kept for the text, as GitHub does). Run against the bundled mock server only.
- **A body that breaks the converter is no longer a crash, and `task --complete` is no longer a change that is followed by one.** `<![foo[`, `<![ `, `<![[`, `<![]]>` and `<![x y[` in a page, a task
  or a template ended `page`, `tasks`, `task` and `template` in "unexpected AssertionError", and `<ol start="x">` and `colspan="x"` in "unexpected ValueError": one such task stopped `tasks --all` in
  the middle of the list, and `task ID --complete` made the change and then crashed. A section that has no name is text now, a number that is none (`start`, `colspan`, `rowspan`) is 1, and one of more than
  nine digits is the largest of nine (a `start` of 4,000 digits was written into every item); whatever else breaks the converter is "cannot read this body as storage format" (exit code 1, the hint says to
  read it with `--format storage`, and the words of the error are not printed, because they quote the body). The text of a task that cannot be shown says so (`[the text of the task cannot be shown: it
  nests too deeply, or cannot be read]`), and the other tasks, and a change that was made, are shown as they were. Run against the bundled mock server only.
- **`task --complete` and `--reopen` no longer say `Completed task N` for a task that Confluence still shows as it was.** The call was answered with success, the read after it showed the old state,
  and a note on standard error was the only hint. The JSON has `confirmed` now (`true`: the read shows the state that was asked for; `false`: it shows the other one; `null`: a dry run, a task that was in
  the state already, or a read that failed) and `message`, as `conflu move` has, the exit code stays 0, and the line says `Confluence accepted the request to complete task N (incomplete -> complete), but
  it still shows the task as incomplete.` in place of `Completed`. `property-set` no longer prints `Created the property KEY on the page ID (id , version 1)` for an answer that names no id: the line has no
  parenthesis then, and `propertyId` is `null`. Run against the bundled mock server only.
- **An unexpected error is a JSON error object when JSON is asked for.** A bug that ended a command with `unexpected ...` printed a text line even with `--json`, `CONFLUENCE_OUTPUT=json` or the
  agent profile; it is `{"error": {"code": "ERROR", ...}}` on standard error now (and in the envelope), with the same exit code 1. Without JSON nothing changes.
- `conflu update --if-unchanged-since` with an empty or unreadable time names the option and asks nothing of Confluence, in a dry run too, as `move`, `attach`, `restore` and `blogpost-update` do (the
  message was `Not an ISO 8601 timestamp: ` without the option, after one request). `conflu download --out ''` is a usage error (exit code 2) and no longer saves into the current folder.

### Security

- Credentials in an address are masked or left out everywhere the address is printed, and an address that holds an `@` after its host name is not shown at all.
- `conflu setup --discover` asks one host only, the one of `CONFLUENCE_BASE_URL`, sends no credential and does not follow a redirect.
- **A dry run of `conflu update` no longer shows the people of the page.** An append or a prepend sends the whole body, and the request that was
  printed carried the mentions (account ids) and the e-mail addresses in it. The printed request is now a copy without them (the JSON says
  `payloadRedacted`); what is sent is unchanged. `--with-users`, refused when `CONFLUENCE_HIDE_USERS=true`, prints the exact request.
- **The address of a page no longer shows the e-mail address that its title holds.** Confluence ends the address with the title
  (`/pages/123/Contact+alex%40example.com`), and `conflu page`, `search`, `update`, `create` and others printed it next to a title that they had
  redacted. The address now ends at the id (and opens the page just the same) when its title holds an e-mail address or the link to a person; the
  raw answers that `conflu api` scrubs under `CONFLUENCE_HIDE_USERS=true` get the same treatment.
- `conflu update`, `create`, `import-md`, `folder-create` and `smartlink-create` print the title that Confluence answers redacted, as every other
  command does, and so does `conflu use` for the name of the space.
- **`conflu export` can no longer be made to write outside its folder.** The file name of a page used the id from Confluence's answer as it came; a hostile
  server, or a proxy that rewrites answers, could send an id such as `7/../../AGENTS` and plant a Markdown file anywhere the person can write (and with
  `--force` replace one). Whatever is not a letter, a digit, `_` or `-` in an id becomes `_`.
- **A hostile page can no longer freeze a read.** The patterns that redact e-mail addresses and personal links took a time that grew with the square of the
  text: one word of 40 000 characters took about 10 seconds, and `conflu page` runs them twice. They read the text once now.
- **A page in a personal space shows no key and no owner address** unless you add `--with-users` (the key is `[hidden]`, and the address names the page by its
  id), and the raw answers that `conflu api` scrubs under `CONFLUENCE_HIDE_USERS=true` now also hide the people of a task (`createdBy`, `assignedTo`,
  `completedBy`), a `principal`, a mention in the other body formats (`data-account-id`, an ADF `mention`), a user that is only a name, and the key and the
  name of a personal space.
- A new test runs every command line of every feature area against a mock that puts an e-mail address into every free text, and fails when a command
  prints one, or a person, without being asked.
- `conflu import-md-dir` leaves out a link to a file outside the folder that it publishes: a folder that somebody else filled (a clone) could otherwise make it
  publish any text file that you can read. A download no longer creates a file whose name starts with a dot (`.mcp.json`, `.env`) as it is: the name gets a `_` in front.
- `conflu label PAGE --remove ..` is refused, a label made of dots cannot be added, and a segment of a request path that is made of dots is always sent
  percent-encoded: a server that collapses dot segments could have turned the removal of a label into the deletion of the page.
- `conflu attach` refuses the configuration file and any file that holds the API token (as it is, as the `Authorization` header, in UTF-8 or UTF-16), a dry run too.
  `conflu download` never writes into the folder that holds the configuration. What an attachment says is cleaned of terminal controls and of invisible format and tag
  characters before it is printed, and Office files are read with limits against archive, entity, tag and expansion bombs.
- **A personal space is no longer listed with the name and the account id of its owner.** Confluence names a personal space after its owner and keys it by
  `~` and the owner's account id, so `conflu spaces`, `conflu space ~KEY` and `conflu use ~KEY` printed a person. Without `--with-users` such a space (its
  `type` is `personal`, or its key starts with `~`) is now an entry with the key `[hidden]`, the name `[personal space]` and no description or address; its
  id, type, status, home page and date stay, and the keys of the JSON do not change. `conflu use ~KEY` prints `Current space: [hidden] ([personal space])`
  and still saves the key that you typed. `--search` looks at what is printed, so `--search alex` cannot tell that a personal space of an Alex exists, and
  the count and the cursor of the list are those of the masked list. `--with-users` is new on `conflu spaces` and `conflu space` and shows the space as
  Confluence names it; `CONFLUENCE_HIDE_USERS=true` refuses it. `conflu permissions --space` and `conflu space-access` print a personal space the same way.
- **Trees, folders and exports no longer print the key of a personal space.** Its key is `~` and the account id of its owner, and `conflu tree` (`root.spaceKey`),
  `conflu folder`, `whiteboard`, `database` and `smartlink` (`spaceKey` and the address), `folder-create` and `smartlink-create`, `conflu export` (the `space` of the result, the
  `space:` line of every file and the `space` of `index.json`, also for `export --space ~KEY`, where you typed the key yourself), `conflu move` and `restore` printed it, or an
  address with it, as did the messages that name a space (a title that exists already, a parent of another space, a `page:` reference that matches pages in several spaces).
  They print `[hidden]` now, and the address of a page names it by its id alone; `--with-users`, where a command has it, shows what Confluence names. A file that `export`
  wrote with `space: [hidden]` is imported by its `page_id`, and `import-md` takes the space of a new page from `--space` when it reads that line.
- **`conflu search` no longer lists people.** The search index holds people and spaces besides pages, and `conflu search --cql 'type = user AND user.fullname ~ "a*"' --all`
  printed names, account ids and profile addresses, also under `CONFLUENCE_HIDE_USERS=true` and in the agent profile (`conflu users search` refused). Without `--with-users` the
  hits about people are now left out of the hits and of `--raw`; the `notes` say how many, never who. A hit about a personal space comes out as the space commands print it (key
  `[hidden]`, name `[personal space]`, no address), and so does such a space in the raw answer. `--with-users` lists them as before, and `CONFLUENCE_HIDE_USERS=true` still refuses it.
- **The path of `conflu api` cannot climb out of the API folder in disguise.** `..` and `%2e%2e` were refused, but `.%2e`, `%2e.`, `..;x` and a `..` that a fragment hid
  (`pages/..#x`, which is sent as `pages/..`) were not, and a server or a proxy that collapses dot segments would have answered a different call than the one you wrote. A
  segment of two dots is refused in every spelling, in upper and lower case.
- **`conflu download` prints and saves a file name without the address that it may hold, and holds its limits to what arrives.** An attachment can be named after
  an e-mail address (`alex@example.com-cv.pdf`); `attachments` showed `[email]`, but `download` printed the raw name in the `name` and `path` of its answer and in its
  messages. Without `--with-users` it now prints the name redacted everywhere and **saves the file under the name that it prints** (made safe, as `export` does), so
  `path` is the file that is on disk; `--name` still finds the real name, the file is asked for by its id, and two names that become one once redacted are refused before
  anything is written. `download --text` redacts the text as a whole: it was cut into pieces of 512 characters first, and an address across a cut came out unchanged.
  A run that saves several files and stops after it wrote some now always says which (an answer that nobody foresaw skipped that summary and ended as an
  `unexpected ValueError`). `--max-bytes` and the 25 MiB limit of `--text` were checked against the size that Confluence lists only: the limit is now given to the transport,
  which stops reading at it, and what arrives is checked again, so a server that lists 1 byte and sends 512 MiB gets nothing decoded.
- **A server can no longer write a line into your configuration that locks you out.** `conflu use KEY` saved the key of the space as Confluence answered it, so an answer with a
  line break in the key made every later command fail. The key is checked like one that you type, and when it fails (exit code 7) nothing is saved. The same rule refuses a control
  character, a line separator or a paragraph separator in any value that `conflu config set` or `setup-token` writes.
- **A slow or hostile server can no longer keep a command busy for hours.** `CONFLUENCE_MAX_TIME` limits the whole answer (it limited the wait for the next bytes: one byte every
  few seconds was accepted for ever), and a gzip answer is read in at most 16 members (the rest of the body was copied again for each member: 80 000 empty ones took 24 seconds,
  160 000 about two minutes, and the 64 MiB limit would have taken hours).
- **Programs run `python conflu.py`, not the Windows launcher.** `conflu.cmd` forwards its arguments with `%*`, and cmd.exe splits the command line before a batch file runs: a
  program (an agent harness) that starts it with an argument list and passes an argument with a quote in it (`x" & echo INJECTED & "y`) ran a second command. No line of the batch
  file can prevent that. The `launcher` check of `conflu doctor`, `docs/how-to/use-with-ai-agents.md` and `docs/how-to/install-and-update.md` now tell a program to run
  `python "<install folder>\conflu.py" ARGS`, which Python reads without cmd.exe; the launchers are for people at a shell (PowerShell 5.1 strips the quote and is not affected).
- **A server can no longer have a person printed through the text of an error.** The explanation of a refusal, the address of a redirect and the answer kept in `details` go
  through the same redaction as page texts, plus one for account ids, and the raw answer is left out of the error under the policy that never prints people (it could hold a
  person in a form that no pattern finds). A download that is redirected to `https://wiki.example.com:99999/x`, an address whose port is no port, is refused as a damaged answer (exit
  code 7) without a name being looked up for it.
- **The key of a personal space no longer comes out of the commands that only name it.** The key is `~` and the account id of its owner. `conflu pages`, `conflu blogposts`,
  `conflu labels --space ~KEY` and `conflu tasks --space ~KEY` printed it in the `space` of their JSON (also the key that you typed), `conflu templates --space ~KEY` and `conflu template`
  in the `space` of the list, in its `SPACE` column, in the `spaceKey` of every template and in the text of a refusal (HTTP 403), `conflu search` repeated it in the `cql` of the answer and of
  `--raw` (also in a query that you wrote; only in the value of a `space` comparison, so a proximity search such as `"a b"~10`, fuzziness and `title ~ "~notes"` are printed as they were typed), and a page, a blog post, a comment or a template that links to a page in a personal space showed it in the Markdown (`page:~KEY/Title`) and in
  `--format storage` and `--raw` (`ri:space-key`), so a team page that links to somebody's notes carried the account id. They print `[hidden]` now (`page:[hidden]/Title`); `spaceId` and the
  rest stay, `--with-users` shows what Confluence says where a command has it (`tasks`, `search`, `page`), and what was sent to Confluence is still the real key. A storage format that was
  read that way is refused when it is written back, as one with hidden mentions is. The title of the home page of a personal space is the name of its owner, and a title is free text:
  that stays the documented limit.
- **The key of a personal space that is your current space is not printed by `conflu current`, `conflu config show` and `conflu doctor` either.** They print `[hidden]` (so does the
  error for a space that is not there, and the check that `conflu doctor` remembers for `--cached`), as `conflu use` and `conflu spaces` do. The setting itself, in the settings file or
  the environment, keeps the real key, and every command that takes the current space still uses it; to read the key, open the settings file (`conflu config path`). The key of any other space is
  printed as before.
- **`conflu mcp` on Windows: a part of a path that ends in a dot or a blank (`.. `, `...`) no longer gets a link or a short name past the path policy.** Windows takes the dots and
  blanks off the end of a name, `Path.resolve` stops following links below such a part, and the server handed the command the path that `resolve` had returned: a call could write
  through a junction out of the working folder, into `.git` by its short name (`GIT~1`), or reach the folder of the settings. Such a part is refused now (`.` and `..` stay
  allowed), a path is refused when resolving the result once more gives another place ("cannot be resolved reliably"), and the folder of the settings and the caches are compared by
  which folder they are and not by how a name is written.
- **`out` of `conflu_download` over MCP must lie below `tmp/conflu-attachments`**, not anywhere below the working folder: the names and the bytes of these files are the work of the
  authors of the attachments, and a model chose where they went (`src`, `docs`, the folder of a build). `conflu_export` keeps its `out`; its file names are made by the CLI. In a
  shell nothing changed.
- **The search for the token in a file covers UTF-32** (with a byte order mark, little endian, big endian), as `conflu mcp` and `conflu attach` look for it: a UTF-32 copy of the settings
  file is text to the CLI and was let through. The encodings of the search are the ones that the reader of text files (`decode_text`) reads, from one table, so the two cannot differ.
- **A client that does not read standard error can no longer stop `conflu mcp`.** The log was written synchronously, a full pipe (4 KiB on Windows) made the server wait for good, and a
  model chooses how many lines it writes. The messages go through a bounded queue to a thread that writes them; a line that does not fit is dropped and counted.
- **`conflu mcp` puts `~` in place of your home folder and your account name in what it returns** (every tool; `conflu_doctor` said where the settings file and the launcher are, with
  the name of the account). The log on standard error is not changed, and a page that quotes your exact home folder reads back with `~`.
- **`conflu mcp` offers no property that writes a file on a tool that is not a file tool.** `--out` and its `--force` (`page`, `blogpost`, `template`, `convert`) are for a shell; over MCP the text is in
  the result, and the property would have let `conflu_page`, which says `readOnlyHint: true` and is in the default set, put the text of a page under a name that the model chose into the project. Such a
  tool is offered without `out` and `force`, with or without `--allow-files`; `conflu_download` and `conflu_export` are the file tools.
- **A write that the page of a proxy answered is no longer reported as done, and a refused request no longer names the people in its body.** `property-set` said `Created the property ...`
  and `task --complete` `Completed task ...` for a request that something between you and Confluence had answered with a page of HTML, an empty body or `[]`: it is exit code 7 now, and nothing is reported.
  The answer that `details.confluence` keeps of a refusal with no status of its own (HTTP 400, for example) had its text redacted but not the people in it: `assignedTo: {accountId, displayName, email}`
  kept the name, which no text pattern finds. It goes through the same removal of people as the raw API under `CONFLUENCE_HIDE_USERS=true` first (a user is `{"hidden": true}`, a person id
  `[hidden]`); under that policy and in the agent profile the answer is still left out.
- **A body made of one long run of blanks, of `&`, or of markup that is never closed no longer hangs `page`, `template`, `tasks` and `conflu mcp`, which serves one call at a time.** The text
  of a page, a template, a task or a comment is converted for every command that shows it, and one body could take the square of its length: a code block or a code macro of one run of blanks
  (40,000 took 2.7 s, 160,000 took 48 s), a text of `&` (a million characters took 15 s), and a body of comments (`<!--`), end tags (`</p `), instructions (`<?x `), declarations (`<!x `),
  `<![if ` or a CDATA section that never ends (320,000 characters of `<!--` took 48 s, of `</p ` 5 s; only a start tag that is never closed was handled). The blanks before a line end are cut off line
  by line, a character reference is looked at where it stands and not in a copy of the rest of the text, and every opener that has no end is written as the text it is before the parser sees it (a tag,
  an end tag, a declaration or an instruction needs a `>` before the next `<`, a comment a `-->` after it, a CDATA section a `]]>`; `<![` that is no CDATA section is no XML). The inside of a comment
  and of a CDATA section is not looked at, so what a parser reads as markup after it has ended one earlier than the text says was a way past that check: a comment that some parsers end at `-- >` or
  `--!>` is an empty comment now, and a section that some end at `]] >` (code such as `a[b[i]] > 3`) is the text that it holds, which also shows the whole code of such a macro (it was cut at the
  `]] >`). A table whose short rows would be padded to more than 2,000,000 cells is refused ("a table is too large to convert";
  `--format storage` shows it): the Markdown of one row of 5,000 cells and 5,000 rows of one made 75 MB out of a body of 95 KB. 640,000 characters of each of these shapes convert in 0.15 to 0.35 s, the
  neutralisation alone in 0.04 to 0.14 s. A nesting of quotes or of macros costs its depth times the size, up to the limit of 100 levels, and a million `<` take 5 s; both are linear and not
  changed. Run against the bundled mock server and in memory only; Python 3.13.3 is the only version this was measured on.
- **A text of JSON in a content property no longer shows the people in it.** Apps store `JSON.stringify(state)`, which is a text, so `conflu properties` showed the display name of a user object inside
  it (also with `CONFLUENCE_HIDE_USERS=true`): the rules for texts hide addresses, links and account ids, and a name is none of them. A text that begins like an object or an array and is JSON (up to 1,000,000
  characters, also when it was encoded up to four times) is read as JSON, so the user objects in it are hidden like the others, and it is shown as compact JSON (`{"reviewer":{"hidden":true}}`) when
  something in it was hidden and as it is when nothing was; with `--with-users` it is the stored text. An account id in capitals was not hidden (`5B10AC8D82E05B22CC7D4EF5`) and is now. `property-set`
  still refuses a value that is the reading written back (the changed text is named in the refusal), and the real value, read with `--with-users --max-chars 0 --json`, is taken back as `unchanged`.
- **`template --format storage` says how many addresses and links the body lost, and the dry run of `create`, `update` and `blogpost-create` says what the part that it cuts holds.** The body that
  the guide tells you to save (`template ID --format storage --body-only --out body.xml`) has `[email]` and `[personal link]` where the template has addresses and links, and a page created from it
  carries those words: a warning on standard error says how many there are, and that `template` has no `--with-users`. The text of a dry run shows at most the first 1500 characters of the body, and an
  image from an address or a macro that `html` or `include` runs could stand behind them: the cut says how many macros and external addresses (`ri:url`) are in the part that is left out
  (`... (1283 more characters, among them 2 macros and 1 external address)`), as a count and never as the text; `--json` is never cut. The guide
  [Tasks, properties and templates](docs/how-to/tasks-properties-and-templates.md) says both.
- **A Markdown text, a heading or a value on the command line made of one long run no longer keeps the CLI busy for minutes.** Patterns that tried every way to split a run of blanks between two
  parts, or ran on to the end of the text from every start, took the square of its length, the pattern of a heading line the cube: `# a`, 2,300 blanks and an `x` took 18 s to convert, 40,000
  blanks in a heading of `page --outline` took 18 s, and 80,000 headings 16 s. They are read in a time that grows with their length now: in a Markdown text that is converted (`convert`, and every command that
  writes a page, a comment or a blog post from Markdown, also the Markdown copy of the current body that an `update` compares a Markdown body with) the heading line, the fence line, the delimiter row of a table, an
  address that is not made a link (`(http://(http://...`), a run of `)` behind an address and a run of blank lines behind a quote; the title line of a file that is imported; in `page --outline` and
  `--section` the end of a heading line, its links, images and emphasis, and a page with many headings; a length of time (`doctor --cached`), the address of `config set CONFLUENCE_EMAIL`, and the `~` that
  `conflu mcp` puts in place of your home folder (a result of 35,000 slashes took 14 s). What was read before is read the same: a test holds the answers of the old patterns for the cases where their parts
  had to share a run. One text changed: U+FFF0 and U+FFF1, the marks that the converter sets aside for its own pieces, are written as U+FFFD in a Markdown text, because a code span that held one made the
  conversion run for ever. Not changed, because it is linear: a link or an image opened and never closed (`[a](` over and over) costs up to 2,000 characters of look-ahead each, and 100 KB of them took 2.7 s.
  Run against the bundled mock server and in memory only; Python 3.13.3 is the only version this was measured on.
- **`conflu mcp` is safe by default.** The tools that change Confluence are absent unless `--allow-write` (a call of one is refused as an unknown tool, `-32602`, and each has `dryRun`), the tools that
  write files on the computer (`conflu_download`, `conflu_export`) are absent unless `--allow-files` (the two switches are independent: neither offers the other's tools, and not even `--group Read` offers
  them), and the property `withUsers` is refused unless `--show-users` (and always under `CONFLUENCE_HIDE_USERS=true`); `conflu_ping` is always asked to be quiet, because the owner of the token is a person. A
  call is checked against the schema of its tool before anything runs (an unknown or a missing property, a wrong type, a value outside the choices, a NUL character, a lone surrogate). Every option is written
  `--flag=value`, so that a value never becomes an option; a positional argument that starts with `-` is refused, and so is a value that starts with `@` or is `-` for the properties that accept `@FILE`
  (the `text` and `cql` of `search`, the `text` of `users`): a model must not read a file of the computer through them. Which properties those are is declared on the arguments of the commands
  (`Arg(at_file=True)`), not found by the English of a help text, and a test over every real command fails when an argument looks like a path or `@FILE` and declares nothing.
- **`conflu mcp` keeps a model away from the files of the computer.** A property that names a path (the `file` of `conflu_update`, `conflu_create`, `conflu_comment`, `conflu_import_md` and the
  others, the files of `conflu_attach`, the `dir` of `conflu_import_md_dir`, the `out` of `conflu_export` and `conflu_download`) is refused, with an error result that says what is allowed and without running
  the command, unless the path lies below the folder the server was started in once `..` and links are resolved. A network or device path (`\\host\share`, `//host`, `\\?\`, `\\.\`, `\??\`) is refused without
  being looked at, also when blanks stand in front of it, and a device name is read as Windows reads it (`con .txt`). The settings file of the CLI and anything in the folder of the settings or of the cache
  are refused, and a file that holds the token (as it is, as the header that carries it, in UTF-8, UTF-16 or UTF-32) is not read by a path property; the refusal does not show it. A call that writes may not write into a
  hidden folder (`.git`, `.vscode`) or let `download` write into the working folder itself (and `download` writes only below `tmp/conflu-attachments`); `force` is not honoured (`update`, `import-md`, `import-md-dir`, `comment`, `blogpost-update`, `download`, `export`);
  and a working folder that is a drive root, the home folder or a folder above it, or the folder of the settings or of the cache (`~/.config/conflu-c-cli`, `~/.cache/conflu-c-cli`) or one above it, is refused.
  A folder that a call reads is not searched for the token, and the files that `conflu_download` writes come from the author of the attachment.
- **`conflu mcp` judges the path that the command uses, and gives the command that path.** A blank or an invisible character at either end of a path (a space, a no-break space, U+3000, U+0085, a
  zero-width space) and a control or format character anywhere in it are refused (the message writes it out, as `\xa0` or `\u200b`), because a command may strip, split or normalise a text: `conflu download`
  strips the blanks off `out`, so ` .git/hooks` would be one folder to the check and another to the command. A call that is allowed gives the command the approved path in full (resolved, absolute, one argument
  for each file of `attach`), never the text that the model wrote, so that a command cannot reach another place than the one that was checked. A relative path means relative to the working folder of the server,
  whatever folder the process is in.
- **`conflu mcp` judges the place that a command uses when a call leaves a path out.** `conflu_download` without `out` writes to `tmp/conflu-attachments/ID` (a shell would write into the working
  folder itself, among the files of the project, under names that the author of the attachment chose): with a junction or a symbolic link at `tmp` that leads out of the working folder (a cloned repository can
  bring one), the files of the author would be written outside it. The place is worked out as the command works it out, judged as a given path is, and handed to the command as `--out`; a refusal says that the
  property "was left out" and names the place. `download` with `text: true` writes no file and is not judged. No other tool has a place of its own: every optional property that names a path is held by a test to be
  in the table of places or in the table of properties that have none, with what the command does without it.
- Storage-format redaction (`--format storage`, raw JSON, the strings of a property) recognises `name='value'`, blanks around `=` and any letter case of the `ri:` and `data-` attributes that name an
  account id, a user key, a user name or a personal `ri:space-key`, and the write-back guard recognises the same forms.
- E-mail addresses that hold `' & ! # $ % * ^ ` { | } ~` in the local part (`o'connor@example.com`) are redacted completely.

## [1.0.0] - 2026-10-17

The first release of conflu-c-cli, a command line client for Confluence Cloud for people at a terminal and for programs and AI agents. It was
built against Atlassian's published API descriptions. The test suite runs against a bundled mock Confluence Cloud server, and the read commands
were also checked, read-only, against a real Confluence Cloud site. `conflu doctor` is the check against your own site and token.

### Added

- **Read and navigate Confluence Cloud.** `conflu page`, `conflu pages`, `conflu tree`, `conflu versions`, `conflu search`, `conflu comments`,
  `conflu labels`, `conflu attachments`, `conflu spaces` and `conflu space` read pages, trees, histories, search results, metadata and spaces.
  `conflu page --body-only` prints nothing but the body, to save it in a file. `conflu download` saves attachments and keeps credentials away from
  the media host that serves the file. `conflu page` and `conflu tree` also take `page:KEY/Title` (and `page:Title` with `--space`), the form in
  which the Markdown shows a link to another page; when the space KEY exists but holds no page of that name, the whole text is used as a title in
  the current space (`page:CI/CD pipeline`).
- **Read a page in parts.** `conflu page --outline` lists the headings with the size of each section, `--section TITLE|N` reads one, `--max-chars N`
  cuts at the end of a paragraph and says so (`body.truncated`, `body.totalChars`). On a real page of 17,800 characters the outline and the one
  section needed were 5 % of it. A code block ends only at a closing fence with at most three spaces in front of it (as in CommonMark), so a line
  inside a code block is never taken for a heading or a cut by `--outline` and `--max-chars`.
- **Search that works for questions.** `conflu search` turns the text into words and `"phrases"`, leaves out filler words (English and German) and
  the punctuation at the end of a word, and says what it left out (`terms`, `ignored`). The words of a plain search form one query
  (`text ~ "a b"`), and a phrase is a clause of its own. When no page holds every word it searches again for the pages that hold some and says so
  (`relaxed`, `match`); `--match all|any|auto` chooses. When nothing is found, `notes` says what to try. A title is shown as written (`Q&A`).
- **Hits that can be judged without opening the page.** Each hit has its `path` (the parent pages), `labels` and `version`; `--snippets N` reads the
  first N pages with one request and shows the passage around the words (`snippet`, `matched`), cut from the page as `conflu page` shows it, so
  people stay out. Wildcards in the words of a search (`a*b*c*`) cannot slow the snippets down on a hostile page, and a word that occurs often
  cannot hide a rare one from the passage that is shown.
- **Safe page changes.** `conflu update`, `conflu move`, `conflu comment`, `conflu label`, `conflu attach` and `conflu create` change pages with
  `--dry-run` previews. `conflu update` supports `--append`, `--prepend`, `--if-version` and `--if-unchanged-since`; Markdown replacements are
  blocked unless `--force` when the page holds constructs Markdown cannot express.
- **Markdown publishing and offline mirrors.** `conflu import-md` and `conflu import-md-dir` publish Markdown files with front matter (`title`,
  `space`, `parent`, `page_id`, `labels`, `message`). `conflu export` writes a local mirror of a space or page tree with front matter, `lossy`
  markers and `index.json`, in Markdown or storage format; every file gets a `path:` line and every entry of `index.json` a `path`, which the
  import ignores. An unedited export imports again as a no-op, and a Markdown replacement of a body that holds what Markdown cannot say (also
  `redacted-text`: hidden e-mail addresses and personal links) is refused without `--force`. A title survives the round trip: `export` writes it
  exactly as it is, double spaces included, so that importing the file again does not rename the page; a title that had to be redacted is refused
  on import, and an e-mail address in a title never reaches a file name. `conflu export` and `conflu import-md-dir` are two one-way commands, not
  a sync: an import does not notice changes made in Confluence after the export. The help of both commands, the skill and the guides say so and
  give a safe routine.
- **Program and agent support.** `--json` on every data command, `CONFLUENCE_OUTPUT=json` for a whole session, fixed exit codes, JSON errors on
  stderr, `conflu commands --json` as a full machine-readable catalog, and the shipped skill `skills/conflu-c-cli/SKILL.md`. `conflu help`,
  `conflu how-to`, `conflu changelog` and `conflu skill` all work offline.
- **Tool descriptions for agents.** `conflu commands --format mcp [--only read|write|all]` prints the commands an agent may use in the shape of an
  MCP `tools/list` answer: name, description, JSON Schema for the input, annotations (read-only, destructive, idempotent) and `_meta.conflu` for
  the command line. Commands for the person (the token, the settings, the default space) and the raw `api` are never listed. Every command says
  when to use it (`whenToUse` in the catalog, "When to use" in the help).
- **A guide to finding information**, `conflu how-to find-information`, for people and agents: which command, how the search works, reading in
  parts, a mirror to search together with the code, a loop that spends little, and a checklist for when nothing is found.
- **Connection setup and diagnostics.** `conflu setup-token`, `conflu remove-token`, `conflu use`, `conflu current`, `conflu clear-space`,
  `conflu config`, `conflu ping` and `conflu doctor` configure the connection, save the token safely, remember a current space and explain setup
  problems step by step. A certificate that no known authority vouches for (`unable to get local issuer certificate`) is reported with the chain
  the server presented and what to do about it, and is not retried. A 401 or 403 from an address that is not an atlassian.net address (a custom
  domain of the site, where Atlassian does not read API tokens) names the gateway address `https://api.atlassian.com/ex/confluence/CLOUD_ID` as the
  way out, and `conflu doctor` warns about such an address before anything fails.
- **Settings for real enterprise networks.** `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_SPACE`,
  `CONFLUENCE_CA_BUNDLE` (adds authorities to the system store), `CONFLUENCE_TLS_STRICT`, `CONFLUENCE_INSECURE`, `CONFLUENCE_ALLOW_HTTP`,
  `CONFLUENCE_HIDE_USERS`, `CONFLUENCE_CONNECT_TIMEOUT`, `CONFLUENCE_MAX_TIME`, `CONFLUENCE_RETRY` and `CONFLUENCE_OUTPUT` cover connection setup,
  privacy, TLS, timeouts and retries.
- **Escape hatches and packaging.** `conflu convert` previews the Markdown and storage-format converters, and `conflu api` exposes REST calls below
  the wiki root (`api/` and `rest/`) with guarded writes (`--write`, `--dry-run`, no general DELETE). `python install.py` installs, updates and
  uninstalls the program, its docs, the skill and the examples.
- **Offline documentation and tests.** A README, architecture notes, how-to guides, generated reference documents, examples and a test suite
  around a mock Confluence Cloud server (`python -m unittest discover -s tests -t .`, `python scripts/generate_docs.py`,
  `python scripts/check_release.py`).

### Security

- **Private by default.** People, account ids, e-mail addresses and personal links are hidden unless `--with-users` is allowed and given;
  `CONFLUENCE_HIDE_USERS=true` makes that a rule.
- **A link to a profile counts as a mention.** `/wiki/people/ID` and `/wiki/spaces/~ID`, absolute or as the page writes them, are shown as `@user`
  in the Markdown and the text of a page, in the snippets and in an export, and a Markdown link to one is removed with its text. Ordinary paths
  that merely contain a folder called `people` are left alone.
- **Search excerpts name nobody by default.** The search index writes the names of mentioned people into the excerpt as plain text, so
  `conflu search` leaves the excerpt out (`null` in the JSON) unless you add `--with-users`, which `CONFLUENCE_HIDE_USERS=true` refuses.
- The snippets of a search are cut from the page as `conflu page` shows it, so a mention is `@user` and an e-mail address `[email]`; the path of a
  hit is redacted like every title.
- **Credentials stay with Confluence.** The token is never accepted on the command line, is shown masked, and is taken out, together with the
  account e-mail, of what Confluence echoes in an error. Credentials go only to the configured address: a download follows the redirect to the
  media host without them, and `conflu api` refuses a path that names a host or contains `..`.
- **Text written by others cannot drive the terminal.** Control, escape and C1 characters are removed from text output, error messages and
  progress messages, and written as `\u` escapes in JSON.
- **Files stay where you point them.** `conflu download` and `conflu export` make file names safe (no folders, no Windows device names, no
  invisible or right-to-left override characters), refuse names that would end up as the same file, and need `--force` to overwrite.
- **No script links.** A Markdown link or image whose address uses a scheme other than http, https, mailto, ftp, ftps or tel (`javascript:` in any
  spelling, `data:`, `file:` and so on) loses the link and keeps its text.
- **Bounded input.** An answer of Confluence larger than 64 MiB once decoded, or a file larger than 512 MiB, is refused; compressed answers are
  decoded under the same cap; content nested too deeply is refused with a clear error.
