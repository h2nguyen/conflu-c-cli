# Watches and users

Two small things about people: whether **you** get notifications for a page or a space (a *watch*), and who a person is
(find an account id by name, or see who is behind an account id). This guide shows both and says what the CLI does not do.

The commands follow the Confluence Cloud REST API documentation. They are tested against a mock server that follows
the same documents, not against a real site, so try a change with `--dry-run` first.

## Do you watch it?

```bash
conflu watching 123456                 # a page: its id, or the address copied from the browser
conflu watching --space ENG            # a space, by its key
conflu watching 123456 --json
```

A blog post, a folder or any other content is named by its id. Without a page and without `--space`, `conflu watching` asks
about the current space of `conflu use`. The answer is yes or no, for **your own account** only: Confluence is asked
without naming anybody, so it answers for the owner of the token. Who else watches is not shown. A space is shown as `conflu spaces`
shows it: its name has its e-mail addresses redacted, and a personal space, which is named after its owner and keyed by the owner's
account id, comes out as `[hidden] ([personal space])` (the key that you typed is still the one that is sent).

## Watch it, or stop

```bash
conflu watch 123456 --dry-run          # what would be sent; nothing is sent
conflu watch 123456
conflu watch --space ENG
conflu watch 123456 --remove           # stop watching
```

- **Your own watch only.** There is no option that names another person, here or in the calls below it. (The REST API lets an
  administrator name another person's account; this CLI never does.)
- **A change names what it changes.** Give the id or address of the content, or `--space KEY`. The current space of
  `conflu use` is not assumed (`conflu watching` may assume it, because it only reads).
- **The status is read first**, so the command can be repeated:

  | You ask for | You now | `action` | Sent |
  | --- | --- | --- | --- |
  | `conflu watch X` | do not watch | `watched` | `POST` |
  | `conflu watch X` | watch | `unchanged` | nothing |
  | `conflu watch X --remove` | watch | `unwatched` | `DELETE` |
  | `conflu watch X --remove` | do not watch | `unchanged` | nothing |

- **The dry run reads and sends nothing.** It names the call that the real run makes (`call` in the JSON).
- **The status is read again after the change.** If that read fails, or Confluence still shows the old state, the change
  is still reported as made: exit code 0, `confirmed` is `null` (or `false`), a warning on standard error says how to
  check (`conflu watching X`), and `message` says the same in the JSON. Do not repeat the command because of it.
- **`--remove` removes only your own watch.** A watch is a notification setting of your account, not content, and the call
  cannot name anybody else. It is the one command, besides `conflu label --remove`, that sends a `DELETE`.

The REST API v2 has no call for watches, so the commands use the v1 calls `GET`, `POST` and `DELETE` of
`/rest/api/user/watch/content/{contentId}` and `/rest/api/user/watch/space/{spaceKey}`. Every write carries the header
`X-Atlassian-Token: no-check`, which the document asks for because of the XSRF protection of most of them.
[compatibility](../reference/compatibility.md) lists the calls with the reason for each.

## Find a person

```bash
conflu users search alex --with-users
conflu users search Alex Example --with-users --json       # several words need no quotes
conflu users search '@name.txt' --with-users               # the name in a file
conflu users lookup 5b10ac8d82e05b22cc7d4ef5 --with-users
conflu users lookup '@ids.txt' --with-users --json         # account ids, one to a line
```

`search` shows the people whose name holds the text, case aside. `lookup` shows the people behind account ids, such as the
ones other commands print when you ask for people: separated by blanks or commas, at most 250 at a time. Each person is the
account id, the display name, the e-mail address **only when Confluence returns one** (it depends on the privacy setting of
the person) and the account type.

```text
ACCOUNT ID                NAME          EMAIL             TYPE
5b10ac8d82e05b22cc7d4ef5  Alex Example  alex@example.com  atlassian
```

- **People are shown on request only.** Both actions are refused without `--with-users` (a usage error, exit code 2) and
  **always** when `CONFLUENCE_HIDE_USERS=true`, which the profile `CONFLUENCE_PROFILE=agent` sets (exit code 1). Nothing is
  sent in either case, and a file named as `@FILE` is not even opened. This is the one place where people are the point; it is
  no way around the policy, and no other command shows more because of it.
- **A name stays a text.** It goes into the CQL string `user.fullname ~ "..."` with its double quotes and backslashes
  escaped, so a name such as `a" OR user = "b` finds nobody of that name and changes nothing else in the query. The text that
  was sent is `cql` in the JSON.
- **A name with double quotes in Windows PowerShell 5.1** arrives without them, because PowerShell removes them inside an
  argument. Put the name in a file and pass it in single quotes, `'@name.txt'` (a bare `@name` is splatting in PowerShell); a pipe with `-` works for ASCII
  only in that shell. A file may be UTF-8, UTF-16 or Windows-1252.
- **A search comes in pieces.** `--limit N` (1 to 250; Confluence may allow fewer) and `--start N` pick a piece; the JSON has
  `nextStart` for the next one (`null` on the last), and a note on standard error says where to go on. `--all` fetches every
  person (up to 5000, and says when it stopped there).
- **An account id that Confluence does not describe is not an error.** It is left out of `users` and listed in `notFound`:
  the id is wrong, or the person cannot be looked up by this account.
- `--select a,b.c` and `--format table|tsv|md` shape the list, as for the other lists.

`search` is the v1 call `GET /rest/api/search/user` (the API v2 has no search for people); `lookup` is the v2 bulk lookup,
`POST /api/v2/users-bulk`.

## What the CLI does not do

- It does not change anybody else's watch, list who watches a page or a space, or watch a label (the API has a call for that;
  no command uses it).
- It does not search for groups, and it shows a person only as far as Confluence describes them: nothing is guessed, and no
  picture, time zone or personal space is shown.
- It does not say who may read or edit a page: the permissions of content are not read by these two commands.

## Related guides

- [find-information.md](find-information.md)
- [use-with-ai-agents.md](use-with-ai-agents.md)
- [configure.md](configure.md)
