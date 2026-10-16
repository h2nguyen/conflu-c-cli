# Security policy

conflu-c-cli handles an API token, reads pages that other people wrote, and writes files and pages on your behalf.
Please report a security problem privately, so that users can be protected before the details are public.

## Supported versions

| Version | Security fixes |
| --- | --- |
| The latest 1.x release | Yes |
| Anything older | No: update to the latest release |

## Report a vulnerability

Use GitHub's private vulnerability reporting: open the
[Security tab of the repository](https://github.com/h2nguyen/conflu-c-cli/security) and choose **Report a
vulnerability**. Please do not open a public issue, pull request or discussion for it.

If that button is not available, open an issue titled "Security contact request" without any details. A
maintainer will then arrange a private channel.

A good report has: the version (`conflu version`), the operating system and Python version, the steps to
reproduce, and what an attacker gains. **Leave out real tokens, the name of your site and the text of your
pages**; use placeholders. If you found a token that leaked, revoke it first at
<https://id.atlassian.com/manage-profile/security/api-tokens>.

The project is maintained in spare time, so there is no service level. The maintainers aim to acknowledge a
report within 7 days and will keep you informed while they work on it.

## What counts as a vulnerability

conflu-c-cli runs on your computer and talks to the Confluence Cloud site you configure. It trusts your operating
system account, its configuration file and the certificate chain of the site. It does not trust what comes from
the network or from people: page text, titles, comments, file names and the answers of a server.

In scope, for example:

- **Credentials.** The API token or the account e-mail address is printed, logged, accepted as a command line
  argument, kept in an error message, or sent to any address other than the configured one (for instance the
  media host of a download, or a host named in a `conflu api` path).
- **Personal data.** People (names, account ids, e-mail addresses, personal links) appear although `--with-users`
  was not given or `CONFLUENCE_HIDE_USERS=true` is set.
- **The terminal.** Text from a page, a title or an error that carries control, escape or C1 characters through to
  the terminal.
- **Files.** `conflu download` or `conflu export` writes outside the folder that was named, overwrites without
  `--force`, or produces unsafe file names (path separators, device names, invisible characters).
- **Markdown and storage format.** A script link (`javascript:`, `data:` and similar) or injected markup or macro
  that survives a conversion.
- **TLS.** Certificate verification is skipped, or a plain `http://` address is accepted, without the setting that
  allows it.
- **Limits.** Input that gets past the documented bounds (an answer of 64 MiB once decoded, a file of 512 MiB,
  deeply nested content, hostile Markdown or search words) and uses up memory or time.
- **The installer.** `install.py` replaces or removes something it did not create.

Out of scope:

- Vulnerabilities in Confluence, in other Atlassian services or in Python itself. Report them to the vendor.
- Someone who already controls your user account, your files or your environment. The token is kept in a
  configuration file that file permissions protect; it is not encrypted.
- Behaviour that the documentation describes as a choice: `CONFLUENCE_INSECURE=true`,
  `CONFLUENCE_ALLOW_HTTP=true`, `--with-users`, `--force`, and the strict X.509 checks, which are off by default
  (the certificate chain and the host name are always verified).
- Instructions in a page that an AI agent decides to follow. The
  [guide for agents](docs/how-to/use-with-ai-agents.md) tells them to treat Confluence text as data, but what an
  agent does is outside the control of this program.

## What happens after your report

1. **Triage.** A maintainer reproduces the problem and answers in the private advisory.
2. **Severity.** It is judged by what an attacker gains. Exposing a credential or personal data, and changes to
   Confluence that nobody asked for, weigh the most.
3. **Fix.** The fix is prepared in private with a test that fails without it, and ships as a patch release. The
   changelog describes it under `Security`.
4. **Disclosure.** The advisory is published together with the release, and you are credited if you wish.
5. **If it was already exploited,** the advisory says so and tells users what to do, such as revoking their API tokens.
