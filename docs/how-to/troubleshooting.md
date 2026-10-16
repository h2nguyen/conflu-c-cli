# Troubleshooting

When something is wrong, start with the one command that checks the whole setup:

```bash
conflu doctor
conflu doctor --json
```

It checks the runtime, config file, base URL, e-mail address, token, TLS, the connection, whether spaces can be
read, the current space and the privacy policy.

## `conflu` is not found

On Windows the installer writes `conflu` and `conflu.cmd` to `~/bin`, which Git Bash usually searches and
PowerShell usually does not. Three fixes are in [install and update](install-and-update.md#use-it-from-powershell-and-cmd);
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
# the cloud id of the site, public, no login: open this in a browser
#   https://wiki.company.example/_edge/tenant_info
conflu config set CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID
conflu doctor
```

An API token with scopes needs `read:space:confluence` and `read:page:confluence` to read, more to write.

## A search finds nothing, or the wrong pages

`conflu search` says how it searched (`terms`, `ignored`, `match`, `relaxed`, `notes`). The usual reasons: the words are in another language than the
pages (the search does not translate), a needed word was left out as filler (put it in quotes), or the word is only inside a macro, which the index does
not hold. [Find information](find-information.md#6-when-nothing-is-found) has the checklist.

## An explicit proxy does not work

That is expected. The CLI does not implement `HTTP_PROXY` or `HTTPS_PROXY`. Transparent inspection can work with
a trusted CA; an explicit proxy cannot.

## PowerShell 5.1 breaks JSON on the command line

Windows PowerShell 5.1 removes double quotes inside an argument. Symptoms:

- `conflu api ... --data '{"a": 1}'` becomes invalid JSON
- a bare `@file.json` is parsed by PowerShell before the CLI sees it

Use a file instead:

```powershell
conflu api PUT api/v2/pages/123456/title --data-file payload.json --write --dry-run
```

The same advice applies to longer page bodies: `--file notes.md` is easier than an inline argument.

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
Do not retry blindly.

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
