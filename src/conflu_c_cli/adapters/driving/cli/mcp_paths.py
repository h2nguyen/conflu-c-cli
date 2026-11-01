"""Where a tool call may read and write: below the folder the server was started in, and nowhere near what holds the token.

A model chooses the paths of a call, perhaps after reading text that a stranger put into a page. A path that names the settings file of
the CLI would hand the token to the model (`conflu_comment` with `file` set to it and `dryRun` shows the file as the payload), and a folder
outside the working folder would take the bytes of an attachment, whose name and content an author chose. So every property that names a
path (`Arg.path`, read through `mcp_calls.access_of`) is checked before the command runs, and a call is refused, with what is allowed, when
its path

- is not below the working folder once the links in it are followed (`..` and symbolic links included),
- is a network or device path (`\\\\host\\share`, `//host`, `\\\\?\\`, `\\\\.\\`, `\\??\\`): it is never looked at, because a look could sign
  in to a host that the model chose,
- starts or ends with a blank or an invisible character, or holds a control character: a command may take such a character off (the
  download strips its folder) and then use another path than the one that was checked,
- is the settings file of the CLI, or lies in the folder of the settings or of the cache (judged by which folder a name is: a link or a short
  name that `resolve` did not follow is the same folder),
- is a file that holds the token (where a file is read, in every encoding that `textio.decode_text` reads), or where a call writes: a hidden
  folder, a file that exists, or the working folder itself for files whose names come from Confluence (`download`), and for those files
  anything but a folder below `tmp/conflu-attachments`,
- has a part that ends in a dot or a blank (on Windows, which takes them off), is longer than `MAX_PATH_CHARS`, or resolves to another place
  when it is resolved once more: below such a part `Path.resolve` does not follow a link or a short name, and the command would open what
  it returned through that link, out of the working folder or into the folder of the settings.

What is approved is not what the model wrote: the command is given the path in full, links followed (`Verdict.approved`), so that nothing a
command does to a text can lead it to another place than the one that was checked. A property that the call leaves out is judged by the
place that the command would then work at (`mcp_calls.DEFAULT_PLACES`: the folder of a download), and the command is given that place as the
value of the property.

A working folder that is the root of a drive, the home folder or a folder above it, or the place where the CLI keeps its files by default,
keeps nothing out, so a call that names a path is refused there.
"""
from __future__ import annotations

import getpass
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ....domain.attachguards import SCAN_LIMIT, SCAN_PIECE, holds_secret, secret_needles
from ....domain.errors import ConfluCliError
from .mcp_calls import DOWNLOAD_HERE, Access
from .spec import READS_FILE, READS_FILE_OR_FOLDER, READS_FILES, WRITES_BELOW_FOLDER, WRITES_FILE, WRITES_FOLDER

APP_FOLDER = "conflu-c-cli"  # the folder below `.config` and `.cache` that the CLI uses; a test holds this and `adapters.driven.paths` together
LEFT_OUT = "was left out"  # what a refusal of a default place says of its property; the hint of such a refusal is chosen by it
MAX_PATH_CHARS = 4096  # a path of a call is no longer than this: no system takes a longer one, and a longer one only makes the file calls fail in odd ways
_WINDOWS = os.name == "nt"
# Two separators in front: a share of another host, or a device (`\\?\`, `\\.\`); and the form of the object manager, `\??\`.
_NETWORK = ("\\\\", "//", "\\/", "/\\", "\\??\\")
_DRIVE = re.compile(r"^[A-Za-z]:")
_NOT_IN_A_NAME = frozenset('<>"|?*')
# What can stand in front of a path or behind it unseen: blanks, line and paragraph separators, controls, invisible format characters.
_HIDING = frozenset({"Zs", "Zl", "Zp", "Cc", "Cf"})
_NO_PATH_HOLDS = frozenset({"Cc", "Cf", "Zl", "Zp"})  # and what no path holds inside either
# The names that Windows reads as a device: Python's `ntpath.isreserved` (3.13) knows them, and this project supports older versions.
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{device}{digit}" for device in ("COM", "LPT") for digit in "123456789\u00b9\u00b2\u00b3"}
)
_WRITES = (WRITES_FILE, WRITES_FOLDER, WRITES_BELOW_FOLDER)
_READS_A_FILE = (READS_FILE, READS_FILES, READS_FILE_OR_FOLDER)


@dataclass(frozen=True)
class Secrets:
    """What the CLI keeps that a call must not reach: where its settings are, and the token (with the e-mail address that goes with it: the
    header of a request holds both)."""

    settings_file: str
    token: str
    email: str = ""


@dataclass(frozen=True)
class Verdict:
    """What the policy says of a call: what it refuses, a sentence each, and, when it refuses nothing, the value that the command is to be
    given for each property that names a path, in place of the text that the model wrote: the path in full (a tuple of them, one for each
    file, for the files of `attach`)."""

    problems: list[str] = field(default_factory=list)
    approved: dict[str, Any] = field(default_factory=dict)


def _unset(value: Any) -> bool:
    """A property that the call left out: absent, null, an empty text or a flag that is false (and not `0`, which is no flag)."""
    return value is None or value is False or (isinstance(value, str) and value == "")


def _hides(char: str) -> bool:
    """A character that can stand in front of a path or behind it unseen, and that a command may take off: `str.strip()` takes the blanks,
    a program may take more."""
    return char.isspace() or unicodedata.category(char) in _HIDING


def _written_out(char: str) -> str:
    """A character as a message shows it: itself when it can be seen (and a plain blank), else its escape (`\\u200b`, `\\x85`)."""
    return char if char == " " or char.isprintable() else char.encode("unicode_escape").decode("ascii")


def _shown(text: str, limit: int = 200) -> str:
    """A path as a message shows it: what cannot be seen is written out, and a long text is cut. The text of a path is whatever a model wrote:
    it must not put a control character into the log of the server, which is a terminal."""
    shown = "".join(_written_out(char) for char in text)
    return shown if len(shown) <= limit else shown[:limit] + "..."


def _blank_problem(text: str) -> str:
    """What is wrong with the blanks and the invisible characters of a text that is to name a path, judged before anything is asked of the
    file system. A command may take a character off the ends (the download does `out.strip()`), and what is left may be another path than the
    one that was checked: `<blank>.git/hooks` is no hidden folder to a policy, `<blank>\\\\host\\share` is no share. So such a text is refused,
    and the network form is also looked for in what is left once the blanks in front are gone."""
    start = 0
    while start < len(text) and _hides(text[start]):
        start += 1
    if text[start:].startswith(_NETWORK):
        return "is a network or device path (a share of another computer, `\\\\?\\` or `\\\\.\\`)"
    if text and (_hides(text[0]) or _hides(text[-1])):
        return "starts or ends with a blank or an invisible character: write the path without it (a command may take it off and use another path)"
    if any(unicodedata.category(char) in _NO_PATH_HOLDS for char in text):
        return "holds a control character or an invisible one (a format or separator character such as U+200B)"
    return ""


def _shape_problem(text: str) -> str:
    """What is wrong with the text of a path before anything is asked of the file system. A network or device path is refused here and
    nowhere later: resolving it could contact a host."""
    problem = _blank_problem(text)
    if problem:
        return problem
    if len(text) > MAX_PATH_CHARS:
        return f"is longer than {MAX_PATH_CHARS:,} characters"
    if _WINDOWS:
        if _NOT_IN_A_NAME & set(text):
            return "holds a character that Windows does not allow in a name (`< > \" | ? *`)"
        if ":" in (text[2:] if _DRIVE.match(text) else text):
            return "names a stream or a device (a colon after the drive)"
        for part in re.split(r"[\\/]+", text):
            if part not in ("", ".", "..") and part != part.rstrip(" ."):
                # Windows takes the dots and blanks off the end of a name, so `.. ` and `...` are other folders than the ones written, and
                # `resolve` does not follow a link or a short name that comes after such a part (the check of what it returns catches the rest)
                return f"holds a part that ends in a dot or a blank ({_shown(part)}): Windows takes those off, so it names another folder than it says"
    return ""


def _reserved(name: str) -> bool:
    """Whether Windows reads a name as a device: the part before the first dot, without the blanks at its end, in capitals, is one of
    `_RESERVED` (`con`, `NUL .txt`, `com1.x`, `COM¹`). The rule of `ntpath.isreserved`."""
    return name.partition(".")[0].rstrip(" ").upper() in _RESERVED


def _resolve(text: str, base: Path | None = None) -> Path | None:
    """The path in full, links followed. A relative text is relative to `base` (the working folder of the server: the policy does not depend on
    the folder the process happens to be in), or to the folder of the process when there is no base."""
    try:
        return (Path(text) if base is None else base / text).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _same(first: Path, second: Path) -> bool:
    if os.path.normcase(str(first)) == os.path.normcase(str(second)):
        return True
    try:
        return os.path.samefile(first, second)  # a link, a hard link, a short name or a case that the plain comparison does not see
    except (OSError, ValueError):  # a path that is not there, or too long for the system to look at
        return False


def _within(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or lies in it, judged by what the names are and not by how they are written: the way they are written first,
    then whether a folder on the way to `path` is the same folder as `folder` (a short name, a case, a link that `resolve` did not follow)."""
    return _inside(path, folder) or any(_same(ancestor, folder) for ancestor in (path, *path.parents))


def _homes(environ: Mapping[str, str]) -> list[Path]:
    """The folders that can be the home folder of the user for the cache of the CLI: what it looks at, and a bit more."""
    found = [environ.get("HOME", ""), environ.get("HOMEDRIVE", "") + environ.get("HOMEPATH", "")]
    try:
        found.append(str(Path.home()))
    except RuntimeError:
        pass
    return [_resolve(text) or Path(text) for text in found if text]


def real_home() -> Path | None:
    """The home folder of the user as the operating system has it. On Linux and macOS that is the account database, not `$HOME`. On Windows it
    is what `os.path.expanduser("~")` makes of `USERPROFILE` (else of `HOMEDRIVE` and `HOMEPATH`): the process that starts the server can set
    those, a model cannot. `HOME` and the variables for the folders of the settings and the cache are never asked: a test or a client can set
    them to any folder, and a working folder is too wide because it is where the user lives, not because such a variable says so.

    None when the system knows none: `expanduser` then returns `~` unchanged, which is no folder, and a path that is not absolute would be
    read relative to the working folder (and make the whole of it "the home folder")."""
    try:
        if os.name == "nt":
            found = Path(os.path.expanduser("~"))
        else:
            import pwd

            found = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, OSError, RuntimeError):
        return None
    return found if found.is_absolute() else None


def cache_folders(environ: Mapping[str, str]) -> list[Path]:
    """Where the CLI may keep its cache. A driving adapter cannot ask the driven one (`adapters.driven.paths.cache_directory`), so this
    names every place that one can pick, by the same rule; a test holds the two together."""
    found = [home / ".cache" / APP_FOLDER for home in _homes(environ)]
    if environ.get("XDG_CACHE_HOME"):
        found.append(Path(environ["XDG_CACHE_HOME"]) / APP_FOLDER)
    return [_resolve(str(path)) or path for path in found]


def local_identity(environ: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """(the home folders, the account names) of the person at this computer, for `mcp_calls.private_text_filter`: every spelling that this
    process knows of the home folder (the operating system's answer, the variables, each with its links followed) and of the name of the
    account. A folder that is not absolute is none: it would be read relative to the working folder."""
    texts = [environ.get(key, "") for key in ("USERPROFILE", "HOME")] + [environ.get("HOMEDRIVE", "") + environ.get("HOMEPATH", "")]
    system = real_home()
    if system is not None:
        texts.append(str(system))
    try:
        texts.append(str(Path.home()))
    except (OSError, RuntimeError):
        pass
    homes: list[str] = []
    for text in texts:
        if not text or not Path(text).is_absolute():
            continue
        homes.append(text)
        followed = _resolve(text)
        if followed is not None:
            homes.append(str(followed))
    names = [environ.get(key, "") for key in ("USERNAME", "USER", "LOGNAME")] + [Path(home).name for home in homes]
    try:
        names.append(getpass.getuser())
    except (ImportError, KeyError, OSError):
        pass
    return homes, [name for name in names if name]


def _holds_token(path: Path, secrets: Secrets) -> str:
    """`yes` when the file holds the token (as it is or in the header that carries it, in every encoding that `textio.decode_text` reads), `large`
    when it is too big to be searched, else nothing. The token is not printed."""
    needles = secret_needles(secrets.token, secrets.email)
    if not needles:
        return ""
    try:
        if path.stat().st_size > SCAN_LIMIT:
            return "large"
        with path.open("rb") as handle:
            return "yes" if holds_secret(iter(lambda: handle.read(SCAN_PIECE), b""), needles) else ""
    except (OSError, ValueError):
        return ""  # the command meets the same error and says so


class PathPolicy:
    """The rules for the paths of a call, for the folder the server runs in. `secrets` is asked when a call names a path, not before.
    `home` says where the home folder of the user is (the operating system's answer unless a test says another): a working folder that
    is that folder, a folder above it, the place where the CLI keeps its files by default (below that home folder) or one above that, or
    the root of a drive, is refused, because a boundary that wide keeps nothing out."""

    def __init__(
        self, root: Path, environ: Mapping[str, str], secrets: Callable[[], Secrets], home: Callable[[], Path | None] = real_home
    ) -> None:
        self._root = root.resolve()
        self._environ = environ
        self._secrets = secrets
        found = home()
        if found is not None and not found.is_absolute():  # no home folder known (`~` unexpanded): not a folder, and not a part of the project
            found = None
        self._home = (_resolve(str(found)) or found) if found else None
        # Where the CLI keeps its settings and its cache when nothing says otherwise. Only these, below the home folder of the operating system:
        # a folder that a setting or a variable names inside the project is the project's own, and a call may not name it either way.
        self._kept = [] if self._home is None else [self._home / ".config" / APP_FOLDER, self._home / ".cache" / APP_FOLDER]

    @property
    def root(self) -> Path:
        return self._root

    def allowed(self, problems: Sequence[str] = ()) -> str:
        """What a call may name, for the hint of a refusal. A refusal of a place that the command would have used for a property that was left
        out says what to do about that as well."""
        text = (
            f"A path must lie below the working folder of the server ({self._root}); write it relative to that folder, for example tmp/export, "
            "with no blank or invisible character around it. "
            "Not allowed: a network or device path, a path that leaves the folder (`..` or a link), the settings and the cache of the CLI, "
            "a file that holds the token, and where a call writes: a hidden folder (a name that starts with a dot) or a file that exists. "
            f"The files of attachments, which strangers wrote, go below {DOWNLOAD_HERE} only (`out` of conflu_download). "
            "`force` is not honoured: the user decides to replace a file or content, not a call."
        )
        if any(LEFT_OUT in problem for problem in problems):
            text += (
                " A property that is left out is judged by the place that the command then uses (`out` of conflu_download: "
                f"{DOWNLOAD_HERE}/ID): give the property to use another place."
            )
        return text

    def refusals(self, access: Mapping[str, Access], arguments: Mapping[str, Any]) -> list[str]:
        """What the policy refuses in a call, a sentence each, naming the property; nothing when the call may run."""
        return self.check(access, arguments).problems

    def check(self, access: Mapping[str, Access], arguments: Mapping[str, Any]) -> Verdict:
        """What the policy says of a call: what it refuses, or else the value that each property naming a path is to be given. The command
        gets that value, the path in full, and never the text that the model wrote (`mcp_calls.command_line`): the policy has judged
        exactly the place that the command is then sent to.

        That holds for a property that the call leaves out as well, when the command then works at a place of its own (`DEFAULT_PLACES`):
        the place is worked out as the command works it out, judged like a path that was given, and given to the command as the value of the
        property. A command that is left to find its own place would be free to follow a link in it anywhere."""
        used = {name: rule for name, rule in access.items() if not _unset(arguments.get(name))}
        found = [
            f"'{name}' is not honoured over MCP: it replaces a file, or content that would be lost, and the user decides that. "
            "Leave it out, or ask the user to run the command with --force"
            for name, rule in used.items()
            if rule.overwrites
        ]
        named = {name: rule.path for name, rule in used.items() if rule.path}
        left_out = self._left_out(access, arguments)
        if not named and not left_out:
            return Verdict(found, {})
        broad = self._too_wide()
        if broad:
            return Verdict([*found, broad], {})
        secrets = self._secrets()
        approved: dict[str, Any] = {}
        refused: set[str] = set()
        for name, kind in named.items():
            problem, taken = self._problem(name, kind, arguments[name], secrets, used[name].below)
            if problem:
                found.append(problem)
                refused.add(name)
            else:
                approved[name] = taken
        for name, rule in left_out.items():  # after the others: a place may be made of a path that was approved just now
            problem, taken = self._default(name, rule, arguments, approved, refused, secrets)
            if problem:
                found.append(problem)
            elif taken is not None:
                approved[name] = taken
        return Verdict(found, {} if found else approved)

    @staticmethod
    def _left_out(access: Mapping[str, Access], arguments: Mapping[str, Any]) -> dict[str, Access]:
        """The properties that name a path, that the call leaves out, and at whose default place the command would work. Not the ones whose
        place the command does not use in this call (a flag says so), and not the ones that the call lacks what the place is made of for:
        the schema requires that, and the command says what is missing."""
        found: dict[str, Access] = {}
        for name, rule in access.items():
            default = rule.default
            if default is None or not rule.path or not _unset(arguments.get(name)):
                continue
            wired = dict(default.properties)
            if default.place.unused_with and arguments.get(wired[default.place.unused_with]) is True:
                continue
            if any(_unset(arguments.get(wired[argument])) for argument in default.place.made_of):
                continue
            found[name] = rule
        return found

    def _default(
        self, name: str, rule: Access, arguments: Mapping[str, Any], approved: Mapping[str, Any], refused: set[str], secrets: Secrets
    ) -> tuple[str, Any]:
        """(what is wrong with the place that the command would use for a property that was left out, or nothing) and (the place in full), or
        no place when it is made of a path that was refused: that refusal is the answer."""
        assert rule.default is not None
        wired = dict(rule.default.properties)
        if any(wired[argument] in refused for argument in rule.default.place.made_of):
            return "", None
        values = {argument: approved.get(wired[argument], arguments.get(wired[argument])) for argument in rule.default.place.made_of}
        try:
            place = rule.default.place.build(values)
        except ConfluCliError as error:  # the command would refuse the same value before it touched a file
            return f"'{name}' {LEFT_OUT}, and the place that the command would use instead cannot be worked out: {error.message}", None
        return self._one(name, rule.path, place, secrets, default=True, below=rule.below)

    def _too_wide(self) -> str:
        why = ""
        if self._root.parent == self._root:
            why = "a drive or the root of the file system"
        elif self._home is not None and _within(self._home, self._root):
            why = "your home folder or a folder above it"
        elif any(_within(folder, self._root) for folder in self._kept):
            why = "the folder where the CLI keeps its settings or its cache, or a folder above it"
        if not why:
            return ""
        return (
            f"The working folder of the server ({self._root}) is {why}: too wide to keep the files of a call to one project. "
            "Start the server in the folder of the project, or set the `cwd` of its configuration to it"
        )

    def _problem(self, name: str, kind: str, value: Any, secrets: Secrets, below: tuple[str, ...] = ()) -> tuple[str, Any]:
        """(what is wrong with the value of a property, or nothing) and (what the command is given in its place): the path in full, or for
        an array of paths, the tuple of them, each judged by itself and given to the command as one argument, so that no command can split
        a name at a blank."""
        if isinstance(value, (list, tuple)):
            taken: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    return f"'{name}' must be paths, each written as a text", ()
                problem, path = self._one(name, kind, item, secrets, below=below)
                if problem:
                    return problem, ()
                taken.append(path)
            return "", tuple(taken)
        if not isinstance(value, str):  # the schema says a text; anything else that gets here is refused rather than let through unchecked
            return f"'{name}' must be one path, written as a text", ""
        return self._one(name, kind, value, secrets, below=below)

    def _one(self, name: str, kind: str, text: str, secrets: Secrets, *, default: bool = False, below: tuple[str, ...] = ()) -> tuple[str, str]:
        """(what is wrong with one path, or nothing) and (the path in full, links followed: what the command is given in place of `text`).
        `default` says that `text` is the place that the command would use because the call left the property out. `below` is a folder below the
        working folder that the path must lie below as well (where the files of strangers go)."""

        def refuse(what: str) -> tuple[str, str]:
            if default:
                return f"'{name}' {LEFT_OUT}, and the place that the command then uses ({_shown(text)}) {what}", ""
            return f"'{name}' ({_shown(text)}) {what}", ""

        shape = _shape_problem(text)
        if shape:
            return refuse(shape)
        target = _resolve(text, self._root)
        if target is None:
            return refuse("cannot be resolved to a path")
        if len(str(target)) > MAX_PATH_CHARS:
            return refuse(f"resolves to a path longer than {MAX_PATH_CHARS:,} characters")
        if _resolve(str(target)) != target:
            # Below a folder that is not there `resolve` stops following links and short names, and a name that the system reads in two ways makes it
            # stop early: what it returned is then not the place that the command is sent to, and a second look leads somewhere else.
            return refuse("cannot be resolved reliably: the system reads a part of it in two ways. Write the path plainly")
        if not _inside(target, self._root):
            return refuse("is not below the working folder of the server")
        protected = self._protected(target, secrets)
        if protected:
            return refuse(protected)
        parts = target.relative_to(self._root).parts
        if _WINDOWS and any(_reserved(part) for part in parts):
            return refuse("names a device (CON, NUL, COM1 ...)")
        if kind in _WRITES:
            hidden = next((part for part in parts if part.startswith(".")), "")
            if hidden:
                return refuse(f"would write into '{hidden}': a hidden folder or file (a name that starts with a dot) is not allowed")
            if kind == WRITES_BELOW_FOLDER and not parts:
                return refuse("is the working folder itself: the names of these files come from Confluence, so they go into a folder below it")
            if kind == WRITES_FILE and target.exists():
                return refuse("is a file that exists: a call never replaces a file, choose a new name")
        if below:
            # The folder as it is written, below the resolved working folder: a link at `tmp` or at `conflu-attachments` that leads somewhere else
            # (a cloned repository can bring one, also to a folder of the project itself) makes the resolved path leave it, and the call is refused.
            base = self._root.joinpath(*below)
            if target == base or not _inside(target, base):
                folder = "/".join(below)
                return refuse(f"is not below {folder}: the names and the bytes of these files come from strangers, so they go into a folder below it (for example {folder}/ID)")
        if kind in _READS_A_FILE and secrets.token and target.is_file():
            held = _holds_token(target, secrets)
            if held == "yes":
                return refuse("is a file that holds the token of this server: it is not read")
            if held == "large":
                return refuse(f"is too large to be checked for the token ({SCAN_LIMIT >> 20} MiB at most): it is not read")
        return "", str(target)

    def _protected(self, target: Path, secrets: Secrets) -> str:
        settings = _resolve(secrets.settings_file) if secrets.settings_file else None
        if settings is not None and _same(target, settings):
            return "is the settings file of the CLI: it is not read or written over MCP"
        folders = ([settings.parent] if settings is not None else []) + cache_folders(self._environ)
        # Judged by which folder a name is and not by how it is written: a short name, a case or a link that `resolve` did not follow (it stops
        # below a folder that is not there) is the same folder. A folder that holds the working folder itself cannot be kept out: only the
        # settings file is then.
        if any(_within(target, folder) for folder in folders if not _within(self._root, folder)):
            return "lies in the folder where the CLI keeps its settings or its cache: it is not read or written over MCP"
        return ""
