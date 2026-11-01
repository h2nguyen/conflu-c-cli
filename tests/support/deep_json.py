"""JSON that nests deeper than the decoder of a Python reads, for the tests of what the program does when the decoder gives up.

How deep the decoder reads is no constant: Python 3.13 gives up at 3,000 levels on Windows and at 10,000 on Linux and macOS, 3.12 and 3.13 differ
again, and 3.14 reads as many as its stack holds (60,000 levels are no limit there). A test that needs the decoder to give up cannot count on a number.
So it does one of two things: it makes the decoder give up (`giving_up`), which is the same on every system and version, or it runs the real
thing where the decoder of this Python really gives up on the body (`decoder_gives_up_on`), and is skipped where it reads it.
"""
from __future__ import annotations

import json
from typing import Any
from unittest import mock

LEVELS = 400  # what `giving_up` takes for a nesting that no decoder reads: this many `[` (or `{"a":`) in a row, or more
_REAL_LOADS = json.loads


def decoder_gives_up_on(body: bytes) -> bool:
    """Whether the decoder of this Python gives up on `body` because it nests too deeply. A body that it reads, or that it refuses as no JSON
    after it went through all of the nesting, is not one."""
    try:
        _REAL_LOADS(body)
    except RecursionError:
        return True
    except ValueError:
        return False
    return False


def giving_up():
    """For the length of a `with`: `json.loads` raises the `RecursionError` that the decoder raises when a text nests too deeply, for a text that
    has `LEVELS` openings of an array, or of the object `{"a":`, in a row, or more. Every other text is decoded as it is."""
    markers = ("[" * LEVELS, '{"a":' * LEVELS)

    def loads(text: Any, *args: Any, **kwargs: Any) -> Any:
        probe = text.decode("utf-8", "replace") if isinstance(text, (bytes, bytearray)) else text
        if isinstance(probe, str) and any(marker in probe for marker in markers):
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array from a unicode string")
        return _REAL_LOADS(text, *args, **kwargs)

    return mock.patch("json.loads", loads)
