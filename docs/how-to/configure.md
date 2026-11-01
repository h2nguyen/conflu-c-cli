# Configure the connection

Four commands set it up. Run `conflu doctor` at the end; it checks every step and says how to fix what fails.

```bash
conflu config set CONFLUENCE_BASE_URL https://example.atlassian.net/wiki
conflu config set CONFLUENCE_EMAIL user@example.com
conflu setup-token
conflu use ENG
conflu doctor
```

## The token

Create an API token in the Atlassian account that owns the Confluence access
(<https://id.atlassian.com/manage-profile/security/api-tokens>) and run `conflu setup-token`. The input is not
shown. The token goes into the configuration file with restricted permissions and is never printed, logged or
accepted as a command line argument, so it does not end up in the shell history.

- **Scripts and agents:** `printf '%s' "$TOKEN" | conflu setup-token --stdin`.
- **Git Bash without a real terminal:** `conflu setup-token` warns that the input may be visible when it cannot
  hide it. Use `winpty conflu setup-token`, or pipe the token in with `--stdin`.
- **Remove it:** `conflu remove-token`. Rotate the token in Atlassian if it was ever exposed.

Authentication is HTTP Basic with the Atlassian account e-mail (`CONFLUENCE_EMAIL`) and the API token
(`CONFLUENCE_API_TOKEN`). `conflu config set` refuses the secret on purpose; only `conflu setup-token` saves it.

## Where the settings live

Settings come from, in this order: **environment variables**, the **configuration file**, the **defaults**.
A variable that is set but empty counts as not set. `conflu config show` lists every setting with its value and
its source; secrets are masked and the e-mail address is shortened. `conflu config path` prints the file.
Because the environment wins, `conflu config set`, `conflu use` and the other commands that change the file warn
when the variable they change is also set in your environment.

The file is `~/.config/conflu-c-cli/config`. It holds `KEY=value` lines and is parsed as data, never executed.
Shell quoting works (`'a b'`, `"a b"`, `a\ b`), but shell expansion is refused instead of being guessed:
`$(...)`, backticks, `$VAR` and a leading `~` must be written as plain values, or kept in the environment.

Which file is used, in this order:

1. `CONFLUENCE_CONFIG_FILE`, when set.
2. `XDG_CONFIG_HOME/conflu-c-cli/config`, when that file exists.
3. `.config/conflu-c-cli/config` in the first home folder that has one. The home folders, in this order:
   `HOME` when it is set (Git Bash sets it); otherwise the Windows home drive and path (`HOMEDRIVE` plus
   `HOMEPATH`, when that folder exists); then always the Windows profile.
4. Otherwise a new file is created in `XDG_CONFIG_HOME` when that is set, else in the first home folder.

PowerShell and cmd do not set `HOME`, but they still find the same configuration that Git Bash uses on a laptop
with a home drive. `conflu config path` prints the file in use, and `conflu doctor` checks it.

The settings you will meet first:

| Setting | Use |
| --- | --- |
| `CONFLUENCE_BASE_URL` | Address of the Confluence Cloud site. Required. Use `https://example.atlassian.net/wiki`. |
| `CONFLUENCE_EMAIL` | E-mail address of the Atlassian account that owns the token. Required. |
| `CONFLUENCE_API_TOKEN` | The token. Save it with `conflu setup-token`. Required. |
| `CONFLUENCE_SPACE` | The current space. Set it with `conflu use KEY`, forget it with `conflu clear-space`. |
| `CONFLUENCE_HIDE_USERS` | `true` forbids printing people. See below. |
| `CONFLUENCE_CA_BUNDLE` | A PEM file with certificate authorities to trust **in addition to** the system store: a private company CA, or a public one your system lacks. |
| `CONFLUENCE_TLS_STRICT` | `true` turns on Python's strict X.509 checks. See below. |
| `CONFLUENCE_INSECURE` | `true` switches certificate checks off. Diagnostic only. |
| `CONFLUENCE_ALLOW_HTTP` | `true` accepts a plain `http://` base URL outside localhost. |
| `CONFLUENCE_OUTPUT` | `json` makes every command that supports it print JSON. |
| `CONFLUENCE_JSON_ENVELOPE` | `1`, `true`, `yes` or `on` in the **environment** (not a setting of the file: `conflu config set` does not know it) wraps every result and every error into one JSON object on standard output, like `--json-envelope`. |
| `CONFLUENCE_PROFILE` | `agent` for AI agents: people hidden, JSON by default, informational messages off standard error. See [the agent profile](#the-agent-profile). |
| `CONFLUENCE_CONNECT_TIMEOUT`, `CONFLUENCE_MAX_TIME`, `CONFLUENCE_RETRY` | Connection timeout, overall timeout and read retries. |

All settings are in the [configuration reference](../reference/configuration.md).

## When the configuration file cannot be read

A value with a line break, or any other control character, is refused by `conflu config set` (exit code 1): the file holds one line per setting. If a line of
the file cannot be read (it was edited by hand, or an old version wrote it), every command that needs a setting stops with the number of the line and the
file, for example `CONFLUENCE_SPACE has unbalanced quotes in the config file (line 3 of ...)`, and asks nothing of Confluence: a file that cannot be read never
turns into a default that is more permissive (a privacy policy that cannot be read is not "off"). These work anyway: `conflu config path`,
`conflu config set NAME VALUE` (replaces the line), `conflu config unset NAME` (removes it), `conflu setup-token`, `conflu remove-token` and `conflu clear-space`,
and so do `conflu help`, `conflu how-to` and `conflu version`. A line that is no setting of this program is removed in an editor. `conflu doctor` shows the line as well.

## The site address

Use the Confluence Cloud site root, usually `https://SITE.atlassian.net/wiki`.

- If you set `https://SITE.atlassian.net`, the CLI adds `/wiki` automatically.
- If you use a scoped token with Atlassian's API gateway, use
  `https://api.atlassian.com/ex/confluence/CLOUD_ID`; the CLI adds `/wiki` there as well.
- The address must not contain credentials, a query or a fragment. If one holds a user name or a password anyway,
  `conflu config show` and `conflu doctor` print `https://********@host/wiki` (or nothing at all when an `@` follows the
  host name), never the secret.
- **A custom domain of your company does not work with an API token.** If your wiki is reached at an address of your own
  (`wiki.company.example`) instead of `SITE.atlassian.net`, Atlassian does not read API tokens on it: Confluence answers
  403 "caller cannot access Confluence" as it does an anonymous caller. Use the gateway address instead, and let the CLI
  find it. It asks the host of `CONFLUENCE_BASE_URL`, and no other, for its cloud id (`/_edge/tenant_info` at the root of
  that host: public, nothing is sent that identifies you, and a redirect is not followed) and proposes the address:

  ```bash
  conflu setup --discover             # asks before it saves; without a terminal it prints the `conflu config set` command
  conflu setup --discover --yes       # saves without asking
  conflu setup --discover --dry-run   # says what would be saved, saves nothing
  ```

  The gateway address goes with an API token **with scopes**; a token without scopes works on the site address
  (`SITE.atlassian.net`), so an atlassian.net address does not have to change. To set it yourself:

  ```bash
  conflu config set CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID
  ```

  `conflu doctor` warns about an address that is not an atlassian.net address and says this.

## HTTPS only

The e-mail address and the token travel in every request, so the CLI refuses a plain `http://` address:
anybody on the network path could read them. Addresses on this computer (`localhost`, `127.0.0.1`) are always
accepted, for tests. If Confluence really only offers http, on a network you trust, accept the risk
explicitly:

```bash
conflu config set CONFLUENCE_ALLOW_HTTP true
```

`conflu doctor` reports the state.

## TLS, company CAs and Python 3.13 strictness

By default the CLI trusts what the operating system trusts. On a managed Windows laptop a company CA is often
installed there already, so nothing else is needed. If `conflu doctor` reports a certificate error, point the
CLI at a PEM bundle:

```bash
conflu config set CONFLUENCE_CA_BUNDLE "C:/certs/company-ca.pem"
```

The file is trusted **in addition to** the system store, so one setting serves the office (where a proxy may re-sign
traffic with a company CA) and home (where it does not). The chain and the host name are checked as always.

A detail matters for Confluence Cloud behind some company proxies: **Python 3.13 enables strict X.509 checks
that reject many TLS-inspecting proxies with `CERTIFICATE_VERIFY_FAILED ... Missing Authority Key Identifier`.**
That is why `CONFLUENCE_TLS_STRICT` defaults to `false`. In that default mode the CLI still verifies the
certificate chain and the host name; it simply leaves those extra strict checks off. Turn the setting on only
when you want Python's stricter behaviour:

```bash
conflu config set CONFLUENCE_TLS_STRICT true
```

`CONFLUENCE_INSECURE=true` switches all certificate verification off. Use it only as a short diagnostic, never
as a standing setting.

## Proxy limitation

The CLI has **no explicit proxy support**: `HTTP_PROXY` and `HTTPS_PROXY` are not read. Transparent TLS
inspection can work when the right CA is trusted; an explicit proxy does not. Put that in front of an agent too,
so it does not keep retrying the impossible.

## Keep people out of the output

Every command hides people by default where it can: authors, owners, who saved a version, comment authors,
mention account ids, e-mail addresses and personal links in text. Commands that can show people do so only when
you ask with `--with-users`, and they are refused when the policy forbids it. To make "no people" a rule
instead of a habit:

```bash
conflu config set CONFLUENCE_HIDE_USERS true
```

Now no command prints people, `--with-users` is refused, `conflu ping` hides who the token belongs to, raw JSON
answers from `conflu api` are scrubbed, and storage format has mention account ids blanked when it is read.

A **personal space** is a person as well: Confluence names it after its owner and keys it by `~` and the owner's account id.
`conflu spaces`, `conflu space` and `conflu use` print it as `[hidden]` (the key) and `[personal space]` (the name), with no
description or address, so that `conflu spaces --all` lists that such spaces exist and not whose they are. A search with
`--search` looks at what is printed, so it cannot find a person's space by the person's name. The key that you give to
`conflu use` is saved as you typed it: the settings file is yours. `conflu current`, `conflu config show` and `conflu doctor` print the key of a personal space as `[hidden]` like every
other command, so the setting is the one place that holds it. `conflu spaces --with-users` and
`conflu space KEY --with-users` show the space as Confluence names it, and the policy above refuses them. Every other command that prints the key or the
address of a page in a personal space does the same (the key is `[hidden]`, the address ends at the page id): also where the space is only named, in the list
of `conflu pages`, `blogposts`, `labels --space`, `tasks --space` and `templates --space` (and the space of every template), in the query that `conflu search` repeats, and in a link in
the body of a page or a template (`page:[hidden]/Title`, and `ri:space-key` in storage format, which then is refused when it is written back). One limit stays: Confluence titles the home page
of a personal space with the name of its owner, and a title cannot be told from a name, so that title can still appear in a `path`, an ancestor list or a title. Free text of any
other kind (the value of a macro parameter, of a property, a label) is not searched for keys either: a key that somebody wrote into it stays as it is.

## The agent profile

For a program or an AI agent, one setting does the work of three:

```bash
conflu config set CONFLUENCE_PROFILE agent     # or CONFLUENCE_PROFILE=agent in the environment of the agent
```

`agent` makes `CONFLUENCE_HIDE_USERS=true` and `CONFLUENCE_OUTPUT=json` the defaults and keeps informational messages
(not warnings, not errors) off standard error. A setting of your own still wins, even `false`: with
`CONFLUENCE_HIDE_USERS=false` people can be shown again, which `conflu doctor` reports as a warning and
`conflu doctor --strict-privacy` as a failure. `conflu config show` lists the profile, and the settings that it sets
have the source `profile`. Errors are JSON as well when the settings ask for JSON, not only with `--json`.

## Timeouts and retries

`CONFLUENCE_CONNECT_TIMEOUT` (default 10 seconds) and `CONFLUENCE_MAX_TIME` (120 seconds) bound a request; both are
at most 86400 seconds. `CONFLUENCE_MAX_TIME` is the wait for the next bytes of an answer and, once the body has begun
to come in, the time for all of it. It does not bound a server that sends the status line and the headers a few bytes at
a time, each within that wait: such a request goes on until you stop it (Ctrl+C, exit code 130). Give an unattended
run the time limit of its scheduler or shell as well.
`CONFLUENCE_RETRY` (default 2) retries a **read** after a network error or HTTP 429, 502, 503 or 504. Writes are
never retried, because a repeated write could create a duplicate or a second version.
An answer is read only up to a size (64 MiB) and a number of objects (250,000 in all, 1,000 results in a list, where a
request returns 250 at most): more is no answer of Confluence, and the command ends with exit code 7.
