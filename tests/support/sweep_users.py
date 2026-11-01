"""The sweep lines of looking up people: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock knows Alex Example from the start. A line that is refused (no `--with-users`, or the privacy policy) sends nothing."""
from __future__ import annotations

from .sweeps import line

LINES = (
    line("users", "search", "alex", "--with-users"),
    line("users", "search", "alex", "--with-users", "--all"),
    line("users", "search", "alex", "--with-users", "--limit", "1", "--start", "1"),
    line("users", "search", "alex", "--with-users", "--select", "accountId,displayName", "--format", "tsv"),
    line("users", "search", "-", "--with-users", stdin='Alex "Example"\n'),  # a double quote in the name stays a text
    line("users", "lookup", "5b10ac8d82e05b22cc7d4ef5", "--with-users"),
    line("users", "lookup", "5b10ac8d82e05b22cc7d4ef5", "--with-users", "--select", "accountId,displayName", "--format", "md"),
    line("users", "lookup", "5b10ac8d82e05b22cc7d4ef5", "0000000000000000000000ff", "--with-users", "--json"),  # the second is unknown: left out
    line("users", "search", "alex", code=2),  # people are shown on request only
    line("users", "lookup", "5b10ac8d82e05b22cc7d4ef5", "--with-users", env=(("CONFLUENCE_HIDE_USERS", "true"),), code=1),  # and never under the policy
)
