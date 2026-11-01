"""Confluence storage format as Markdown or text.

The parser is tolerant: storage fragments may be malformed, truncated, or use Confluence prefixes
without XML namespace declarations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .errors import ValidationError
from .privacy import HIDDEN, is_personal_space, is_profile_link, redact_text

_MAX_NESTING = 100
_MAX_TABLE_CELLS = 2_000_000  # rows times columns, the short rows filled up: a table of 5 000 rows and 5 000 columns comes from a body of 100 KB and is 75 MB of Markdown
_PUNCT_ESCAPES = "\\`*_[]<>|"
_INLINE_ESCAPES = {ord(char): "\\" + char for char in _PUNCT_ESCAPES}
_ABSOLUTE_URL = re.compile(r"^(?:https?|mailto|ftp|ftps|tel):", re.IGNORECASE)
_ENTITY = re.compile(r"&(?:#?[A-Za-z0-9]+);")
_WHOLE_NUMBER = re.compile(r"\s*([+-]?)([0-9]+)\s*")
_LARGEST_NUMBER = 999_999_999  # nine digits: the most that an attribute that counts is believed
# What an `ac:link` can point at, and the name that a loss of it has (`link:NAME`). A page and an attachment are written as `page:...` and `attachment:...`, an
# address as a link, a person as a mention; for every other target Markdown has no way to say where the link goes.
_LINK_KINDS = {"ri:page": "page", "ri:attachment": "attachment", "ri:blog-post": "blogpost", "ri:space": "space", "ri:shortcut": "shortcut", "ri:content-entity": "content"}


@dataclass(frozen=True)
class Converted:
    text: str
    dropped: tuple[str, ...]


def storage_to_markdown(storage: str, *, show_mentions: bool = False) -> Converted:
    """Best-effort Markdown for a storage-format fragment, with what it could not say."""
    storage = _normalize(storage)
    if not storage.strip():
        return Converted("", ())
    try:
        root = _parse(storage)
        _check_tree_depth(root)
        renderer = _MarkdownRenderer(show_mentions=show_mentions)
        return Converted(_cleanup(renderer.render_blocks(root.children)), tuple(sorted(renderer.dropped)))
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - whatever a body does to the converter, it is a body that cannot be read, never a crash
        raise _refused(exc) from exc


def storage_to_text(storage: str, *, show_mentions: bool = False) -> str:
    """Plain text for a storage-format fragment."""
    storage = _normalize(storage)
    if not storage.strip():
        return ""
    try:
        root = _parse(storage)
        _check_tree_depth(root)
        renderer = _TextRenderer(show_mentions=show_mentions)
        return _cleanup(renderer.render_blocks(root.children))
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - see storage_to_markdown
        raise _refused(exc) from exc


def _refused(error: Exception) -> ValidationError:
    """What a body that the converter cannot read becomes. The depth is said; for anything else the text of the error is left out, because it may quote the body."""
    if isinstance(error, RecursionError):
        return ValidationError("nested too deeply to convert", hint="Simplify the nesting: the storage format is nested too deeply to convert.")
    return ValidationError("cannot read this body as storage format", hint="Read it as Confluence keeps it: --format storage shows the body as it is.")


def lossy_constructs(storage: str) -> tuple[str, ...]:
    """What a Markdown copy of the storage body would lose."""
    return storage_to_markdown(storage).dropped


def _normalize(text: str) -> str:
    return _neutralize(str(text or "").replace("\r\n", "\n").replace("\r", "\n"))


# What makes Python's HTML parser slow is a construct that is never closed: for every `<name`, `</name`, `<!x`, `<?x`, `<!--` and `<![` that has no end it looks
# for the end again in all that follows, so a body made of such openers takes minutes (12 000 characters of `<p ` take seconds, so do 80 000 of `<!--`). Storage
# format is XML, where such a `<` is always closed, so one that is not is text, and it is written as `&lt;` before the parser sees it. Closed is: a tag, an end
# tag, a declaration or an instruction has a `>` before the next `<`; a comment has a `-->` after it; a CDATA section has a `]]>`. A `<![` that is not `<![CDATA[`
# is no XML at all, and the parser fails on some of it (`<![foo[`).
# The inside of a comment and of a CDATA section is raw (a comment may hold anything, and code has every `<` in it), so it is not looked at. That is right where every
# parser ends it where the text says, and Python's parsers do not agree: in some a comment ends at `--` blanks `>` or `--!>`, and a section at `]` blanks `]` blanks `>`
# (code has `a[b[i]] > 3`), and HTML5 ends `<!-->` and `<!--->` at once; what a parser then reads as markup is what nobody has looked at. So a comment that a parser
# may end early is dropped (nothing is made of a comment), a section that it may end early is written as the text that it holds, and `<!-->` is text.
_REGION = re.compile(r"<!(?:(?P<cdata>\[CDATA\[)|(?P<comment>--)|(?P<section>\[))")
_UNCLOSED = re.compile(r"<(?=[A-Za-z/?]|!(?!--|\[))(?![^<>]*>)")
_SECTION_END = re.compile(r"\]\s*\]\s*>")
_COMMENT_END = re.compile(r"--(?:\s|!)*>")


def _unclosed_as_text(text: str, first: int, last: int) -> str:
    """`text[first:last]` with each tag, end tag, declaration and instruction in it that has no `>` before the next `<` (or before `last`, which is one) written as text."""
    return _UNCLOSED.sub("&lt;", text[first:last])


def _neutralize(text: str) -> str:
    """The text with each `<` that opens something that is never closed written as the text that it is (`&lt;`), so that the parser reads the body in a moment.
    One pass: the comments and the sections are looked at one by one, and the text between them, where a tag stands, by one pattern."""
    if "<" not in text:
        return text
    last_comment_end = text.rfind("-->")
    sections_end = True  # False from the first CDATA section that never ends: no later one can end either
    parts: list[str] = []
    done = 0  # what lies before `done` is in `parts`
    skip = 0  # what lies before `skip` is the inside of a comment or of a CDATA section
    for found in _REGION.finditer(text):
        start = found.start()
        if start < skip:
            continue
        kind = found.lastgroup
        if kind == "comment":
            if last_comment_end < start + 4 or text.startswith((">", "->"), start + 4):
                parts += (_unclosed_as_text(text, done, start), "&lt;")
                done = start + 1
                continue
            skip = text.find("-->", start + 4) + 3
            early = _COMMENT_END.search(text, start + 4, skip)
            # an empty comment instead of one that a parser may end early: every parser reads it the same, and nothing that is left can join what stands around it into a tag
            parts += (_unclosed_as_text(text, done, start), "<!---->" if early is not None and early.end() < skip else text[start:skip])
            done = skip
        elif kind == "cdata":
            end = text.find("]]>", start + 9) if sections_end else -1
            if end < 0:
                sections_end = False  # a section that never ends is no section: its opener is text, and what follows is read as the text that it is
                parts += (_unclosed_as_text(text, done, start), "&lt;")
                done = start + 1
                continue
            skip = end + 3
            early = _SECTION_END.search(text, start + 9, skip)
            if early is not None and early.end() < skip:
                lead = start - 1 if start > done and text[start - 1] == "<" else start  # a `<` in front of the code would make a tag of its first character
                parts += (_unclosed_as_text(text, done, lead), "&lt;" * (lead < start), text[start + 9 : end].replace("&", "&amp;").replace("<", "&lt;"))
            else:
                parts += (_unclosed_as_text(text, done, start), text[start:skip])
            done = skip
        else:  # `<![` that is no CDATA section
            parts += (_unclosed_as_text(text, done, start), "&lt;")
            done = start + 1
    parts.append(_unclosed_as_text(text, done, len(text)))
    return "".join(parts)


def _cleanup(text: str) -> str:
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))  # not `[ \t]+\n`: that takes the square of a run of blanks that no line end follows
    lines = text.strip().split("\n")
    cleaned: list[str] = []
    blank_run = 0
    fence = ""
    for line in lines:
        token = line.strip()
        if token.startswith("```"):
            fence = "" if fence else token[:3]
            blank_run = 0
            cleaned.append(line)
            continue
        if not token and not fence:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _collapse(text: str) -> str:
    return re.sub(r"[ \t\r\n\f]+", " ", text.replace("\xa0", " ")).strip()


def _soft_collapse(text: str) -> str:
    return re.sub(r"[ \t\r\n\f]+", " ", text.replace("\xa0", " "))


def _max_tick_run(text: str) -> int:
    runs = re.findall(r"`+", text)
    return max((len(run) for run in runs), default=0)


def _number(text: str, default: int) -> int:
    """The whole number that an attribute (`start`, `colspan`, `rowspan`) holds. What is no number is `default`, and a number of more than nine digits is the
    largest one of nine: a counter is written into every line that it numbers, so a start of 4 000 digits would be written a million times."""
    found = _WHOLE_NUMBER.fullmatch(text)
    if found is None:
        return default
    digits = found.group(2).lstrip("0") or "0"  # `int` of a longer text is refused by the interpreter
    value = _LARGEST_NUMBER if len(digits) > 9 else int(digits)
    return -value if found.group(1) == "-" else value


def _check_tree_depth(root: _Node) -> None:
    stack: list[tuple[_Node, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_NESTING:
            raise ValidationError("nested too deeply to convert", hint="Simplify the nesting: the storage format is nested too deeply to convert.")
        for child in node.children:
            stack.append((child, depth + 1))


def _escape_inline_markdown(text: str, *, in_table: bool = False) -> str:
    """The text with each character that means something to Markdown behind a backslash, and the `&` of what looks like a character reference too. A table
    cell needs no more (`|` is among the characters already), so `in_table` stays as the callers say it."""
    return _ENTITY.sub(lambda match: "\\" + match.group(0), text.translate(_INLINE_ESCAPES))


def _escape_block_line(line: str) -> str:
    if not line:
        return line
    if line.startswith("[!"):
        return "\\" + line
    if line.startswith(("```", "~~~")):
        return "\\" + line
    if re.match(r"^(?:[-+*]|\d+[.)])(?:\s|$)", line):
        if line[0].isdigit():
            return re.sub(r"^(\d+)([.)])", r"\1\\\2", line, count=1)
        return "\\" + line
    if re.match(r"^[-*_]{3,}\s*$", line) or re.match(r"^=+\s*$", line):
        return "\\" + line
    if line[0] in "#>":
        return "\\" + line
    return line


def _escape_block_text(text: str, *, in_table: bool = False) -> str:
    separator = "<br>" if in_table else "\n"
    parts = text.split(separator)
    escaped = parts if in_table else [_escape_block_line(part) for part in parts]
    return separator.join(escaped)


def _markdown_code_span(text: str) -> str:
    fence = "`" * max(3 if "\n" in text else 1, _max_tick_run(text) + 1)
    padded = text
    if padded.strip(" ") == "" and "\t" not in padded:
        return fence + padded + fence
    if not padded:
        return fence + fence
    if padded.startswith((" ", "`")) or padded.endswith((" ", "`")):
        padded = " " + padded + " "
    return fence + padded + fence


def _encode_link_destination(href: str) -> str:
    result: list[str] = []
    for char in href:
        code = ord(char)
        if char in "<>\n\r" or code < 0x20 or code == 0x7F:
            result.append("%{:02X}".format(code & 0xFF))
        else:
            result.append(char)
    return "".join(result)


def _has_balanced_parens(value: str) -> bool:
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _markdown_link(label: str, href: str, *, title: str = "") -> str:
    safe_href = _encode_link_destination(href)
    if (
        label == href
        and _ABSOLUTE_URL.match(href)
        and not any(char in href for char in "<> \t\r\n\\[]`\"'")
        and all(0x20 <= ord(char) != 0x7F for char in href)
        and _has_balanced_parens(href)
    ):
        return "<" + safe_href + ">"
    destination = safe_href
    if any(char in safe_href for char in " \t[]`") or not _has_balanced_parens(safe_href):
        destination = "<" + safe_href.replace("\\", "\\\\").replace(">", "\\>") + ">"
    title_part = f' "{title}"' if title else ""
    return f"[{label}]({destination}{title_part})"


def _markdown_fenced_code(text: str, language: str = "") -> str:
    fence = "`" * max(3, _max_tick_run(text) + 1)
    prefix = fence + language
    if not text:
        return prefix + "\n" + fence
    return prefix + "\n" + text + "\n" + fence


def _escape_markdown(text: str, *, line_start: bool = False, in_table: bool = False) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")
    text = text.replace("[", "\\[").replace("]", "\\]")
    if in_table:
        text = text.replace("|", "\\|")
    if "<" in text:
        text = text.replace("<", "\\<")
    if line_start and text:
        if text[0] in "#>-+":
            text = "\\" + text
        if re.match(r"^\d+\.", text):
            text = "\\" + text
    return text


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list["_Node"] = field(default_factory=list)
    text: str = ""

    def add_text(self, value: str) -> None:
        if value:
            self.children.append(_Node("#text", {}, text=value))

    def attr(self, name: str) -> str:
        return self.attrs.get(name, "")


class _Builder(HTMLParser):
    VOID = {"br", "hr", "img", "col", "ri:user", "ri:url", "ri:attachment", "ac:emoticon"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.open: dict[str, int] = {}  # how many elements of a tag are open: an end tag of one that is not open skips the search of the stack

    def handle_starttag(self, tag: str, attrs) -> None:
        node = _Node(tag.lower(), {name.lower(): value or "" for name, value in attrs if name})
        self.stack[-1].children.append(node)
        if node.tag not in self.VOID:
            self.stack.append(node)
            self.open[node.tag] = self.open.get(node.tag, 0) + 1

    def handle_startendtag(self, tag: str, attrs) -> None:
        node = _Node(tag.lower(), {name.lower(): value or "" for name, value in attrs if name})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.open.get(tag):
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                for closed in self.stack[index:]:
                    self.open[closed.tag] -= 1
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].add_text(data)

    def unknown_decl(self, data: str) -> None:
        if data.startswith("CDATA["):
            self.stack[-1].add_text(data[6:])

    def close(self) -> _Node:
        super().close()
        return self.root


def _parse(storage: str) -> _Node:
    parser = _Builder()
    try:
        parser.feed(storage)
    except Exception:
        pass
    return parser.close()


def _text_content(node: _Node) -> str:
    if node.tag == "#text":
        return node.text
    return "".join(_text_content(child) for child in node.children)


class _BaseRenderer:
    HARMLESS = {"div", "section", "tbody", "thead", "tfoot", "colgroup", "col", "p", "span"}
    INLINE_NATIVE = {"strong", "em", "b", "i", "code", "a", "u", "sub", "sup", "del", "s", "strike", "time", "br"}
    BLOCK = {
        "p",
        "div",
        "section",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "ul",
        "ol",
        "table",
        "pre",
        "hr",
        "ac:structured-macro",
        "ac:task-list",
        "ac:layout",
        "ac:layout-section",
        "ac:layout-cell",
    }

    def __init__(self, *, show_mentions: bool) -> None:
        self.show_mentions = show_mentions
        self.dropped: set[str] = set()

    def record(self, value: str) -> None:
        # A name can hold text of the document (a macro, an element, a kind of link): the people stay out of it, as they stay out of any text.
        self.dropped.add(value if self.show_mentions else redact_text(value))

    def render_blocks(self, nodes: list[_Node]) -> str:
        blocks: list[str] = []
        pending: list[_Node] = []
        for node in nodes:
            if self._is_block(node):
                if pending:
                    paragraph = self.render_paragraph_nodes(pending)
                    if paragraph:
                        blocks.append(paragraph)
                    pending = []
                rendered = self.render_block(node)
                if rendered:
                    blocks.append(rendered)
            else:
                pending.append(node)
        if pending:
            paragraph = self.render_paragraph_nodes(pending)
            if paragraph:
                blocks.append(paragraph)
        return "\n\n".join(block for block in blocks if block)

    def render_paragraph_nodes(self, nodes: list[_Node]) -> str:
        return self.render_inline_nodes(nodes).strip()

    def render_inline_nodes(self, nodes: list[_Node], *, in_table: bool = False, preserve_breaks: bool = False) -> str:
        return "".join(self.render_inline(node, in_table=in_table, preserve_breaks=preserve_breaks) for node in nodes)

    def render_inline(self, node: _Node, *, in_table: bool = False, preserve_breaks: bool = False) -> str:
        raise NotImplementedError

    def render_block(self, node: _Node) -> str:
        raise NotImplementedError

    def _is_block(self, node: _Node) -> bool:
        return node.tag in self.BLOCK

    def _is_plain_inline_node(self, node: _Node) -> bool:
        if node.tag == "#text" or node.tag in self.INLINE_NATIVE:
            return True
        if node.tag in {"ac:link", "ac:image", "ac:emoticon", "ac:inline-comment-marker", "ac:adf-extension"}:
            return True
        if node.tag.startswith("ri:"):
            return True
        if node.tag == "span":
            return not node.attr("style")
        return False

    def _unknown_html(self, node: _Node, *, in_table: bool = False) -> str:
        if node.tag not in self.HARMLESS and node.tag not in self.INLINE_NATIVE:
            self.record(f"html:{node.tag}")
        return self.render_inline_nodes(node.children, in_table=in_table)

    def _name_link_targets(self, node: _Node) -> None:
        """Names what the Markdown of an `ac:link` cannot say about where it goes: the kind of each target it has, and the anchor in it. A link to an address
        or to a person is not named here: the first is a link in Markdown too, the second is a mention."""
        if node.attr("ac:anchor"):
            self.record("link:anchor")
        for child in node.children:
            if child.tag.startswith("ri:") and child.tag not in {"ri:url", "ri:user"}:
                self.record("link:" + _LINK_KINDS.get(child.tag, child.tag[3:]))

    def _find_child(self, node: _Node, tag: str) -> _Node | None:
        for child in node.children:
            if child.tag == tag:
                return child
        return None

    def _has_text_align(self, node: _Node) -> bool:
        style = node.attr("style").lower()
        return bool(node.attr("align") or "text-align:" in style)

    def _has_background(self, node: _Node) -> bool:
        style = node.attr("style").lower()
        return bool(node.attr("data-highlight-colour") or "background" in style or "background-color" in style)

    def _join_table_lines(self, text: str, separator: str) -> str:
        return separator.join(line for line in (item.strip() for item in text.split("\n")) if line)

    def _macro_params(self, node: _Node) -> dict[str, str]:
        return {
            child.attr("ac:name").lower(): _collapse(_text_content(child))
            for child in node.children
            if child.tag == "ac:parameter" and child.attr("ac:name")
        }

    def _table_cell_markdown(self, cell: _Node) -> tuple[str, bool]:
        pieces: list[str] = []
        rich = False
        pending: list[_Node] = []
        for child in cell.children:
            if child.tag == "p":
                if pending:
                    text = self.render_inline_nodes(pending, in_table=True)
                    if text.strip():
                        pieces.append(text.strip())
                    pending = []
                text = self.render_inline_nodes(child.children, in_table=True)
                if text.strip():
                    pieces.append(text.strip())
                continue
            if self._is_block(child) and child.tag != "p":
                if pending:
                    text = self.render_inline_nodes(pending, in_table=True)
                    if text.strip():
                        pieces.append(text.strip())
                    pending = []
                rich = True
                rendered = self.render_block(child)
                if rendered:
                    pieces.append(self._join_table_lines(rendered, "<br>"))
                continue
            if not self._is_plain_inline_node(child):
                rich = True
            pending.append(child)
        if pending:
            text = self.render_inline_nodes(pending, in_table=True)
            if text.strip():
                pieces.append(text.strip())
        escaped = [_escape_block_text(piece, in_table=True) for piece in pieces if piece]
        return "<br>".join(escaped), rich

    def _table_cell_text(self, cell: _Node) -> tuple[str, bool]:
        pieces: list[str] = []
        rich = False
        pending: list[_Node] = []
        for child in cell.children:
            if child.tag == "p":
                if pending:
                    text = self.render_inline_nodes(pending)
                    if _collapse(text):
                        pieces.append(_collapse(text))
                    pending = []
                text = self.render_inline_nodes(child.children)
                if _collapse(text):
                    pieces.append(_collapse(text))
                continue
            if self._is_block(child) and child.tag != "p":
                if pending:
                    text = self.render_inline_nodes(pending)
                    if _collapse(text):
                        pieces.append(_collapse(text))
                    pending = []
                rich = True
                rendered = self.render_block(child)
                if rendered:
                    pieces.append(_collapse(rendered.replace("\n", " ")))
                continue
            if not self._is_plain_inline_node(child):
                rich = True
            pending.append(child)
        if pending:
            text = self.render_inline_nodes(pending)
            if _collapse(text):
                pieces.append(_collapse(text))
        return " ".join(piece for piece in pieces if piece), rich


class _MarkdownRenderer(_BaseRenderer):
    def render_paragraph_nodes(self, nodes: list[_Node]) -> str:
        text = self.render_inline_nodes(nodes).strip()
        return _escape_block_text(text) if _collapse(text) else ""

    def render_block(self, node: _Node) -> str:
        if node.tag == "p":
            if self._has_text_align(node):
                self.record("formatting:align")
            text = self.render_inline_nodes(node.children).strip()
            return _escape_block_text(text) if _collapse(text) else ""
        if re.fullmatch(r"h[1-6]", node.tag):
            if self._has_text_align(node):
                self.record("formatting:align")
            level = int(node.tag[1])
            text = self.render_inline_nodes(node.children, preserve_breaks=True).strip()
            return "" if not _collapse(text) else "#" * level + " " + _escape_block_text(text)
        if node.tag == "blockquote":
            body = self.render_blocks(node.children)
            return "\n".join("> " + line if line else ">" for line in body.split("\n"))
        if node.tag in {"ul", "ol"}:
            if node.attr("type") or node.attr("style"):
                self.record("formatting:list")
            return self._render_list(node, 0)
        if node.tag == "ac:task-list":
            return self._render_task_list(node, 0)
        if node.tag == "hr":
            return "---"
        if node.tag == "pre":
            body = _text_content(node).replace("\xa0", " ")
            return _markdown_fenced_code(body)
        if node.tag == "table":
            return self._render_table(node)
        if node.tag == "ac:structured-macro":
            return self._render_macro(node)
        if node.tag in {"ac:layout", "ac:layout-section", "ac:layout-cell"}:
            self.record("layout")
            return self.render_blocks(node.children)
        if node.tag in {"div", "section"}:  # a wrapper: its paragraphs, lists and tables are blocks, not one run of text
            return self.render_blocks(node.children)
        if node.tag == "ac:inline-comment-marker":
            self.record("inline-comment")
            return self.render_inline_nodes(node.children)
        if node.tag.startswith("ac:") or node.tag.startswith("ri:"):
            self.record(f"tag:{node.tag.split(':', 1)[1]}")
            return self.render_blocks(node.children)
        return self._unknown_html(node).strip()

    def render_inline(self, node: _Node, *, in_table: bool = False, preserve_breaks: bool = False) -> str:
        if node.tag == "#text":
            return _escape_inline_markdown(_soft_collapse(node.text), in_table=in_table)
        if node.tag in {"strong", "b"}:
            return f"**{self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)}**"
        if node.tag in {"em", "i"}:
            return f"*{self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)}*"
        if node.tag in {"del", "s", "strike"}:
            return f"~~{self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)}~~"
        if node.tag == "code":
            if any(child.tag != "#text" for child in node.children):
                self.record("formatting:inline-code")  # a link, bold or the like inside code: Markdown has code that holds text and nothing else
            content = _text_content(node)
            return _markdown_code_span(content)
        if node.tag == "br":
            if in_table or preserve_breaks:
                return "<br>"
            return "\\\n"
        if node.tag == "u":
            self.record("formatting:underline")
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag == "sub":
            self.record("formatting:subscript")
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag == "sup":
            self.record("formatting:superscript")
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag == "time":
            self.record("time")
            return _escape_inline_markdown(node.attr("datetime") or _collapse(_text_content(node)), in_table=in_table)
        if node.tag == "span":
            style = node.attr("style").lower()
            text = self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
            if "text-decoration" in style and "line-through" in style:
                return f"~~{text}~~"
            if "underline" in style:
                self.record("formatting:underline")
            if "color:" in style:
                self.record("formatting:color")
            if "vertical-align: sub" in style:
                self.record("formatting:subscript")
            if "vertical-align: super" in style:
                self.record("formatting:superscript")
            if "text-align:" in style:
                self.record("formatting:align")
            return text
        if node.tag == "a":
            href = node.attr("href")
            if node.attr("name") or node.attr("id"):
                self.record("anchor")  # a place that a link of the page, or of another page, jumps to: the text stays, the place does not
            if not self.show_mentions and is_profile_link(href):
                self.record("mention")  # a link to a profile names a person, as a mention does
                return "@user"
            title = node.attr("title")
            text = self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks) or _escape_inline_markdown(href, in_table=in_table)
            if not href:
                return text
            return _markdown_link(text, href, title=title)
        if node.tag == "ac:link":
            return self._render_ac_link(node, in_table=in_table)
        if node.tag == "ri:user":
            self.record("mention")
            account = node.attr("ri:account-id") or "user"
            return "@<" + account + ">" if self.show_mentions and account else "@user"
        if node.tag == "ac:image":
            return self._render_image(node)
        if node.tag == "ac:emoticon":
            self.record("emoticon")
            fallback = node.attr("ac:emoji-fallback") or f":{node.attr('ac:name') or 'emoticon'}:"
            return _escape_inline_markdown(fallback, in_table=in_table)
        if node.tag == "ac:inline-comment-marker":
            self.record("inline-comment")
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag == "ac:placeholder":
            self.record("placeholder")  # the grey hint of a template: it is text that a reader sees, and Markdown has no such text
            return ""
        if node.tag == "ac:structured-macro":
            return self._render_macro(node)
        if node.tag == "ac:adf-extension":
            self.record("adf-extension")
            fallback = self._find_child(node, "ac:adf-fallback")
            return self.render_inline_nodes(fallback.children if fallback else [], in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag.startswith("ac:") or node.tag.startswith("ri:"):
            self.record(f"tag:{node.tag.split(':', 1)[1]}")
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        return self._unknown_html(node, in_table=in_table)

    def _render_ac_link(self, node: _Node, *, in_table: bool) -> str:
        label_source = self._find_child(node, "ac:plain-text-link-body") or self._find_child(node, "ac:link-body")
        label = self.render_inline_nodes(label_source.children if label_source else [], in_table=in_table)
        self._name_link_targets(node)
        page = self._find_child(node, "ri:page")
        if page is not None:
            title = page.attr("ri:content-title")
            space = page.attr("ri:space-key")
            if not self.show_mentions and is_personal_space(space):
                space = HIDDEN  # the key of a personal space is the account id of its owner, as the account id of a mention is the one of a person
            target = f"page:{space}/{title}" if space else f"page:{title}"
            return f"[{label or _escape_inline_markdown(title, in_table=in_table)}]({target})"
        attachment = self._find_child(node, "ri:attachment")
        if attachment is not None:
            name = attachment.attr("ri:filename")
            return f"[{label or _escape_inline_markdown(name, in_table=in_table)}](attachment:{name})"
        url = self._find_child(node, "ri:url")
        if url is not None:
            target = url.attr("ri:value")
            text = label or _escape_inline_markdown(target, in_table=in_table)
            return _markdown_link(text, target)
        anchor = node.attr("ac:anchor")
        if anchor:
            return f"[{label or _escape_inline_markdown(anchor, in_table=in_table)}](#{anchor})"
        user = self._find_child(node, "ri:user")
        if user is not None:
            return self.render_inline(user, in_table=in_table)
        return label

    def _render_image(self, node: _Node) -> str:
        alt = node.attr("ac:alt")
        important = {"ac:alt"}
        unknown_children = [child for child in node.children if child.tag not in {"ri:url", "ri:attachment"}]
        if any(name not in important for name in node.attrs) or unknown_children:
            self.record("formatting:image")
        url = self._find_child(node, "ri:url")
        if url is not None:
            return f"![{_escape_inline_markdown(alt)}]({url.attr('ri:value')})"
        attachment = self._find_child(node, "ri:attachment")
        if attachment is not None:
            return f"![{_escape_inline_markdown(alt)}]({attachment.attr('ri:filename')})"
        return _escape_inline_markdown(alt)

    def _render_list(self, node: _Node, indent: int) -> str:
        ordered = node.tag == "ol"
        counter = _number(node.attr("start"), 1)
        lines: list[str] = []
        for child in node.children:
            if child.tag != "li":
                continue
            marker = f"{counter}. " if ordered else "- "
            counter += 1
            lines.extend(self._render_list_item(child, indent, marker))
        return "\n".join(lines)

    def _render_list_item(self, item: _Node, indent: int, marker: str) -> list[str]:
        continuation = len(marker)
        nested_list_indent = max(4, len(marker))
        base_prefix = " " * indent
        nested_indent = indent + continuation
        blocks = self._list_item_blocks(item, nested_indent, indent + nested_list_indent)
        if not blocks:
            return [base_prefix + marker.rstrip()]
        lines: list[str] = []
        first = True
        previous_nested = False
        for kind, block in blocks:
            if not block:
                continue
            if kind == "nested":
                if first:
                    lines.append(base_prefix + marker.rstrip())
                    first = False
                elif not previous_nested and lines:
                    pass
                lines.extend(block.split("\n"))
                previous_nested = True
                continue
            if not first and not previous_nested:
                lines.append("")
            block_lines = block.split("\n") or [""]
            if first:
                lines.append(base_prefix + marker + block_lines[0])
                lines.extend(" " * nested_indent + line for line in block_lines[1:])
                first = False
            else:
                lines.append(" " * nested_indent + block_lines[0])
                lines.extend(" " * nested_indent + line for line in block_lines[1:])
            previous_nested = False
        return lines

    def _list_item_blocks(self, item: _Node, block_indent: int, nested_list_indent: int) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        pending: list[_Node] = []
        for child in item.children:
            if child.tag in {"ul", "ol"}:
                if pending:
                    text = self.render_inline_nodes(pending).strip()
                    if _collapse(text):
                        blocks.append(("paragraph", text))
                    pending = []
                if child.attr("type") or child.attr("style"):
                    self.record("formatting:list")
                nested = self._render_list(child, nested_list_indent)
                if nested:
                    blocks.append(("nested", nested))
                continue
            if child.tag == "ac:task-list":
                if pending:
                    text = self.render_inline_nodes(pending).strip()
                    if _collapse(text):
                        blocks.append(("paragraph", text))
                    pending = []
                nested = self._render_task_list(child, nested_list_indent)
                if nested:
                    blocks.append(("nested", nested))
                continue
            if child.tag == "p":
                if pending:
                    text = self.render_inline_nodes(pending).strip()
                    if _collapse(text):
                        blocks.append(("paragraph", text))
                    pending = []
                text = self.render_inline_nodes(child.children).strip()
                if _collapse(text):
                    blocks.append(("paragraph", text))
                continue
            if self._is_block(child) and child.tag != "p":
                if pending:
                    text = self.render_inline_nodes(pending).strip()
                    if _collapse(text):
                        blocks.append(("paragraph", text))
                    pending = []
                rendered = self.render_block(child)
                if rendered:
                    blocks.append(("block", rendered))
                continue
            pending.append(child)
        if pending:
            text = self.render_inline_nodes(pending).strip()
            if _collapse(text):
                blocks.append(("paragraph", text))
        return blocks

    def _render_task_list(self, node: _Node, indent: int) -> str:
        lines: list[str] = []
        prefix = " " * indent
        for task in node.children:
            if task.tag != "ac:task":
                continue
            status = self._find_child(task, "ac:task-status")
            body = self._find_child(task, "ac:task-body")
            mark = "x" if _collapse(_text_content(status or _Node("", {}))).lower() == "complete" else " "
            text = self.render_inline_nodes(body.children if body else []).strip()
            lines.append(prefix + f"- [{mark}] {text}".rstrip())
        return "\n".join(lines)

    def _render_macro(self, node: _Node) -> str:
        name = node.attr("ac:name").lower()
        params = self._macro_params(node)
        rich = self._find_child(node, "ac:rich-text-body")
        plain = self._find_child(node, "ac:plain-text-body")
        if name == "code":
            if any(key != "language" for key in params):
                self.record("macro:code")
            language = params.get("language", "")
            body = _text_content(plain or _Node("", {})).replace("\xa0", " ")
            if body.endswith("\n"):
                self.record("macro:code")
            return _markdown_fenced_code(body, language)
        if name == "noformat":
            self.record("macro:noformat")
            body = _text_content(plain or _Node("", {})).replace("\xa0", " ")
            return _markdown_fenced_code(body)
        if name in {"info", "note", "warning", "tip"}:
            if any(params.get(key) for key in params):
                self.record(f"macro:{name}")
            label = {"info": "NOTE", "tip": "TIP", "note": "IMPORTANT", "warning": "WARNING"}[name]
            body = self.render_blocks(rich.children if rich else [])
            if not body:
                return f"> [!{label}]"
            return "\n".join([f"> [!{label}]"] + ["> " + line if line else ">" for line in body.split("\n")])
        if name == "panel":
            if params:
                self.record("macro:panel")
            body = self.render_blocks(rich.children if rich else [])
            return "\n".join("> " + line if line else ">" for line in body.split("\n")) if body else ""
        if name == "quote":
            if params:
                self.record("macro:quote")
            body = self.render_blocks(rich.children if rich else [])
            return "\n".join("> " + line if line else ">" for line in body.split("\n")) if body else ""
        if name == "status":
            self.record("macro:status")
            return "[" + params.get("title", "").strip() + "]"
        if name in {"toc", "jira", "expand", "children"}:
            self.record(f"macro:{name}")
            return self.render_blocks(rich.children if rich else [])
        if rich is not None:
            self.record(f"macro:{name}")
            return self.render_blocks(rich.children)
        if plain is not None:
            self.record(f"macro:{name}")
            return _markdown_fenced_code(_text_content(plain).replace("\xa0", " "))
        self.record(f"macro:{name}")
        return ""

    def _render_table(self, node: _Node) -> str:
        rows: list[_Node] = []
        orphans: list[_Node] = []  # what stands in the table and is no row (a caption, say): its text goes above the table, and the element is named
        for child in node.children:
            if child.tag == "tr":
                rows.append(child)
            elif child.tag in {"tbody", "thead", "tfoot"}:
                for grand in child.children:
                    (rows if grand.tag == "tr" else orphans).append(grand)
            elif child.tag not in {"colgroup", "col"}:
                orphans.append(child)
        lead = self.render_blocks([item for item in orphans if item.tag != "#text"])
        if not rows:
            return lead
        if self._has_background(node):
            self.record("formatting:color")
        if self._has_text_align(node):
            self.record("formatting:align")
        parsed: list[list[str]] = []
        alignments: list[str] = []
        merged = False
        rich = False
        for row_index, row in enumerate(rows):
            if self._has_background(row):
                self.record("formatting:color")
            if self._has_text_align(row):
                self.record("formatting:align")
            cells = [child for child in row.children if child.tag in {"th", "td"}]
            if row_index > 0 and any(cell.tag == "th" for cell in cells):
                self.record("table:row-headers")
            current: list[str] = []
            for cell_index, cell in enumerate(cells):
                if _number(cell.attr("colspan"), 1) > 1 or _number(cell.attr("rowspan"), 1) > 1:
                    merged = True
                if self._has_background(cell):
                    self.record("formatting:color")
                if self._has_text_align(cell):
                    self.record("formatting:align")
                alignment = ""
                if "text-align:" in cell.attr("style").lower():
                    style = cell.attr("style").lower()
                    if "text-align: center" in style:
                        alignment = "center"
                    elif "text-align: right" in style:
                        alignment = "right"
                    elif "text-align: left" in style:
                        alignment = "left"
                elif cell.attr("align"):
                    alignment = cell.attr("align").lower()
                if len(alignments) <= cell_index:
                    alignments.append(alignment)
                elif not alignments[cell_index]:
                    alignments[cell_index] = alignment
                text, cell_rich = self._table_cell_markdown(cell)
                rich = rich or cell_rich
                current.append(text)
            parsed.append(current)
        if merged:
            self.record("table:merged-cells")
        if rich:
            self.record("table:rich-cells")
        width = max((len(row) for row in parsed), default=0)
        if width * len(parsed) > _MAX_TABLE_CELLS:  # Markdown has no short rows: one wide row and many narrow ones is a table of the square of what the body holds
            raise ValidationError("a table is too large to convert", hint="Read it as Confluence keeps it: --format storage shows the body as it is.")
        first_cells = [child for child in rows[0].children if child.tag in {"th", "td"}]
        has_header = bool(first_cells) and all(cell.tag == "th" for cell in first_cells)
        if not has_header:
            parsed.insert(0, [""] * width)
        parsed = [row + [""] * (width - len(row)) for row in parsed]
        alignments += [""] * (width - len(alignments))
        delimiter = []
        for alignment in alignments[:width]:
            if alignment == "left":
                delimiter.append(":---")
            elif alignment == "center":
                delimiter.append(":---:")
            elif alignment == "right":
                delimiter.append("---:")
            else:
                delimiter.append("---")
        lines = ["| " + " | ".join(cell for cell in parsed[0]) + " |", "| " + " | ".join(delimiter) + " |"]
        for row in parsed[1:]:
            lines.append("| " + " | ".join(cell for cell in row) + " |")
        table = "\n".join(lines)
        return f"{lead}\n\n{table}" if lead else table


class _TextRenderer(_BaseRenderer):
    def render_paragraph_nodes(self, nodes: list[_Node]) -> str:
        text = _collapse(self.render_inline_nodes(nodes))
        return text if text else ""

    def render_block(self, node: _Node) -> str:
        if node.tag == "p":
            return _collapse(self.render_inline_nodes(node.children))
        if re.fullmatch(r"h[1-6]", node.tag):
            return _collapse(self.render_inline_nodes(node.children, preserve_breaks=True))
        if node.tag == "blockquote":
            return self.render_blocks(node.children)
        if node.tag in {"ul", "ol"}:
            return self._render_list(node, 0)
        if node.tag == "ac:task-list":
            return self._render_task_list(node, 0)
        if node.tag == "hr":
            return ""
        if node.tag == "pre":
            return _text_content(node).replace("\xa0", " ").strip("\n")
        if node.tag == "table":
            return self._render_table(node)
        if node.tag == "ac:structured-macro":
            return self._render_macro(node)
        if node.tag in {"ac:layout", "ac:layout-section", "ac:layout-cell"}:
            return self.render_blocks(node.children)
        if node.tag in {"div", "section"}:
            return self.render_blocks(node.children)
        if node.tag == "ac:inline-comment-marker":
            return self.render_inline_nodes(node.children)
        if node.tag.startswith("ac:") or node.tag.startswith("ri:"):
            return self.render_blocks(node.children)
        return self.render_inline_nodes(node.children)

    def render_inline(self, node: _Node, *, in_table: bool = False, preserve_breaks: bool = False) -> str:
        if node.tag == "#text":
            return _soft_collapse(node.text)
        if node.tag in {"strong", "b", "em", "i", "del", "s", "strike", "u", "sub", "sup", "span"}:
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag == "code":
            return _text_content(node)
        if node.tag == "br":
            return "\n" if not (in_table or preserve_breaks) else " "
        if node.tag == "a":
            href = node.attr("href")
            if not self.show_mentions and is_profile_link(href):
                return "@user"
            text = _collapse(self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)) or href
            return text if not href or href == text or href.startswith("#") else f"{text} ({href})"
        if node.tag == "ac:structured-macro":
            return self._render_macro(node)
        if node.tag == "ac:link":
            return self._render_ac_link(node, in_table=in_table)
        if node.tag == "ri:user":
            account = node.attr("ri:account-id") or "user"
            return "@<" + account + ">" if self.show_mentions and account else "@user"
        if node.tag == "ac:image":
            return self._render_image(node)
        if node.tag == "ac:emoticon":
            return node.attr("ac:emoji-fallback") or f":{node.attr('ac:name') or 'emoticon'}:"
        if node.tag == "time":
            return node.attr("datetime") or _collapse(_text_content(node))
        if node.tag == "ac:adf-extension":
            fallback = self._find_child(node, "ac:adf-fallback")
            return self.render_inline_nodes(fallback.children if fallback else [], in_table=in_table, preserve_breaks=preserve_breaks)
        if node.tag.startswith("ac:") or node.tag.startswith("ri:"):
            return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)
        return self.render_inline_nodes(node.children, in_table=in_table, preserve_breaks=preserve_breaks)

    def _render_ac_link(self, node: _Node, *, in_table: bool) -> str:
        label_source = self._find_child(node, "ac:plain-text-link-body") or self._find_child(node, "ac:link-body")
        label = _collapse(self.render_inline_nodes(label_source.children if label_source else [], in_table=in_table))
        page = self._find_child(node, "ri:page")
        if page is not None:
            return label or page.attr("ri:content-title")
        attachment = self._find_child(node, "ri:attachment")
        if attachment is not None:
            name = attachment.attr("ri:filename")
            return f"{label or name} (attachment:{name})" if label else name
        url = self._find_child(node, "ri:url")
        if url is not None:
            target = url.attr("ri:value")
            text = label or target
            return text if text == target else f"{text} ({target})"
        anchor = node.attr("ac:anchor")
        if anchor:
            return label or anchor
        user = self._find_child(node, "ri:user")
        if user is not None:
            return self.render_inline(user, in_table=in_table)
        return label

    def _render_image(self, node: _Node) -> str:
        alt = node.attr("ac:alt")
        if alt:
            return alt
        attachment = self._find_child(node, "ri:attachment")
        if attachment is not None:
            return attachment.attr("ri:filename")
        url = self._find_child(node, "ri:url")
        return url.attr("ri:value") if url is not None else ""

    def _render_list(self, node: _Node, indent: int) -> str:
        ordered = node.tag == "ol"
        counter = _number(node.attr("start"), 1)
        lines: list[str] = []
        for child in node.children:
            if child.tag != "li":
                continue
            marker = f"{counter}. " if ordered else "- "
            counter += 1
            lines.extend(self._render_list_item(child, indent, marker))
        return "\n".join(lines)

    def _render_list_item(self, item: _Node, indent: int, marker: str) -> list[str]:
        continuation = len(marker)
        nested_list_indent = max(4, len(marker))
        base_prefix = " " * indent
        nested_indent = indent + continuation
        blocks = self._list_item_blocks(item, nested_indent, indent + nested_list_indent)
        if not blocks:
            return [base_prefix + marker.rstrip()]
        lines: list[str] = []
        first = True
        previous_nested = False
        for kind, block in blocks:
            if not block:
                continue
            if kind == "nested":
                if first:
                    lines.append(base_prefix + marker.rstrip())
                    first = False
                lines.extend(block.split("\n"))
                previous_nested = True
                continue
            if not first and not previous_nested:
                lines.append("")
            block_lines = block.split("\n") or [""]
            if first:
                lines.append(base_prefix + marker + block_lines[0])
                lines.extend(" " * nested_indent + line for line in block_lines[1:])
                first = False
            else:
                lines.append(" " * nested_indent + block_lines[0])
                lines.extend(" " * nested_indent + line for line in block_lines[1:])
            previous_nested = False
        return lines

    def _list_item_blocks(self, item: _Node, nested_indent: int, nested_list_indent: int) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        pending: list[_Node] = []
        for child in item.children:
            if child.tag in {"ul", "ol"}:
                if pending:
                    text = _collapse(self.render_inline_nodes(pending))
                    if text:
                        blocks.append(("paragraph", text))
                    pending = []
                nested = self._render_list(child, nested_list_indent)
                if nested:
                    blocks.append(("nested", nested))
                continue
            if child.tag == "ac:task-list":
                if pending:
                    text = _collapse(self.render_inline_nodes(pending))
                    if text:
                        blocks.append(("paragraph", text))
                    pending = []
                nested = self._render_task_list(child, nested_list_indent)
                if nested:
                    blocks.append(("nested", nested))
                continue
            if child.tag == "p":
                if pending:
                    text = _collapse(self.render_inline_nodes(pending))
                    if text:
                        blocks.append(("paragraph", text))
                    pending = []
                text = _collapse(self.render_inline_nodes(child.children))
                if text:
                    blocks.append(("paragraph", text))
                continue
            if self._is_block(child) and child.tag != "p":
                if pending:
                    text = _collapse(self.render_inline_nodes(pending))
                    if text:
                        blocks.append(("paragraph", text))
                    pending = []
                rendered = self.render_block(child)
                if rendered:
                    blocks.append(("block", rendered))
                continue
            pending.append(child)
        if pending:
            text = _collapse(self.render_inline_nodes(pending))
            if text:
                blocks.append(("paragraph", text))
        return blocks

    def _render_task_list(self, node: _Node, indent: int) -> str:
        prefix = " " * indent
        lines: list[str] = []
        for task in node.children:
            if task.tag != "ac:task":
                continue
            status = self._find_child(task, "ac:task-status")
            body = self._find_child(task, "ac:task-body")
            mark = "x" if _collapse(_text_content(status or _Node("", {}))).lower() == "complete" else " "
            text = _collapse(self.render_inline_nodes(body.children if body else []))
            lines.append(prefix + f"- [{mark}] {text}".rstrip())
        return "\n".join(lines)

    def _render_macro(self, node: _Node) -> str:
        name = node.attr("ac:name").lower()
        params = self._macro_params(node)
        rich = self._find_child(node, "ac:rich-text-body")
        plain = self._find_child(node, "ac:plain-text-body")
        if name == "code":
            return _text_content(plain or _Node("", {})).replace("\xa0", " ").strip("\n")
        if name == "noformat":
            return _text_content(plain or _Node("", {})).replace("\xa0", " ")
        if name in {"info", "note", "warning", "tip", "panel", "quote"}:
            return self.render_blocks(rich.children if rich else [])
        if name == "status":
            return "[" + params.get("title", "").strip() + "]"
        if plain is not None:
            return _text_content(plain).replace("\xa0", " ")
        return self.render_blocks(rich.children if rich else [])

    def _render_table(self, node: _Node) -> str:
        rows: list[_Node] = []
        for child in node.children:
            if child.tag == "tr":
                rows.append(child)
            elif child.tag in {"tbody", "thead", "tfoot"}:
                rows.extend(grand for grand in child.children if grand.tag == "tr")
        lines: list[str] = []
        for row in rows:
            cells = [child for child in row.children if child.tag in {"th", "td"}]
            parts: list[str] = []
            for cell in cells:
                text, _ = self._table_cell_text(cell)
                parts.append(text)
            lines.append(" | ".join(part for part in parts))
        return "\n".join(lines)
