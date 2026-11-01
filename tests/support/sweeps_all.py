"""The modules of the conformance sweep, one for each feature area. A new area adds its module here (and nowhere else)."""
from __future__ import annotations

from . import (
    sweep_access,
    sweep_attachments,
    sweep_blogposts,
    sweep_comments,
    sweep_core,
    sweep_history,
    sweep_labels,
    sweep_personal,
    sweep_properties,
    sweep_structure,
    sweep_tasks,
    sweep_templates,
    sweep_users,
    sweep_watches,
)

SWEEPS = (
    sweep_core,
    sweep_structure,
    sweep_blogposts,
    sweep_history,
    sweep_comments,
    sweep_labels,
    sweep_attachments,
    sweep_access,
    sweep_watches,
    sweep_users,
    sweep_tasks,
    sweep_properties,
    sweep_templates,
    sweep_personal,
)
