# Markdown and storage format

Confluence keeps the body of a page in **storage format**: XHTML with extra elements for macros, links to pages and
people, images and the like. People write Markdown. `conflu` converts between the two with a small, conservative
converter that has no dependencies. This guide says what it turns into what, what Markdown cannot say, and why
`update` and `import-md` refuse to replace a page body in some cases.

Three commands show the formats:

```bash
conflu page 123456                      # the body as Markdown (the default)
conflu page 123456 --format storage     # the body as Confluence keeps it
conflu convert notes.md                 # the storage format that create, update and comment would send
conflu convert page.xml --source storage   # the Markdown that `page` would show
```

## Reading: from storage to Markdown

| In the page | In the Markdown |
| --- | --- |
| Headings, paragraphs, line breaks | `#` to `######`, paragraphs, a backslash at the end of the line |
| Bold, italic, strike-through, code | `**bold**`, `*italic*`, `~~strike~~`, `` `code` `` |
| Links | `[text](address)`; `<address>` when the text is the address itself; an address with spaces is written `[text](<address>)` |
| Images (by address or attached file) | `![alt](address)` and `![alt](file.png)` |
| Bulleted, numbered and nested lists | `-` and `1.`, nested by four spaces |
| Task lists | `- [ ]` and `- [x]` |
| Block quotes, horizontal rules | `>` and `---` |
| Tables | a pipe table; the cells keep bold, links, code and images |
| Code macro | a fenced code block with the language; the fence is longer than any run of backticks in the code |
| Preformatted (`noformat`) macro | a plain fenced code block; the macro type is not kept (`macro:noformat`) |
| Info, note, tip and warning macros | a GitHub alert: `> [!NOTE]`, `> [!IMPORTANT]`, `> [!TIP]`, `> [!WARNING]` |
| Panel and quote macros | a block quote |
| A link to another page | `[text](page:SPACE/Title)` (or `page:Title` in the same space) |
| A link to an attachment | `[text](attachment:file.pdf)` |
| A mention of a person | `@user` (the account id only with `--with-users`) |
| A status lozenge | `[DONE]` |

`--format text` gives plain text without any Markdown syntax.

Characters that Markdown would read as syntax, when they are plain text in the page (a `*`, a `#` or `1.` at the start
of a line, backticks, brackets, pipes, an `&nbsp;` typed as text), are written with a backslash, so that they come
back as the same characters when the Markdown is imported again.

## What Markdown cannot say

Whatever the Markdown cannot carry is named, in the text output on stderr and in the JSON as `body.dropped`. The
same list is written as `lossy` into the front matter and the index of an `export`. An empty list means that
converting the Markdown back gives an equivalent page, apart from white space that is only layout: runs of spaces and
non-breaking spaces become one space, and empty paragraphs used as spacers disappear. Code and preformatted text keep
every space.

| Name | What is lost |
| --- | --- |
| `macro:NAME` | A macro without a Markdown equivalent (`toc`, `jira`, `expand`, `children`, `status` ...). Its text, when it has some, stays. Also a code, info, note, tip, warning, panel or quote macro with parameters that Markdown cannot hold (a title, an icon, line numbers, colours), and a code macro whose code starts or ends with blank lines. A `noformat` macro becomes a plain fenced block, which is a different macro when it is imported again. |
| `layout` | Sections and columns. The text of every cell stays, one after the other. |
| `inline-comment` | The marker of a comment that was made on a piece of text. The text stays. |
| `link:page`, `link:attachment`, `link:anchor` | The target of the link is written as `page:...`, `attachment:...` or `#...`, which Markdown does not turn back into the link. |
| `mention` | The person behind an `@user`; a link to a person's profile is shown the same way. |
| `emoticon`, `time` | Emoticons become their character or `:name:`, dates become their text. |
| `adf-extension` | Newer editor elements (decisions, some panels); only their fallback text stays. |
| `table:merged-cells` | Cells that span rows or columns. |
| `table:rich-cells` | A table cell that holds more than a line of text (a list, a macro, a nested table); its parts are joined with line breaks. |
| `table:row-headers` | A header cell below the first row. |
| `formatting:underline`, `formatting:color`, `formatting:subscript`, `formatting:superscript`, `formatting:align`, `formatting:image`, `formatting:list` | Underline, colours and backgrounds, sub- and superscript, text alignment, image size or alignment, and other list styles (letters, roman numbers). The text stays. |
| `html:TAG`, `tag:NAME` | An element that the converter does not know; its text stays. |
| `redacted-text` | E-mail addresses and personal profile links, which are hidden from the text as `[email]` and `[personal link]` unless you add `--with-users`. |

## Writing: from Markdown to storage

| In the Markdown | In the page |
| --- | --- |
| `#` headings and underlined headings | Headings |
| Paragraphs, a backslash or two spaces at the end of a line | Paragraphs and line breaks |
| `**bold**`, `*italic*`, `~~strike~~`, `` `code` `` | Strong, emphasis, a struck-through span, code |
| Bulleted and numbered lists, nested by two to four spaces or a tab | Lists; a number other than 1 at the start is kept |
| A list in which every item starts with `[ ]` or `[x]` and is a line of text (a continuation line joins it) | A task list. With other items mixed in, or a nested list, several paragraphs or code inside a task item, it stays an ordinary list and the brackets stay as text: nothing is dropped |
| Fenced and indented code | The code macro; the language of the fence is passed on (`js`, `bash`, `cpp`, `c#`, `powershell`, `python`, `yaml`, `text` and so on, with the usual aliases such as `typescript`, `sh`, `shell`, `csharp`, `ps1`, `yml`) |
| `> [!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]` | The info, tip, note and warning macros |
| Other block quotes and `---` | A quote and a horizontal rule |
| Pipe tables with a header row and optional alignment | A table; alignment becomes `text-align` |
| Links, `<address>` links, `[text](<address with spaces>)` and bare web addresses (`http://`, `https://`, `www.`) | Links, with the GitHub rules for a bare address: trailing punctuation is not part of it, parentheses are when they are balanced. Only web (`http`, `https`, `ftp`, `ftps`), mail and phone addresses, pages of the site and anchors become links: a link or an image to a script or a data address (`javascript:` in any spelling, `data:`, `file:` ...) loses the link and keeps its text. No link is made inside the text of another link |
| Character references such as `&copy;` and `&nbsp;`, and a backslash before punctuation (`\*`) | The character (a non-breaking space is U+00A0) and the punctuation as plain text. `&amp;`, `&lt;`, `&gt;`, `&quot;` and valid numeric references stay; anything else (`&foo;`, `&#0;`) is shown as typed. The XML written is always well formed |
| `![alt](https://host/x.png)` | An image from that address |
| `![alt](diagram.png)` | The image that is attached to the page under that name: `conflu attach` it |
| Raw HTML | Shown as text: it is escaped, so nothing in a Markdown file can inject markup or macros. Only `<br>` is kept |

A final newline, Windows line ends, a leading byte order mark and characters that XML forbids (which are removed) make no
difference to the result. Only a line feed, a carriage return or both end a line: a U+2028 or a vertical tab stays in
the text. A blank line
between the items of a list does not turn their text into paragraphs. Footnotes, definition lists and the like
are not supported and stay as text.

## Replacing, appending, and the guard

Writing a Markdown body over a page that holds more than Markdown can say would silently destroy the rest: the
macros, the mentions, the layout, the targets of links. So:

- `update --append` and `update --prepend` add text and keep the rest as it is. The guard does not apply to them.
- `update` and `import-md` that **replace** the body with Markdown are refused (exit code 1) when the existing
  body has anything in the list above, `redacted-text` included. The message names it; `--force` replaces the
  body anyway, and the result says what was lost.
- A Markdown that is exactly what the page already shows as Markdown changes nothing (`unchanged`, no new
  version). That is why an unedited `export` can be imported again, also for pages with macros: only a page you
  edited is checked.
- `--format storage` replaces the body with the storage format you give, as it is. Take it from `conflu page
  PAGE --format storage --with-users`: without `--with-users` the account ids of mentions are blanked, and a
  storage format with blanked mentions is refused, because it would break them.
- `--dry-run` shows exactly what would be sent, and `conflu convert` shows what the converter makes of a file.

## Recipes

Change the wording of a page that has macros and mentions, without losing any of them:

```bash
conflu page 123456 --no-body --json                                        # note version.number, here 7
conflu page 123456 --format storage --with-users --body-only > page.xml    # only the source, into a file
# edit the text in page.xml, keep the elements around it
conflu update 123456 --file page.xml --format storage --if-version 7 --dry-run
conflu update 123456 --file page.xml --format storage --if-version 7 --message "Fixed the wording"
```

Add a section to the end of a page:

```bash
conflu update 123456 --file section.md --append --message "Added the October section"
```

Find out what stands in the way of editing a page as Markdown:

```bash
conflu page 123456 --json      # read body.dropped
```

## Limits

The converter handles the CommonMark constructs in the tables above, plus pipe tables, task lists, strike-through
and GitHub alerts. It does not try to be a full Markdown implementation: unusual nesting and emphasis edge cases
can come out differently from what another renderer would make. It cannot create macros other than code, info,
tip, note and warning, nor mentions or page links: for those use the storage format. The Markdown it writes is
meant to be read and edited by people; `page`, `export` and `convert` show it, and `--dry-run` shows what would
be sent.

Content that is nested more than 100 levels deep (quotes inside lists inside quotes ...) is refused with a clear
error instead of being converted. Hostile input is bounded: a megabyte of Markdown made only of brackets, emphasis marks,
backticks or half-open tags is converted in a few seconds.

See also [publish Markdown pages](publish-markdown.md), [export and sync](export-and-sync.md), the
[JSON output reference](../reference/json-output.md) and [use the CLI with AI agents](use-with-ai-agents.md).
