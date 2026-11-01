"""The formats that a body is shown or given in.

They are in a module of their own because the command line offers them as the choices of its options when it starts, and `rendering.py`, which converts
between them, is code that a command that never converts a body (`conflu search`) should not have to load for that.
"""

BODY_FORMATS = ("markdown", "text", "storage")  # what a body is shown as
INPUT_FORMATS = ("markdown", "storage")  # what a body is given as
