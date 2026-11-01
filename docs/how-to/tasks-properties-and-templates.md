# Tasks, properties and templates

Three small things that live next to the pages of a space: the **tasks** (the checkboxes) that are written into pages and blog posts, the **content properties**
(a piece of JSON under a key, on a page or on other content), and the **templates** of a space. This guide shows how to read all three, how to tick a task off,
how to set a property, and what the CLI does not do.

The commands follow the Confluence Cloud REST API documentation. They are tested against a mock server that follows the same documents, not against a real
site, so try a change with `--dry-run` first.

## Find tasks

```bash
conflu tasks --mine --status incomplete
conflu tasks --page 123456
conflu tasks --task 7201 --task 7203 --json
conflu tasks --space ENG --due-after 2026-10-26 --due-before 2026-11-01
conflu tasks --created-by-me --status complete --all --select id,pageId,completedAt --format tsv
conflu tasks --mine --with-users --json
```

Without a filter `conflu tasks` lists the tasks of the whole site; every filter that you give has to hold. The current space of `conflu use` is **not** assumed.

| Filter | Keeps |
| --- | --- |
| `--space KEY` | the tasks of one space; a personal space is `[hidden]` in the answer (its key is the account id of its owner) unless you add `--with-users` |
| `--page ID` | the tasks of one page or blog post (an id, or the address copied from the browser) |
| `--task ID`, once for each task | the tasks with those ids: at most 250, each a positive whole number |
| `--status incomplete` or `complete` | the tasks in that state |
| `--mine` | the tasks that are assigned to the user of the token |
| `--created-by-me` | the tasks that the user of the token created |
| `--due-after DAY`, `--due-before DAY` | a range of due days, `YYYY-MM-DD` |

- **A date is a day.** It counts from 00:00 UTC, both ends are in the range, and a task that has no due date is in no range at all. A date that is no day
  (`2026-02-30`), or a year before 1970, is a usage error that says so before anything is sent.
- **`--mine` and `--created-by-me` need one more request**, to find out who the token belongs to. That account id is the filter and is never printed.
- **A page or a blog post is asked what it is first**, because the ids of pages, blog posts, folders and the rest are numbers of one sequence. A folder or a
  comment holds no tasks, and the message says what the id is.
- **One task by its id.** `conflu tasks --task 7201` (and `--task 7201 --task 7203` for two) lists only those tasks, in one read. It is how to read a task where
  `conflu task`, which can also change one, is not offered: `conflu mcp` without `--allow-write` offers `tasks` and not `task`. The answer is a list like any other
  (`count`, `tasks`); an id that no task has, or that your other filters do not let through, is simply not in it, and that is no error. An id that is not a positive whole
  number, or more than 250 ids, is refused (exit code 2) before anything is sent; the same id twice is sent once.
- **The text of a task is plain text.** A mention is `@user` and an e-mail address is redacted, like everywhere else.
- **A list comes in pieces.** `--limit N` (1 to 250) and `--cursor TOKEN` pick one; a note on standard error gives the cursor of the next one (the JSON has
  `nextCursor`). `--all` reads every piece: `--limit` and `--cursor` are not used then, but a `--limit` out of range is still refused (exit code 2).
  `--select a,b.c` and `--format table|tsv|md` shape the list, as for the other lists.

### Who made it, who got it, who did it

The people of a task (`assignedTo`, `createdBy`, `completedBy`) are `null` in the JSON and left out of the table unless you add `--with-users`. They are shown as
account ids with the name and the address that Confluence gives for them, looked up in one request for the whole list; a person whom Confluence does not describe
stays an id. `CONFLUENCE_HIDE_USERS=true` refuses `--with-users` and sends nothing. `conflu task ID` never names anybody.

## Tick a task off, or untick it

```bash
conflu task 7201
conflu task 7201 --complete --dry-run
conflu task 7201 --complete
conflu task 7201 --reopen --json
```

Without a flag `conflu task ID` shows the task and changes nothing. With `--complete` or `--reopen` the task is read first, so the command can be repeated:

| You ask for | The task is | `action` | Sent |
| --- | --- | --- | --- |
| `--complete` | incomplete | `completed` | `PUT` of the status |
| `--complete` | complete | `unchanged` | nothing |
| `--reopen` | complete | `reopened` | `PUT` of the status |
| `--reopen` | incomplete | `unchanged` | nothing |

- **The status is all that a call can change** about a task: Confluence's own description says that the call "currently only supports updating task status".
  What is sent is `{"status": "complete"}` or `{"status": "incomplete"}`, and nothing else (`payload` in the JSON).
- **The dry run reads the task and sends nothing**; the payload that it shows is the one that the real run sends.
- **The task is read again after the change**, and what that read shows is what the answer says, as for `conflu move`: `confirmed` in the JSON is `true` when the task is in the state that was
  asked for, and the line is `Completed task N: ...` (or `Reopened`). When Confluence accepted the call and the task did not change, or somebody changed it again in between, `confirmed` is `false`
  and the line says so instead (`Confluence accepted the request to complete task N (incomplete -> complete), but it still shows the task as incomplete.`); `message` and a warning on standard error
  say how to look (`conflu task N --json`, `status`), and the exit code is 0. If the read fails, the change is still reported as made: `readBack` is `false`, `confirmed` is `null`, and `notes`,
  `message` and a warning say so. A dry run and a task that is in the state already have nothing to confirm (`confirmed` is `null`). Do not repeat the command because of either: look at the task first.
- `--complete` and `--reopen` together are a usage error, and so is `--dry-run` without one of them (there is nothing to preview).
- Changing a task needs the permission to edit the page that holds it. Without it Confluence answers that the task is not found (the API document gives HTTP 404 for a
  missing permission as well as for a missing task, so that is exit code 4, `Not found: PUT /api/v2/tasks/ID`, although the same command has just read the task; a 403,
  if a site sends one, is exit code 5), and the task is as it was.

## Content properties

A **content property** is a small piece of JSON with a key and a version, kept on a page, a blog post, a folder, a whiteboard, a database, a smart link, an
attachment or a comment. Apps keep their settings and their marks in them, and so do scripts.

```bash
conflu properties 123456
conflu properties 123456 --key team.review --json
conflu properties att5001 --all --max-chars 0
conflu properties 123456 --with-users
```

- **Any kind of content.** The id is asked what it is, and each kind has its own collection in the API. An attachment's id starts with `att`, which says what it is.
  Spaces, apps and the custom content of apps also have properties; no command here reads them.
- **A value is any JSON** and is shown as one line of compact JSON, cut at `--max-chars N` characters (2000 unless you say another number; 0 cuts nothing). In the
  JSON a value is the value itself, and only one that was cut is a text instead: the beginning of its compact form followed by `[value cut]`, with `truncated` and `totalChars`.
  **To change a value, read it whole:** `conflu properties ID --key KEY --max-chars 0 --json` (add `--with-users` when it holds people; an agent passes `maxChars` 0 to the tool). Zero cuts nothing, and a value that
  this CLI writes is at most 32 KiB, so the answer stays small; `property-set` refuses the cut text (see below).
- **People stay out of a value.** A user object, an account id (as a value, inside a text and as the key of an object, in capitals or not), an e-mail address and a link to a profile are
  hidden unless you add `--with-users`, which `CONFLUENCE_HIDE_USERS=true` refuses. The key of a property is free text and is treated alike.
- **A text that holds JSON is read as JSON.** Apps store `JSON.stringify(state)`, which is a text, and a display name in it is neither an address nor an account id. A text that begins like an
  object or an array and is JSON (up to 1,000,000 characters, also when it was encoded up to four times, and not nested deeper than 100 levels with the value that holds it) is read as JSON, so
  that the user objects in it are hidden like the others, and it is shown as compact JSON again (`{"reviewer":{"hidden":true}}`) when something in it was hidden; when nothing was, it is shown
  as it is, down to its blanks. A text that is not JSON, or that is longer or deeper, is read by the rules for texts only: an account id, an address and a link are hidden in it, a name is not.
  With `--with-users` the text is what is stored.
- **A value that nests arrays and objects too deeply** is shown as `[nested too deeply to show]`; one that is nested far deeper than the program can read at all
  is an error that says so (exit code 7), not a crash.
- `--key KEY` shows the one property with that key (case sensitive). A list comes in pieces as for the tasks (`--limit`, `--cursor`, `--all`).

## Set a property

```bash
conflu property-set 123456 --key team.review --value '{"status":"open"}' --dry-run
conflu property-set 123456 --key team.review --file value.json --if-version 3 --message "Reviewed"
conflu property-set 123456 --key my-app:flag --value true
conflu property-set 123456 --key note --value '"a text"' --json
```

The property with the key is looked for first:

| The key is | The value is | `action` | Sent |
| --- | --- | --- | --- |
| not there | any | `created` | `POST` with the key and the value |
| there | another | `updated` | `PUT` with the value and the next version: the current one plus one |
| there | the same | `unchanged` | nothing |

A creation is reported as `Created the property KEY on the page ID (id N, version 1).`, with what Confluence answered. An answer that names no id for the new property is still a
creation, and the line is `Created the property KEY on the page ID.` without an id (`propertyId` is `null` in the JSON): look the property up with `conflu properties ID --key KEY`.

- **The value must be valid JSON**, at most 32 KiB as compact JSON and 100 levels deep, and every number must be finite: `1e999` is refused (JSON has no infinity). A number with a fraction or
  an exponent is kept as a 64-bit float, so `12345678901234567890.5` is sent as `1.2345678901234567e+19`; a whole number keeps all its digits. A text needs its own double quotes (`'"a text"'`); a bare word is a usage error
  that says so. **Windows PowerShell 5.1 removes the double quotes inside an argument**: put the value into a file and pass `--file value.json`; a pipe, `--file -`, works for
  ASCII only in that shell (it turns every other character into `?`). A file may be UTF-8, UTF-16 or Windows-1252. `1` and `1.0` are one number, and an object has no order of its keys, so neither makes a new version.
  A negative number with an exponent (`-1e5`) must be written `--value=-1e5`: without the `=` the program takes it for an option.
- **The key** holds letters, digits and `_ . : -` only, from 1 to 255 characters, and is case sensitive.
- **What `conflu properties` shows is not always the value.** A reading hides people, cuts long values and leaves the title off the address of a page when the title holds an e-mail address. A new
  value that is a copy of such a reading is refused (exit code 1, nothing sent, also in a dry run): saving it would overwrite what the property holds, and no command may redact what Confluence holds.
  These markers make a value a copy: `[hidden]` (an account id), `[email]`, `[personal link]`, `[personal space]`, `{"hidden": true}` (a user object), `[nested too deeply to show]`, an attribute
  that was blanked in a text that is storage format (`ri:account-id="hidden"`, `data-account-id="hidden"`, `ri:space-key="[hidden]"` and the like), and `[value cut]`, the end of a value that was cut at `--max-chars`.
  A text that was shown in a changed form with no marker in it (an address that lost its title, or a text of JSON that was shown as compact JSON without its user objects) is refused as well, and the message shows it. Read the whole real value with
  `conflu properties ID --key KEY --with-users --max-chars 0 --json` (`--with-users` is refused under `CONFLUENCE_HIDE_USERS=true`, and a value that holds people cannot be edited then), change only what you need
  and write that; written back unchanged it is `unchanged`. A marker that the property holds itself (an app's flag `{"hidden": true}`, a text that says `[email]`) does not count, unless it stands where the reading hid a person:
  the value is compared with the reading place by place, so that a marker of the app next to an account id does not let that account id be overwritten, and what was moved to another place is found by counting the markers and
  the changed texts. A new property may hold anything but `[value cut]`, which no value is: it is refused for a property that is new as well.
- **A guard.** `--if-version N` refuses (exit code 3, nothing sent, also in a dry run) unless the property is at version N now; `0` says that it must not exist yet.
  Without it, a save that loses against somebody else's is Confluence's HTTP 409, which is exit code 3 as well, and the hint says to read the property again.
- **A message.** `--message TEXT` is stored with the new version of a property that is saved again; a new property has none, and a note says so.
- **The dry run reads and sends nothing.** It says whether the property would be created or saved, shows the value that is there (without people) and the new one, and
  gives the payload that a real run sends (`payload` in the JSON).
- **Apps use properties.** A property that an app keeps may be read by the app on every use: changing it can change what the app does. Look at what a property holds
  (`conflu properties`, with `--with-users` when it holds people) before you set it, and keep the old value: the answer of a change shows it (without people), and
  setting it again makes a new version with the old value.
- **No command deletes a property**, and the CLI has no undo. That is on purpose: a property may be somebody else's setting.

## Templates

```bash
conflu templates
conflu templates --space ENG --json
conflu templates --blueprints --space ENG --all
conflu template 123456
conflu template 123456 --format storage --body-only --out body.xml
```

`conflu templates` lists the page templates of one space (`--space KEY`), or the global ones without it (the current space is not assumed), and with `--blueprints` the
templates that blueprints provide. The table has the id, the name, the type, the space and the description; the labels and the blueprint that a template references are in the JSON
(`--json`, or `--select id,labels` for those keys alone). `conflu template ID` shows one template: what it
is, the **variables** that it declares, and its body.

- **The body is converted like the body of a page** (`--format markdown`, `text` or `storage`), with the people hidden. The variables of a template are `<at:var>`
  elements, which the Markdown copy cannot show, so they are listed from the storage format, each once, in the order in which they first appear
  (`variables` in the JSON). What looks like a variable inside a comment (`<!-- ... -->`) or a CDATA section (the code of a code macro stands in one) is text, and is not listed.
  A body that holds more such tags than a person writes (or longer ones) is read as far as is reasonable and says that the list may be
  incomplete (`variablesComplete` is `false`); so does a comment or a CDATA section that never ends.
- **A template of a personal space** lies in a space whose key is the account id of its owner: the list says `[hidden]` for the space (`space`, and the `spaceKey` of each template, and the
  text of a refusal), `conflu template` does too, and a link in a body to a page in a personal space reads `page:[hidden]/Title`. The calls still name the space by its key.
- **Templates are known to the older REST API only** (`/rest/api/template`), which pages with `--start` and `--limit`: the JSON has `nextStart`, and `--all` reads every piece (`--limit` and `--start` are not
  used then, but a `--limit` out of range or a negative `--start` is still refused, exit code 2).
  [compatibility](../reference/compatibility.md) lists the calls and why.
- **A template that does not exist is HTTP 403**, as it is for one that this account may not see: that is exit code 5, and the message says so without repeating Confluence's
  own words. A space that does not exist is "not found" (exit code 4): the key is asked for first.
- **The API cannot make a page from a template**, and nothing in this CLI does. To start a page from one, save the body and create the page from the file:

  ```bash
  conflu template 123456 --format storage --body-only --out body.xml
  conflu create --space ENG --title "Release 2026.11" --file body.xml --format storage --dry-run
  ```

  `--out` writes the body as UTF-8 itself and does not replace a file that is there without `--force`; `>` would damage every character that is not ASCII in Windows PowerShell 5.1.
  The people in a template come out blanked, so a template with a mention cannot be copied like this: `conflu create` refuses a body with a mention whose account id
  was hidden. Copy such a template in the browser. The variables stay in the body as the template has them.

  **E-mail addresses and personal links come out as `[email]` and `[personal link]`**, and `conflu create` does not refuse them: a page created from that file would carry those words. When the
  body of `--format storage` has lost any, the command says so on standard error (the body itself is on standard output, or in the file, and is the same):

  ```text
  [conflu] WARNING: N e-mail addresses and personal links were replaced by [email] and [personal link] in this body: a page created from it would carry those words, not the addresses and links. `template` has no --with-users, so put the real ones into the file before you create the page, or take them out.
  ```

  `N` is the number of places (`1 e-mail address or personal link was replaced` for one). `conflu template` has no `--with-users`: the template commands never show people, so the real address or
  link has to be typed into the file, or left out, before `create`. A body that says `[email]` itself is not counted again. Markdown and text bodies say nothing (their `dropped` list and the note
  on standard error name `redacted-text`), and neither does a template that holds no address and no link.
- **A dry run of `create` cuts a long body, and says what is in the cut part.** The text of the dry run of `create`, `update`, `blogpost-create` and the other commands that print a request shows at most
  the first 1500 characters of the body. When the part that is left out has macros or external addresses in it (an `ac:structured-macro`, a `ri:url`), the cut says how many, as a count and never
  as the text: `... (1283 more characters, among them 2 macros and 1 external address)`. `--json` is never cut: it holds the whole body, as the request that a real run sends.

## What the CLI does not do

- It does not create, delete or edit tasks, or change who they are assigned to, their due date or their text: the API changes the status only.
- It does not delete a property, and it does not read or set the properties of a space, of an app or of custom content.
- It does not create, change or delete a template, and it does not make a page from one.
- It shows people only on request, and never says who a person is beyond what Confluence describes.

## Related guides

- [find-information.md](find-information.md)
- [folders-and-structure.md](folders-and-structure.md)
- [use-with-ai-agents.md](use-with-ai-agents.md)
- [configure.md](configure.md)
