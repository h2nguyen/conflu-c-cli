# Changelog

All notable changes to conflu-c-cli are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html): `MAJOR.MINOR.PATCH`.

## [Unreleased]

### Added

### Changed

### Fixed

### Security

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
