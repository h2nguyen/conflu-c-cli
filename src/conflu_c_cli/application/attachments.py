"""Use cases around attachments: list, download, upload."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Sequence

from ..domain.errors import NotFoundError, UnavailableError, UsageError, ValidationError
from ..domain.model import Attachment, is_attachment_id, parse_page_id
from ..domain.naming import safe_file_name
from .paging import PAGE_SIZE, fetch_all
from .ports import ConfluenceGateway, Files


@dataclass
class AttachmentList:
    page_id: str
    attachments: list[Attachment]
    next_cursor: str = ""


class ListAttachments:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, *, name: str = "", limit: int = 50, cursor: str = "", fetch_everything: bool = False) -> AttachmentList:
        page_id = parse_page_id(ref)

        def read(next_cursor: str):
            return self._gateway.list_attachments(page_id, filename=name, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        if fetch_everything:
            items, _ = fetch_all(read)
            return AttachmentList(page_id, items)
        chunk = read(cursor)
        return AttachmentList(page_id, chunk.items, chunk.cursor)


@dataclass
class Download:
    attachment: Attachment
    path: str
    action: str  # downloaded | would download
    size: int = 0


class DownloadAttachments:
    def __init__(self, gateway: ConfluenceGateway, files: Files) -> None:
        self._gateway = gateway
        self._files = files

    def _select(self, target: str, names: Sequence[str], everything: bool) -> list[Attachment]:
        if is_attachment_id(target):
            return [self._gateway.get_attachment(target.strip())]
        page_id = parse_page_id(target)
        if everything:
            found, _ = fetch_all(lambda cursor: self._gateway.list_attachments(page_id, limit=PAGE_SIZE, cursor=cursor))
            if not found:
                raise NotFoundError(f"Page {page_id} has no attachments.")
            return found
        if not names:
            raise UsageError("Name the attachment to download.", hint="Use --name FILE (more than once for several) or --all; `conflu attachments PAGE` lists them.")
        chosen: list[Attachment] = []
        for name in names:
            matches = self._gateway.list_attachments(page_id, filename=name, limit=PAGE_SIZE).items
            exact = [item for item in matches if item.title == name]
            if not exact:
                raise NotFoundError(f"Page {page_id} has no attachment named {name}.", hint="`conflu attachments PAGE` lists the names.")
            chosen.append(exact[0])
        return chosen

    def execute(
        self,
        target: str,
        *,
        names: Sequence[str] = (),
        everything: bool = False,
        out_dir: str = ".",
        force: bool = False,
        dry_run: bool = False,
    ) -> list[Download]:
        plan = []
        taken: dict[str, Attachment] = {}
        for item in self._select(target, names, everything):
            name = safe_file_name(item.title)
            # Windows and macOS keep one file for names that differ only in case or in how an accent is spelled, and a
            # name made safe can equal another one: the later download would silently replace the earlier.
            key = unicodedata.normalize("NFC", name).casefold()
            earlier = taken.get(key)
            if earlier is not None and earlier.id == item.id:
                continue  # the same attachment asked for twice
            if earlier is not None:
                raise ValidationError(
                    f"{earlier.title} and {item.title} would be saved as the same file ({name}); nothing was downloaded.",
                    hint="Download them one at a time with --name, each into its own --out folder.",
                    details={"attachments": [earlier.id, item.id], "file": name},
                )
            taken[key] = item
            plan.append((item, self._files.join(out_dir, name)))
        clashes = [path for _, path in plan if self._files.exists(path)]
        if clashes and not force:
            raise ValidationError(f"{clashes[0]} exists already.", hint="Use --force to overwrite, or --out to choose another folder.")
        done: list[Download] = []
        for item, path in plan:
            if dry_run:
                done.append(Download(item, path, "would download", item.size))
                continue
            data = self._gateway.download_attachment(item)
            if item.size and len(data) != item.size:
                raise UnavailableError(
                    f"{item.title} arrived incomplete ({len(data)} of {item.size} bytes); nothing was written for it.",
                    hint="Try again.",
                )
            self._files.write_bytes(path, data)
            done.append(Download(item, path, "downloaded", len(data)))
        return done


@dataclass
class Upload:
    path: str
    name: str
    size: int
    attachment: Attachment | None = None
    action: str = "uploaded"  # uploaded | would upload


@dataclass
class UploadResult:
    page_id: str
    uploads: list[Upload]
    dry_run: bool


class UploadAttachments:
    def __init__(self, gateway: ConfluenceGateway, files: Files) -> None:
        self._gateway = gateway
        self._files = files

    def execute(self, ref: str, paths: Sequence[str], *, comment: str = "", minor: bool = False, dry_run: bool = False) -> UploadResult:
        page_id = parse_page_id(ref)
        if not paths:
            raise UsageError("No file to upload.", hint="Pass one or more files.")
        plan = []
        for path in paths:
            if not self._files.exists(path) or self._files.is_dir(path):
                raise ValidationError(f"Not a file: {path}")
            name = self._files.name(path)
            if not name.strip():
                raise ValidationError(f"The file has no name: {path}")
            plan.append(Upload(path, name, self._files.size(path), None, "would upload" if dry_run else "uploaded"))
        if dry_run:
            self._gateway.get_page(page_id, with_body=False)  # proves that the page exists
            return UploadResult(page_id, plan, True)
        for upload in plan:
            upload.attachment = self._gateway.upload_attachment(
                page_id, upload.name, self._files.read_bytes(upload.path), comment=comment, minor=minor
            )
        return UploadResult(page_id, plan, False)
