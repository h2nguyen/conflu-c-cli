"""The application as the driving adapters see it: one object holding every use case.

`Application.create` wires the use cases from ports only, so the same wiring serves the real
adapters (see `bootstrap.py`) and the fakes of the tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .attachments import DownloadAttachments, ListAttachments, UploadAttachments
from .comments import AddComment, ListComments
from .doctor import Doctor
from .exporting import ExportPages
from .extras import ConvertText, InstallSkill, RawApi, ReadDocs
from .imports import ImportMarkdown, ImportMarkdownDirectory
from .labels import ChangeLabels, ListLabels
from .pages import ListPages, ListVersions, TreePages, ViewPage
from .ports import Clock, ConfigStore, ConfluenceGateway, Diagnostics, Docs, Files
from .search import SearchContent
from .session import ConfigService, Ping
from .settings import Settings
from .spaces import ListSpaces, ShowSpace
from .writing import CreatePage, MovePage, UpdatePage


@dataclass
class Application:
    settings: Settings
    diagnostics: Diagnostics
    docs: Docs
    files: Files
    view_page: ViewPage
    list_pages: ListPages
    tree_pages: TreePages
    list_versions: ListVersions
    search_content: SearchContent
    list_spaces: ListSpaces
    show_space: ShowSpace
    list_comments: ListComments
    add_comment: AddComment
    list_labels: ListLabels
    change_labels: ChangeLabels
    list_attachments: ListAttachments
    download_attachments: DownloadAttachments
    upload_attachments: UploadAttachments
    create_page: CreatePage
    update_page: UpdatePage
    move_page: MovePage
    import_markdown: ImportMarkdown
    import_markdown_directory: ImportMarkdownDirectory
    export_pages: ExportPages
    config: ConfigService
    ping: Ping
    doctor: Doctor
    read_docs: ReadDocs
    install_skill: InstallSkill
    convert_text: ConvertText
    raw_api: RawApi
    closers: tuple[Callable[[], None], ...] = ()

    def close(self) -> None:
        """Release what the adapters hold open, such as the connection to Confluence."""
        for closer in self.closers:
            closer()

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
    ) -> "Application":
        create_page = CreatePage(gateway, settings)
        update_page = UpdatePage(gateway)
        change_labels = ChangeLabels(gateway)
        import_markdown = ImportMarkdown(files, gateway, settings, create_page, update_page, change_labels)
        return cls(
            settings=settings,
            diagnostics=diagnostics,
            docs=docs,
            files=files,
            view_page=ViewPage(gateway, settings, diagnostics),
            list_pages=ListPages(gateway, settings),
            tree_pages=TreePages(gateway, settings),
            list_versions=ListVersions(gateway, settings, diagnostics),
            search_content=SearchContent(gateway, settings),
            list_spaces=ListSpaces(gateway),
            show_space=ShowSpace(gateway, settings),
            list_comments=ListComments(gateway, settings, diagnostics),
            add_comment=AddComment(gateway),
            list_labels=ListLabels(gateway),
            change_labels=change_labels,
            list_attachments=ListAttachments(gateway),
            download_attachments=DownloadAttachments(gateway, files),
            upload_attachments=UploadAttachments(gateway, files),
            create_page=create_page,
            update_page=update_page,
            move_page=MovePage(gateway),
            import_markdown=import_markdown,
            import_markdown_directory=ImportMarkdownDirectory(files, import_markdown),
            export_pages=ExportPages(gateway, files, clock, settings),
            config=ConfigService(store, settings, environ, gateway),
            ping=Ping(gateway, settings),
            doctor=Doctor(gateway, settings, files, store.path, runtime),
            read_docs=ReadDocs(docs),
            install_skill=InstallSkill(docs, files),
            convert_text=ConvertText(),
            raw_api=RawApi(gateway, settings),
            closers=closers,
        )
