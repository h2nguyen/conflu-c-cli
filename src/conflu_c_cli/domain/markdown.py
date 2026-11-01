"""Markdown to Confluence storage format.

The converter is conservative and dependency-free: unknown HTML is shown as text, code stays literal,
and arbitrary input is handled on a best-effort basis.
"""
from __future__ import annotations

import re
from html import unescape
from itertools import count
from string import punctuation

from .errors import ValidationError

_REFERENCE = re.compile(r'^[ \t]{0,3}\[([^\]]+)\]:[ \t]*<?([^\s>]+)>?(?:[ \t]+(["\'])(.*?)\3)?[ \t]*$')
_ATX_START = re.compile(r"^[ \t]{0,3}(#{1,6})([ \t]+)")
_SETEXT_1 = re.compile(r"^[ \t]{0,3}=+[ \t]*$")
_SETEXT_2 = re.compile(r"^[ \t]{0,3}-+[ \t]*$")
_HR = re.compile(r"^[ \t]{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
_FENCE_START = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*")
_ORDERED = re.compile(r"^(\d{1,9})([.)])$")
_LIST_MARKER = re.compile(r"^([ \t]*)([-+*]|\d{1,9}[.)])(?:[ \t]+(.*)|[ \t]*)$")  # at most nine digits, as in CommonMark: `int()` refuses thousands of them
_TABLE_DELIM_CELL = re.compile(r":?-+:?")
_TABLE_DELIM_ONE = re.compile(r"^[ \t]*\|[ \t]*:?-+:?[ \t]*\|[ \t]*$")  # the delimiter row of a table of one column
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_BARE_URL = re.compile(r"https?://[^\s<\ufff0\ufff1]+")
_AUTOLINK = re.compile(r"<([^ <>\n]+)>")
_RAW_HTML = re.compile(r"</?[A-Za-z][^>]*>")
_BACKSLASH = set(punctuation)
_SAFE_SCHEMES = {"http", "https", "mailto", "ftp", "ftps", "tel"}
_XML_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_TOKEN_RE = re.compile("\ufff0C(\\d+)\ufff1")
_ESCAPE_RE = re.compile(r"\\([!\"#$%&'()*+,./:;<=>?@[\\\]^_`{|}~-])")
_MAX_NESTING = 100
_INLINE_LOOKAHEAD = 2000
_REF_LIKE_AMP = re.compile(r"&(?:#?[A-Za-z0-9]+);")
_LANGUAGE_ALIASES = {
    "javascript": "js",
    "typescript": "js",
    "ts": "js",
    "jsx": "js",
    "tsx": "js",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "console": "bash",
    "c++": "cpp",
    "csharp": "c#",
    "cs": "c#",
    "ps1": "powershell",
    "py": "python",
    "yml": "yaml",
    "plaintext": "text",
    "txt": "text",
}
_ALERTS = {
    "note": "info",
    "tip": "tip",
    "important": "note",
    "warning": "warning",
    "caution": "warning",
}


def markdown_to_storage(text: str) -> str:
    """The Confluence storage format fragment for a Markdown body."""
    text = _strip_illegal_xml(_normalize_newlines(text))
    # U+FFF0 and U+FFF1 mark the pieces that the converter sets aside (`_apply_tokens`): in the text they would be taken for one of them, and a code span
    # that holds `\ufff0C0\ufff1` was put into itself for ever
    text = text.replace("\ufff0", "\ufffd").replace("\ufff1", "\ufffd")
    if not text.strip():
        return ""
    lines, references = _extract_references(text.split("\n"))
    try:
        parser = _MarkdownParser(lines, references)
        return "\n".join(block for block in parser.parse_blocks(0, 0)[0] if block)
    except RecursionError as exc:
        raise ValidationError("nested too deeply to convert", hint="Simplify the nesting: the Markdown is nested too deeply to convert.") from exc


def _normalize_newlines(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return value[1:] if value.startswith("\ufeff") else value


def _strip_illegal_xml(text: str) -> str:
    kept: list[str] = []
    for char in text:
        code = ord(char)
        if char in "\n\t":
            kept.append(char)
        elif code == 0x0D:
            kept.append("\n")
        elif 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF:
            kept.append(char)
    return "".join(kept)


def _extract_references(lines: list[str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    kept: list[str] = []
    references: dict[str, tuple[str, str]] = {}
    for line in lines:
        match = _REFERENCE.match(line)
        if match:
            references[match.group(1).strip().lower()] = (match.group(2), match.group(4) or "")
        else:
            kept.append(line)
    return kept, references


def _is_valid_xml_codepoint(code: int) -> bool:
    return code in {0x09, 0x0A, 0x0D} or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


def _decode_entity(entity: str) -> str | None:
    if entity.startswith("&#x") or entity.startswith("&#X"):
        try:
            code = int(entity[3:-1], 16)
        except ValueError:
            return None
        return chr(code) if _is_valid_xml_codepoint(code) else None
    if entity.startswith("&#"):
        try:
            code = int(entity[2:-1], 10)
        except ValueError:
            return None
        return chr(code) if _is_valid_xml_codepoint(code) else None
    decoded = unescape(entity)
    return None if decoded == entity else decoded


def _append_xml_text(out: list[str], text: str) -> None:
    for char in text:
        code = ord(char)
        if not _is_valid_xml_codepoint(code):
            continue
        if char == "&":
            out.append("&amp;")
        elif char == "<":
            out.append("&lt;")
        elif char == ">":
            out.append("&gt;")
        elif char == '"':
            out.append("&quot;")
        else:
            out.append(char)


def _escape_xml_text(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "&":
            match = _ENTITY.match(text, index)
            if match:
                entity = match.group(0)
                decoded = _decode_entity(entity)
                if entity in _XML_ENTITIES:
                    out.append(entity)
                elif entity.startswith("&#") and decoded is not None:
                    out.append(entity)
                elif decoded is not None:
                    _append_xml_text(out, decoded)
                else:
                    out.append("&amp;")
                    _append_xml_text(out, entity[1:])
                index = match.end()
                continue
            out.append("&amp;")
            index += 1
            continue
        _append_xml_text(out, text[index])
        index += 1
    return "".join(out)


def _escape_attr(text: str) -> str:
    return _escape_xml_text(text).replace("\n", " ").replace("\t", " ")


def _basename(path: str) -> str:
    value = path.split("?")[0].split("#")[0].rstrip("/\\")
    if not value:
        return path
    return value.split("/")[-1].split("\\")[-1]


def _decode_attachment_name(path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    return re.sub(r"%([0-9A-Fa-f]{2})", replace, path)


def _cdata(text: str) -> str:
    return text.replace("]]>", "]]]]><![CDATA[>")


def _normalize_language(info: str) -> str:
    token = (info.strip().split() or [""])[0].lower()
    if not token:
        return ""
    return _LANGUAGE_ALIASES.get(token, token)


def _split_table_row(line: str) -> list[str]:
    trimmed = line.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(trimmed):
        char = trimmed[index]
        if char == "\\" and index + 1 < len(trimmed) and trimmed[index + 1] in {"|", "\\"}:
            current.append("|" if trimmed[index + 1] == "|" else "\\\\")  # `\|` is a pipe in the cell; `\\` stays as it is, for the reader of the inline text
            index += 2
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _table_alignments(line: str) -> list[str]:
    items = _split_table_row(line)
    result: list[str] = []
    for item in items:
        value = item.strip()
        left = value.startswith(":")
        right = value.endswith(":")
        if left and right:
            result.append("center")
        elif right:
            result.append("right")
        elif left:
            result.append("left")
        else:
            result.append("")
    return result


def _is_table_delimiter(line: str) -> bool:
    """A delimiter row of two cells or more: dashes with a colon at either end or at none, between pipes (the pipe at each end of the row is optional).
    The cells are cut apart and looked at one by one: a pattern for the whole row backtracks over every way to split the blanks of a long one."""
    row = line.strip(" \t")
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    cells = row.split("|")
    return len(cells) >= 2 and all(_TABLE_DELIM_CELL.fullmatch(cell.strip(" \t")) for cell in cells)


def _format_cell(tag: str, text: str, align: str) -> str:
    style = f' style="text-align: {align};"' if align else ""
    return f"<{tag}{style}>{_render_inline(text, {})}</{tag}>"


def _render_table(lines: list[str]) -> str:
    header = _split_table_row(lines[0])
    align = _table_alignments(lines[1])
    width = max(len(header), len(align), *(len(_split_table_row(row)) for row in lines[2:]) or [0])
    header += [""] * (width - len(header))
    align += [""] * (width - len(align))
    rows = ["<tr>" + "".join(_format_cell("th", header[index], align[index]) for index in range(width)) + "</tr>"]
    for row in lines[2:]:
        cells = _split_table_row(row)
        cells += [""] * (width - len(cells))
        rows.append("<tr>" + "".join(_format_cell("td", cells[index], align[index]) for index in range(width)) + "</tr>")
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def _apply_tokens(template: str, tokens: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return tokens[index] if index < len(tokens) else match.group(0)

    previous = None
    while previous != template:
        previous = template
        template = _TOKEN_RE.sub(replace, template)
    return template


def _normalize_code_span(content: str) -> str:
    content = content.replace("\n", " ")
    if len(content) >= 2 and content.startswith(" ") and content.endswith(" ") and content.strip(" ") != "":
        return content[1:-1]
    return content


def _decode_text_entities(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "&":
            match = _ENTITY.match(text, index)
            if match:
                decoded = _decode_entity(match.group(0))
                if decoded is not None:
                    result.append(decoded)
                    index = match.end()
                    continue
        result.append(text[index])
        index += 1
    return "".join(result)


def _canonical_destination(destination: str) -> str:
    value = _decode_text_entities(destination)
    value = value.replace("\t", "").replace("\n", "").replace("\r", "")
    return value.strip(" \x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x7f")


def _plain_inline_text(text: str, references: dict[str, tuple[str, str]]) -> str:
    rendered = _render_inline(text, references, allow_brackets=False, allow_autolink=False)
    rendered = re.sub(r"<br\s*/?>", " ", rendered)
    rendered = re.sub(r"<[^>]*>", "", rendered)
    rendered = rendered.replace("\ufff0", "").replace("\ufff1", "")
    return unescape(rendered)


def _count_preceding_backslashes(text: str, index: int) -> int:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count


def _trim_bare_url(value: str) -> str:
    value = value.rstrip("?!.,:*_~'\"")
    opened, closed = value.count("("), value.count(")")
    end = len(value)
    while end and value[end - 1] == ")" and opened < closed:  # counted once: a count for each parenthesis that goes is the square of the run of them
        end -= 1
        closed -= 1
    value = value[:end]
    if value.endswith(";") and re.search(r"&(?:#?[A-Za-z0-9]+);$", value):
        value = value[:-1]
    return value


def _render_inline(
    text: str,
    references: dict[str, tuple[str, str]],
    *,
    allow_brackets: bool = True,
    allow_autolink: bool = True,
) -> str:
    if not text:
        return ""
    text = _strip_illegal_xml(text)
    tokens: list[str] = []

    def protect(rendered: str) -> str:
        token = f"\ufff0C{len(tokens)}\ufff1"
        tokens.append(rendered)
        return token

    def replace_code(source: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(source):
            if source[index] != "`" or _count_preceding_backslashes(source, index) % 2 == 1:
                out.append(source[index])
                index += 1
                continue
            run = 1
            while index + run < len(source) and source[index + run] == "`":
                run += 1
            closing = source.find("`" * run, index + run)
            if closing < 0:
                out.append(source[index : index + run])
                index += run
                continue
            code = _normalize_code_span(source[index + run : closing])
            out.append(protect("<code>" + _escape_xml_text(code) + "</code>"))
            index = closing + run
        return "".join(out)

    def parse_destination(chunk: str) -> tuple[str, str]:
        body = chunk.replace("\r", "").replace("\n", "").strip()
        if not body:
            return "", ""
        if body.startswith("<"):
            escaped = False
            end = -1
            for position in range(1, len(body)):
                char = body[position]
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == ">":
                    end = position
                    break
            if end > 0:
                destination = body[1:end].replace("\\>", ">")
                rest = body[end + 1 :].strip()
                if not rest:
                    return destination, ""
                match = re.match(r'(["\'])(.*?)\1[ \t]*$', rest)
                if match:
                    return destination, match.group(2)
        if " " not in body and "\t" not in body:
            return body, ""
        match = re.match(r'(\S+)[ \t]+(["\'])(.*?)\2[ \t]*$', body)
        if match:
            return match.group(1), match.group(3)
        return body, ""

    def replace_brackets(source: str) -> str:
        if not allow_brackets:
            return source
        if "]" not in source and "<" not in source:
            return source
        if "(" in source and ")" not in source and "[" in source:
            return source
        out: list[str] = []
        index = 0
        while index < len(source):
            if source.startswith("![", index):
                end_text = source.find("]", index + 2, min(len(source), index + 2 + _INLINE_LOOKAHEAD))
                if end_text >= 0 and end_text + 1 < len(source) and source[end_text + 1] == "(":
                    end_link = -1
                    if end_text + 2 < len(source) and source[end_text + 2] == "<":
                        escaped = False
                        for cursor in range(end_text + 3, min(len(source), end_text + 3 + _INLINE_LOOKAHEAD)):
                            char = source[cursor]
                            if escaped:
                                escaped = False
                                continue
                            if char == "\\":
                                escaped = True
                                continue
                            if char == ">" and cursor + 1 < len(source) and source[cursor + 1] == ")":
                                end_link = cursor + 1
                                break
                    if end_link < 0:
                        end_link = _find_closing_paren(source, end_text + 1)
                    if end_link >= 0:
                        alt = source[index + 2 : end_text]
                        destination, _ = parse_destination(source[end_text + 2 : end_link])
                        out.append(protect(_render_image(alt, destination)))
                        index = end_link + 1
                        continue
                    out.append(source[index : end_text + 2])
                    index = end_text + 2
                    continue
            if source[index] == "[":
                end_text = source.find("]", index + 1, min(len(source), index + 1 + _INLINE_LOOKAHEAD))
                if end_text >= 0 and end_text + 1 < len(source) and source[end_text + 1] == "(":
                    end_link = -1
                    if end_text + 2 < len(source) and source[end_text + 2] == "<":
                        escaped = False
                        for cursor in range(end_text + 3, min(len(source), end_text + 3 + _INLINE_LOOKAHEAD)):
                            char = source[cursor]
                            if escaped:
                                escaped = False
                                continue
                            if char == "\\":
                                escaped = True
                                continue
                            if char == ">" and cursor + 1 < len(source) and source[cursor + 1] == ")":
                                end_link = cursor + 1
                                break
                    if end_link < 0:
                        end_link = _find_closing_paren(source, end_text + 1)
                    if end_link >= 0:
                        label = source[index + 1 : end_text]
                        destination, title = parse_destination(source[end_text + 2 : end_link])
                        out.append(protect(_render_link(label, destination, title, references)))
                        index = end_link + 1
                        continue
                    out.append(source[index : end_text + 2])
                    index = end_text + 2
                    continue
                if end_text >= 0 and end_text + 1 < len(source) and source[end_text + 1] == "[":
                    end_ref = source.find("]", end_text + 2, min(len(source), end_text + 2 + _INLINE_LOOKAHEAD))
                    if end_ref >= 0:
                        label = source[index + 1 : end_text]
                        key = source[end_text + 2 : end_ref].strip().lower()
                        if key in references:
                            destination, title = references[key]
                            out.append(protect(_render_link(label, destination, title, references)))
                            index = end_ref + 1
                            continue
                    out.append(source[index : end_text + 2])
                    index = end_text + 2
                    continue
            auto = _AUTOLINK.match(source, index)
            if auto:
                raw_html = _RAW_HTML.match(source, index)
                if raw_html and not (":" in auto.group(1) or auto.group(1).startswith(("//", "#", "./", "../"))):
                    out.append(source[index])
                    index += 1
                    continue
                url = _canonical_destination(auto.group(1))
                if url and _is_safe_destination(url) and (
                    _URL_SCHEME.match(url) or url.startswith(("//", "#", "/", "./", "../"))
                ):
                    out.append(protect(f'<a href="{_escape_attr(url)}">{_escape_xml_text(url)}</a>'))
                    index = auto.end()
                    continue
                if url and (_URL_SCHEME.match(url) or url.startswith(("//", "#", "./", "../"))):
                    out.append(protect(_escape_xml_text(url)))
                    index = auto.end()
                    continue
            out.append(source[index])
            index += 1
        return "".join(out)

    def replace_escapes(source: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(source):
            if source[index] == "\\" and index + 1 < len(source) and source[index + 1] in _BACKSLASH:
                if source[index + 1] == "\\":
                    out.append("\\")
                else:
                    out.append(protect(_escape_xml_text(source[index + 1])))
                index += 2
                continue
            out.append(source[index])
            index += 1
        return "".join(out)

    def replace_html(source: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(source):
            if source[index] == "\\" and index + 1 < len(source) and source[index + 1] in _BACKSLASH:
                out.append(_escape_xml_text(source[index + 1]))
                index += 2
                continue
            if source[index] == "<":
                if source.find(">", index + 1, min(len(source), index + 1 + 256)) < 0:
                    out.append("&lt;")
                    index += 1
                    continue
                match = _RAW_HTML.match(source, index)
                if match:
                    tag = match.group(0).lower().replace(" ", "")
                    if tag in {"<br>", "<br/>", "<br />"}:
                        out.append(protect("<br />"))
                    else:
                        out.append(_escape_xml_text(match.group(0)))
                    index = match.end()
                    continue
            if source[index] == "&":
                entity = _ENTITY.match(source, index)
                if entity:
                    token = entity.group(0)
                    decoded = _decode_entity(token)
                    if token in _XML_ENTITIES:
                        out.append(token)
                    elif decoded is not None:
                        out.append(_escape_xml_text(decoded))
                    else:
                        out.append("&amp;" + _escape_xml_text(token[1:]))
                    index = entity.end()
                    continue
                out.append("&amp;")
                index += 1
                continue
            # the guard comes before the match: a match runs to the next blank, and a text of `(http://(http://...` would be matched to its end from every `http://`
            if allow_autolink and (index == 0 or source[index - 1] not in "\"'=("):
                url = _BARE_URL.match(source, index)
                value = _trim_bare_url(url.group(0)) if url else ""
                if value:
                    out.append(protect(f'<a href="{_escape_attr(value)}">{_escape_xml_text(value)}</a>'))
                    index += len(value)
                    continue
            out.append(_escape_xml_text(source[index]))
            index += 1
        return "".join(out)

    text = replace_code(text)
    text = replace_escapes(text)
    text = replace_brackets(text)
    text = replace_html(text)
    text = _render_emphasis(text)
    return _apply_tokens(text, tokens)


def _find_closing_paren(text: str, start: int) -> int:
    depth = 0
    stop = min(len(text), start + _INLINE_LOOKAHEAD)
    for index in range(start, stop):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _is_safe_destination(destination: str) -> bool:
    """A link or an image may lead to a web or mail address, a phone number, a page of the site or an anchor, but not to
    a script or a data address. Browsers ignore white space inside a scheme, so it is ignored here too."""
    scheme = _URL_SCHEME.match(destination)
    return scheme is None or scheme.group(0)[:-1].lower() in _SAFE_SCHEMES


def _render_link(label: str, destination: str, title: str, references: dict[str, tuple[str, str]]) -> str:
    if not destination:
        return _escape_xml_text("[" + label + "]")
    body = _render_inline(label, references, allow_autolink=False)
    canonical = _canonical_destination(destination)
    if not canonical or "\ufff0" in canonical or "\ufff1" in canonical:
        return body
    if not _is_safe_destination(canonical):
        return body  # the text stays, the link goes
    title_attr = f' title="{_escape_attr(title)}"' if title and "\ufff0" not in title and "\ufff1" not in title else ""
    return f'<a href="{_escape_attr(canonical)}"{title_attr}>{body}</a>'


def _render_image(alt: str, source: str) -> str:
    if not source:
        return _escape_xml_text("![" + alt + "]")
    alt_text = _plain_inline_text(alt, {})
    alt_attr = f' ac:alt="{_escape_attr(alt_text)}"' if alt_text else ""
    canonical = _canonical_destination(source)
    if not canonical or "\ufff0" in canonical or "\ufff1" in canonical:
        return _escape_xml_text(alt_text)
    if not _is_safe_destination(canonical):
        return _escape_xml_text(alt_text)  # the alternative text stays, the picture goes
    if canonical.startswith("//") or _URL_SCHEME.match(canonical):
        return f'<ac:image{alt_attr}><ri:url ri:value="{_escape_attr(canonical)}" /></ac:image>'
    name = _decode_attachment_name(_basename(canonical))
    return f'<ac:image{alt_attr}><ri:attachment ri:filename="{_escape_attr(name)}" /></ac:image>'


def _render_emphasis(text: str) -> str:
    marker_tags = {
        "***": ("<strong><em>", "</em></strong>"),
        "___": ("<strong><em>", "</em></strong>"),
        "**": ("<strong>", "</strong>"),
        "__": ("<strong>", "</strong>"),
        "*": ("<em>", "</em>"),
        "_": ("<em>", "</em>"),
        "~~": ('<span style="text-decoration: line-through;">', "</span>"),
    }
    output: list[str] = []
    stack: list[tuple[str, int]] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] == "\ufff0":
            end = text.find("\ufff1", index)
            if end >= 0:
                output.append(text[index : end + 1])
                index = end + 1
                continue
        if text.startswith("~~", index):
            marker = "~~"
            if stack and stack[-1][0] == marker:
                opener, position = stack.pop()
                output[position] = marker_tags[opener][0]
                output.append(marker_tags[opener][1])
            else:
                stack.append((marker, len(output)))
                output.append(marker)
            index += 2
            continue
        if text[index] in "*_":
            char = text[index]
            run = 1
            while index + run < length and text[index + run] == char and run < 3:
                run += 1
            consumed = 0
            while consumed < run:
                size = 3 if run - consumed >= 3 else 2 if run - consumed >= 2 else 1
                marker = char * size
                if marker == "_" and 0 < index < length - 1 and text[index - 1].isalnum() and text[index + 1].isalnum():
                    output.append("_")
                    consumed += 1
                    index += 1
                    continue
                if stack and stack[-1][0] == marker:
                    opener, position = stack.pop()
                    output[position] = marker_tags[opener][0]
                    output.append(marker_tags[opener][1])
                else:
                    stack.append((marker, len(output)))
                    output.append(marker)
                consumed += size
                index += size
            continue
        output.append(text[index])
        index += 1
    return "".join(output)


def _atx(line: str) -> tuple[int, str] | None:
    """The level and the title of an ATX heading line (`## Title ##`; the closing hashes and the blanks around the title are cut off), or None. The end of
    the line is cut by hand: a pattern for it backtracks over every way to share a long run of blanks between its parts."""
    start = _ATX_START.match(line)
    if start is None:
        return None
    rest = line[start.end() :]
    if not rest:
        return (len(start.group(1)), "") if len(start.group(2)) >= 2 else None  # a title needs a character, and the blanks after the `#` are all there is to give
    return len(start.group(1)), rest.rstrip(" \t").rstrip("#").rstrip(" \t") or rest[0]


def _fence(line: str) -> tuple[str, str] | None:
    """The fence and the info string of a line that opens a fenced code block (three backticks or tildes or more, and an info string without a backtick), or
    None. The info string is looked at outside the pattern: the blanks in front of it could be part of it, and a pattern for both backtracks over every way to
    share them."""
    start = _FENCE_START.match(line)
    if start is None:
        return None
    info = line[start.end() :]
    return None if "`" in info else (start.group(1), info)


class _MarkdownParser:
    def __init__(self, lines: list[str], references: dict[str, tuple[str, str]], *, depth: int = 0) -> None:
        if depth > _MAX_NESTING:
            raise ValidationError("nested too deeply to convert", hint="Simplify the nesting: the Markdown is nested too deeply to convert.")
        self.lines = lines
        self.references = references
        self.task_ids = count(1)
        self.depth = depth

    def parse_blocks(self, start: int, base_indent: int) -> tuple[list[str], int]:
        blocks: list[str] = []
        index = start
        while index < len(self.lines):
            line = self.lines[index]
            if not line.strip():
                index += 1
                continue
            indent = self._indent(line)
            if indent < base_indent:
                break
            stripped = line[indent:]
            fence = _fence(stripped)
            if fence:
                rendered, index = self._fenced_code(index, fence[0], len(fence[0]), fence[1])
                blocks.append(rendered)
                continue
            heading = _atx(stripped)
            if heading:
                level = heading[0]
                blocks.append(f"<h{level}>{_render_inline(heading[1].strip(), self.references)}</h{level}>")
                index += 1
                continue
            if index + 1 < len(self.lines) and self.lines[index + 1].strip():
                next_line = self.lines[index + 1]
                if self._indent(next_line) >= base_indent:
                    test = next_line[self._indent(next_line) :]
                    if _SETEXT_1.match(test):
                        blocks.append(f"<h1>{_render_inline(stripped.strip(), self.references)}</h1>")
                        index += 2
                        continue
                    if _SETEXT_2.match(test):
                        blocks.append(f"<h2>{_render_inline(stripped.strip(), self.references)}</h2>")
                        index += 2
                        continue
            if _HR.match(stripped):
                blocks.append("<hr />")
                index += 1
                continue
            if self._is_table(index, base_indent):
                rendered, index = self._table(index, base_indent)
                blocks.append(rendered)
                continue
            if stripped.startswith(">"):
                rendered, index = self._blockquote(index, base_indent)
                blocks.append(rendered)
                continue
            if self._list_match(line, base_indent):
                rendered, index = self._list(index, base_indent)
                blocks.append(rendered)
                continue
            if self._is_indented_code(line, base_indent):
                rendered, index = self._indented_code(index, base_indent)
                blocks.append(rendered)
                continue
            rendered, index = self._paragraph(index, base_indent)
            blocks.append(rendered)
        return blocks, index

    def _indent(self, line: str) -> int:
        count = 0
        for char in line:
            if char == " ":
                count += 1
            elif char == "\t":
                count += 4 - (count % 4)
            else:
                break
        return count

    def _list_match(self, line: str, base_indent: int) -> re.Match[str] | None:
        match = _LIST_MARKER.match(line)
        if not match:
            return None
        indent = self._indent(match.group(1))
        return match if indent >= base_indent else None

    def _is_indented_code(self, line: str, base_indent: int) -> bool:
        indent = self._indent(line)
        if indent < base_indent:
            return False
        if line.lstrip(" ").startswith("\t"):
            return True
        return indent - base_indent >= 4

    def _is_table(self, index: int, base_indent: int) -> bool:
        if index + 1 >= len(self.lines):
            return False
        line = self.lines[index]
        next_line = self.lines[index + 1]
        if self._indent(line) != base_indent or self._indent(next_line) != base_indent:
            return False
        stripped = line[base_indent:]
        if "|" not in stripped:
            return False
        delimiter = next_line[base_indent:]
        if _is_table_delimiter(delimiter):
            return True
        # One column, as `conflu page` writes a table of one column: a pipe on each side of both rows tells it from a rule and from a line that has a pipe in it.
        header = stripped.strip()
        return bool(_TABLE_DELIM_ONE.match(delimiter)) and len(header) > 1 and header.startswith("|") and header.endswith("|") and len(_split_table_row(header)) == 1

    def _table(self, index: int, base_indent: int) -> tuple[str, int]:
        rows = [self.lines[index][base_indent:], self.lines[index + 1][base_indent:]]
        index += 2
        while index < len(self.lines):
            line = self.lines[index]
            if not line.strip() or self._indent(line) != base_indent or "|" not in line[base_indent:]:
                break
            rows.append(line[base_indent:])
            index += 1
        return _render_table(rows), index

    def _fenced_code(self, index: int, fence_char: str, length: int, info: str) -> tuple[str, int]:
        opening_line = self.lines[index]
        opening_prefix = opening_line[: len(opening_line) - len(opening_line.lstrip(" \t"))]
        index += 1
        body: list[str] = []
        char = fence_char[0]
        closed = False
        while index < len(self.lines):
            line = self.lines[index]
            stripped = line.lstrip(" \t")
            token = stripped.split()[0] if stripped.split() else stripped
            if token and token[0] == char and len(token) >= length and all(item == char for item in token):
                index += 1
                closed = True
                break
            body.append(line[len(opening_prefix) :] if opening_prefix and line.startswith(opening_prefix) else line)
            index += 1
        if not closed:
            while body and body[-1] == "":
                body.pop()
        language = _normalize_language(info)
        parameter = f'<ac:parameter ac:name="language">{_escape_xml_text(language)}</ac:parameter>' if language else ""
        macro = '<ac:structured-macro ac:name="code" ac:schema-version="1">'
        macro += parameter
        macro += "<ac:plain-text-body><![CDATA[" + _cdata("\n".join(body)) + "]]></ac:plain-text-body></ac:structured-macro>"
        return macro, index

    def _indented_code(self, index: int, base_indent: int) -> tuple[str, int]:
        body: list[str] = []
        while index < len(self.lines):
            line = self.lines[index]
            if not line.strip():
                body.append("")
                index += 1
                continue
            indent = self._indent(line)
            if indent < base_indent + 4 and not line.startswith("\t"):
                break
            trim = 1 if line.startswith("\t") else base_indent + 4
            body.append(line[trim:])
            index += 1
        if index >= len(self.lines):
            while body and body[-1] == "":
                body.pop()
        macro = '<ac:structured-macro ac:name="code" ac:schema-version="1">'
        macro += "<ac:plain-text-body><![CDATA[" + _cdata("\n".join(body)) + "]]></ac:plain-text-body></ac:structured-macro>"
        return macro, index

    def _blockquote(self, index: int, base_indent: int) -> tuple[str, int]:
        quote_lines: list[str] = []
        blank_before = False
        while index < len(self.lines):
            line = self.lines[index]
            if not line.strip():
                probe = index + 1
                while probe < len(self.lines) and not self.lines[probe].strip():
                    probe += 1
                if quote_lines and probe < len(self.lines):
                    next_line = self.lines[probe]
                    next_stripped = next_line[self._indent(next_line) :] if self._indent(next_line) >= base_indent else ""
                    if next_stripped.startswith(">"):
                        break
                quote_lines.extend([""] * (probe - index))  # the whole run at once: every blank line of it looks at the same next line, and one by one that is the square of the run
                blank_before = True
                index = probe
                continue
            if self._indent(line) < base_indent:
                break
            stripped = line[self._indent(line) :]
            if stripped.startswith(">"):
                quote = stripped[1:]
                if quote.startswith(" "):
                    quote = quote[1:]
                quote_lines.append(quote)
                blank_before = False
                index += 1
                continue
            if blank_before:
                break
            quote_lines.append(stripped)
            index += 1
        body, _ = _MarkdownParser(quote_lines, self.references, depth=self.depth + 1)._alert_or_blocks()
        return body, index

    def _alert_or_blocks(self) -> tuple[str, int]:
        cleaned = list(self.lines)
        first = ""
        first_index = -1
        for idx, line in enumerate(cleaned):
            if line.strip():
                first = line.strip()
                first_index = idx
                break
        match = re.match(r"^\[!([A-Za-z]+)\](?:[ \t]+(.*))?$", first, re.IGNORECASE)
        blocks, _ = self.parse_blocks(0, 0)
        if not match or match.group(1).lower() not in _ALERTS:
            return "<blockquote>" + "\n".join(blocks) + "</blockquote>", 0
        rest = match.group(2) or ""
        cleaned[first_index] = rest
        body = _MarkdownParser(cleaned, self.references, depth=self.depth + 1)
        inner, _ = body.parse_blocks(0, 0)
        return (
            f'<ac:structured-macro ac:name="{_ALERTS[match.group(1).lower()]}" ac:schema-version="1"><ac:rich-text-body>'
            + "\n".join(inner)
            + "</ac:rich-text-body></ac:structured-macro>",
            0,
        )

    def _list(self, index: int, base_indent: int) -> tuple[str, int]:
        first = self._list_match(self.lines[index], base_indent)
        if not first:
            return self._paragraph(index, base_indent)
        start_indent = self._indent(first.group(1))
        ordered = bool(_ORDERED.match(first.group(2)))
        start_value = int(first.group(2)[:-1]) if ordered else 1
        items: list[dict[str, object]] = []
        while index < len(self.lines):
            match = self._list_match(self.lines[index], base_indent)
            if not match or self._indent(match.group(1)) != start_indent or bool(_ORDERED.match(match.group(2))) != ordered:
                break
            marker_end = start_indent + len(match.group(2)) + 1
            content_indent = marker_end + (len(self.lines[index]) - len(self.lines[index].lstrip(" \t")) - start_indent)
            first_text = match.group(3) or ""
            index += 1
            body = [first_text]
            saw_blank = False
            while index < len(self.lines):
                candidate = self.lines[index]
                if not candidate.strip():
                    probe = index
                    while probe < len(self.lines) and not self.lines[probe].strip():
                        probe += 1
                    if probe >= len(self.lines):
                        index = probe
                        break
                    next_line = self.lines[probe]
                    sibling = self._list_match(next_line, base_indent)
                    if sibling and self._indent(sibling.group(1)) == start_indent and bool(_ORDERED.match(sibling.group(2))) == ordered:
                        index = probe
                        break
                    if self._indent(next_line) <= start_indent and not next_line.lstrip().startswith(">"):
                        index = probe
                        break
                    body.append("")
                    saw_blank = True
                    index = probe
                    continue
                sibling = self._list_match(candidate, base_indent)
                if sibling and self._indent(sibling.group(1)) == start_indent and bool(_ORDERED.match(sibling.group(2))) == ordered:
                    break
                if self._indent(candidate) <= start_indent and not candidate.lstrip().startswith(">"):
                    break
                stripped = self._strip_indent(candidate, max(start_indent + 2, min(content_indent, self._indent(candidate))))
                body.append(stripped)
                index += 1
            items.append({"body": body, "blank": saw_blank, "ordered": ordered, "start": start_value})
        if items and all(self._task_item_payload(item) is not None for item in items):
            return self._task_list(items), index
        tag = "ol" if ordered else "ul"
        attr = f' start="{start_value}"' if ordered and start_value != 1 else ""
        rendered_items = [self._render_list_item(item) for item in items]
        return f"<{tag}{attr}>" + "".join(rendered_items) + f"</{tag}>", index

    def _strip_indent(self, line: str, indent: int) -> str:
        width = 0
        for index, char in enumerate(line):
            if width >= indent:
                return line[index:]
            if char == " ":
                width += 1
            elif char == "\t":
                width += 4 - (width % 4)
            else:
                return line[index:]
        return ""

    def _task_state(self, line: str) -> str | None:
        match = re.match(r"^\[( |x|X)\][ \t]*(.*)$", line)
        if not match:
            return None
        return "complete" if match.group(1).lower() == "x" else "incomplete"

    def _task_item_payload(self, item: dict[str, object]) -> tuple[str, str] | None:
        line = str(item["body"][0])
        match = re.match(r"^\[( |x|X)\][ \t]*(.*)$", line)
        if not match:
            return None
        continuation = [match.group(2)] + [str(part) for part in list(item["body"])[1:]]
        blocks, _ = _MarkdownParser(continuation, self.references, depth=self.depth + 1).parse_blocks(0, 0)
        if len(blocks) != 1 or not blocks[0].startswith("<p>") or not blocks[0].endswith("</p>"):
            return None
        body = blocks[0][3:-4].replace("\n", " ")
        status = "complete" if match.group(1).lower() == "x" else "incomplete"
        return status, body

    def _task_list(self, items: list[dict[str, object]]) -> str:
        tasks: list[str] = []
        for item in items:
            payload = self._task_item_payload(item)
            if payload is None:
                continue
            status, body = payload
            tasks.append(
                "<ac:task>"
                f"<ac:task-id>{next(self.task_ids)}</ac:task-id>"
                f"<ac:task-status>{status}</ac:task-status>"
                f"<ac:task-body>{body}</ac:task-body>"
                "</ac:task>"
            )
        return "<ac:task-list>" + "".join(tasks) + "</ac:task-list>"

    def _render_list_item(self, item: dict[str, object]) -> str:
        body_lines = list(item["body"])
        blocks, _ = _MarkdownParser(body_lines, self.references, depth=self.depth + 1).parse_blocks(0, 0)
        tight = not item["blank"] and len(blocks) == 1 and blocks[0].startswith("<p>") and blocks[0].endswith("</p>")
        if tight:
            return "<li>" + blocks[0][3:-4] + "</li>"
        return "<li>" + "".join(blocks) + "</li>"

    def _paragraph(self, index: int, base_indent: int) -> tuple[str, int]:
        lines: list[str] = []
        while index < len(self.lines):
            line = self.lines[index]
            if not line.strip():
                break
            indent = self._indent(line)
            if indent < base_indent:
                break
            stripped = line[indent:]
            if lines and (
                _atx(stripped)
                or _HR.match(stripped)
                or _fence(stripped)
                or stripped.startswith(">")
                or self._list_match(line, base_indent)
                or self._is_table(index, base_indent)
            ):
                break
            lines.append(self._strip_indent(line, base_indent))
            index += 1
        parts: list[str] = []
        for line_index, line in enumerate(lines):
            trailing_backslashes = len(line) - len(line.rstrip("\\"))
            hard_break = line.endswith("  ") or trailing_backslashes % 2 == 1
            text = line[:-2] if line.endswith("  ") else line[:-1] if trailing_backslashes % 2 == 1 else line
            parts.append(text)
            if hard_break:
                parts.append("<br />")
            elif line_index + 1 < len(lines):
                parts.append("\n")
        body = _render_inline("".join(parts), self.references)
        return f"<p>{body}</p>", index
