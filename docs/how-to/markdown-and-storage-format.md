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
conflu convert page.xml --source storage   # the Markdown of a source, without the redaction of `page`
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
| A link to a blog post, a space, a shortcut or other content | only the text of the link (`link:blogpost` ...: see the table below) |
| A mention of a person | `@user` (the account id only with `--with-users`) |
| A status lozenge | `[DONE]` |

`--format text` gives plain text without any Markdown syntax.

Characters that Markdown would read as syntax, when they are plain text in the page (a `*`, a `#` or `1.` at the start
of a line, backticks, brackets, pipes, an `&nbsp;` typed as text), are written with a backslash, so that they come
back as the same characters when the Markdown is imported again.

## What Markdown cannot say

Whatever the Markdown cannot carry is named, in the text output on stderr and in the JSON as `body.dropped`. The
same list is written as `lossy` into the front matter and the index of an `export`. The one exception is formatting
that is only how the page looks, which is described after the table (*Formatting that is not named*). An empty list
means that converting the Markdown back gives an equivalent page, apart from that formatting and from white space that
is only layout: runs of spaces and non-breaking spaces become one space, and empty paragraphs used as spacers
disappear. Code and preformatted text keep every space.

| Name | What is lost |
| --- | --- |
| `macro:NAME` | A macro without a Markdown equivalent (`toc`, `jira`, `expand`, `children`, `status` ...). Its text, when it has some, stays. Also a code, info, note, tip, warning, panel or quote macro with parameters that Markdown cannot hold (a title, an icon, line numbers, colours), and a code macro whose code starts or ends with blank lines. A `noformat` macro becomes a plain fenced block, which is a different macro when it is imported again. |
| `layout` | Sections and columns. The text of every cell stays, one after the other. |
| `inline-comment` | The marker of a comment that was made on a piece of text. The text stays. |
| `link:page`, `link:attachment`, `link:anchor` | The target of the link is written as `page:...`, `attachment:...` or `#...`, which Markdown does not turn back into the link. `link:anchor` is also named when a link to a page, an attachment or an address goes to an anchor in it: the anchor is not written. The key of a personal space (the account id of its owner) is `[hidden]` in a `page:` target, and in `ri:space-key` of `--format storage`, unless you add `--with-users`; storage format that was read that way is refused when it is written back. |
| `link:blogpost`, `link:space`, `link:shortcut`, `link:content`, `link:NAME` | A link to a blog post, to a space, to a shortcut (a Jira issue key, say), to content by its id (`ri:content-entity`), or to any other kind of target (`NAME` is what the element is called). Markdown has no address for them, so only the text of the link stays, nothing when the link had none, and the link is gone when the Markdown is imported. |
| `anchor` | A named anchor (`<a name="top">`, or with an `id`) that links of the page or of other pages jump to. The text around it stays, the place does not. An anchor made with the anchor macro is `macro:anchor`. |
| `placeholder` | The grey hint of a template (`<ac:placeholder>`): text that a reader sees until it is replaced. It is left out. |
| `mention` | The person behind an `@user`; a link to a person's profile is shown the same way. |
| `emoticon`, `time` | Emoticons become their character or `:name:`, dates become their text. |
| `adf-extension` | Newer editor elements (decisions, some panels); only their fallback text stays. |
| `table:merged-cells` | Cells that span rows or columns. |
| `table:rich-cells` | A table cell that holds more than a line of text (a list, a macro, a nested table); its parts are joined with line breaks. |
| `table:row-headers` | A header cell below the first row. |
| `formatting:underline`, `formatting:color`, `formatting:subscript`, `formatting:superscript`, `formatting:align`, `formatting:image`, `formatting:list` | Underline, colours and backgrounds, sub- and superscript, text alignment, image size or alignment, and other list styles (letters, roman numbers). The text stays. |
| `formatting:inline-code` | A link, bold text or other markup inside a piece of inline code. Markdown has code that holds text only, so the text stays, as code. |
| `html:TAG`, `tag:NAME` | An element that the converter does not know; its text stays. A table caption is one of them (`html:caption`): it becomes the paragraph above the table. |
| `redacted-text` | E-mail addresses and personal profile links, which are hidden from the text as `[email]` and `[personal link]` unless you add `--with-users`. |

**Formatting that is not named.** The indentation of a paragraph, the width and the layout of a table and of its columns, the classes and other style attributes of an element (the background of a paragraph, the size of a font), how a link looks and whether it opens in a new window, comments in the source (`<!-- -->`), and the numbers and ids that Confluence keeps for tasks, macros and tables have no name above. The text, the links and the structure of the page are the same without them, so a Markdown that replaces the page is not refused because of them, and they are lost when it does: indentation and widths come back as the defaults, and the tasks are numbered again from 1.

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
macros, the mentions, the layout, the targets of links (to a blog post or a space as much as to a page), the anchors.
So:

- `update --append` and `update --prepend` add text and keep the rest as it is. The guard does not apply to them.
- `update` and `import-md` that **replace** the body with Markdown are refused (exit code 1) when the existing
  body has anything in the list above, `redacted-text` included; formatting that is not named does not stop them.
  The message names it; `--force` replaces the body anyway, and the result says what was lost.
- A Markdown that is exactly what the page already shows as Markdown changes nothing (`unchanged`, no new
  version). That is why an unedited `export` can be imported again, also for pages with macros: only a page you
  edited is checked.
- `--format storage` replaces the body with the storage format you give, as it is. Take it from `conflu page
  PAGE --format storage --with-users`: without `--with-users` the account ids of mentions are blanked, and a
  storage format with blanked mentions is refused, because it would break them.
- `--dry-run` shows what would be sent (the people that the body mentions are left out of the preview unless you add `--with-users`; the request
  that is sent has them), and `conflu convert` shows what the converter makes of a file.
- The same guard protects a comment (`conflu comment PAGE --edit ID`), a blog post (`conflu blogpost-update`) and the other writers that replace a
  body: a comment that holds a mention or a macro is not replaced from Markdown without `--force`, so write storage format; and a restore
  (`conflu restore`) never goes through Markdown at all, Confluence brings the old version back as it was.

## Recipes

Change the wording of a page that has macros and mentions, without losing any of them:

```bash
conflu page 123456 --no-body --json                                                  # note version.number, here 7
conflu page 123456 --format storage --with-users --body-only --out page.xml          # only the source, into a file that the program writes as UTF-8
# edit the text in page.xml, keep the elements around it
conflu update 123456 --file page.xml --format storage --if-version 7 --dry-run
conflu update 123456 --file page.xml --format storage --if-version 7 --message "Fixed the wording"
```

Save the source with `--out`, not with `>`: Windows PowerShell 5.1 re-encodes what `>` writes (`Grüße` would come out as `Gr├╝├ƒe`), and `update` would then write that damage
back into the page. `--out` writes the file itself, as UTF-8 without a byte-order mark, and never replaces a file that is there unless you add `--force`
(see [troubleshooting](troubleshooting.md#saving-output-with--in-windows-powershell-51)). `conflu convert notes.md --out page.xml` does the same for a conversion.

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
