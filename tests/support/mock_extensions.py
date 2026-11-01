"""The route handlers of the mock Confluence, one per feature area. `MockConfluence` asks them in this order before its own routes."""
from __future__ import annotations

from .mock_access import AccessRoutes
from .mock_attachments import AttachmentsRoutes
from .mock_blogposts import BlogpostsRoutes
from .mock_comments import CommentsRoutes
from .mock_history import HistoryRoutes
from .mock_labels import LabelsRoutes
from .mock_properties import PropertiesRoutes
from .mock_structure import StructureRoutes
from .mock_tasks import TasksRoutes
from .mock_templates import TemplatesRoutes
from .mock_users import UsersRoutes
from .mock_watches import WatchesRoutes

EXTENSIONS = (
    StructureRoutes,
    BlogpostsRoutes,
    HistoryRoutes,
    CommentsRoutes,
    LabelsRoutes,
    AttachmentsRoutes,
    AccessRoutes,
    WatchesRoutes,
    UsersRoutes,
    TasksRoutes,
    PropertiesRoutes,
    TemplatesRoutes,
)
