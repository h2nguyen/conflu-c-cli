# Access and restrictions

Who may see or change a page, what your own account may do with it, and who may use a space: three commands answer these
questions, and all three only read. `conflu permissions` says what the account of your token may do, `conflu restrictions`
shows whether content is restricted and how many users and groups are granted access, and `conflu space-access` shows how
a space gives access. People stay out of every answer until you add `--with-users`.

The commands follow the Confluence Cloud REST API v2 documentation (v2 has all of it). They are tested against a mock server
that follows the same document, not against a real site, so compare an answer with the web interface before you rely on it.

## What may my account do? `conflu permissions`

```bash
conflu permissions 123456                       # a page: every operation that this account is allowed
conflu permissions 123456 --only update,delete  # yes or no for each name
conflu permissions --space ENG                  # the same in a space (without --space: the current space)
conflu permissions 123456 --json
```

```text
What this account may do with the page [123456]:
OPERATION         ALLOWED  ON
read              yes      page
update            yes      page
delete            yes      page
archive           yes      page
copy              yes      page
create            yes      attachment, comment
restrict_content  yes      page
```

- The id is that of a page, blog post, folder, whiteboard, database, smart link, comment or attachment, or the address copied from
  the browser. What it is gets looked up with one request, so the right call is made; an attachment id (`att5001`) says what it is.
  The key of a space is not an id: `conflu permissions ENG` says so and points at `--space ENG`.
- Read, update and delete are always answered, yes or no; the other operations are listed when they are allowed. `ON` says what an
  operation is done to: `create` can be allowed for a comment and an attachment and not for a page.
- `--only update,delete` keeps those operations and answers `no` for one that is not allowed. A name that is not an operation of the
  documents (`updat`) is refused with the list of the known ones, before anything is asked: `no` for a typo would be a wrong answer.
- It answers for the account of the token only. It does not say who else may read or edit.

## Is it restricted? `conflu restrictions`

```bash
conflu restrictions 123456                       # the state, and how many users and groups hold read and update
conflu restrictions 123456 --with-users          # and who they are (the account ids of users, the ids of groups)
conflu restrictions 123456 --with-users --all --select operation,principalType,principalId --format tsv
```

```text
The page [123456] is VIEW_RESTRICTED.
Viewing and editing are restricted to the users and groups that are granted it.
Set on 2026-10-03T09:00:00.000Z.

5 direct permissions:
OPERATION  USERS  GROUPS
read       2      1
update     1      1
```

| State | What the document says |
| --- | --- |
| `OPEN` | No direct restriction. A parent may still restrict who can see or edit it. |
| `EDIT_RESTRICTED` | Viewing is open, but editing is restricted to the users and groups that are granted it. |
| `VIEW_RESTRICTED` | Viewing and editing are restricted to the users and groups that are granted it. |

- **Only what is set on the content itself.** A restriction that a parent page or folder sets is not in these calls, so `OPEN`
  does not mean that everybody may read it. The answer says so in `notes`.
- Pages, blog posts, folders, whiteboards and databases have a restriction of their own. A smart link, a comment and an attachment
  have none: the command says so (exit code 1) and tells you to ask for the content that it belongs to.
- The counts are of all the direct permissions, whatever piece you ask for. The principals come one piece at a time (`--limit N`,
  default 25; `--cursor TOKEN` is the `nextCursor` of the previous answer; `--all` shows every one), sorted by operation, kind and id.
  `--select` and `--format table|tsv|md` shape that list.
- With `--with-users` the answer also names who set the restriction. A group is shown by its id: naming it would need a call that
  v2 does not have. `conflu users lookup ACCOUNT_ID --with-users` says who an account id is.

## Who may use a space? `conflu space-access`

```bash
conflu space-access ENG                   # the role mode, and how many users, groups and roles hold what
conflu space-access ENG --with-users --all --json
conflu space-access ENG --with-users --select principalType,principalId,roleName --format md
```

A site gives access with permissions, with roles, or while it moves from one to the other, and the command asks the site:

| Role mode | What is read |
| --- | --- |
| `PRE_ROLES` | The permission assignments: who may do what in the space. |
| `ROLES` | The role assignments: who has which role (Admin, Contributor, Viewer or a role of the site), with the names of the roles. |
| `ROLES_TRANSITION` | Both. |
| none reported | A site without space roles reports none: both are tried, and the permissions are what is shown when the roles are not there (Confluence answers "not found" or a bad request). |

The counts say how many users, groups and roles (or access classes, the audiences that are no single person, such as everybody
who has an account) hold each operation or role. The roles are those of the space; a role that cannot be named is shown by its id, and
a `notes` line says why. The principals are listed with `--with-users`, in the same pieces as in `restrictions`.

## People: when ids and names appear

- Without `--with-users` no account id, group id, display name or e-mail address is printed, and an address that a space or role name
  holds is redacted. A personal space is named after its owner and keyed by the owner's account id, so it comes out as `[hidden]` (the key)
  and `[personal space]` (the name), as in `conflu spaces`; `permissions` always shows it so, `space-access` shows it as Confluence names it with `--with-users`.
- `--with-users` is refused (exit code 1) when `CONFLUENCE_HIDE_USERS=true` (the agent profile sets it), before anything is asked;
  the counts still work. See [configure](configure.md).
- `--limit`, `--cursor`, `--all`, `--select` and `--format` shape the list of principals, which there is none of without
  `--with-users`: they are a usage error (exit code 2) without it.
- Exit codes: 1 for something that is no id, a key that is no space key, content that has no restriction of its own, or a refused
  `--with-users`; 2 for a command line that is wrong; 4 for content or a space that does not exist (Confluence says the same for
  what this account may not see); 5 when Confluence refuses the token.

## For programs

Every command takes `--json`: `target` says what was asked about (`id`, `type`, and for a space `key` and `title`), and the counts,
`usersShown`, `nextCursor` and `notes` are always there. The principals are `null` until `--with-users`. The keys are in the
[JSON reference](../reference/json-output.md). The three commands only read, so `conflu mcp` can offer them to a model; see
[use with AI agents](use-with-ai-agents.md) for how people are kept out of what a model sees.

## What the CLI does not do

- It changes nothing: no restriction, no permission, no role. Who may see or edit content is changed in the web interface, or
  with `conflu api ... --write` (it sends `POST` and `PUT` only, and `--dry-run` shows the request first).
- It does not show a restriction that a parent sets, and it does not work out who may read a page after all restrictions: the REST API
  has no call for that.
- It does not name groups, and it does not list the permissions that a site offers.

## Related guides

- [use-with-ai-agents.md](use-with-ai-agents.md)
- [configure.md](configure.md)
- [folders-and-structure.md](folders-and-structure.md)
- [troubleshooting.md](troubleshooting.md)
