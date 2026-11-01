"""Use cases around attachments: list them, show one with its versions and labels, save them, read them as text, attach files."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from ..domain.attachguards import SCAN_LIMIT, SCAN_PIECE, check_replaced_version, check_unchanged_since, holds_secret, secret_needles
from ..domain.attachmenttext import (
    DEFAULT_MAX_CHARS,
    KIND_OTHER,
    Reading,
    cut_text,
    human_size,
    printable,
    reading_of,
    redact_people,
    text_of,
)
from ..domain.content import describe, kind_named, parse_content_id
from ..domain.errors import AuthError, ConfluCliError, NotFoundError, UnavailableError, UnreadableDocument, UsageError, ValidationError
from ..domain.model import Attachment, Chunk, Label, VersionInfo, is_attachment_id, parse_page_id
from ..domain.naming import safe_file_name
from ..domain.privacy import has_redaction_marker, hide_version, redact_address, redact_text
from ..domain.timeutil import parse_guard_time
from .containers import not_a_page
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all, name_users, named
from .ports import ConfluenceGateway, Diagnostics, Files
from .ports_attachments import ComparesPlaces, ReadsPieces
from .services import Services
from .settings import Settings

TEXT_MAX_BYTES = 25 * 1024 * 1024  # what `--text` reads of one file unless told otherwise: the file and its text are held in memory
SIZE_LOOKUPS = 50  # the versions of an attachment whose size is asked for, one request each (the list of versions has no size)
LISTING_CALLS = 10  # the calls that read the attachments of a page, to find the ones that several files would replace, before the missing names are asked for by themselves
LONG_PATH = 230  # characters of a path from which a failed write says so: Windows refuses 260, and the file is written under a temporary name first
_NAMED = 12  # file names that a message lists before "and N more"


def _named(names: Sequence[str]) -> str:
    shown = ", ".join(printable(name) for name in names[:_NAMED])
    return shown + (f" and {len(names) - _NAMED} more" if len(names) > _NAMED else "")


def _lacks_permission(error: ConfluCliError) -> bool:
    """A refusal for want of permission or scope (HTTP 403): the one failure of a read that does not say that the upload would fail too (a token that
    may write attachments and not read them). A 401 says that the credentials are wrong, and everything else that the server is not there."""
    return isinstance(error, AuthError) and error.details.get("status") == 403


def _same_place(files: Files, first: str, second: str) -> bool:
    """Whether two paths lead to the same file or folder, as far as the file system can say; else whether they are spelled alike."""
    return files.same_place(first, second) if isinstance(files, ComparesPlaces) else first == second


def _folder_of(files: Files, path: str) -> str:
    """The folder of a path, with the separator at its end (`Files` knows the last name of a path, which is what is cut off)."""
    return path[: len(path) - len(files.name(path))]


def _title(item: Attachment, with_users: bool) -> str:
    """What an attachment is called, as it is printed and as its file is named: the name can hold an e-mail address (it is data that somebody typed),
    so it is redacted unless people are shown. The attachment is still looked for, and asked for, by its real name and its id."""
    return item.title if with_users else redact_text(item.title)


def _label(item: Attachment, with_users: bool) -> str:
    """`_title` for a message, made fit for a terminal."""
    return printable(_title(item, with_users))


def _shown(item: Attachment, with_users: bool) -> Attachment:
    """The attachment as it may be printed: its name and its comment can hold an e-mail address, and the download address ends in the name, so
    they are redacted unless people are shown. The type is text that the uploader chose."""
    if with_users:
        return item
    return replace(
        item,
        title=redact_text(item.title),
        comment=redact_text(item.comment),
        media_type=redact_text(item.media_type),
        download_link=redact_address(item.download_link),
    )


def _check_max_bytes(max_bytes: int) -> None:
    if max_bytes < 0:  # 0 is no limit of its own
        raise UsageError("--max-bytes must be a number greater than 0.", hint="Example: --max-bytes 10000000")


def _refuse_large(items: Sequence[Attachment], limit: int, *, from_default: bool = False, with_users: bool = False) -> None:
    """A file over the limit is refused by what Confluence says of its size, before anything is fetched; all of them are named."""
    large = [item for item in items if limit and item.size > limit]
    if not large:
        return
    listed = _named([_title(item, with_users) for item in large]) if len(large) > 1 else f"{_label(large[0], with_users)} ({human_size(large[0].size)})"
    verb = "is" if len(large) == 1 else "are"
    over = f"the limit of {human_size(limit)} that --text reads" if from_default else f"--max-bytes {limit} ({human_size(limit)})"
    raise ValidationError(
        f"{listed} {verb} larger than {over}; nothing was fetched.",
        hint="Raise --max-bytes, or choose the other files by id or --name." + (" `conflu download` saves a file without reading it." if from_default else ""),
        details={"attachments": [{"attachmentId": item.id, "size": item.size} for item in large], "maxBytes": limit},
    )


def _not_a_holder(content_id: str, kind: str | None, error: NotFoundError) -> NotFoundError:
    """The error for an id that is neither a page nor a blog post: the same, with a hint that says what the id is and which command shows it."""
    if kind is None or kind == "page":
        return error  # unknown, or a page that this account cannot read: the first answer stands
    known = kind_named(kind)
    use = f" `conflu {known.command} {content_id}` shows it." if known is not None and known.command else ""
    return NotFoundError(
        error.message,
        hint=f"{content_id} is {describe(kind)}, not a page or a blog post: only those hold attachments.{use}",
        details={**error.details, "type": kind},
    )


class Holder:
    """The page or the blog post whose files are listed. A page is asked for first, which is one request and nothing else for the common case;
    only when Confluence says that there is no such page does the id get a second look: `content_types` says whether it is a blog post."""

    def __init__(self, gateway: ConfluenceGateway, content_id: str) -> None:
        self._gateway = gateway
        self.id = content_id
        self.kind = ""  # page or blogpost, once it is known

    @property
    def noun(self) -> str:
        return "Blog post" if self.kind == "blogpost" else "Page"

    def read(self, *, filename: str = "", limit: int = PAGE_SIZE, cursor: str = "") -> Chunk[Attachment]:
        if self.kind != "blogpost":
            try:
                chunk = self._gateway.list_attachments(self.id, filename=filename, limit=limit, cursor=cursor)
            except NotFoundError as error:
                if self.kind == "page":
                    raise  # it was a page a moment ago
                self._find_out(error)
            else:
                self.kind = "page"
                return chunk
        return self._gateway.list_blogpost_attachments(self.id, filename=filename, limit=limit, cursor=cursor)

    def _find_out(self, error: NotFoundError) -> None:
        try:
            kind = self._gateway.content_types([self.id]).get(self.id)
        except ConfluCliError:
            raise error from None
        if kind != "blogpost":
            raise _not_a_holder(self.id, kind, error)  # the first answer, or the same with a hint that says what the id is
        self.kind = "blogpost"


def _choose(
    gateway: ConfluenceGateway, target: str, names: Sequence[str], everything: bool, version: int, with_users: bool = False
) -> list[Attachment]:
    """The attachments that a command means: one by its id, or those of a page or a blog post by name or all of them. With a version, exactly one,
    as it was in that version (its size and its number are those of the version)."""
    if version:
        if version < 1:
            raise UsageError("--version must be a number of 1 or more.", hint="`conflu attachment ID --versions` lists the versions of an attachment.")
        if everything or len(names) > 1:
            raise UsageError(
                "--version needs exactly one attachment.", hint="Choose it by its id or with one --name: --all and several names ask for several files."
            )
    if is_attachment_id(target):
        if everything or names:
            raise UsageError(
                f"{target.strip()} is an attachment: --name and --all choose among the attachments of a page.",
                hint="Leave them out, or pass the page or the blog post instead of the attachment.",
            )
        chosen = [gateway.get_attachment(target.strip())]
    else:
        chosen = _of_holder(Holder(gateway, parse_content_id(target)), names, everything)
    return [_as_of(gateway, chosen[0], version, with_users)] if version else chosen


def _of_holder(holder: Holder, names: Sequence[str], everything: bool) -> list[Attachment]:
    if everything:
        found, _ = fetch_all(lambda cursor: holder.read(cursor=cursor))
        if not found:
            raise NotFoundError(f"{holder.noun} {holder.id} has no attachments.")
        return found
    if not names:
        raise UsageError(
            "Name the attachment to download.", hint="Use --name FILE (more than once for several) or --all; `conflu attachments PAGE` lists them."
        )
    chosen: list[Attachment] = []
    for name in names:
        exact = [item for item in holder.read(filename=name).items if item.title == name]  # by the real name: a redacted one is nobody's name
        if not exact:
            hint = "`conflu attachments PAGE` lists the names."
            if has_redaction_marker(name):
                hint = "That is how a name with an e-mail address in it is shown, not the name. Choose the file by its id (`conflu attachments PAGE` lists them)."
            raise NotFoundError(f"{holder.noun} {holder.id} has no attachment named {printable(name)}.", hint=hint)
        chosen.append(exact[0])
    return chosen


def _as_of(gateway: ConfluenceGateway, item: Attachment, version: int, with_users: bool = False) -> Attachment:
    """The attachment as it was in that version; NotFoundError, with where to look, when it has none."""
    hint = f"The attachment is at version {item.version}: `conflu attachment {item.id} --versions` lists the versions it has."
    details = {"attachmentId": item.id, "version": version, "currentVersion": item.version}
    if version > item.version:
        raise NotFoundError(f"{_label(item, with_users)} ({item.id}) has no version {version}.", hint=hint, details=details)
    try:
        return gateway.get_attachment_version(item.id, version)
    except NotFoundError as error:
        raise NotFoundError(f"{_label(item, with_users)} ({item.id}) has no version {version}.", hint=hint, details={**error.details, **details}) from error


# -- list ---------------------------------------------------------------------------------------


@dataclass
class AttachmentList:
    page_id: str  # the page that was asked for; empty for a blog post
    attachments: list[Attachment]
    next_cursor: str = ""
    blog_post_id: str = ""  # the blog post that was asked for; empty for a page


class ListAttachments:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings | None = None) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self, ref: str, *, name: str = "", limit: int = 50, cursor: str = "", fetch_everything: bool = False, with_users: bool = False
    ) -> AttachmentList:
        if is_attachment_id(ref):
            raise ValidationError(
                f"{ref.strip()} is an attachment, not a page or a blog post.",
                hint=f"`conflu attachment {ref.strip()}` shows one attachment; `conflu attachments PAGE` lists the attachments of a page.",
            )
        if self._settings is not None:
            ensure_users_allowed(with_users, self._settings)
        holder = Holder(self._gateway, parse_content_id(ref))

        def read(next_cursor: str) -> Chunk[Attachment]:
            return holder.read(filename=name, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        if fetch_everything:
            items, _ = fetch_all(read)
            chunk = Chunk(items, "")
        else:
            chunk = read(cursor)
        shown = [_shown(item, with_users) for item in chunk.items]
        if holder.kind == "blogpost":
            return AttachmentList("", shown, chunk.cursor, holder.id)
        return AttachmentList(holder.id, shown, chunk.cursor)


# -- one attachment -----------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionRow:
    version: VersionInfo
    size: int | None  # the answer that lists the versions has no size: it is asked for, and None when it was not


@dataclass
class AttachmentView:
    attachment: Attachment
    versions: list[VersionRow] | None = None  # when they were asked for
    labels: list[Label] | None = None
    next_cursor: str = ""  # of the versions
    users_shown: bool = False
    sizes_left_out: int = 0  # the versions that were listed and whose size was not asked for (`SIZE_LOOKUPS`)


class ShowAttachment:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(
        self,
        ref: str,
        *,
        versions: bool = False,
        labels: bool = False,
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
        with_users: bool = False,
    ) -> AttachmentView:
        attachment_id = (ref or "").strip()
        if not is_attachment_id(attachment_id):
            raise ValidationError(
                f"Not an attachment id: {printable(attachment_id) or '<missing>'}",
                hint="An attachment id looks like att123456; `conflu attachments PAGE` lists those of a page.",
            )
        ensure_users_allowed(with_users, self._settings)
        item = self._gateway.get_attachment(attachment_id)
        view = AttachmentView(_shown(item, with_users), users_shown=with_users)
        if versions:
            self._add_versions(view, item, limit, cursor, fetch_everything)
        if labels:
            found, _ = fetch_all(lambda next_cursor: self._gateway.list_attachment_labels(attachment_id, limit=PAGE_SIZE, cursor=next_cursor))
            view.labels = found
        return view

    def _add_versions(self, view: AttachmentView, item: Attachment, limit: int, cursor: str, fetch_everything: bool) -> None:
        def read(next_cursor: str) -> Chunk[VersionInfo]:
            return self._gateway.list_attachment_versions(item.id, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        if fetch_everything:
            listed, _ = fetch_all(read)
            view.next_cursor = ""
        else:
            chunk = read(cursor)
            listed, view.next_cursor = chunk.items, chunk.cursor
        if view.users_shown:
            known = name_users(self._gateway, self._diagnostics, [version.author for version in listed])
            listed = [replace(version, author=named(version.author, known)) for version in listed]
        else:
            listed = [hide_version(version) for version in listed]  # type: ignore[misc]
        rows, asked = [], 0
        for version in listed:
            size: int | None = None
            if version.number == item.version:
                size = item.size
            elif asked < SIZE_LOOKUPS:
                asked += 1
                try:
                    size = self._gateway.get_attachment_version(item.id, version.number).size
                except NotFoundError:
                    size = None  # a version that the list names and that cannot be read: the size stays unknown
            else:
                view.sizes_left_out += 1
            rows.append(VersionRow(version, size))
        view.versions = rows


# -- save ---------------------------------------------------------------------------------------


@dataclass
class Download:
    attachment: Attachment  # as it may be printed (`_shown`): the name is the one the file was saved under, before it was made safe
    path: str
    action: str  # downloaded | would download
    size: int = 0


class DownloadAttachments:
    """Saves attachments as files in a folder: under names that are safe (the name as it is printed, so one that holds an e-mail address is saved
    redacted unless people are shown), never over a file that is there without `force` (not even one that appears while the download runs), and
    never into the folder that holds the configuration of the CLI, which holds the token. What is known before the first request (a file over
    `max_bytes`, a file that is there) stops the run before it fetches anything. A run that is stopped after it wrote files says which."""

    def __init__(
        self,
        gateway: ConfluenceGateway,
        files: Files,
        settings: Settings | None = None,
        *,
        protected: Sequence[str] = (),
    ) -> None:
        self._gateway = gateway
        self._files = files
        self._settings = settings
        self._protected = tuple(path for path in protected if path)

    def execute(
        self,
        target: str,
        *,
        names: Sequence[str] = (),
        everything: bool = False,
        out_dir: str = ".",
        force: bool = False,
        dry_run: bool = False,
        version: int = 0,
        max_bytes: int = 0,
        with_users: bool = False,
    ) -> list[Download]:
        if self._settings is not None:
            ensure_users_allowed(with_users, self._settings)  # saving shows no people, but the option is refused under the policy everywhere
        _check_max_bytes(max_bytes)
        if not out_dir.strip():  # given and empty (`--out "$FOLDER"` with a variable that is not set): the current folder is `.`, never "left out"
            raise UsageError("The output folder is empty.", hint="Pass the folder with --out, or leave --out out to save into the current folder.")
        self._refuse_own_folder(out_dir)  # first: a refused folder costs no request
        chosen = _choose(self._gateway, target, names, everything, version, with_users)
        _refuse_large(chosen, max_bytes, with_users=with_users)
        plan = self._plan(chosen, out_dir, with_users)
        self._refuse_folders(plan, out_dir)
        clashes = [path for _, path in plan if self._files.exists(path)]
        if clashes and not force:
            raise ValidationError(f"{printable(clashes[0])} exists already.", hint="Use --force to overwrite, or --out to choose another folder.")
        if dry_run:
            return [Download(_shown(item, with_users), path, "would download", item.size) for item, path in plan]
        done: list[Download] = []
        for item, path in plan:
            try:
                done.append(self._save(item, path, force, max_bytes, out_dir, version, with_users))
            except ConfluCliError as error:
                if not done:
                    raise
                raise self._interrupted(error, item, done, len(plan), out_dir) from error
            except Exception as error:  # noqa: BLE001 - what no adapter foresaw (a hostile answer) must not hide the files that were written either
                if not done:
                    raise
                stopped = UnavailableError(
                    f"The download of {_label(item, with_users)} stopped with an unexpected {type(error).__name__}.", hint="Try again."
                )
                raise self._interrupted(stopped, item, done, len(plan), out_dir) from error
        return done

    def _plan(self, chosen: Sequence[Attachment], out_dir: str, with_users: bool) -> list[tuple[Attachment, str]]:
        plan: list[tuple[Attachment, str]] = []
        taken: dict[str, Attachment] = {}
        for item in chosen:
            name = safe_file_name(_title(item, with_users))  # as printed: what is printed as the name of the file is the name of the file
            # Windows and macOS keep one file for names that differ only in case or in how an accent is spelled, and a
            # name made safe can equal another one: the later download would silently replace the earlier.
            key = unicodedata.normalize("NFC", name).casefold()
            earlier = taken.get(key)
            if earlier is not None and earlier.id == item.id:
                continue  # the same attachment asked for twice
            if earlier is not None:
                raise ValidationError(
                    f"{_label(earlier, with_users)} and {_label(item, with_users)} would be saved as the same file ({printable(name)}); nothing was downloaded.",
                    hint=self._clash_hint(earlier, item, with_users),
                    details={"attachments": [earlier.id, item.id], "file": name},
                )
            taken[key] = item
            plan.append((item, self._files.join(out_dir, name)))
        return plan

    def _clash_hint(self, earlier: Attachment, item: Attachment, with_users: bool) -> str:
        if with_users or (redact_text(earlier.title) == earlier.title and redact_text(item.title) == item.title):
            return "Download them one at a time with --name, each into its own --out folder."
        own = "" if self._settings is not None and self._settings.hide_users else ", or add --with-users to save them under their own names"
        return f"Their names are redacted, which made them alike. Download them one at a time by id, each into its own --out folder{own}."

    def _refuse_own_folder(self, out_dir: str) -> None:
        """No file is written into the folder that holds the configuration of the CLI, the configuration itself included: an attachment named like
        it would replace the token and the address that it is sent to, or make a configuration that sends it elsewhere. The places are compared,
        not the spellings, so a relative path, a link or another case of the same name is caught too (a folder below it is no risk)."""
        for path in self._protected:
            if _same_place(self._files, out_dir, _folder_of(self._files, path)):
                raise UsageError(
                    f"{printable(out_dir)} is the folder where the CLI keeps its own configuration, which holds the token: an attachment could replace it.",
                    hint="Choose another folder with --out. This is refused with --force too, and in a dry run.",
                )

    def _refuse_folders(self, plan: Sequence[tuple[Attachment, str]], out_dir: str) -> None:
        if self._files.exists(out_dir) and not self._files.is_dir(out_dir):
            raise ValidationError(f"{printable(out_dir)} is a file, not a folder.", hint="Choose another folder with --out.")
        blocked = [self._files.name(path) for _, path in plan if self._files.is_dir(path)]
        if blocked:
            what = f"{printable(blocked[0])} is a folder" if len(blocked) == 1 else f"{len(blocked)} of the names ({_named(blocked)}) are folders"
            raise ValidationError(
                f"{what} in {printable(out_dir)}, where a file would be written.",
                hint="Nothing was written. Remove or rename the folder, or choose another folder with --out; --force does not replace a folder.",
            )

    def _save(self, item: Attachment, path: str, force: bool, max_bytes: int, out_dir: str, version: int, with_users: bool) -> Download:
        data = self._gateway.fetch_attachment(item, version, max_bytes)
        if max_bytes and len(data) > max_bytes:  # for an adapter that does not stop at the limit itself
            raise ValidationError(
                f"{_label(item, with_users)} is {human_size(len(data))}, more than --max-bytes {max_bytes}; nothing was written for it.",
                hint="Raise --max-bytes, or choose the other files by id or --name.",
                details={"attachmentId": item.id, "size": len(data), "maxBytes": max_bytes},
            )
        if item.size and len(data) != item.size:
            raise UnavailableError(
                f"{_label(item, with_users)} arrived incomplete ({len(data)} of {item.size} bytes); nothing was written for it.",
                hint="Try again.",
            )
        if not force and self._files.exists(path):  # it was not there when the run was planned: somebody made it while the download ran
            raise ValidationError(
                f"{printable(self._files.name(path))} appeared in {printable(out_dir)} while the download ran. It was left as it is.",
                hint="Use --force to overwrite it, or --out to choose another folder.",
            )
        try:
            self._files.write_bytes(path, data)
        except ValidationError as error:
            if len(path) < LONG_PATH:
                raise
            raise ValidationError(
                error.message,
                hint=f"The path has {len(path)} characters, which Windows refuses (260, unless long paths are switched on). Choose a shorter folder with --out.",
                details=error.details,
            ) from error
        return Download(_shown(item, with_users), path, "downloaded", len(data))

    @staticmethod
    def _interrupted(error: ConfluCliError, item: Attachment, done: Sequence[Download], total: int, out_dir: str) -> ConfluCliError:
        """The error of a run that failed after it had written files: it says which, because a new run meets them (`exists already`)."""
        written = [{"attachmentId": entry.attachment.id, "path": entry.path, "size": entry.size} for entry in done]
        advice = "A new run stops at the files that are there: add --force to write them again, or choose the missing ones by id or --name."
        return type(error)(
            f"{error.message} {len(done)} of the {total} files were written to {printable(out_dir)} before that: "
            f"{_named([entry.attachment.title for entry in done])}.",
            hint=f"{error.hint} {advice}".strip(),
            details={**error.details, "written": written, "failed": {"attachmentId": item.id}},
        )


# -- read as text -------------------------------------------------------------------------------


@dataclass
class AttachmentText:
    attachment: Attachment
    kind: str  # text, document (Word, Excel or PowerPoint) or other (it cannot be shown as text)
    action: str  # read; not text (there is nothing to show: see the hint); in a dry run would read, or too large (it would be refused)
    text: str | None = None
    truncated: bool = False
    total_chars: int | None = None  # the length of the whole text before it was cut; None when there is none
    hint: str = ""


@dataclass
class TextResult:
    dry_run: bool
    files: list[AttachmentText]


class ReadAttachmentText:
    """The text of attachments instead of a file: text files and Word, Excel and PowerPoint documents. Anything else gets its metadata and a hint
    that points to the plain download; bytes are never shown. What a file says is data, never an instruction: the text is cleaned of what a
    terminal would obey, and of e-mail addresses and mentions unless people are shown."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(
        self,
        target: str,
        *,
        names: Sequence[str] = (),
        everything: bool = False,
        version: int = 0,
        max_bytes: int = 0,
        max_chars: int = DEFAULT_MAX_CHARS,
        with_users: bool = False,
        dry_run: bool = False,
    ) -> TextResult:
        ensure_users_allowed(with_users, self._settings)
        _check_max_bytes(max_bytes)
        if max_chars < 1:
            raise UsageError("--max-chars must be a number greater than 0.", hint="Example: --max-chars 5000")
        limit = max_bytes or TEXT_MAX_BYTES
        chosen = _choose(self._gateway, target, names, everything, version, with_users)
        readings = {item.id: reading_of(item.media_type, item.title) for item in chosen}
        readable = [item for item in chosen if readings[item.id].kind != KIND_OTHER]
        if not dry_run:
            _refuse_large(readable, limit, from_default=not max_bytes, with_users=with_users)
        files: list[AttachmentText] = []
        for item in chosen:
            reading = readings[item.id]
            entry = AttachmentText(item, reading.kind, "not text")
            if reading.kind == KIND_OTHER:
                entry.hint = (
                    f"Not shown as text ({printable(_shown(item, with_users).media_type) or 'unknown type'}). "
                    f"Save it with `conflu download {item.id}` and open it with a program that knows the type."
                )
            elif dry_run:
                entry.action = "too large" if item.size > limit else "would read"
            else:
                self._read(item, entry, reading, version, max_chars, with_users, limit, from_default=not max_bytes)
            files.append(entry)
        return TextResult(dry_run, [replace(entry, attachment=_shown(entry.attachment, with_users)) for entry in files])

    def _read(
        self, item: Attachment, entry: AttachmentText, reading: Reading, version: int, max_chars: int, with_users: bool, limit: int, *, from_default: bool
    ) -> None:
        data = self._gateway.fetch_attachment(item, version, limit)
        if len(data) > limit:
            # What Confluence says of the size is a claim, and `_refuse_large` went by it: what arrived counts, and nothing of it is decoded.
            over = f"the limit of {human_size(limit)} that --text reads" if from_default else f"--max-bytes {limit} ({human_size(limit)})"
            raise ValidationError(
                f"{_label(item, with_users)} arrived with {human_size(len(data))}, more than {over}; nothing was read from it.",
                hint="Raise --max-bytes, or choose the other files by id or --name." + (" `conflu download` saves a file without reading it." if from_default else ""),
                details={"attachmentId": item.id, "size": len(data), "maxBytes": limit},
            )
        save = f"Save the file with `conflu download {item.id}` instead."
        try:
            text = text_of(data, reading)
        except UnreadableDocument as error:
            entry.hint = f"{error.message} {save}"
            return
        except Exception as error:  # noqa: BLE001 - one file that breaks the reader must not stop the others (`--all`); the class says enough
            self._diagnostics.debug(f"{_label(item, with_users)}: the reader failed with {type(error).__name__}")
            entry.hint = f"The content could not be read ({type(error).__name__}). {save}"
            return
        entry.action = "read"
        text = printable(text)  # an escape sequence in a file must not reach the terminal of the person who reads the answer
        if not with_users:
            text = redact_people(text)  # before the cut, so that an address cannot be cut in half and slip through
        entry.total_chars = len(text)
        entry.text, entry.truncated = cut_text(text, max_chars)
        if not text.strip():
            entry.hint = "The file holds no text."


# -- attach -------------------------------------------------------------------------------------


@dataclass
class Upload:
    path: str
    name: str
    size: int
    attachment: Attachment | None = None
    action: str = "uploaded"  # uploaded | would upload
    replaces: Attachment | None = None  # the attachment of that name that the file becomes a new version of, as it was read before
    checked: bool = True  # False: the attachments of the page could not be read, so what the file replaces is not known (`replaces` is None, and means nothing)


@dataclass
class UploadResult:
    page_id: str
    uploads: list[Upload]
    dry_run: bool
    comment: str = ""
    minor: bool = False


class UploadAttachments:
    """Attaches files to a page. What is checked, in this order and before the first request that changes anything, in a dry run too: the files
    (they are there, are no folders and have a name), that none of them is the configuration of the CLI or holds its token (an attachment can be
    opened by everyone who can see the page and cannot be taken back), that the page exists, and the conflict guards for the attachments that a
    file would give a new version. A guard that is given empty is an error (`None` is no guard). A run that is stopped after it uploaded files
    says which: they are on the page, and the same command run again would give each of them another version."""

    def __init__(
        self,
        gateway: ConfluenceGateway,
        files: Files,
        settings: Settings | None = None,
        *,
        protected: Sequence[str] = (),
        diagnostics: Diagnostics | None = None,
    ) -> None:
        self._gateway = gateway
        self._files = files
        self._diagnostics = diagnostics
        self._protected = tuple(path for path in protected if path)
        self._needles = secret_needles(settings.api_token, settings.email) if settings is not None else ()

    def execute(
        self,
        ref: str,
        paths: Sequence[str],
        *,
        comment: str = "",
        minor: bool = False,
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
    ) -> UploadResult:
        page_id = parse_page_id(ref)
        if not paths:
            raise UsageError("No file to upload.", hint="Pass one or more files.")
        if if_version is not None:
            if if_version < 0:
                raise UsageError("--if-version must be 0 or more.", hint="0 says that the file is new: that the page has no attachment of that name.")
            if len(paths) != 1:
                raise UsageError("--if-version names the version of one attachment, so it needs exactly one file.", hint="Attach the files one at a time.")
        if if_unchanged_since is not None:
            parse_guard_time(if_unchanged_since)  # an empty value is an error naming the option, never "no guard": refused before anything is looked at, in a dry run too
        plan = self._plan(paths)
        self._refuse_own_files(plan)
        self._refuse_secrets(plan)
        guarded = if_version is not None or if_unchanged_since is not None
        existing = self._existing(page_id, plan, required=guarded, dry_run=dry_run)
        for upload in plan:
            upload.checked = existing is not None
            upload.replaces = existing[upload.name] if existing is not None else None
            self._guard(upload, if_version, if_unchanged_since)
        if dry_run:
            for upload in plan:
                upload.action = "would upload"
            return UploadResult(page_id, plan, True, comment, minor)
        done: list[Upload] = []
        for position, upload in enumerate(plan):
            try:
                if position and (if_version is not None or if_unchanged_since is not None):
                    # What was read for this file may be old by now, after the files before it were sent: a guard is looked at again just before its file goes.
                    upload.replaces = self._lookup(page_id, upload.name)
                    self._guard(upload, if_version, if_unchanged_since)
                data = self._files.read_bytes(upload.path)
                if holds_secret([data], self._needles):  # what is sent is what was looked at, also when the file changed meanwhile
                    raise self._token_error(upload.path, after_uploads=bool(done))
                upload.attachment = self._gateway.upload_attachment(page_id, upload.name, data, comment=comment, minor=minor)
            except ConfluCliError as error:
                if not done:
                    raise
                raise self._interrupted(error, upload, done, plan, page_id) from error
            except Exception as error:  # noqa: BLE001 - what no adapter foresaw (a hostile answer) must not hide the files that were uploaded either
                if not done:
                    raise
                stopped = UnavailableError(f"The upload of {printable(upload.name)} stopped with an unexpected {type(error).__name__}.")
                raise self._interrupted(stopped, upload, done, plan, page_id) from error
            done.append(upload)
        return UploadResult(page_id, plan, False, comment, minor)

    @staticmethod
    def _interrupted(error: ConfluCliError, upload: Upload, done: Sequence[Upload], plan: Sequence[Upload], page_id: str) -> ConfluCliError:
        """The error of a run that failed after it had uploaded files: it says which. They are on the page already, and the same command run
        again would give each of them another version."""
        uploaded = []
        for entry in done:
            attachment = entry.attachment
            uploaded.append(
                {
                    "path": entry.path,
                    "name": entry.name,
                    "size": entry.size,
                    "attachmentId": attachment.id if attachment is not None else None,
                    "version": attachment.version if attachment is not None else None,
                }
            )
        left = [entry.name for entry in plan[len(done) :]]  # the one that failed, and those behind it
        advice = (
            f"The files that were uploaded are on the page: do not run the same command as it is, it would give each of them another version. "
            f"`conflu attachments {page_id}` shows what the page has now (the file that failed may have arrived); attach the files that are left: {_named(left)}."
        )
        return type(error)(
            f"{error.message} {len(done)} of the {len(plan)} files were uploaded to page {page_id} before that: {_named([entry.name for entry in done])}.",
            hint=f"{error.hint} {advice}".strip(),
            details={**error.details, "uploaded": uploaded, "failed": {"path": upload.path, "name": upload.name}},
        )

    @staticmethod
    def _guard(upload: Upload, if_version: int | None, if_unchanged_since: str | None) -> None:
        if if_version is not None:
            check_replaced_version(upload.replaces, upload.name, if_version)
        if if_unchanged_since is not None:
            check_unchanged_since(upload.replaces, upload.name, if_unchanged_since)

    def _plan(self, paths: Sequence[str]) -> list[Upload]:
        plan: list[Upload] = []
        taken: dict[str, str] = {}
        for path in paths:
            if not self._files.exists(path) or self._files.is_dir(path):
                raise ValidationError(f"Not a file: {printable(path)}")
            name = self._files.name(path)
            if not name.strip():
                raise ValidationError(f"The file has no name: {printable(path)}")
            earlier = taken.get(name.casefold())
            if earlier is not None:
                raise ValidationError(
                    f"{printable(earlier)} and {printable(path)} are both called {printable(name)}: the second would only become a new version of the first.",
                    hint="Nothing was sent. Attach them one at a time, or rename one of them.",
                )
            taken[name.casefold()] = path
            plan.append(Upload(path, name, self._files.size(path)))
        return plan

    def _refuse_own_files(self, plan: Sequence[Upload]) -> None:
        """The configuration of the CLI is never attached: it holds the token. The places are compared, not the spellings: a link to it, a
        relative path, `..` or another case of its name is caught too."""
        for config in self._protected:
            if not self._files.exists(config):
                continue
            for upload in plan:
                if _same_place(self._files, upload.path, config):
                    raise UsageError(
                        f"{printable(upload.path)} is the configuration file of this CLI. It holds the API token and is never attached.",
                        hint="Nothing was sent. Everyone who can see the page can open an attachment, and it cannot be taken back.",
                    )

    def _refuse_secrets(self, plan: Sequence[Upload]) -> None:
        """No file that holds the token is attached: a copy of the settings, a shell history, a log with the headers of a request. The bytes are
        looked at, piece by piece where the file system can do that, so a file of any size is searched without being held; a file that is too
        large to be searched is refused, because it cannot be known to be free of the token."""
        if not self._needles:
            return
        for upload in plan:
            if upload.size > SCAN_LIMIT:
                raise ValidationError(
                    f"{printable(upload.path)} is {human_size(upload.size)}, more than the {human_size(SCAN_LIMIT)} that are searched for the API token "
                    "before a file is attached; a file that is not searched is not attached.",
                    hint="Nothing was sent. Attach a smaller file, or attach this one in the browser.",
                )
            if holds_secret(self._pieces(upload.path), self._needles):
                raise self._token_error(upload.path)

    def _pieces(self, path: str) -> Iterable[bytes]:
        return self._files.read_pieces(path, SCAN_PIECE) if isinstance(self._files, ReadsPieces) else [self._files.read_bytes(path)]

    @staticmethod
    def _token_error(path: str, *, after_uploads: bool = False) -> UsageError:
        sent = "This file was not sent." if after_uploads else "Nothing was sent."  # a file that changed while earlier ones were uploaded is the one case
        return UsageError(
            f"{printable(path)} holds the API token of this CLI. It would be published to everyone who can see the page.",
            hint=f"{sent} Attach a file without the token (a copy of the settings, a shell history or a log with the headers of a request "
            "is where it usually is), and replace the token if it was sent anywhere: `conflu setup-token`.",
        )

    def _existing(self, page_id: str, plan: Sequence[Upload], *, required: bool, dry_run: bool) -> dict[str, Attachment | None] | None:
        """The attachment of the page that each file would give a new version, None for a file that is new; None as a whole when the attachments of the
        page could not be read and nothing depends on them. One read serves all the files (a list of the page, or one call with the name when there is
        one file), not one read for each, and it also proves that the page exists (a blog post is no page). A guard needs what was read, so then a
        failure stops the command. Without a guard only a refusal for want of permission (HTTP 403: a token that may write attachments and not read
        them) lets the files go on, and the answer says that it does not know which of them replace a file; any other failure (the server is down, the
        credentials are wrong, a proxy answered) is what the upload would meet too, in a dry run as well as in a real one."""
        names = list(dict.fromkeys(upload.name for upload in plan))
        try:
            found = self._read_named(page_id, names)
        except NotFoundError as error:
            raise not_a_page(self._gateway, page_id, error) from error
        except ConfluCliError as error:
            if required or not _lacks_permission(error):
                raise
            if self._diagnostics is not None:
                what = "the files would be sent" if dry_run else "the files are sent anyway"
                self._diagnostics.warn(
                    f"Could not read the attachments of page {page_id} ({error.message}): {what} without looking for a file of the same name to replace, "
                    "so it is not known which of them become new versions."
                )
            return None
        return {upload.name: found.get(upload.name) for upload in plan}

    def _read_named(self, page_id: str, names: Sequence[str]) -> dict[str, Attachment]:
        """The attachments of the page with these names. One file: one call with its name. Several: the list of the page, until every name is found
        or the list ends, for at most `LISTING_CALLS` calls; a name that is still missing after that is asked for by itself, so that the answer is right
        on a page with thousands of attachments too."""
        if len(names) == 1:
            found = self._lookup(page_id, names[0])
            return {names[0]: found} if found is not None else {}
        wanted = set(names)
        found_items: dict[str, Attachment] = {}
        cursor = ""
        for _ in range(LISTING_CALLS):
            chunk = self._gateway.list_attachments(page_id, limit=PAGE_SIZE, cursor=cursor)
            for item in chunk.items:
                if item.title in wanted and item.title not in found_items:
                    found_items[item.title] = item
            if wanted <= found_items.keys() or not chunk.cursor or not chunk.items:
                return found_items
            cursor = chunk.cursor
        for name in names:  # in the order of the files, whatever the hash seed of this run
            if name in found_items:
                continue
            item = self._lookup(page_id, name)
            if item is not None:
                found_items[name] = item
        return found_items

    def _lookup(self, page_id: str, name: str) -> Attachment | None:
        items = self._gateway.list_attachments(page_id, filename=name, limit=PAGE_SIZE).items  # a 404 is explained once, by `_existing`
        return next((item for item in items if item.title == name), None)


# -- the area -----------------------------------------------------------------------------------


@dataclass
class AttachmentsUseCases:
    """The use cases of the area, reached as `app.attachments.<name>`; the commands use these, which know where the CLI keeps its settings."""

    list_attachments: ListAttachments
    show: ShowAttachment
    download: DownloadAttachments
    read_text: ReadAttachmentText
    upload: UploadAttachments


def build(services: Services) -> AttachmentsUseCases:
    own = (services.store.path,)  # the configuration holds the token: it is never attached, and nothing is written next to it
    return AttachmentsUseCases(
        list_attachments=ListAttachments(services.gateway, services.settings),
        show=ShowAttachment(services.gateway, services.settings, services.diagnostics),
        download=DownloadAttachments(services.gateway, services.files, services.settings, protected=own),
        read_text=ReadAttachmentText(services.gateway, services.settings, services.diagnostics),
        upload=UploadAttachments(services.gateway, services.files, services.settings, protected=own, diagnostics=services.diagnostics),
    )
