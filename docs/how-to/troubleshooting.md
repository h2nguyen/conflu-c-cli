# Troubleshooting

When something is wrong, start with the one command that checks the whole setup:

```bash
conflu doctor
conflu doctor --json
```

It checks the runtime, config file, base URL, e-mail address, token, TLS, where the launcher is, the connection, whether
spaces can be read, which of the two REST APIs answer, the current space and the privacy policy.

`conflu doctor --quick` asks Confluence twice at most and leaves out the check of the current space.
`conflu doctor --cached 10m` reuses the online checks of the last successful run if it is not older than ten minutes
(`30s`, `10m`, `2h`, `1d`) and says so; run it without `--cached` for a fresh answer. The file it reads is
`doctor-HASH.json` in `~/.cache/conflu-c-cli` (`XDG_CACHE_HOME` first); it holds the checks only and can be deleted at
any time. `conflu doctor --strict-privacy` fails when people can be shown.

## `conflu` is not found

On Windows the installer writes `conflu` and `conflu.cmd` to `~/bin`, which Git Bash usually searches and
PowerShell usually does not. `conflu doctor` has a check `launcher` that warns about exactly this and prints the
`python install.py --bin-dir DIR` command; the installer prints it too, with a folder that is on the `PATH`, that you
can write to and that already holds the launcher of the sibling `jira` CLI. Three fixes are in
[install and update](install-and-update.md#use-it-from-powershell-and-cmd);
the quickest one needs no `PATH` change:

```powershell
python "$env:LOCALAPPDATA\conflu-c-cli\conflu.py" doctor
```

Restart VS Code after changing the `PATH`.

## `CONFLUENCE_BASE_URL is not set` or the wrong config file is used

Check the file in use:

```bash
conflu config path
conflu config show
```

Remember the lookup order:

1. `CONFLUENCE_CONFIG_FILE`
2. `XDG_CONFIG_HOME/conflu-c-cli/config` when that file exists
3. `.config/conflu-c-cli/config` below `HOME`, else `HOMEDRIVE` + `HOMEPATH`, else the Windows profile

An environment variable overrides the file while it is set.

## `CONFLUENCE_EMAIL` or the token is wrong

```bash
conflu config show
conflu ping
conflu remove-token
conflu setup-token
```

`conflu config show` masks the token and shortens the e-mail address. If the token was exposed, rotate it in
Atlassian and save a new one.

## TLS errors on a company network

If you see a certificate error, especially one like:

```text
CERTIFICATE_VERIFY_FAILED ... Missing Authority Key Identifier
```

then a TLS-inspecting company proxy is a likely cause. The CLI already leaves Python 3.13's strict X.509 checks
off by default (`CONFLUENCE_TLS_STRICT=false`), while still verifying the certificate chain and the host name.
What to try, in order:

1. **Use the company CA bundle** when the company CA is not in the system store:

   ```bash
   conflu config set CONFLUENCE_CA_BUNDLE C:/certs/company-ca.pem
   conflu doctor
   ```

2. **If you turned strict mode on, turn it off again** unless you really need Python's default strictness:

   ```bash
   conflu config set CONFLUENCE_TLS_STRICT false
   ```

3. **Use `CONFLUENCE_INSECURE` only as a short diagnostic.** It disables all certificate verification and should
   not become the standing fix.

## `unable to get local issuer certificate`

The server sent its certificate, but the system store of this computer holds no authority that vouches for it. The error
now names the chain the server presented, for example:

```text
'wiki.company.example' <- 'Amazon RSA 2048 M04' <- 'Amazon Root CA 1' <- 'Starfield Services Root Certificate Authority - G2' (not sent by the server)
```

Typical causes: the computer manages its own list of trusted authorities and a public one is missing (Amazon, here), or the
company's TLS-inspecting proxy re-signs traffic with a company CA that this computer does not know. What to do:

1. Check whether you need that address at all: for a company domain see [API tokens do not work on a custom domain](#401-or-403-on-a-company-domain-api-tokens-do-not-work-there)
   below; the gateway address `api.atlassian.com` is usually trusted already.
2. Otherwise get the certificate of the missing authority **from the organisation that runs it** (a public CA publishes its
   roots, for example Amazon Trust Services publishes Amazon Root CA 1) or from your IT department, check its SHA-256
   fingerprint against what they publish, save it as a PEM file and add it:

   ```bash
   conflu config set CONFLUENCE_CA_BUNDLE C:/certs/amazon-root-ca-1.pem
   conflu doctor
   ```

   The file is trusted in addition to the system store. Do not take the certificate from the server that is being refused:
   anyone who can sit between you and it could hand you theirs.
3. `CONFLUENCE_INSECURE` would switch all checks off. It is not a fix.

## 401 or 403 on a company domain: API tokens do not work there

If `CONFLUENCE_BASE_URL` is an address of your own (`https://wiki.company.example/wiki`) and `conflu doctor` says 401, or 403
with `caller cannot access Confluence`, the token was not even read: Atlassian accepts API tokens on `SITE.atlassian.net` and on
its gateway, not on a custom domain of the site. The same 403 comes back without any credentials, which is how to recognise it.

```bash
conflu setup --discover      # proposes https://api.atlassian.com/ex/confluence/CLOUD_ID and asks before it saves
conflu doctor
```

`conflu setup --discover` reads the public tenant information of the host in `CONFLUENCE_BASE_URL` (no credential is
sent). To do it by hand, open `https://wiki.company.example/_edge/tenant_info` in a browser, copy the cloud id and run
`conflu config set CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID`. The gateway address goes with
an API token with scopes, which needs `read:space:confluence` and `read:page:confluence` to read, more to write; a token
without scopes works on the site address (`SITE.atlassian.net`).

## `setup --discover` says the address may not be a Confluence Cloud site

The host answered with something other than the cloud id: HTML, an error, a redirect (it is not followed) or an answer of
more than 64 KiB. Open `CONFLUENCE_BASE_URL` in a browser, correct it, and run the command again.

## The message of an error says `[email]`, `[personal link]` or `[account id]`

That is on purpose: where Confluence named a person in its refusal, the words of the server are redacted as page texts are. To see who it was, open the page
or the space in the browser. What no pattern can find is a name written out in a sentence (`Alex Example has no permission`): it stays in the words of the
server, as it does in the text of a page. Where that matters, treat the message as page text.

## "The answer was still coming in when the time allowed for it was up"

`CONFLUENCE_MAX_TIME` (120 seconds) is the time for a whole answer, counted from the end of the request; it also bounds a whole download. A big download
over a slow link needs more: `conflu config set CONFLUENCE_MAX_TIME 600`.

## "Confluence sent an answer that could not be read" (exit code 7)

Also: "Confluence answered with ... that is not a number", or "redirected the download to an address that cannot be used". Something between you and Confluence
(a proxy, a captive portal, a damaged answer) changed what Confluence said, and the CLI refuses to guess. Try again; if it stays, ask the person who runs the
network. Your address is not the problem.

"Confluence answered HTTP 200 with something that is not JSON (text/html)" (or "with an empty body") is the same thing: the answer is not from Confluence. A proxy, a
captive portal or a login page (a VPN that is not connected, a network that asks you to sign in) answered in its place. Check the VPN and `CONFLUENCE_BASE_URL`;
`conflu doctor` shows the `connection` check as failed.

"Confluence answered HTTP 200 with a number that is too long to be read (more than 4,300 digits)": somebody stored a content property that holds an integer of more than
4,300 digits, and the list that holds it cannot be read by this program (Python will not turn such a number into an integer). Look at the property in Confluence or take
it out there; `conflu api GET` of the property does not help, it is the same answer.

## A search finds nothing, or the wrong pages

`conflu search` says how it searched (`terms`, `ignored`, `match`, `relaxed`, `notes`). The usual reasons: the words are in another language than the
pages (the search does not translate), a needed word was left out as filler (put it in quotes), or the word is only inside a macro, which the index does
not hold. [Find information](find-information.md#6-when-nothing-is-found) has the checklist. A search that finds only people prints `Nothing found.` and says
on standard error how many hits it left out: people are listed only with `--with-users` (see [find information](find-information.md)).

## A file or a pipe is refused as too large (exit code 2)

`<source> holds more than 1,048,576 bytes: a query may hold at most ...` (or `16,777,216` for a body, a comment or standard input). The file
is not the text you meant (a log, a picture, a device such as `/dev/zero`): point to the right file, or cut the text into parts. The CLI reads one byte more
than the limit and stops; it never trusts the size that a file claims.

## `conflu api` refuses the path (exit code 2)

The message says that the path must not contain `..` (written in any way, `%2e%2e` and `.%2e` too) or an encoded separator. The path of a `conflu api` call holds a dot segment or an
encoded `/` or `\`; such a path is never sent. Write the path without it, and give query parameters with `--param KEY=VALUE`.

## An explicit proxy does not work

That is expected. The CLI does not implement `HTTP_PROXY` or `HTTPS_PROXY`. Transparent inspection can work with
a trusted CA; an explicit proxy cannot.

## PowerShell 5.1 breaks quotes, queries and JSON on the command line

Windows PowerShell 5.1 removes double quotes inside an argument. Symptoms:

- `conflu api ... --data '{"a": 1}'` becomes invalid JSON
- a bare `@file.json` is parsed by PowerShell before the CLI sees it
- `conflu search "\"SSO group\" roles"` or a CQL such as `title ~ "a b"` arrives broken, and the error is
  `unrecognized arguments`

Use a file instead:

```powershell
conflu api PUT api/v2/pages/123456/title --data-file payload.json --write --dry-run
```

For a search text or a CQL query, in the order to try:

1. `--phrase 'SSO group'` (repeat it) gives an exact phrase without a double quote to type.
2. Put the text in a file and pass it in **single quotes**, `conflu search '@question.txt'` or
   `conflu search --cql '@query.txt'` (a bare `@name` is splatting in PowerShell). A pipe works too, `Get-Content query.txt | conflu search --cql -`, but **for ASCII
   text only**: Windows PowerShell 5.1 encodes what it pipes into a program with `$OutputEncoding` (US-ASCII), so every other character (`ü`, `é`, `€`) arrives as `?`.
   The CLI reads a file itself, as UTF-8, UTF-16 or Windows-1252, so `@FILE` is the safe form for any text.
3. Write each double quote as `\"` inside single quotes.

The error of a usage error says so. A `&` in a path is another trap: `cmd.exe` and PowerShell treat it specially, so
use `--param KEY=VALUE` (repeatable, URL-encoded) instead of `'rest/api/search?cql=...&limit=5'`.

Files that PowerShell 5.1 writes are read as they are: `>` and `Out-File` write UTF-16 with a byte order mark,
`Set-Content` writes Windows-1252, and the settings file saved by Notepad may be UTF-16. No `-Encoding utf8` is needed for a text that you wrote (what a program prints
is another matter: see [Saving output with `>`](#saving-output-with--in-windows-powershell-51)).
A file with NUL characters (a picture) is refused with "is not text". Three more messages and what they mean:
`The search text is empty: query.txt holds no text`, `The body is empty: notes.md holds no text` (an editor that saved
nothing would otherwise clear a page; `--body ''` clears it on purpose) and `A value that starts with @ is read from the
file of that name` (for `--cql` and for `users`: put a space in front of a text that really starts with `@`, or use `--phrase` for a search). A search text
that starts with `@` is searched for as text when no file of that name exists, with a warning "no file of that name was found": if you meant a file, check its name and
the working folder.

The same advice applies to longer page bodies: `--file notes.md` is easier than an inline argument.

## Saving output with `>` in Windows PowerShell 5.1

`conflu page 123456 --format storage --with-users --body-only > page.xml` damages every character that is not ASCII when it runs in Windows PowerShell 5.1: `Grüße` is saved as
`Gr├╝├ƒe`. The program prints UTF-8, PowerShell decodes what a program prints with the code page of the console, and `>` stores the result as UTF-16. The CLI reads such a file
without complaint (it reads UTF-16), so nothing warns, and `conflu update 123456 --file page.xml --format storage` then writes the damage back into the page. Nothing in the CLI can
undo it, and in Constrained Language Mode there is no way round it in PowerShell.

Let the program write the file:

```powershell
conflu page 123456 --format storage --with-users --body-only --out page.xml
conflu blogpost 123456 --format storage --body-only --out post.xml
conflu template 123456 --format storage --body-only --out body.xml
conflu convert notes.md --out page.xml
```

`--out FILE` writes exactly the text that the command would have printed, as UTF-8 without a byte-order mark and with plain line ends, so it does not depend on the shell, and prints one line:
`Wrote N bytes to page.xml` (`{"file": ..., "bytes": ...}` with `--json`). Folders that are missing are made. A file that exists is not replaced unless you add `--force`, and never the settings
file of the CLI, a file in its folder, or a file that holds the token. People stay out of the file as they stay out of the screen (`--with-users` shows them). `page`, `blogpost` and `template`
take `--out` only with `--body-only`, which is the part of their output that is a file's content; it writes a file on this computer and changes nothing in Confluence.
Other commands that make files write them themselves (`conflu export --out`, `conflu download --out`).

## `update` is refused because Markdown would lose content

`conflu page 123456 --json` names what Markdown cannot express under `body.dropped`. If the page has entries
there, a Markdown replacement is blocked unless you force it.

Safer choices:

- `conflu update 123456 --file notes.md --append`
- `conflu update 123456 --file notes.md --prepend`
- `conflu page 123456 --format storage --with-users` and then `conflu update 123456 --format storage ...`

Use `--force` only when you accept the loss.

## Storage format read earlier is refused on write-back

If the storage format was read without `--with-users`, mention account ids were blanked as `ri:account-id="hidden"`.
That protects mentions from being broken by accident, and `conflu update`, `conflu create` and `conflu comment`
refuse such a body.

Read the page again with `--with-users` before you edit and write it back.

## Exit code 3: somebody changed the page

Exit code 3 means a conflict:

- your `--if-version N` or `--if-unchanged-since` guard failed, or
- Confluence itself refused a stale update with HTTP 409, or
- `conflu create` found a page with the same title in the space

Read the page again (`conflu page ... --json` or `conflu pages --space ... --title ...`) and decide what to do.
Do not retry blindly. For a comment read it again with `conflu comment PAGE --get ID`; a `conflu restore` is guarded by a check just before the
write, because the API has no atomic guard for it.

## `comment --edit` or `--resolve` is refused

Confluence lets only the author change the text of a comment (exit code 5, HTTP 403): answer with `conflu comment PAGE --text ... --reply-to ID`
instead. A comment that holds a mention or a macro is not replaced from Markdown without `--force` (write storage format), and a text that holds
`[email]` or `[personal link]` is refused: leave the placeholder out. `--resolve` and `--reopen` are for inline comments only.

## Download problems

- `download` does not overwrite files unless you add `--force`.
- Credentials go only to Confluence, never to the media host that serves the file.
- Downloads are kept in memory, with a hard limit of 512 MiB. Any other answer of Confluence is refused above
  64 MiB once it is decoded; ask for less (a narrower search, a smaller `--limit`).
- Two attachments that would end up as the same file are refused before anything is downloaded: names that differ
  only in upper and lower case, or that become equal once characters Windows refuses are replaced by `_`. Fetch them
  one at a time with `--name`, each into its own `--out` folder.
- Control, zero-width and right-to-left override characters in an attachment name are replaced by `_`, so a file
  shows the name it really has.
- A partial file is not written: the CLI checks the size it expected.
- A name longer than a file system takes is cut at 200 bytes, and `download` refuses an `--out` that is the folder of the configuration, also with
  `--force` or `--dry-run`. `conflu download ID --text` reads a text, Word, Excel or PowerPoint file without saving it; other types get a hint.
- `conflu attach` refuses the configuration file and any file that holds the API token (exit code 2, nothing sent, also in a dry run).

## Import or export surprises

- `conflu import-md-dir` reads only `*.md` files in one folder, not subfolders.
- `conflu export` refuses to overwrite existing files unless you add `--force`.
- Markdown exports carry `lossy` markers when the page contains constructs that Markdown cannot show.
- An unchanged exported file re-imports as `unchanged`, which is the intended no-op.

## Read the installed guides offline

These guides ship with the CLI, so even on a disconnected laptop you still have:

```bash
conflu how-to
conflu how-to configure
conflu how-to publish-markdown
```
