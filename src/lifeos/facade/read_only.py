from dataclasses import dataclass
from pathlib import Path

from lifeos.facade.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ingestion.taxonomy import extract_source_taxonomy
from lifeos.vault import VaultAccessError, read_vault_markdown
from lifeos.registry.file_tracking import FileTrackingError, validate_vault_path

READ_MARKDOWN_DESCRIPTOR = ToolDescriptor(
    name="vault.read_markdown",
    description="Read the Markdown body of a vault-relative file.",
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
