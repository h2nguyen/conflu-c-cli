# Install, update and uninstall

## What you need

Python 3.10 or newer. Check with `python --version` (on Windows `py -3 --version` works too). Nothing else:
the CLI uses only the Python standard library, so there is no `pip install`, and it needs no curl, jq or
PowerShell script. TLS uses the certificate store of the operating system.

## Install

From the folder that holds `install.py`, in Git Bash, PowerShell or cmd:

```bash
python install.py --dry-run     # shows the Python, the folders and the launchers; changes nothing
python install.py
```

What it does:

1. Copies the program to a **local** folder: `%LOCALAPPDATA%\conflu-c-cli` on Windows,
   `~/.local/share/conflu-c-cli` elsewhere. It contains the package, the documentation, the skill, the
   examples, `README.md`, `CHANGELOG.md`, `LICENSE` and `VERSION`. It builds the new copy in a new folder next to the old
   one and swaps them, so a failure cannot leave a half-copied program.
2. Writes two launchers to `~/bin`: `conflu` (a `sh` script, for Git Bash, Linux and macOS) and `conflu.cmd`
   (for cmd and PowerShell). Both start the Python that ran the installer, in isolated mode (`-I`, so a stray
   `PYTHONPATH` cannot interfere) and with UTF-8 (`-X utf8`), whatever the console encoding.
3. Precompiles the program, starts it once and checks that it reports the version it just installed.

It never touches your configuration (`~/.config/conflu-c-cli`) unless you uninstall with `--purge`.

**Why local.** Python reads many files every time it starts. On a network home drive that is noticeably slower
than on a local disk, so the program does not go into `~` on Windows. The launchers are tiny and stay in
`~/bin`.

| Option | Meaning |
| --- | --- |
| `--dry-run` | Show what would happen, change nothing. |
| `--prefix DIR` | Install into `DIR` (default: `CONFLUENCE_CLI_INSTALL_DIR`, else the local folder above). |
| `--bin-dir DIR` | Write the launchers into `DIR` instead of `~/bin` (default: `CONFLUENCE_CLI_BIN_DIR`, else `bin` in the home folder). |
| `--python PATH` | Let the launchers start this Python instead of the one running the installer. |
| `--force` | Replace a launcher that is not from this program, and move a foreign installation folder aside. |
| `--uninstall` | Remove the program and the launchers (see below). |
| `--purge` | With `--uninstall`: also delete the configuration file and related config folders the program owns. |

## Which home folder

Git Bash sets `HOME`. PowerShell and cmd do not; they use the Windows home drive and path (`HOMEDRIVE` +
`HOMEPATH`) when that folder exists, else the Windows profile. So the launchers go to the same `~/bin`
whichever shell runs the installer, and the CLI finds its configuration there as well (see
[configure the connection](configure.md)). The program itself goes to the local profile, not to that home.

## Use it from PowerShell and cmd

`~/bin` must be on the `PATH` of the shell. Git Bash usually has it; PowerShell and cmd usually do not. Three
ways, from the least to the most invasive:

1. **No setting at all.** Run the program directly, which needs no `PATH`:
   `python "$env:LOCALAPPDATA\conflu-c-cli\conflu.py" version` (PowerShell) or
   `python "%LOCALAPPDATA%\conflu-c-cli\conflu.py" version` (cmd).
2. **Put the launchers where every Windows shell looks already.** The installer prints this when it applies, for
   example `python install.py --bin-dir "C:\Users\YOU\AppData\Local\Microsoft\WindowsApps"`.
3. **Add `~/bin` to the user `PATH`** (Windows Settings, search for environment variables).

Open a new terminal, and restart VS Code, after you change the `PATH`: running programs keep the old one. A
coding agent that works in PowerShell needs one of these; see [use with AI agents](use-with-ai-agents.md).

The launcher is a `.cmd` file on purpose: a company policy such as PowerShell `AllSigned` blocks `.ps1`
scripts, but not `.cmd`.

## Update

Get the new source (pull the repository or copy the folder) and run `python install.py` again. The old program
is replaced completely, the configuration stays. Afterwards:

```bash
conflu version
conflu doctor
```

If you changed the Python interpreter, run the installer with the interpreter you want the launchers to remember.

## Another Python

The launchers remember one interpreter. When you upgrade Python or remove the one that was used, run
`python install.py` with the interpreter you want, or `python install.py --python C:\Python313\python.exe`.
`conflu version` tells you which Python runs.

## Run without installing

From the source folder:

```bash
python conflu.py page 123456 --json
python -m conflu_c_cli version      # with PYTHONPATH=src
```

## Uninstall

```bash
python install.py --uninstall            # program and launchers; the configuration stays
python install.py --uninstall --purge    # also the configuration file and related program folders
python install.py --uninstall --dry-run  # shows what would be removed
```

The uninstaller removes only what it recognises as this program: an installation folder it created and the
launchers that carry the installer's signature **and start that installation**. With `--purge` it deletes the
configuration file in every normal location the program looks in, and then a standard config folder only when
nothing else is left in it. The folder named directly by `CONFLUENCE_CONFIG_FILE` is never removed as a whole.

## Installed documentation

The installer copies the docs, skill and examples too. The environment variable `CONFLUENCE_CLI_HOME` points
`conflu how-to`, `conflu changelog` and `conflu skill` at another installed copy when you need that for testing
or troubleshooting.
