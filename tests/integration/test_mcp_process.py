"""`conflu mcp` as a real process, the way an MCP client starts it: standard input and output are pipes, Confluence is the mock, nothing is faked."""
import getpass
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests.integration.test_end_to_end import ROOT, EndToEnd

WAIT = 60  # seconds: a test that waits longer has hung
TOKEN = "tok-0123456789abcdef-of-the-process-test"  # long and unlike any other text of these tests: a file that holds it holds the token


def make_link(test, link, target):
    """A symbolic link to a folder, or on Windows a junction, which the user may make without a privilege; the link (and not what it leads to) is
    taken away again when the test ends. False when the system makes none."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            return False
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)
        if done.returncode != 0:
            return False

    def take_away():
        try:
            os.rmdir(link)  # a junction, or a link to a folder on Windows
        except OSError:
            try:
                os.unlink(link)
            except OSError:
                pass

    test.addCleanup(take_away)
    return True


class Client:
    """An MCP client over the pipes of a child process: one JSON message per line, and it never waits for ever."""

    def __init__(self, test, *args, env=None, cwd=None, isolated=True, read_log=True):
        inherited = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        # a value of None takes the variable away (a test that runs the server where the system names no home folder)
        environment = {key: value for key, value in {**inherited, **test.env, **(env or {})}.items() if value is not None}
        # the way the other process tests start the program (`-I -X utf8`), or, to show that a console that is not UTF-8 does not matter, as a
        # client on such a machine would: the server writes ASCII and reads UTF-8 whatever the console says
        command = [sys.executable, "-I", "-X", "utf8"] if isolated else [sys.executable]
        if not isolated:
            environment.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"})
        self.child = subprocess.Popen(
            [*command, str(ROOT / "conflu.py"), "mcp", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=cwd or test.folder,
        )
        test.addCleanup(self.stop)
        self.lines: queue.Queue = queue.Queue()
        self.stderr = bytearray()
        threading.Thread(target=self._read_messages, daemon=True).start()
        self._err_reader = threading.Thread(target=self._read_log, daemon=True)
        if read_log:  # a client that never reads standard error leaves the pipe to fill up
            self._err_reader.start()
        self.next_id = 0

    def _read_messages(self):
        for raw in iter(self.child.stdout.readline, b""):
            self.lines.put(raw)
        self.lines.put(None)  # the end of the output

    def _read_log(self):
        for raw in iter(self.child.stderr.readline, b""):
            self.stderr.extend(raw)

    def send(self, message):
        self.child.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.child.stdin.flush()

    def receive(self):
        raw = self.lines.get(timeout=WAIT)
        if raw is None:
            if self._err_reader.ident is not None:
                self._err_reader.join(timeout=2)
            raise AssertionError(f"the server ended; it said on standard error: {self.log}")
        assert raw.endswith(b"\n") and b"\r" not in raw, raw
        return json.loads(raw.decode("ascii"))  # one line of pure ASCII that is one JSON message

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, **({} if params is None else {"params": params})})
        reply = self.receive()
        assert reply["id"] == self.next_id, reply
        return reply

    def call(self, tool, arguments=None):
        return self.request("tools/call", {"name": tool, "arguments": arguments or {}})

    def notify(self, method):
        self.send({"jsonrpc": "2.0", "method": method})

    def tool_names(self):
        return {tool["name"] for tool in self.request("tools/list")["result"]["tools"]}

    def finish(self):
        """The end of the input: the server ends by itself. Its exit code, and what it still wrote."""
        self.child.stdin.close()
        code = self.child.wait(timeout=WAIT)
        leftover = []
        while True:
            raw = self.lines.get(timeout=WAIT)
            if raw is None:
                break
            leftover.append(raw)
        if self._err_reader.ident is not None:
            self._err_reader.join(timeout=WAIT)
        return code, leftover

    def stop(self):
        if self.child.poll() is None:
            self.child.kill()
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            try:
                stream.close()
            except OSError:
                pass
        self.child.wait(timeout=WAIT)

    @property
    def log(self):
        return bytes(self.stderr).decode("utf-8", "replace")


def result_of(reply):
    return reply["result"]


def data_of(reply):
    return json.loads(reply["result"]["content"][0]["text"])


class McpProcessTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.mock.token = TOKEN
        self.folder = self.root / "project"  # the working folder of the server: the folder it is started in
        self.folder.mkdir()
        self.config = self.root / "settings" / "config"
        self.config.parent.mkdir()
        self.write_config()
        # A home folder of its own with a name that no account has, so that no test depends on the home folder of the person who runs it.
        self.profile = self.root / "home" / "fake-user"
        self.profile.mkdir(parents=True)
        # the settings file holds everything, as for a person: the process finds the site and the token there, and the policy knows the file
        self.env = {
            "CONFLUENCE_CONFIG_FILE": str(self.config),
            "HOME": str(self.profile),
            "USERPROFILE": str(self.profile),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        }
        self.addCleanup(lambda: self.assertEqual(self.mock.unknown_endpoints, []))  # nothing was asked of Confluence that its documents do not list

    def write_config(self, path=None):
        (path or self.config).write_text(
            f"CONFLUENCE_BASE_URL={self.mock.base_url}\nCONFLUENCE_EMAIL={self.mock.email}\nCONFLUENCE_API_TOKEN={TOKEN}\n", encoding="utf-8"
        )

    def page_property(self):
        return "page"

    def test_a_client_starts_the_server_lists_the_tools_and_reads_a_page(self):
        client = Client(self)
        hello = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
        initialized = client.request("initialize", hello)
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "conflu-c-cli")
        client.notify("notifications/initialized")  # no answer: the next line is the answer to the next request
        names = client.tool_names()
        self.assertIn("conflu_page", names)
        self.assertTrue(names.isdisjoint({"conflu_update", "conflu_create", "conflu_mcp", "conflu_api", "conflu_setup_token", "conflu_export", "conflu_download"}))
        reply = client.call("conflu_page", {"page": ["2002"], "noBody": True})
        self.assertFalse(result_of(reply)["isError"], reply)
        page = data_of(reply)
        self.assertEqual((page["id"], page["title"], page["body"]), ("2002", "Release notes", None))
        code, leftover = client.finish()
        self.assertEqual((code, leftover), (0, []))
        self.assertGreaterEqual(len(self.sent("GET", "/api/v2/pages/2002")), 1)
        self.assertEqual(self.sent("PUT", ""), [])
        self.assertEqual(self.sent("POST", ""), [])
        self.assertNotIn("Traceback", client.log)
        self.assertIn("MCP server", client.log)

    def test_a_batch_on_the_pipe_is_answered_as_a_batch(self):
        client = Client(self)
        client.send([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "nope"}])
        answers = client.receive()
        self.assertEqual([(answer["id"], "error" in answer) for answer in answers], [(1, False), (2, True)])
        self.assertEqual(client.finish()[0], 0)

    def test_a_failing_call_is_an_error_result_with_the_hint_and_the_server_goes_on(self):
        client = Client(self)
        self.mock.fail_next("/api/v2/pages/2002", 403, body={"errors": [{"status": 403, "title": "Forbidden", "detail": "You do not have the permission to see the page."}]})
        denied = client.call("conflu_page", {"page": ["2002"], "noBody": True})["result"]
        self.assertTrue(denied["isError"])
        error = json.loads(denied["content"][0]["text"])["error"]
        self.assertEqual((error["code"], error["exitCode"]), ("AUTH", 5))
        self.assertTrue(error["hint"])
        missing = data_of(client.call("conflu_page", {"page": ["999"], "noBody": True}))["error"]
        self.assertEqual((missing["code"], missing["exitCode"]), ("NOT_FOUND", 4))
        self.assertFalse(result_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))["isError"])
        self.assertEqual(client.finish()[0], 0)

    def test_what_changes_confluence_exists_only_with_allow_write_and_a_dry_run_sends_nothing(self):
        read_only = Client(self)
        refused = read_only.call("conflu_update", {"page": "2005", "body": "x", "dryRun": True})
        self.assertEqual((refused["error"]["code"], refused["error"]["message"].startswith("Unknown tool: conflu_update")), (-32602, True))
        self.assertIn("--allow-write", refused["error"]["message"])
        self.assertEqual(read_only.finish()[0], 0)
        self.assertEqual(self.sent("PUT", ""), [])
        writer = Client(self, "--allow-write")
        self.assertIn("conflu_update", writer.tool_names())
        arguments = {"page": "2005", "body": "Zusätzlich: Ünïcode — 日本語", "append": True, "message": "Von einem Aufruf"}
        preview = data_of(writer.call("conflu_update", {**arguments, "dryRun": True}))
        self.assertEqual((preview["dryRun"], preview["action"]), (True, "updated"))
        self.assertIn(arguments["body"], json.dumps(preview["payload"], ensure_ascii=False))  # UTF-8 in, whatever the console encoding
        self.assertEqual(self.sent("PUT", ""), [])
        done = writer.call("conflu_update", {**arguments, "ifVersion": 1})["result"]
        self.assertFalse(done["isError"], done)
        self.assertEqual(len(self.sent("PUT", "/api/v2/pages/2005")), 1)
        self.assertIn("Ünïcode", json.dumps(self.sent("PUT", "/api/v2/pages/2005")[0].body, ensure_ascii=False))
        stale = writer.call("conflu_update", {**arguments, "ifVersion": 1})["result"]  # the guard of the command, at the second call
        self.assertEqual((stale["isError"], json.loads(stale["content"][0]["text"])["error"]["exitCode"]), (True, 3))
        self.assertEqual(writer.finish()[0], 0)

    def test_a_tool_that_overrides_is_refused_with_the_command_unrun(self):
        client = Client(self, "--allow-write")
        refused = client.call("conflu_update", {"page": "2005", "body": "x", "force": True, "dryRun": True})["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("'force' is not honoured over MCP", refused["content"][0]["text"])
        self.assertEqual(client.finish()[0], 0)
        self.assertEqual(self.sent("PUT", ""), [])

    def test_people_stay_out_unless_the_server_is_started_to_show_them(self):
        client = Client(self)
        refused = client.call("conflu_page", {"page": ["2002"], "noBody": True, "withUsers": True})
        self.assertEqual(refused["error"]["code"], -32602)
        self.assertIn("withUsers", refused["error"]["message"])
        page = data_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))
        self.assertEqual((page["author"], page["owner"]), (None, None))
        self.assertEqual(client.finish()[0], 0)
        shown = Client(self, "--show-users")
        self.assertEqual(data_of(shown.call("conflu_page", {"page": ["2002"], "noBody": True, "withUsers": True}))["author"]["displayName"], "Alex Example")
        self.assertEqual(shown.finish()[0], 0)

    def test_the_policy_that_hides_people_refuses_with_users_even_with_show_users(self):
        client = Client(self, "--show-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        reply = client.call("conflu_page", {"page": ["2002"], "noBody": True, "withUsers": True})["result"]
        self.assertTrue(reply["isError"])
        self.assertIn("CONFLUENCE_HIDE_USERS", json.loads(reply["content"][0]["text"])["error"]["message"])
        self.assertEqual(client.finish()[0], 0)

    def test_the_agent_profile_in_the_environment_of_the_server_keeps_people_out_as_everywhere(self):
        client = Client(self, "--show-users", env={"CONFLUENCE_PROFILE": "agent"})
        reply = client.call("conflu_page", {"page": ["2002"], "noBody": True, "withUsers": True})["result"]
        self.assertTrue(reply["isError"])
        self.assertIn("CONFLUENCE_HIDE_USERS", json.loads(reply["content"][0]["text"])["error"]["message"])  # the profile sets the policy
        page = data_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))
        self.assertEqual((page["id"], page["author"], page["owner"]), ("2002", None, None))
        self.assertEqual(client.finish()[0], 0)

    def test_the_owner_of_the_token_stays_out_of_the_connection_check(self):
        client = Client(self)
        check = data_of(client.call("conflu_ping", {}))
        self.assertEqual((check["ok"], check["user"]), (True, None))
        self.assertEqual(client.finish()[0], 0)

    def test_the_environment_cannot_wrap_a_result_in_an_envelope_or_add_a_line(self):
        client = Client(self, env={"CONFLUENCE_JSON_ENVELOPE": "1", "CONFLUENCE_OUTPUT": "text"})
        page = data_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))
        self.assertEqual(page["id"], "2002")
        self.assertNotIn("ok", page)
        self.assertEqual(client.finish(), (0, []))

    def test_the_end_of_the_input_ends_the_server_with_exit_code_0(self):
        client = Client(self)
        self.assertEqual(client.finish(), (0, []))
        self.assertIn("MCP server", client.log)

    def test_with_dash_v_the_requests_to_confluence_are_logged_and_never_the_token(self):
        client = Client(self, "-v")
        reply = client.call("conflu_page", {"page": ["2002"], "noBody": True})
        self.assertFalse(result_of(reply)["isError"])
        self.assertEqual(client.finish(), (0, []))
        self.assertIn("/api/v2/pages/2002", client.log)
        self.assertNotIn(TOKEN, client.log)
        self.assertNotIn(TOKEN, json.dumps(reply))

    def test_an_unknown_group_ends_the_process_with_a_usage_error_and_no_message_on_standard_output(self):
        client = Client(self, "--group", "Nope")
        code, leftover = client.finish()
        self.assertEqual((code, leftover), (2, []))
        self.assertIn("Unknown group: 'Nope'", client.log)

    def test_a_group_keeps_the_tools_of_that_group(self):
        client = Client(self, "--group", "Spaces")
        names = client.tool_names()
        self.assertTrue({"conflu_spaces", "conflu_space"} <= names)
        self.assertTrue(names.isdisjoint({"conflu_page", "conflu_search"}))
        refused = client.call("conflu_page", {"page": ["2002"]})
        self.assertEqual(refused["error"]["code"], -32602)
        self.assertIn("--group Spaces", refused["error"]["message"])
        self.assertEqual(client.finish()[0], 0)

    def listed(self, *args):
        client = Client(self, *args)
        names = client.tool_names()
        self.assertEqual(client.finish()[0], 0)
        return names

    def test_the_tools_that_write_files_exist_only_with_allow_files(self):
        files = {"conflu_download", "conflu_export"}
        for args in ((), ("--allow-write",), ("--group", "Read"), ("--allow-write", "--group", "Read")):
            with self.subTest(args=args):
                self.assertEqual(self.listed(*args) & files, set())
        for args in (("--allow-files",), ("--allow-write", "--allow-files")):
            with self.subTest(args=args):
                names = self.listed(*args)
                self.assertEqual(names & files, files)
                self.assertEqual("conflu_update" in names, "--allow-write" in args)  # each switch offers its own tools
        refused = Client(self, "--group", "Read")
        answer = refused.call("conflu_download", {"attachmentOrPage": "2002", "all": True})
        self.assertEqual(answer["error"]["code"], -32602)
        self.assertIn("--allow-files", answer["error"]["message"])
        self.assertEqual(refused.finish()[0], 0)
        self.assertFalse((self.folder / "tmp").exists())  # nothing was written

    def test_a_tool_cannot_read_the_settings_file_that_lies_in_the_working_folder(self):
        config = self.folder / "config"
        self.write_config(config)
        client = Client(self, "--allow-write", env={"CONFLUENCE_CONFIG_FILE": str(config)})
        (self.folder / "notes.md").write_text("a note for the page", encoding="utf-8")
        cases = [
            ("conflu_update", {"page": "2005", "file": "config", "dryRun": True}),
            ("conflu_update", {"page": "2005", "file": str(config), "dryRun": True}),
            ("conflu_update", {"page": "2005", "file": "./config", "dryRun": True}),
            ("conflu_create", {"title": "T", "space": "ENG", "file": "sub/../config", "dryRun": True}),
            ("conflu_import_md", {"file": "config", "dryRun": True}),
            ("conflu_attach", {"page": "2005", "file": ["notes.md", "config"], "dryRun": True}),
        ]
        for tool, arguments in cases:
            with self.subTest(tool=tool, arguments=arguments):
                reply = client.call(tool, arguments)
                self.assertTrue(reply["result"]["isError"], reply)
                self.assertNotIn(TOKEN, json.dumps(reply))
                self.assertIn("settings file", reply["result"]["content"][0]["text"])
        copy = self.folder / "copy.txt"
        copy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
        held = client.call("conflu_update", {"page": "2005", "file": "copy.txt", "dryRun": True})
        self.assertTrue(held["result"]["isError"])
        self.assertIn("holds the token", held["result"]["content"][0]["text"])
        for codec in ("utf-16", "utf-32", "utf-32-be"):  # a copy that an editor or `Out-File -Encoding` saved: the CLI reads the first two as text
            copy.write_bytes(config.read_text(encoding="utf-8").encode(codec))
            held = client.call("conflu_update", {"page": "2005", "file": "copy.txt", "dryRun": True})
            self.assertTrue(held["result"]["isError"], codec)
            self.assertIn("holds the token", held["result"]["content"][0]["text"], codec)
        copy.unlink()
        fine = client.call("conflu_update", {"page": "2005", "file": "notes.md", "append": True, "dryRun": True})["result"]  # a file of the project is still read
        self.assertFalse(fine["isError"], fine)
        self.assertIn("a note for the page", json.dumps(json.loads(fine["content"][0]["text"])["payload"]))
        self.assertEqual(client.finish()[0], 0)
        self.assertEqual(self.sent("PUT", ""), [])
        self.assertEqual(self.sent("POST", ""), [])
        self.assertNotIn(TOKEN, client.log)
        self.assertEqual(client.log.count("was refused"), len(cases) + 4)
        self.assertNotIn("Traceback", client.log)

    def test_the_settings_file_is_refused_by_a_hard_link_too(self):
        link = self.folder / "alias.txt"
        try:
            os.link(self.config, link)
        except (OSError, NotImplementedError):
            self.skipTest("this file system has no hard link")
        self.addCleanup(os.unlink, link)
        client = Client(self, "--allow-write")
        reply = client.call("conflu_update", {"page": "2005", "file": "alias.txt", "dryRun": True})
        self.assertTrue(reply["result"]["isError"], reply)
        self.assertNotIn(TOKEN, json.dumps(reply))
        self.assertEqual(client.finish()[0], 0)

    def test_a_folder_link_that_leads_out_of_the_working_folder_is_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="mcp-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "x.md").write_text("outside", encoding="utf-8")
        if not make_link(self, self.folder / "linked", outside):
            self.skipTest("this system makes no link")
        client = Client(self, "--allow-write")
        for value in ("linked/x.md", "sub/../linked/x.md"):
            with self.subTest(value=value):
                reply = client.call("conflu_update", {"page": "2005", "file": value, "dryRun": True})["result"]
                self.assertTrue(reply["isError"], reply)
                self.assertIn("not below the working folder", reply["content"][0]["text"])
        self.assertEqual(client.finish()[0], 0)

    def test_with_allow_files_the_files_go_below_the_working_folder_and_nothing_is_replaced(self):
        page = self.mock.add_page("ENG", "A page with files", "<p>x</p>")
        for name, data in (("tasks.json", b'{"attacker": "controlled bytes"}'), ("memo.txt", b"plain")):
            self.mock.add_attachment(page, name, data, "text/plain")
        outside = Path(tempfile.mkdtemp(prefix="mcp-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "tasks.json").write_text("ORIGINAL user file", encoding="utf-8")
        client = Client(self, "--allow-files")

        def refused(tool, arguments, *needles):
            reply = client.call(tool, arguments)["result"]
            self.assertTrue(reply["isError"], reply)
            text = reply["content"][0]["text"]
            for needle in needles:
                self.assertIn(needle, text)
            self.assertNotIn(TOKEN, text)

        saved = client.call("conflu_download", {"attachmentOrPage": page, "all": True})["result"]
        self.assertFalse(saved["isError"], saved)
        folder = self.folder / "tmp" / "conflu-attachments" / page
        self.assertEqual((folder / "tasks.json").read_bytes(), b'{"attacker": "controlled bytes"}')
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": str(outside), "force": True}, "'force' is not honoured")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": str(outside)}, "not below the working folder")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": os.path.relpath(outside, self.folder) if os.path.splitdrive(str(outside))[0] == os.path.splitdrive(str(self.folder))[0] else str(outside)}, "not below the working folder")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": ".vscode"}, "would write into '.vscode'")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": "."}, "is the working folder itself")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": "\\\\nonexistent.invalid\\share"}, "network or device path")
        refused("conflu_download", {"attachmentOrPage": page, "all": True, "force": True}, "'force' is not honoured")
        # The files are what strangers wrote: `out` must lie below the folder for them, not anywhere below the working folder.
        for elsewhere in ("downloads", "tmp", "tmp/conflu-attachments", "tmp/conflu-attachments/../other", "src/x"):
            refused("conflu_download", {"attachmentOrPage": page, "all": True, "out": elsewhere}, "is not below tmp/conflu-attachments")
        self.assertFalse(any((self.folder / name).exists() for name in ("downloads", "other", "src")))
        chosen = client.call("conflu_download", {"attachmentOrPage": page, "name": ["memo.txt"], "out": "./tmp/../tmp/conflu-attachments/chosen"})["result"]
        self.assertFalse(chosen["isError"], chosen)
        self.assertEqual((self.folder / "tmp" / "conflu-attachments" / "chosen" / "memo.txt").read_bytes(), b"plain")
        self.assertEqual(sorted(path.name for path in outside.iterdir()), ["tasks.json"])
        self.assertEqual((outside / "tasks.json").read_text(encoding="utf-8"), "ORIGINAL user file")
        self.assertFalse((self.folder / ".vscode").exists())
        (folder / "tasks.json").write_text("EDITED by the user", encoding="utf-8")
        refused("conflu_download", {"attachmentOrPage": page, "all": True}, "exists already")  # no force over MCP: a file that exists stays as it is
        self.assertEqual((folder / "tasks.json").read_text(encoding="utf-8"), "EDITED by the user")
        exported = client.call("conflu_export", {"space": "ENG", "out": "tmp/mirror"})["result"]
        self.assertFalse(exported["isError"], exported)
        index = (self.folder / "tmp" / "mirror" / "index.json").read_bytes()
        self.assertIn(b"A page with files", index)
        refused("conflu_export", {"space": "ENG", "out": "tmp/mirror"}, "exists already")
        refused("conflu_export", {"space": "ENG", "out": "tmp/mirror", "force": True}, "'force' is not honoured")
        refused("conflu_export", {"space": "ENG", "out": str(outside / "mirror")}, "not below the working folder")
        refused("conflu_export", {"space": "ENG", "out": ".git/mirror"}, "would write into '.git'")
        self.assertEqual((self.folder / "tmp" / "mirror" / "index.json").read_bytes(), index)
        self.assertFalse((outside / "mirror").exists())
        self.assertIn(TOKEN, self.config.read_text(encoding="utf-8"))  # the settings file is as it was
        self.assertEqual(client.finish()[0], 0)
        self.assertNotIn("Traceback", client.log)

    def test_blanks_around_the_folder_of_a_download_do_not_switch_the_policy_off(self):
        """As a real process: the download strips `out`, so ` .git/hooks` was approved as a folder with a blank in its name and a stranger's
        attachment became a git hook; ` ../../x` wrote above the working folder."""
        page = self.mock.add_page("ENG", "A page with a hook", "<p>x</p>")
        self.mock.add_attachment(page, "pre-commit", b"#!/bin/sh\necho owned\n", "application/octet-stream")
        self.mock.add_attachment(page, "memo.txt", b"plain", "text/plain")
        (self.folder / ".git" / "hooks").mkdir(parents=True)
        (self.folder / "src").mkdir()
        above = self.folder.parent
        names = ("escaped", "escaped2", "deep")
        for name in names:
            self.assertFalse((above / name).exists(), "a folder of an earlier run is in the way")
        files = lambda: sorted(str(path.relative_to(self.folder)) for path in self.folder.rglob("*") if path.is_file())  # noqa: E731
        before = files()
        client = Client(self, "--allow-files")
        spellings = (
            " .git/hooks", "\u00a0.git/hooks", "\u3000.vscode", "\u2003.github/workflows", "\u0085.git/hooks", "\u200b.git/hooks", "\t.git/hooks",
            " ../../escaped2", "\u00a0../../deep", " ../escaped", "\u00a0.", "\u00a0..", " ../src", ".git/hooks ",
        )
        for out in spellings:
            with self.subTest(out=out):
                reply = client.call("conflu_download", {"attachmentOrPage": page, "name": ["pre-commit"], "out": out})
                self.assertTrue(reply["result"]["isError"], reply)
                self.assertIn("starts or ends with a blank or an invisible character", reply["result"]["content"][0]["text"])
        self.assertEqual(files(), before)
        self.assertEqual(list((self.folder / ".git" / "hooks").iterdir()), [])
        self.assertEqual([name for name in names if (above / name).exists()], [])  # nothing above the working folder either
        saved = client.call("conflu_download", {"attachmentOrPage": page, "name": ["memo.txt"], "out": "./tmp/../tmp/conflu-attachments/ok"})["result"]
        self.assertFalse(saved["isError"], saved)
        self.assertEqual((self.folder / "tmp" / "conflu-attachments" / "ok" / "memo.txt").read_bytes(), b"plain")  # the folder that was approved, in full
        self.assertFalse((self.folder / "downloads").exists())
        self.assertEqual(client.finish()[0], 0)
        self.assertEqual(client.log.count("was refused"), len(spellings))

    def test_a_working_folder_that_is_too_wide_refuses_a_call_that_names_a_path_and_runs_the_others(self):
        client = Client(self, "--allow-write", cwd=Path(self.root.anchor))  # the root of the drive: a boundary that keeps nothing out
        refused = client.call("conflu_update", {"page": "2005", "file": "x.md", "dryRun": True})["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("too wide", refused["content"][0]["text"])
        self.assertFalse(result_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))["isError"])
        self.assertEqual(client.finish()[0], 0)

    def test_a_console_that_is_not_utf_8_does_not_matter(self):
        client = Client(self, "--allow-write", isolated=False)
        text = "Zusätzlich: Ünïcode — 日本語 \U0001f600"
        preview = data_of(client.call("conflu_update", {"page": "2005", "body": text, "append": True, "dryRun": True}))
        self.assertIn(text, json.dumps(preview["payload"], ensure_ascii=False))
        self.assertEqual(client.finish()[0], 0)
        self.assertNotIn("Traceback", client.log)

    def test_a_server_started_where_the_system_knows_no_home_folder_still_serves_the_paths_of_a_call(self):
        """With no home folder known `expanduser("~")` is `~`, which read as a path is a folder in the working folder: the working folder was
        taken for the home folder and every call that named a path was refused as too wide."""
        (self.folder / "notes.md").write_text("a note for the page", encoding="utf-8")
        client = Client(self, "--allow-write", env={"USERPROFILE": None, "HOME": None, "HOMEDRIVE": None, "HOMEPATH": None})
        fine = client.call("conflu_update", {"page": "2005", "file": "notes.md", "append": True, "dryRun": True})["result"]
        self.assertFalse(fine["isError"], fine)
        self.assertIn("a note for the page", json.dumps(json.loads(fine["content"][0]["text"])["payload"]))
        refused = client.call("conflu_update", {"page": "2005", "file": "../outside.md", "dryRun": True})["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("not below the working folder", refused["content"][0]["text"])
        self.assertNotIn("too wide", refused["content"][0]["text"])
        self.assertEqual(client.finish()[0], 0)

    @unittest.skipUnless(os.name == "nt", "the home folder of Windows is the profile, and a variable names it")
    def test_a_working_folder_that_is_the_home_folder_refuses_a_call_that_names_a_path(self):
        client = Client(self, "--allow-write", cwd=self.profile)
        refused = client.call("conflu_update", {"page": "2005", "file": "x.md", "dryRun": True})["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("your home folder or a folder above it", refused["content"][0]["text"])
        self.assertFalse(result_of(client.call("conflu_page", {"page": ["2002"], "noBody": True}))["isError"])
        self.assertEqual(client.finish()[0], 0)

    def test_a_client_that_never_reads_standard_error_cannot_stop_the_server(self):
        """The pipe of standard error fills up (4 KiB on Windows) and a write into it waits for good. The server never writes into it itself, so
        it goes on answering and ends when its input ends, with the exit code 0, as it does for a client that reads."""
        client = Client(self, read_log=False)
        for number in range(500):  # each refused call is a line of the log: far more than a pipe holds
            reply = client.call("conflu_convert", {"file": f"../x{number}"})
            self.assertTrue(reply["result"]["isError"], reply)
        self.assertEqual(client.request("ping"), {"jsonrpc": "2.0", "id": client.next_id, "result": {}})
        started = time.monotonic()
        code, leftover = client.finish()
        self.assertEqual((code, leftover), (0, []))
        self.assertLess(time.monotonic() - started, 20)  # it does not wait for a reader that does not read, for longer than a moment

    def test_a_tool_result_does_not_hand_the_model_the_home_folder_or_the_account_name(self):
        """`conflu_doctor` says where the settings file and the cache of the CLI are and where the launcher is: paths that carry the name of the
        account. The last filter over a result puts `~` in their place."""
        config = self.profile / ".config" / "conflu-c-cli" / "config"
        config.parent.mkdir(parents=True)
        self.write_config(config)
        client = Client(self, env={"CONFLUENCE_CONFIG_FILE": None, "XDG_CACHE_HOME": None, "XDG_CONFIG_HOME": None})
        reply = client.call("conflu_doctor", {"quick": True})
        self.assertIn("result", reply, reply)
        text = " ".join(block["text"] for block in reply["result"]["content"])
        self.assertIn("config", text)  # it did say where the settings are
        for spelling in (str(self.profile), self.profile.as_posix(), str(self.profile).replace("\\", "\\\\")):
            self.assertNotIn(spelling, text)
        self.assertNotIn("fake-user", text)
        self.assertIn("~", text)
        try:
            account = getpass.getuser()
        except (ImportError, KeyError, OSError):
            account = ""
        if len(account) >= 3:  # the launcher, found on the PATH of the person, is below the real home folder
            self.assertIsNone(re.search(r"[\\/]" + re.escape(account) + r"(?![\w.-])", text), text)
        self.assertEqual(client.finish()[0], 0)

    @unittest.skipUnless(os.name == "nt", "how Windows reads dots and blanks")
    def test_a_link_below_a_part_of_dots_and_blanks_does_not_get_a_write_out_of_the_working_folder(self):
        """`resolve` stops following links below such a part, and the command then opened the path that it returned, through the link."""
        outside = Path(tempfile.mkdtemp(prefix="mcp-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        if not make_link(self, self.folder / "jlink", outside):
            self.skipTest("this system makes no link")
        client = Client(self, "--allow-files")
        for out in (".. /jlink/a", "...\\jlink\\a", ". \\jlink\\a"):
            with self.subTest(out=out):
                reply = client.call("conflu_export", {"space": "ENG", "out": out})["result"]
                self.assertTrue(reply["isError"], reply)
                self.assertIn("ends in a dot or a blank", reply["content"][0]["text"])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(client.finish()[0], 0)

    def test_a_path_that_is_too_long_is_refused_and_is_no_internal_error(self):
        client = Client(self)
        reply = client.call("conflu_convert", {"file": "a/" * 3000 + "b"})
        self.assertNotIn("error", reply, reply)
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("is longer than 4,096 characters", reply["result"]["content"][0]["text"])
        self.assertEqual(client.finish()[0], 0)

    def test_a_setting_that_changed_is_read_at_the_next_call_and_a_variable_of_the_environment_is_not(self):
        client = Client(self)
        self.assertFalse(result_of(client.call("conflu_spaces", {}))["isError"])
        self.config.write_text(self.config.read_text(encoding="utf-8").replace(TOKEN, "a-token-that-confluence-does-not-know"), encoding="utf-8")
        failed = data_of(client.call("conflu_spaces", {}))["error"]
        self.assertEqual((failed["code"], failed["exitCode"]), ("AUTH", 5))
        self.write_config()
        self.assertFalse(result_of(client.call("conflu_spaces", {}))["isError"])
        self.assertEqual(client.finish()[0], 0)


if __name__ == "__main__":
    unittest.main()
