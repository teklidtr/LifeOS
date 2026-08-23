from dataclasses import dataclass
from pathlib import Path

from lifeos.facade.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.markdown.parser import parse_markdown_note
from lifeos.context import ContextSearchError, lexical_search_report
from lifeos.ingestion.taxonomy import extract_source_taxonomy
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.registry.file_tracking import FileTrackingError, validate_vault_path

READ_MARKDOWN_DESCRIPTOR = ToolDescriptor(
    name="vault.read_markdown",
    description="Read the Markdown body of a vault-relative file.",
    effect=ToolEffect.READ_ONLY,
)

WIKI_SEARCH_DESCRIPTOR = ToolDescriptor(
    name="wiki.search",
    description="Search durable wiki Markdown before choosing ingestion targets.",
    effect=ToolEffect.READ_ONLY,
)


@dataclass(frozen=True, slots=True)
class ReadMarkdownRequest:
    vault_path: str


@dataclass(frozen=True, slots=True)
class ReadMarkdownResult:
    vault_path: str
    markdown_body: str
    source_tags: tuple[str, ...] = ()
    source_topics: tuple[str, ...] = ()


def read_markdown(
    *,
    vault_root: Path,
    request: ReadMarkdownRequest,
) -> ReadMarkdownResult:
    """Read a Markdown file from the vault, returning only its body."""
    try:
        validate_vault_path(request.vault_path)
    except FileTrackingError as e:
        raise ToolValidationError(f"Invalid vault path: {e}") from e

    if not request.vault_path.endswith(".md"):
        raise ToolValidationError("Only Markdown files (.md) are supported")

    try:
        source = read_vault_markdown(vault_root, request.vault_path)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            raise ToolNotFoundError("Target file not found") from exc
        if exc.code in {"unsafe-symlink", "invalid-path"}:
            raise ToolValidationError("Unsafe vault path") from exc
        if exc.code == "unsafe-file-type":
            raise ToolExecutionError("Target is not a regular file") from exc
        if exc.code == "invalid-utf8":
            raise ToolExecutionError("File is not valid UTF-8") from exc
        raise ToolExecutionError("Failed to read file") from exc

    parsed = parse_markdown_note(source.path, content=source.content)
    taxonomy = extract_source_taxonomy(parsed.frontmatter)

    return ReadMarkdownResult(
        vault_path=request.vault_path,
        markdown_body=parsed.body,
        source_tags=taxonomy.tags,
        source_topics=taxonomy.topics,
    )


@dataclass(frozen=True, slots=True)
class WikiSearchRequest:
    query: str
    limit: int = 8

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be a non-empty string")
        if type(self.limit) is not int or not 1 <= self.limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")


@dataclass(frozen=True, slots=True)
class WikiSearchHit:
    path: str
    title: str
    description: str
    excerpt: str
    score: int


@dataclass(frozen=True, slots=True)
class WikiSearchResult:
    query: str
    hits: tuple[WikiSearchHit, ...]


def search_wiki(
    *,
    vault_root: Path,
    request: WikiSearchRequest,
) -> WikiSearchResult:
    """Search only canonical wiki Markdown with deterministic lexical ranking."""
    try:
        report = lexical_search_report(
            vault_root=vault_root,
            query=request.query,
            limit=request.limit,
            path_prefix="wiki",
        )
    except ContextSearchError as exc:
        raise ToolValidationError(str(exc)) from exc

    return WikiSearchResult(
        query=request.query,
        hits=tuple(
            WikiSearchHit(
                path=item.path,
                title=item.title,
                description=item.description,
                excerpt=item.excerpt,
                score=item.score,
            )
            for item in report.results
        ),
    )
