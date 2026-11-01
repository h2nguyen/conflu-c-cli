"""The tests run from a source checkout: put `src/` on the import path."""
import faulthandler
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.support import github_annotations  # noqa: E402 - after the import path is set

github_annotations.install()

# CI sets a limit in seconds. A run that is still going when it is over prints the stack of every thread, which names the test that hangs,
# and stops, where the job would be cancelled later without a word.
_LIMIT = os.environ.get("CONFLU_TEST_TIMEOUT", "")
if _LIMIT.isdigit() and int(_LIMIT) > 0:
    faulthandler.dump_traceback_later(int(_LIMIT), exit=True)
