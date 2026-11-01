# Compatibility with Confluence Cloud

conflu-c-cli is written for **Confluence Cloud** and talks to its two REST APIs. **v2** (`/wiki/api/v2`) is the default and the only
choice wherever v2 has the feature. **v1** (`/wiki/rest/api`) is used only where v2 has no equivalent, and every such call is listed
below with its reason. This page says which versions that means, how the CLI is checked against them, which API each command uses,
what `conflu doctor` and `conflu version` say about it, and what the commands do not cover.

## The supported API versions

| | v2 (the default) | v1 (only where v2 has nothing) |
| --- | --- | --- |
| Base path | `/wiki/api/v2` | `/wiki/rest/api` |
| Pagination | cursor (`limit`, `cursor`) | offset (`limit`, `start`) |
| OpenAPI document | https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json (version 2.0.0) | https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json (version 1.0.0) |
| Guide | https://developer.atlassian.com/cloud/confluence/rest/v2/intro/ | https://developer.atlassian.com/cloud/confluence/rest/v1/intro/ |
| Operations in the document | 252, 1 of them deprecated | 130, 2 of them deprecated (the two reads of descendants, which v2 replaces) |
| Read for this release | 2026-10-30 | 2026-10-30 |

Confluence Cloud has no release number to compare with: Atlassian changes the service in place and publishes the two documents above.
So "supported" means: **every call the CLI sends is one that the matching document lists, and none of them is deprecated**. The
paths are the ones below the wiki address of the site (`https://SITE/wiki`, or the gateway address `https://api.atlassian.com/ex/confluence/CLOUD_ID/wiki`
that a token with scopes needs).

Four rules follow, and the tests hold the CLI to them:

- **v2 first.** A feature is built on v2 when v2 has it. Before a feature is added, both documents are read again, and a call moves to
  v2 as soon as v2 has an equivalent.
- **v1 only with a reason.** Each call to v1 is in the table "Why some calls use v1" below, and in `V1_CALLS` of the adapter that makes it.
- **No deprecated call.** The two reads of descendants of v1 and `GET /pages/{id}/children` of v2 are marked as deprecated in the
  documents: the CLI uses `descendants` and `direct-children` of v2 instead.
- **No call outside the documents.** Two addresses are no REST call and are not in a document: the public tenant information that
  `conflu setup --discover` reads (`/_edge/tenant_info`, sent without credentials), and the address of a file at a media service, which
  the transport follows from a documented download (the credentials go to Confluence only, never there).

## How the CLI is checked against the documents

- **The lists.** `tests/support/confluence_cloud_v2_endpoints.txt` and `tests/support/confluence_cloud_v1_endpoints.txt` hold every operation
  of the two documents (method and path template, with the deprecated ones marked), read on 2026-10-30. They are the reference, not what the
  CLI uses.
- **The mock refuses what the documents do not list.** The mock Confluence of the test suite answers HTTP 404 to a call that is not in the
  list of its API, and records it (method, path and which document), and it records a call to a deprecated operation. A command that came to
  depend on an endpoint of another API, an older one or one that does not exist would fail its own test.
- **A sweep of every command.** `tests/integration/test_conformance.py` runs at least one line of every command that asks Confluence
  (`tests/support/sweep_*.py`), through the real HTTP adapter, and asserts that nothing undocumented or deprecated was sent, that every
  call to v1 has its reason, and that the table "Which API each command uses" below is exactly what the commands sent. Every option of every command must
  also be named by a line of a sweep, or stand in the short table `NOT_SWEPT` of `tests/support/conformance.py` with its reason, so that an option whose request
  was never run is noticed.
- **The parameters are checked too.** `tests/support/confluence_cloud_v2_parameters.txt` and `confluence_cloud_v1_parameters.txt` give each operation of the
  lists, on one line, the query parameters (the required ones marked, the documented maximum of `limit`), the required headers and the top-level properties of the
  request body (or the form fields of an upload) that its document names. When the mock's `strict_parameters` is on, which the sweep turns on, the mock answers HTTP 400
  and records the request in `invalid_requests` if a query parameter is not the operation's or a required one is missing, if `limit` is above the maximum, if a
  required header is missing, or if the body is not of the documented kind, has a property that the schema does not list or lacks a required one; the sweep fails and
  names the command line that sent it. A parameter that Confluence accepts although the document does not list it goes into the one table `ACCEPTED_BUT_UNDOCUMENTED` of
  `tests/support/conformance.py`, with the reason (it is empty). The mock judges only what is sent, so the test also reads the source of the REST adapters: every
  query parameter that an adapter can put into a request must be a name in the documents, and some line of the sweep must send it (`NEVER_SENT_IN_A_SWEEP` holds one
  that no line can send, with the reason; it is empty). The files give names, not values: the values that a parameter takes and the rules that a name cannot show
  (a reply names its parent comment and not the page) are checked by reading the operation in the document.
- **What this proves, and what it does not.** It proves that the CLI sends only calls that the two documents know, with the methods the
  documents list, and with query parameters, headers and body properties that those documents name. It does not prove that Confluence Cloud answers as the mock does: the mock follows the documents, and all of these
  checks ran against it, not against a real site. Use `--dry-run` first, a test space before a real one, and `conflu doctor` as the check
  against your own site.
- **What the documents do not say.** What a real site answers for a call can differ from the document: the words of a refusal, which
  fields are filled, how a very large page is cut, how long a cursor lives, which scopes a token needs for a call, and how a media service
  serves a file. The CLI shows Confluence's own message and never hides a refusal.
- **Keeping the lists current.** Atlassian changes the service in place, so the lists are a snapshot with a date. To refresh them, download the
  two documents yourself and run `python scripts/update_endpoint_lists.py --v2 FILE --v1 FILE --read-on YYYY-MM-DD` (`--dry-run` only says what would
  change; the script reads the two files and contacts no server). It rewrites the two lists and the two parameter files, and names every operation that was added, removed or newly
  deprecated and every one whose parameters or body changed; then bring up to date the numbers that state the snapshot (`DOCUMENTS_READ` and the two versions in `src/conflu_c_cli/domain/compat.py`,
  the counts in `tests/integration/test_conformance.py`, the table above) and run the tests. A command that called something that is gone or deprecated
  fails its sweep, and the fix is the call that replaces it, on v2 where v2 has it.

## What `conflu doctor` and `conflu version` say

- `conflu version --json` has the key `confluenceCloud`: the two API versions the CLI is written for, their base paths and the day the
  documents were read.
- `conflu doctor` has a check `api`. It says whether v2 and v1 answered on your site (the two requests it makes anyway: the current user is
  v1, the list of spaces is v2), and what the CLI is written for. A site where only one of them answers, or an address that is not Confluence
  Cloud (a Data Center site has no `/wiki/api/v2`), is a `warn` with the hint that fits. A `warn` never stops a command.

## What the commands cover, and what stays with `conflu api`

The commands are what people and agents do with content every day: read it, find it, change it with a preview and a guard, publish it from files and keep a
copy on disk. The tables below take every group of the two documents (the tag that Atlassian puts on its operations) and say how many of its operations a
command makes (counted from the sweep of every command, as of 2026-10-30), which commands those are, and why the rest is left out. In all, a command makes
109 of the 252 operations of v2 and 18 of the 130 operations of v1; the v1 ones are the ones in the table "Why some
calls use v1". What is left out is of four kinds:

- **Administration.** The admin key, data policies, app properties, dynamic modules, themes, audit, analytics, settings, space settings, the transition of space
  permissions and the creation of spaces are for the person who runs the site, not for reading and writing content. `conflu api` reaches them for someone who knows
  what they do (`GET` is free, `POST` and `PUT` need `--write`).
- **Anything that deletes or redacts content.** Deleting a page, a blog post, a comment, an attachment, a property, a version and the like, and the redaction of
  content, are not offered, and `conflu api` has no `DELETE` either. The only removals the CLI has are a label (`conflu label --remove`) and your own watch
  (`conflu watch --remove`).
- **Who may see or edit content.** Restrictions, content permissions, space permissions and roles, classification levels and content states: the reads are
  commands (`restrictions`, `permissions`, `space-access`), and nothing changes them.
- **No use at a terminal, or not yet.** Likes, custom content, the properties of a space or of a user, relations, long-running tasks, and an inline comment (it
  has to be anchored to a selection of the text) have no command.

### Groups of the API v2

| Group of the document | Operations | Used | By | Left out, and why |
| --- | --- | --- | --- | --- |
| Admin Key | 3 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Ancestors | 5 | 5 | `database`, `export`, `folder`, `move`, `page`, `smartlink`, `whiteboard` | - |
| App Properties | 4 | 0 | - | The storage of an app: no use for a person at a terminal. |
| Attachment | 8 | 3 | `attach`, `attachment`, `attachments`, `download`, `page` | Deleting an attachment, the list of every attachment of the site, those of custom content or of a label, and thumbnails. |
| Blog Post | 7 | 5 | `blogpost`, `blogpost-create`, `blogpost-update`, `blogposts` | Deleting a blog post, and the blog posts that carry a label (`conflu search --label` finds them). |
| Children | 7 | 4 | `database`, `folder`, `smartlink`, `whiteboard` | `pages/{id}/children` is deprecated and `direct-children` of a page is not needed (`conflu tree --depth 1`); custom content has no command. |
| Classification Level | 16 | 0 | - | Not offered: classification is a governance setting, changing it changes who may see content, and reading it has no command yet. |
| Comment | 18 | 11 | `blogpost`, `comment`, `comments`, `page` | Deleting a comment, creating an inline comment (it must be anchored to a selection of the text), the list of every comment of the site, and the comments of attachments and custom content. |
| Content | 1 | 1 | `attach`, `attachments`, `blogpost`, `create`, `download`, `export`, `folder`, `folder-create`, `import-md`, `import-md-dir`, `move`, `page`, `permissions`, `properties`, `property-set`, `restrictions`, `smartlink-create`, `tasks`, `tree`, `watch`, `watching` | - |
| Content Permissions | 30 | 10 | `restrictions` | Every change of a restriction or a permission. It changes who may see or edit content, which this CLI leaves to the web interface (`conflu api ... --write` can still send it). |
| Content Properties | 45 | 24 | `properties`, `property-set` | Deleting a property; the properties of custom content. |
| Custom Content | 8 | 0 | - | No command: apps define custom content, so it has no shape of its own. |
| Data Policies | 2 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Database | 7 | 4 | `create`, `database`, `tree` | Creating a database and deleting one. |
| Descendants | 5 | 5 | `export`, `tree` | - |
| Folder | 3 | 2 | `create`, `database`, `export`, `folder`, `folder-create`, `import-md`, `import-md-dir`, `move`, `page`, `smartlink`, `smartlink-create`, `tree`, `whiteboard` | Deleting content is not offered. |
| Label | 7 | 4 | `attachment`, `blogpost`, `label`, `labels` | The content that carries a label (`conflu search --label` finds pages); adding and removing is v1. |
| Like | 8 | 0 | - | No command: who liked what is people data, and a count is not needed to read or change a page. |
| Operation | 11 | 11 | `permissions` | - |
| Page | 8 | 6 | `api`, `comment`, `create`, `database`, `diff`, `export`, `folder`, `folder-create`, `import-md`, `import-md-dir`, `move`, `page`, `pages`, `restore`, `search`, `smartlink`, `smartlink-create`, `tree`, `update`, `versions`, `whiteboard` | Deleting content is not offered. |
| Redactions | 2 | 0 | - | Not offered: a redaction destroys content. |
| Smart Link | 3 | 2 | `create`, `smartlink`, `smartlink-create`, `tree` | Deleting content is not offered. |
| Space | 3 | 1 | `blogpost-create`, `blogposts`, `create`, `doctor`, `export`, `folder-create`, `import-md`, `import-md-dir`, `labels`, `page`, `pages`, `permissions`, `smartlink-create`, `space`, `space-access`, `spaces`, `tasks`, `templates`, `tree`, `use`, `watch`, `watching` | Creating a space is administration: it is for the person who runs the site, not for reading and writing content. |
| Space Permission Transition | 5 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Space Permissions | 2 | 1 | `space-access` | The list of the permissions that exist is not needed. |
| Space Properties | 5 | 0 | - | No command: the properties of a space are the storage of an app. |
| Space Roles | 8 | 3 | `space-access` | Creating, changing and deleting roles and assigning them. It changes who may see or edit content, which this CLI leaves to the web interface (`conflu api ... --write` can still send it). |
| Task | 3 | 3 | `task`, `tasks` | - |
| User | 3 | 1 | `attachment`, `blogpost`, `comment`, `comments`, `database`, `folder`, `page`, `smartlink`, `tasks`, `users`, `versions`, `whiteboard` | Checking access by e-mail address and inviting by e-mail address: they reveal or change who has access. |
| Version | 12 | 2 | `attachment`, `versions` | The versions of folders, databases, whiteboards, smart links, comments and custom content have no command. |
| Whiteboard | 3 | 1 | `create`, `tree`, `whiteboard` | Creating and deleting a whiteboard. |

### Groups of the API v1

v1 is used only where v2 has nothing, so most of its groups are not used at all.

| Group of the document | Operations | Used | By | Left out, and why |
| --- | --- | --- | --- | --- |
| Analytics | 2 | 0 | - | No command: view counts and who viewed. |
| Audit | 6 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Content | 4 | 0 | - | v2 does all of it, and v2 comes first. |
| Content - attachments | 5 | 2 | `attach`, `download` | Moving an attachment and changing its properties. |
| Content - children and descendants | 5 | 1 | `move` | The reads are deprecated and v2 replaces them; only the move before or after another page is v1. |
| Content - macro body | 3 | 0 | - | No command. |
| Content body | 4 | 0 | - | No command: the conversion is local (`conflu convert`). |
| Content labels | 3 | 2 | `blogpost-create`, `create`, `label` | The read is v2. |
| Content permissions | 1 | 0 | - | No command: `conflu permissions` uses the operations of v2. |
| Content restrictions | 12 | 0 | - | The reads are v2 (`conflu restrictions`); a change of a restriction is not offered: it changes who may see or edit content, which this CLI leaves to the web interface (`conflu api ... --write` can still send it). |
| Content states | 8 | 0 | - | Not offered: a state is a decision of a workflow, and changing it changes who sees what. |
| Content versions | 2 | 1 | `restore` | Deleting a version. |
| Content watches | 12 | 6 | `watch`, `watching` | The watchers of content and other people's watches: only your own watch is read and changed. |
| Dynamic modules | 3 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Experimental | 4 | 0 | - | Experimental API. |
| Group | 8 | 0 | - | Groups are people data, and changing them is administration. |
| Label info | 1 | 0 | - | No command. |
| Long-running task | 2 | 0 | - | No command. |
| Relation | 5 | 0 | - | No command. |
| Search | 2 | 2 | `search`, `users` | - |
| Settings | 5 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Space | 4 | 0 | - | Creating, changing and deleting spaces is administration: it is for the person who runs the site, not for reading and writing content. |
| Space permissions | 3 | 0 | - | It changes who may see or edit content, which this CLI leaves to the web interface (`conflu api ... --write` can still send it). |
| Space settings | 2 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| Template | 6 | 3 | `template`, `templates` | Creating, changing and deleting templates. |
| Themes | 6 | 0 | - | Administration: it is for the person who runs the site, not for reading and writing content. |
| User properties | 5 | 0 | - | No command. |
| Users | 7 | 1 | `comment`, `comments`, `doctor`, `ping`, `tasks` | Other people are looked up with `conflu users` (v2 bulk lookup and the user search); the rest (anonymous user, contributors, memberships) has no command. |

## Which API each command uses

The calls that every command makes, as the sweep recorded them (paths below `/wiki`; each is in the list of its document). A command that
changes Confluence reads its targets first and reads the result back, and `--dry-run` makes the reads and none of the writes. The same API is named
for each command in the line `REST API:` of `conflu help COMMAND`, in the command reference and as `api` in `conflu commands --json`; the table
behind those, `adapters/driving/cli/apis.py`, is held by a test to what the sweep recorded. Commands that ask Confluence for nothing are not in the
table below: `config`, `current`, `clear-space`, `setup-token`, `remove-token`, `setup` (its `--discover` reads the public tenant information, which is no REST
call), `help`, `commands`, `version`, `changelog`, `how-to`, `skill`, `convert` and `mcp` (every tool it serves uses the API of its command).

| Command | API | Calls |
| --- | --- | --- |
| `api` | v2 | `GET /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}/title` |
| `attach` | v2 + v1 | `PUT /rest/api/content/{id}/child/attachment`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/pages/{id}/attachments` |
| `attachment` | v2 | `GET /api/v2/attachments/{id}`, `GET /api/v2/attachments/{id}/labels`, `GET /api/v2/attachments/{id}/versions`, `POST /api/v2/users-bulk` |
| `attachments` | v2 | `GET /api/v2/blogposts/{id}/attachments`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/pages/{id}/attachments` |
| `blogpost` | v2 | `GET /api/v2/blogposts/{id}`, `GET /api/v2/blogposts/{id}/footer-comments`, `GET /api/v2/blogposts/{id}/inline-comments`, `GET /api/v2/blogposts/{id}/labels`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/footer-comments/{id}/children`, `GET /api/v2/inline-comments/{id}/children`, `POST /api/v2/users-bulk` |
| `blogpost-create` | v2 + v1 | `POST /rest/api/content/{id}/label`, `POST /api/v2/blogposts`, `GET /api/v2/spaces` |
| `blogpost-update` | v2 | `GET /api/v2/blogposts/{id}`, `PUT /api/v2/blogposts/{id}` |
| `blogposts` | v2 | `GET /api/v2/blogposts`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/blogposts` |
| `comment` | v2 + v1 | `GET /rest/api/user/current`, `POST /api/v2/footer-comments`, `GET /api/v2/footer-comments/{comment-id}`, `PUT /api/v2/footer-comments/{comment-id}`, `GET /api/v2/inline-comments/{comment-id}`, `PUT /api/v2/inline-comments/{comment-id}`, `GET /api/v2/pages/{id}`, `POST /api/v2/users-bulk` |
| `comments` | v2 + v1 | `GET /rest/api/user/current`, `GET /api/v2/footer-comments/{id}/children`, `GET /api/v2/inline-comments/{id}/children`, `GET /api/v2/pages/{id}/footer-comments`, `GET /api/v2/pages/{id}/inline-comments`, `POST /api/v2/users-bulk` |
| `create` | v2 + v1 | `POST /rest/api/content/{id}/label`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/databases/{id}`, `GET /api/v2/embeds/{id}`, `GET /api/v2/folders/{id}`, `POST /api/v2/pages`, `GET /api/v2/pages/{id}`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages`, `GET /api/v2/whiteboards/{id}` |
| `database` | v2 | `GET /api/v2/databases/{id}`, `GET /api/v2/databases/{id}/ancestors`, `GET /api/v2/databases/{id}/direct-children`, `GET /api/v2/databases/{id}/entries`, `GET /api/v2/databases/{id}/fields`, `GET /api/v2/databases/{id}/views`, `GET /api/v2/folders/{id}`, `GET /api/v2/pages`, `POST /api/v2/users-bulk` |
| `diff` | v2 | `GET /api/v2/pages/{id}` |
| `doctor` | v2 + v1 | `GET /rest/api/user/current`, `GET /api/v2/spaces` |
| `download` | v2 + v1 | `GET /rest/api/content/{id}/child/attachment/{attachmentId}/download`, `GET /api/v2/attachments/{id}`, `GET /api/v2/blogposts/{id}/attachments`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/pages/{id}/attachments` |
| `export` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `GET /api/v2/folders/{id}/ancestors`, `GET /api/v2/folders/{id}/descendants`, `GET /api/v2/pages`, `GET /api/v2/pages/{id}`, `GET /api/v2/pages/{id}/ancestors`, `GET /api/v2/pages/{id}/descendants`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages` |
| `folder` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `GET /api/v2/folders/{id}/ancestors`, `GET /api/v2/folders/{id}/direct-children`, `GET /api/v2/pages`, `POST /api/v2/users-bulk` |
| `folder-create` | v2 | `POST /api/v2/content/convert-ids-to-types`, `POST /api/v2/folders`, `GET /api/v2/folders/{id}`, `GET /api/v2/pages/{id}`, `GET /api/v2/spaces` |
| `import-md` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `POST /api/v2/pages`, `GET /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages` |
| `import-md-dir` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `POST /api/v2/pages`, `GET /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages` |
| `label` | v2 + v1 | `POST /rest/api/content/{id}/label`, `DELETE /rest/api/content/{id}/label/{label}`, `GET /api/v2/pages/{id}/labels` |
| `labels` | v2 | `GET /api/v2/pages/{id}/labels`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/content/labels` |
| `move` | v2 + v1 | `PUT /rest/api/content/{pageId}/move/{position}/{targetId}`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `GET /api/v2/folders/{id}/ancestors`, `GET /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}` |
| `page` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/folders/{id}`, `GET /api/v2/footer-comments/{id}/children`, `GET /api/v2/pages`, `GET /api/v2/pages/{id}`, `GET /api/v2/pages/{id}/ancestors`, `GET /api/v2/pages/{id}/attachments`, `GET /api/v2/pages/{id}/footer-comments`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages`, `POST /api/v2/users-bulk` |
| `pages` | v2 | `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages` |
| `permissions` | v2 | `GET /api/v2/attachments/{id}/operations`, `GET /api/v2/blogposts/{id}/operations`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/custom-content/{id}/operations`, `GET /api/v2/databases/{id}/operations`, `GET /api/v2/embeds/{id}/operations`, `GET /api/v2/folders/{id}/operations`, `GET /api/v2/footer-comments/{id}/operations`, `GET /api/v2/inline-comments/{id}/operations`, `GET /api/v2/pages/{id}/operations`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/operations`, `GET /api/v2/whiteboards/{id}/operations` |
| `ping` | v1 | `GET /rest/api/user/current` |
| `properties` | v2 | `GET /api/v2/attachments/{attachment-id}/properties`, `GET /api/v2/blogposts/{blogpost-id}/properties`, `GET /api/v2/comments/{comment-id}/properties`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/databases/{id}/properties`, `GET /api/v2/embeds/{id}/properties`, `GET /api/v2/folders/{id}/properties`, `GET /api/v2/pages/{page-id}/properties`, `GET /api/v2/whiteboards/{id}/properties` |
| `property-set` | v2 | `GET /api/v2/attachments/{attachment-id}/properties`, `POST /api/v2/attachments/{attachment-id}/properties`, `PUT /api/v2/attachments/{attachment-id}/properties/{property-id}`, `GET /api/v2/blogposts/{blogpost-id}/properties`, `POST /api/v2/blogposts/{blogpost-id}/properties`, `PUT /api/v2/blogposts/{blogpost-id}/properties/{property-id}`, `GET /api/v2/comments/{comment-id}/properties`, `POST /api/v2/comments/{comment-id}/properties`, `PUT /api/v2/comments/{comment-id}/properties/{property-id}`, `POST /api/v2/content/convert-ids-to-types`, `PUT /api/v2/databases/{database-id}/properties/{property-id}`, `GET /api/v2/databases/{id}/properties`, `POST /api/v2/databases/{id}/properties`, `PUT /api/v2/embeds/{embed-id}/properties/{property-id}`, `GET /api/v2/embeds/{id}/properties`, `POST /api/v2/embeds/{id}/properties`, `PUT /api/v2/folders/{folder-id}/properties/{property-id}`, `GET /api/v2/folders/{id}/properties`, `POST /api/v2/folders/{id}/properties`, `GET /api/v2/pages/{page-id}/properties`, `POST /api/v2/pages/{page-id}/properties`, `PUT /api/v2/pages/{page-id}/properties/{property-id}`, `GET /api/v2/whiteboards/{id}/properties`, `POST /api/v2/whiteboards/{id}/properties`, `PUT /api/v2/whiteboards/{whiteboard-id}/properties/{property-id}` |
| `restore` | v2 + v1 | `POST /rest/api/content/{id}/version`, `GET /api/v2/pages/{id}` |
| `restrictions` | v2 | `GET /api/v2/blogposts/{id}/permissions`, `GET /api/v2/blogposts/{id}/restriction-state`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/databases/{id}/permissions`, `GET /api/v2/databases/{id}/restriction-state`, `GET /api/v2/folders/{id}/permissions`, `GET /api/v2/folders/{id}/restriction-state`, `GET /api/v2/pages/{id}/permissions`, `GET /api/v2/pages/{id}/restriction-state`, `GET /api/v2/whiteboards/{id}/permissions`, `GET /api/v2/whiteboards/{id}/restriction-state` |
| `search` | v2 + v1 | `GET /rest/api/search`, `GET /api/v2/pages` |
| `smartlink` | v2 | `GET /api/v2/embeds/{id}`, `GET /api/v2/embeds/{id}/ancestors`, `GET /api/v2/embeds/{id}/direct-children`, `GET /api/v2/folders/{id}`, `GET /api/v2/pages`, `POST /api/v2/users-bulk` |
| `smartlink-create` | v2 | `POST /api/v2/content/convert-ids-to-types`, `POST /api/v2/embeds`, `GET /api/v2/folders/{id}`, `GET /api/v2/pages/{id}`, `GET /api/v2/spaces` |
| `space` | v2 | `GET /api/v2/spaces` |
| `space-access` | v2 | `GET /api/v2/space-role-mode`, `GET /api/v2/space-roles`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/permissions`, `GET /api/v2/spaces/{id}/role-assignments` |
| `spaces` | v2 | `GET /api/v2/spaces` |
| `task` | v2 | `GET /api/v2/tasks/{id}`, `PUT /api/v2/tasks/{id}` |
| `tasks` | v2 + v1 | `GET /rest/api/user/current`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/spaces`, `GET /api/v2/tasks`, `POST /api/v2/users-bulk` |
| `template` | v1 | `GET /rest/api/template/{contentTemplateId}` |
| `templates` | v2 + v1 | `GET /rest/api/template/blueprint`, `GET /rest/api/template/page`, `GET /api/v2/spaces` |
| `tree` | v2 | `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/databases/{id}`, `GET /api/v2/databases/{id}/descendants`, `GET /api/v2/embeds/{id}`, `GET /api/v2/embeds/{id}/descendants`, `GET /api/v2/folders/{id}`, `GET /api/v2/folders/{id}/descendants`, `GET /api/v2/pages`, `GET /api/v2/pages/{id}`, `GET /api/v2/pages/{id}/descendants`, `GET /api/v2/spaces`, `GET /api/v2/spaces/{id}/pages`, `GET /api/v2/whiteboards/{id}`, `GET /api/v2/whiteboards/{id}/descendants` |
| `update` | v2 | `GET /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}`, `PUT /api/v2/pages/{id}/title` |
| `use` | v2 | `GET /api/v2/spaces` |
| `users` | v2 + v1 | `GET /rest/api/search/user`, `POST /api/v2/users-bulk` |
| `versions` | v2 | `GET /api/v2/pages/{id}`, `GET /api/v2/pages/{id}/versions`, `POST /api/v2/users-bulk` |
| `watch` | v2 + v1 | `DELETE /rest/api/user/watch/content/{contentId}`, `GET /rest/api/user/watch/content/{contentId}`, `POST /rest/api/user/watch/content/{contentId}`, `DELETE /rest/api/user/watch/space/{spaceKey}`, `GET /rest/api/user/watch/space/{spaceKey}`, `POST /rest/api/user/watch/space/{spaceKey}`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/spaces` |
| `watching` | v2 + v1 | `GET /rest/api/user/watch/content/{contentId}`, `GET /rest/api/user/watch/space/{spaceKey}`, `POST /api/v2/content/convert-ids-to-types`, `GET /api/v2/spaces` |
| `whiteboard` | v2 | `GET /api/v2/folders/{id}`, `GET /api/v2/pages`, `POST /api/v2/users-bulk`, `GET /api/v2/whiteboards/{id}`, `GET /api/v2/whiteboards/{id}/ancestors`, `GET /api/v2/whiteboards/{id}/direct-children` |

`conflu api` reaches any endpoint that you name (`GET` is free, `POST` and `PUT` need `--write`, `DELETE` does not exist); what it sends is
what you wrote, so the rows above are only the calls of the examples of its sweep line.

## Why some calls use v1

Each of these is a documented, non-deprecated v1 operation for which the v2 document has no equivalent, as of 2026-10-30.

| Call | Why v1 |
| --- | --- |
| `PUT /rest/api/content/{id}/child/attachment` | v2 reads attachments and has no upload. |
| `GET /rest/api/content/{id}/child/attachment/{attachmentId}/download` | v2 describes an attachment but has no call that serves its file. |
| `POST /rest/api/content/{id}/label` | v2 reads the labels of content and has no call that adds one. |
| `DELETE /rest/api/content/{id}/label/{label}` | v2 reads the labels of content and has no call that removes one. |
| `POST /rest/api/content/{id}/version` | v2 reads the versions of a page and has no call that restores one. |
| `PUT /rest/api/content/{pageId}/move/{position}/{targetId}` | v2 can only put a page below another parent, by saving a new version of it: before and after another page need this call. |
| `GET /rest/api/search` | v2 has no CQL search. |
| `GET /rest/api/search/user` | v2 has no search for people: its bulk lookup only answers for account ids that are known already. |
| `GET /rest/api/template/blueprint` | v2 has no templates: it cannot list the templates that blueprints provide. |
| `GET /rest/api/template/page` | v2 has no templates: it cannot list the page templates of a space or the global ones. |
| `GET /rest/api/template/{contentTemplateId}` | v2 has no templates: it cannot read one template with its body. |
| `GET /rest/api/user/current` | v2 has no call for the user who owns the token. |
| `DELETE /rest/api/user/watch/content/{contentId}` | v2 has no watches: it cannot make you stop watching a page or other content. |
| `GET /rest/api/user/watch/content/{contentId}` | v2 has no watches: it cannot say whether you watch a page or other content. |
| `POST /rest/api/user/watch/content/{contentId}` | v2 has no watches: it cannot make you watch a page or other content. |
| `DELETE /rest/api/user/watch/space/{spaceKey}` | v2 has no watches: it cannot make you stop watching a space. |
| `GET /rest/api/user/watch/space/{spaceKey}` | v2 has no watches: it cannot say whether you watch a space. |
| `POST /rest/api/user/watch/space/{spaceKey}` | v2 has no watches: it cannot make you watch a space. |

## When something differs on your site

Run `conflu doctor --json`, and `conflu api GET PATH -v` for the call that failed (`-v` logs the requests, never the credentials). Redact
site names, ids and names of people before you paste anything into an issue (see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
