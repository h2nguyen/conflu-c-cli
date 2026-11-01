"""Word, Excel and PowerPoint files made by hand, for the tests of what is read from an attachment: small archives of XML parts.

Nothing here is a real document of anyone: the texts are made up, and the builders write only what the reader of `domain/ooxml.py` looks at.
"""
from __future__ import annotations

import io
import zipfile

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
P = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def zipped(parts: dict, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def docx(body: str) -> bytes:
    return zipped({"word/document.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{body}</w:body></w:document>'})


def para(text: str, style: str = "", numbered: int | None = None) -> str:
    properties = ""
    if style:
        properties += f'<w:pStyle w:val="{style}"/>'
    if numbered is not None:
        properties += f'<w:numPr><w:ilvl w:val="{numbered}"/><w:numId w:val="1"/></w:numPr>'
    return f"<w:p><w:pPr>{properties}</w:pPr><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def sheet(rows: str) -> str:
    return f"<worksheet {S}><sheetData>{rows}</sheetData></worksheet>"


def workbook(sheets: dict, strings: list | None = None, with_workbook_rels: bool = True) -> bytes:
    names = list(sheets)
    parts = {
        "xl/workbook.xml": f"<workbook {S}><sheets>" + "".join(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>' for n, name in enumerate(names, 1)) + "</sheets></workbook>"
    }
    if with_workbook_rels:
        parts["xl/_rels/workbook.xml.rels"] = f"<Relationships {RELS}>" + "".join(
            f'<Relationship Id="rId{n}" Type="{REL}worksheet" Target="{"/xl/" if n % 2 == 0 else ""}worksheets/sheet{n}.xml"/>' for n in range(1, len(names) + 1)
        ) + "</Relationships>"
    for n, name in enumerate(names, 1):
        parts[f"xl/worksheets/sheet{n}.xml"] = sheets[name]
    if strings is not None:
        parts["xl/sharedStrings.xml"] = f"<sst {S}>" + "".join(strings) + "</sst>"
    return zipped(parts)


def shape(text: str, placeholder: str = "") -> str:
    ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
    return f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:txBody><a:bodyPr/>{text}</p:txBody></p:sp>'


def line(text: str, level: int | None = None) -> str:
    properties = f'<a:pPr lvl="{level}"/>' if level is not None else ""
    return f"<a:p>{properties}<a:r><a:rPr/><a:t>{text}</a:t></a:r></a:p>"


def slide(content: str) -> str:
    return f"<p:sld {P}><p:cSld><p:spTree>{content}</p:spTree></p:cSld></p:sld>"


def a_deck() -> bytes:
    """A presentation of two slides, the first with a title, a list, a group, a table and a notes page."""
    cell = lambda text: f"<a:tc><p:txBody>{line(text)}</p:txBody></a:tc>"  # noqa: E731
    table = f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl><a:tr>{cell('c1')}{cell('c2')}</a:tr><a:tr><a:tc/></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
    first = slide(shape(line("Slide title"), "title") + shape(line("point") + line("sub point", 1)) + "<p:grpSp>" + shape(line("grouped")) + "</p:grpSp>" + table)
    second = slide(shape(line("Second"), "ctrTitle"))
    notes = slide(shape("", "sldImg") + shape(line("Say hello."), "body") + shape(line("7"), "sldNum"))
    return zipped(
        {
            "ppt/presentation.xml": f'<p:presentation {P}><p:sldIdLst><p:sldId id="257" r:id="rId2"/><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Type="{REL}slide" Target="slides/slide1.xml"/><Relationship Id="rId2" Type="{REL}slide" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": first,
            "ppt/slides/slide2.xml": second,
            "ppt/slides/_rels/slide1.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Type="{REL}notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>',
            "ppt/notesSlides/notesSlide1.xml": notes,
        }
    )


def a_specification() -> bytes:
    """A Word document with two headings, a list, a table and an e-mail address in its text."""
    table = "<w:tbl><w:tr><w:tc>" + para("Owner") + "</w:tc><w:tc>" + para("Release Team") + "</w:tc></w:tr></w:tbl>"
    return docx(
        para("Specification", "Heading1")
        + para("The scope is small. Questions go to alex@example.com.")
        + para("Goals", "Heading2")
        + para("faster", numbered=0)
        + para("simpler", numbered=0)
        + table
    )


def a_budget() -> bytes:
    """A workbook of two sheets with shared strings, a number and an inline string."""
    first = sheet(
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1200</v></c></row>'
        '<row r="3"><c r="A3" t="inlineStr"><is><t>Travel</t></is></c><c r="B3"><v>450.5</v></c></row>'
    )
    second = sheet('<row r="1"><c r="A1" t="inlineStr"><is><t>Totals are on the first sheet.</t></is></c></row>')
    return workbook({"Plan": first, "Notes": second}, ["<si><t>Item</t></si>", "<si><t>Amount</t></si>", "<si><t>Hardware</t></si>"])
