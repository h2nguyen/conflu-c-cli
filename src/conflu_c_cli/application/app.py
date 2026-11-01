"""The application as the driving adapters see it: one object that holds every use case.

`Application.create` wires the use cases from ports only, so the same wiring serves the real adapters (see `bootstrap.py`) and the fakes of
the tests. A use case is built, and its module imported, when something first asks for it: a command that needs two of them does not
pay for the other forty (on a computer where every file costs a virus scan, that is most of what a call to `conflu` takes). What is built
is built once, and use cases that share a part (`import_markdown` and `create_page`) share the same object.
"""
from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Callable, Mapping

from .ports_local import Cache, Clock, ConfigStore, Diagnostics, Docs, Files

if TYPE_CHECKING:
    from . import access as access_area
    from . import attachments as attachments_area
    from . import blogposts as blogposts_area
    from . import comments as comments_area
    from . import history as history_area
    from . import labels as labels_area
    from . import properties as properties_area
    from . import structure as structure_area
    from . import tasks as tasks_area
    from . import templates as templates_area
    from . import users as users_area
    from . import watches as watches_area
    from .attachments import DownloadAttachments, ListAttachments, UploadAttachments
    from .comments import AddComment, ListComments
    from .doctor import Doctor
    from .exporting import ExportPages
    from .extras import ConvertText, InstallSkill, RawApi, ReadDocs
    from .imports import ImportMarkdown, ImportMarkdownDirectory
    from .labels import ChangeLabels, ListLabels
    from .outfile import OutFile
    from .pages import ListPages, ListVersions, ViewPage
    from .ports import ConfluenceGateway
    from .search import SearchContent
    from .services import Services
    from .session import ConfigService, Ping
    from .settings import Settings
    from .spaces import ListSpaces, ShowSpace
    from .tenant import DiscoverTenant
    from .writing import CreatePage, MovePage, UpdatePage


class Application:
    """`settings`, `diagnostics`, `docs`, `files` and `closers` are there from the start; every other attribute is a use case, made on first use
    (the feature areas are reached as `app.<area>.<use case>`)."""

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ConfluenceGateway,
        store: ConfigStore,
        files: Files,
        clock: Clock,
        docs: Docs,
        diagnostics: Diagnostics,
        environ: Mapping[str, str],
        runtime: Mapping[str, str],
        closers: tuple[Callable[[], None], ...] = (),
        cache: Cache | None = None,
    ) -> None:
        self.settings = settings
        self.diagnostics = diagnostics
        self.docs = docs
        self.files = files
        self.closers = closers
        self._gateway = gateway
        self._store = store
        self._clock = clock
        self._environ = environ
        self._runtime = runtime
        self._cache = cache

    @classmethod
    def create(
        cls,
        *,
        settings: Settings,
        gateway: ConfluenceGateway,
        store: ConfigStore,
        files: Files,
        clock: Clock,
        docs: Docs,
        diagnostics: Diagnostics,
        environ: Mapping[str, str],
        runtime: Mapping[str, str],
        closers: tuple[Callable[[], None], ...] = (),
        cache: Cache | None = None,
    ) -> Application:
        return cls(
            settings=settings,
            gateway=gateway,
            store=store,
            files=files,
            clock=clock,
            docs=docs,
            diagnostics=diagnostics,
            environ=environ,
            runtime=runtime,
            closers=closers,
            cache=cache,
        )

    def close(self) -> None:
        """Release what the adapters hold open, such as the connection to Confluence."""
        for closer in self.closers:
            closer()

    @cached_property
    def _services(self) -> Services:
        """What a feature area needs to build its use cases, in one object, so that a new area changes no signature."""
        from .services import Services

        return Services(self._gateway, self.settings, self.diagnostics, self.files, self._clock, self._store, self._environ)

    # -- reading ---------------------------------------------------------------------------------

    @cached_property
    def view_page(self) -> ViewPage:
        from .pages import ViewPage

        return ViewPage(self._gateway, self.settings, self.diagnostics)

    @cached_property
    def list_pages(self) -> ListPages:
        from .pages import ListPages

        return ListPages(self._gateway, self.settings)

    @cached_property
    def tree_pages(self) -> structure_area.TreePages:
        from . import structure as structure_area

        return structure_area.TreePages(self._gateway, self.settings)

    @cached_property
    def list_versions(self) -> ListVersions:
        from .pages import ListVersions

        return ListVersions(self._gateway, self.settings, self.diagnostics)

    @cached_property
    def search_content(self) -> SearchContent:
        from .search import SearchContent

        return SearchContent(self._gateway, self.settings)

    @cached_property
    def list_spaces(self) -> ListSpaces:
        from .spaces import ListSpaces

        return ListSpaces(self._gateway, self.settings)

    @cached_property
    def show_space(self) -> ShowSpace:
        from .spaces import ShowSpace

        return ShowSpace(self._gateway, self.settings)

    @cached_property
    def list_comments(self) -> ListComments:
        from .comments import ListComments

        return ListComments(self._gateway, self.settings, self.diagnostics)

    @cached_property
    def list_labels(self) -> ListLabels:
        from .labels import ListLabels

        return ListLabels(self._gateway)

    @cached_property
    def export_pages(self) -> ExportPages:
        from .exporting import ExportPages

        return ExportPages(self._gateway, self.files, self._clock, self.settings)

    # -- changing --------------------------------------------------------------------------------

    @cached_property
    def add_comment(self) -> AddComment:
        from .comments import AddComment

        return AddComment(self._gateway)

    @cached_property
    def change_labels(self) -> ChangeLabels:
        from .labels import ChangeLabels

        return ChangeLabels(self._gateway)

    @cached_property
    def create_page(self) -> CreatePage:
        from .writing import CreatePage

        return CreatePage(self._gateway, self.settings)

    @cached_property
    def update_page(self) -> UpdatePage:
        from .writing import UpdatePage

        return UpdatePage(self._gateway)

    @cached_property
    def move_page(self) -> MovePage:
        from .writing import MovePage

        return MovePage(self._gateway)

    @cached_property
    def import_markdown(self) -> ImportMarkdown:
        from .imports import ImportMarkdown

        return ImportMarkdown(self.files, self._gateway, self.settings, self.create_page, self.update_page, self.change_labels)

    @cached_property
    def import_markdown_directory(self) -> ImportMarkdownDirectory:
        from .imports import ImportMarkdownDirectory

        return ImportMarkdownDirectory(self.files, self.import_markdown)

    # -- attachments: one set of use cases, with the guards; the three fields are the same objects as in `attachments` -----------------

    @cached_property
    def attachments(self) -> attachments_area.AttachmentsUseCases:
        from . import attachments as attachments_area

        return attachments_area.build(self._services)

    @property
    def list_attachments(self) -> ListAttachments:
        return self.attachments.list_attachments

    @property
    def download_attachments(self) -> DownloadAttachments:
        return self.attachments.download

    @property
    def upload_attachments(self) -> UploadAttachments:
        return self.attachments.upload

    # -- the person's own computer -------------------------------------------------------------

    @cached_property
    def config(self) -> ConfigService:
        from .session import ConfigService

        return ConfigService(self._store, self.settings, self._environ, self._gateway)

    @cached_property
    def ping(self) -> Ping:
        from .session import Ping

        return Ping(self._gateway, self.settings)

    @cached_property
    def doctor(self) -> Doctor:
        from .doctor import Doctor

        return Doctor(self._gateway, self.settings, self.files, self._store.path, self._runtime, self._cache, self._clock)

    @cached_property
    def discover_tenant(self) -> DiscoverTenant:
        from .tenant import DiscoverTenant

        return DiscoverTenant(self._gateway, self.settings, self.config)

    @cached_property
    def read_docs(self) -> ReadDocs:
        from .extras import ReadDocs

        return ReadDocs(self.docs)

    @cached_property
    def install_skill(self) -> InstallSkill:
        from .extras import InstallSkill

        return InstallSkill(self.docs, self.files)

    @cached_property
    def convert_text(self) -> ConvertText:
        from .extras import ConvertText

        return ConvertText()

    @cached_property
    def out_file(self) -> OutFile:
        from .outfile import OutFile

        return OutFile(self.files, self.settings, protected=(self._store.path,))  # the configuration holds the token: it is never written over, nor are its neighbours

    @cached_property
    def raw_api(self) -> RawApi:
        from .extras import RawApi

        return RawApi(self._gateway, self.settings)

    # -- the feature areas: the use cases that are not attributes above, reached as `app.<area>.<use case>` -------------------------

    @cached_property
    def structure(self) -> structure_area.StructureUseCases:
        from . import structure as structure_area

        return structure_area.build(self._services)

    @cached_property
    def blogposts(self) -> blogposts_area.BlogpostsUseCases:
        from . import blogposts as blogposts_area

        return blogposts_area.build(self._services)

    @cached_property
    def history(self) -> history_area.HistoryUseCases:
        from . import history as history_area

        return history_area.build(self._services)

    @cached_property
    def comments(self) -> comments_area.CommentsUseCases:
        from . import comments as comments_area

        return comments_area.build(self._services)

    @cached_property
    def labels(self) -> labels_area.LabelsUseCases:
        from . import labels as labels_area

        return labels_area.build(self._services)

    @cached_property
    def access(self) -> access_area.AccessUseCases:
        from . import access as access_area

        return access_area.build(self._services)

    @cached_property
    def watches(self) -> watches_area.WatchesUseCases:
        from . import watches as watches_area

        return watches_area.build(self._services)

    @cached_property
    def users(self) -> users_area.UsersUseCases:
        from . import users as users_area

        return users_area.build(self._services)

    @cached_property
    def tasks(self) -> tasks_area.TasksUseCases:
        from . import tasks as tasks_area

        return tasks_area.build(self._services)

    @cached_property
    def properties(self) -> properties_area.PropertiesUseCases:
        from . import properties as properties_area

        return properties_area.build(self._services)

    @cached_property
    def templates(self) -> templates_area.TemplatesUseCases:
        from . import templates as templates_area

        return templates_area.build(self._services)
