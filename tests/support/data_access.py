"""The synthetic people, groups, roles and permissions of the access area, in one place, so that the fake and the mock Confluence answer alike.

Ids 7500 to 7599 belong to this area: content of the kinds that no other fixture has a use for, so that nothing collides. Nobody here is a real person.
"""
from __future__ import annotations

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"  # the account of the token, as in every fixture
SECOND = "5b10ac8d82e05b22cc7d4ef6"  # another account
GROUP = "00000000-0000-4000-8000-0000000000a1"
GROUP_TWO = "00000000-0000-4000-8000-0000000000a2"
ROLE_ADMIN = "00000000-0000-4000-8000-0000000000b1"
ROLE_CONTRIBUTOR = "00000000-0000-4000-8000-0000000000b2"
ROLE_VIEWER = "00000000-0000-4000-8000-0000000000b3"
ROLE_REVIEWERS = "00000000-0000-4000-8000-0000000000b4"  # a role that nobody holds in ENG

# Content that exists in the fake and in the mock from the start, with what Confluence calls it (see `content_kinds`).
KINDS = {"7501": "folder", "7511": "blogpost", "7521": "whiteboard", "7531": "database", "7541": "embed", "7551": "custom"}

# What the token's user may do, `(operation, targetType)`, for each kind of what has operations; the default of every id.
OPERATIONS = {
    "page": (("read", "page"), ("update", "page"), ("delete", "page"), ("copy", "page"), ("archive", "page"), ("restrict_content", "page"), ("create", "attachment"), ("create", "comment")),
    "blogpost": (("read", "blogpost"), ("update", "blogpost"), ("delete", "blogpost"), ("restrict_content", "blogpost"), ("create", "comment")),
    "folder": (("read", "folder"), ("update", "folder"), ("delete", "folder"), ("restrict_content", "folder")),
    "whiteboard": (("read", "whiteboard"), ("update", "whiteboard"), ("delete", "whiteboard"), ("restrict_content", "whiteboard")),
    "database": (("read", "database"), ("update", "database"), ("delete", "database"), ("restrict_content", "database")),
    "embed": (("read", "embed"), ("update", "embed"), ("delete", "embed")),
    "footer-comment": (("read", "comment"), ("update", "comment"), ("delete", "comment")),
    "inline-comment": (("read", "comment"), ("update", "comment"), ("delete", "comment")),
    "attachment": (("read", "attachment"), ("delete", "attachment")),
    "custom": (("read", "page"), ("update", "page"), ("delete", "page")),
    "space": (
        ("read", "space"), ("create", "page"), ("create", "blogpost"), ("create", "comment"), ("create", "attachment"), ("delete", "page"),
        ("delete", "comment"), ("export", "space"), ("restrict_content", "space"),
    ),
}
# A page that this account may read and comment on, and not change.
OPERATIONS_BY_ID = {"2003": (("read", "page"), ("create", "comment"))}

# The restriction state of content, `(state, when, who, ((operation, principal type, principal id), ...))`: all other content is OPEN.
RESTRICTIONS = {
    "2002": (
        "VIEW_RESTRICTED", "2026-10-03T09:00:00.000Z", ACCOUNT,
        (("read", "user", ACCOUNT), ("read", "user", SECOND), ("read", "group", GROUP), ("update", "user", ACCOUNT), ("update", "group", GROUP)),
    ),
    "2003": ("EDIT_RESTRICTED", "2026-10-04T09:00:00.000Z", ACCOUNT, (("update", "user", ACCOUNT),)),
    "7501": ("VIEW_RESTRICTED", "2026-10-05T09:00:00.000Z", SECOND, (("read", "group", GROUP), ("update", "group", GROUP))),
}

ROLE_MODE = "ROLES_TRANSITION"  # both models are read, so that one command line reaches every call of the area

# The permission model of a space, `(id, principal type, principal id, operation, target type)`, by the id of the space.
SPACE_PERMISSIONS = {
    "1001": (
        ("sp-1", "user", ACCOUNT, "read", "space"),
        ("sp-2", "user", ACCOUNT, "create", "page"),
        ("sp-3", "user", ACCOUNT, "administer", "space"),
        ("sp-4", "user", SECOND, "read", "space"),
        ("sp-5", "group", GROUP, "read", "space"),
        ("sp-6", "group", GROUP, "create", "page"),
        ("sp-7", "group", GROUP, "create", "comment"),
    ),
}
# The roles, `(id, name, type)`, and the role model of a space, `(principal type, principal id, role id)`, by the id of the space.
SPACE_ROLES = (
    (ROLE_ADMIN, "Admin", "SYSTEM"),
    (ROLE_CONTRIBUTOR, "Contributor", "SYSTEM"),
    (ROLE_VIEWER, "Viewer", "SYSTEM"),
    (ROLE_REVIEWERS, "Reviewers", "CUSTOM"),
)
ROLE_ASSIGNMENTS = {
    "1001": (
        ("USER", ACCOUNT, ROLE_ADMIN),
        ("USER", SECOND, ROLE_VIEWER),
        ("GROUP", GROUP, ROLE_CONTRIBUTOR),
        ("GROUP", GROUP_TWO, ROLE_VIEWER),
        ("ACCESS_CLASS", "authenticated-users", ROLE_VIEWER),
    ),
}
