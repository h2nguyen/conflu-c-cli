"""The attachments that the in-memory Confluence and the mock Confluence start with, in one place so that a test against either finds the same
files (ids `att5101` and up belong to this area; `att5001` and `att5002` of page 2002 are older and stay as they are).

    page 2004 ("ADR 0001")                                       blog post 7102 ("Weekly update", a fixture of the blog posts)
    att5101 plan.txt        text, three versions, two labels     att5111 agenda.txt   text, two versions
    att5102 spec.docx       a Word document with an address      att5112 minutes.md   Markdown
    att5103 budget.xlsx     a workbook of two sheets
    att5104 deck.pptx       a presentation with notes
    att5105 contacts.csv    text with an address
    att5106 broken.docx     named like a document, and none

Page 2002 keeps the two files it always had, and page 2003 none: other tests count on both.
"""
from __future__ import annotations

from dataclasses import dataclass

from .office_files import a_budget, a_deck, a_specification

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
PAGE = "2004"
BLOGPOST = "7102"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@dataclass(frozen=True)
class Edition:
    """One version of a file."""

    data: bytes
    message: str = ""
    minor: bool = False
    created: str = ""


@dataclass(frozen=True)
class Fixture:
    id: str
    container: str
    name: str
    media_type: str
    editions: tuple[Edition, ...]
    labels: tuple[str, ...] = ()
    comment: str = ""


PLAN = (
    Edition(b"Release plan\n\nFirst draft.\n", "First draft", False, "2026-10-05T09:00:00.000Z"),
    Edition(b"Release plan\n\nSecond draft.\n\nQuestions go to alex@example.com.\n", "Added the contact", False, "2026-10-07T09:30:00.000Z"),
    Edition(b"Release plan\n\nFinal version.\n\nTasks:\n- build\n- test\n- ship\n", "", True, "2026-10-09T14:00:00.000Z"),
)
AGENDA = (
    Edition(b"Agenda draft\n", "Draft", False, "2026-10-13T08:00:00.000Z"),
    Edition(b"Agenda\n\n1. Welcome\n2. Release status\n", "Added the items", False, "2026-10-14T08:00:00.000Z"),
)

FIXTURES = (
    Fixture("att5101", PAGE, "plan.txt", "text/plain", PLAN, ("draft", "plan"), "The plan for the October release"),
    Fixture("att5102", PAGE, "spec.docx", DOCX, (Edition(a_specification(), "", False, "2026-10-06T10:00:00.000Z"),)),
    Fixture("att5103", PAGE, "budget.xlsx", XLSX, (Edition(a_budget(), "", False, "2026-10-06T10:05:00.000Z"),)),
    Fixture("att5104", PAGE, "deck.pptx", PPTX, (Edition(a_deck(), "", False, "2026-10-06T10:10:00.000Z"),)),
    Fixture("att5105", PAGE, "contacts.csv", "text/csv", (Edition(b"name,email\nRelease Team,alex@example.com\n", "", False, "2026-10-06T10:15:00.000Z"),)),
    Fixture("att5106", PAGE, "broken.docx", DOCX, (Edition(b"this is no document", "", False, "2026-10-06T10:20:00.000Z"),)),
    Fixture("att5111", BLOGPOST, "agenda.txt", "text/plain", AGENDA),
    Fixture("att5112", BLOGPOST, "minutes.md", "text/markdown", (Edition(b"# Minutes\n\nDecisions were made.\n", "", False, "2026-10-14T09:00:00.000Z"),)),
)
