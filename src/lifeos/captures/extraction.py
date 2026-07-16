"""Deterministic local extraction with bounded reads and rebuildable results."""

from __future__ import annotations

import json
import struct
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .contracts import AttachmentManifest, CaptureError
from .storage import AttachmentStore

ExtractionQuality = Literal["high", "medium", "low", "unavailable"]


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    attachment_id: str
    source_hash: str
    method: str
    method_version: str
    status: Literal["completed", "unavailable", "failed", "cancelled", "stale"]
    text: str = ""
    quality: ExtractionQuality = "unavailable"
    source_locator: str | None = None
    metadata: dict[str, object] | None = None
    warning: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ExtractionCancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def checkpoint(self) -> None:
        if self.cancelled:
            raise CaptureError("cancelled", "Attachment extraction was cancelled.")


class LocalExtractionService:
    def __init__(
        self, *, vault_root: Path, runtime_dir: Path, max_text_bytes: int = 2_000_000
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.max_text_bytes = max_text_bytes
        self.store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)

    def extract(
        self, manifest: AttachmentManifest, *, cancellation: ExtractionCancellation | None = None
    ) -> ExtractionResult:
        token = cancellation or ExtractionCancellation()
        token.checkpoint()
        audit = self.store.audit(manifest.attachment_id)
        if audit.status != "ok":
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "local",
                "1",
                "stale" if audit.status == "changed" else "failed",
                warning=audit.details,
            )
        path = self.vault_root / manifest.canonical_path
        media = manifest.media_type
        try:
            if media.startswith("text/") or path.suffix.lower() in {
                ".md",
                ".txt",
                ".csv",
                ".json",
                ".yaml",
                ".yml",
            }:
                raw = self._bounded_read(path)
                token.checkpoint()
                text = raw.decode("utf-8")
                return ExtractionResult(
                    manifest.attachment_id,
                    manifest.content_hash,
                    "utf8-text",
                    "1",
                    "completed",
                    text=text,
                    quality="high",
                )
            if media == "application/pdf" or path.suffix.lower() == ".pdf":
                return self._pdf(path, manifest, token)
            if media.startswith("image/"):
                metadata = self._image_metadata(path)
                return ExtractionResult(
                    manifest.attachment_id,
                    manifest.content_hash,
                    "image-metadata",
                    "1",
                    "completed",
                    quality="high",
                    metadata=metadata,
                )
            if media.startswith("audio/") or path.suffix.lower() == ".wav":
                metadata = self._audio_metadata(path)
                return ExtractionResult(
                    manifest.attachment_id,
                    manifest.content_hash,
                    "audio-metadata",
                    "1",
                    "completed",
                    quality="high",
                    metadata=metadata,
                )
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "none",
                "1",
                "unavailable",
                warning="The file is preserved but no local extractor supports this format.",
            )
        except UnicodeDecodeError:
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "utf8-text",
                "1",
                "failed",
                warning="Text attachment is not valid UTF-8.",
            )
        except CaptureError:
            raise
        except Exception as exc:
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "local",
                "1",
                "failed",
                warning=str(exc),
            )

    def publish(self, result: ExtractionResult) -> str:
        root = self.runtime_dir / "captures" / "extracted"
        root.mkdir(parents=True, exist_ok=True)
        relative = f"captures/extracted/{result.attachment_id}.json"
        target = self.runtime_dir / relative
        target.write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        return relative

    def load(self, attachment_id: str) -> ExtractionResult | None:
        target = self.runtime_dir / "captures" / "extracted" / f"{attachment_id}.json"
        if not target.exists():
            return None
        data = json.loads(target.read_text())
        return ExtractionResult(**data)

    def _bounded_read(self, path: Path) -> bytes:
        size = path.stat().st_size
        if size > self.max_text_bytes:
            raise CaptureError(
                "oversized_for_extraction",
                "Attachment exceeds the configured extraction limit.",
                {"byte_size": size, "limit": self.max_text_bytes},
            )
        return path.read_bytes()

    def _pdf(
        self, path: Path, manifest: AttachmentManifest, token: ExtractionCancellation
    ) -> ExtractionResult:
        raw = self._bounded_read(path)
        token.checkpoint()
        if b"/Encrypt" in raw[:200_000]:
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "pdf-local",
                "1",
                "unavailable",
                warning="Encrypted PDFs are preserved but not extracted locally.",
            )
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError:
            return ExtractionResult(
                manifest.attachment_id,
                manifest.content_hash,
                "pdf-local",
                "1",
                "unavailable",
                warning="PDF text extraction is unavailable because the optional local parser is not installed.",
            )
        reader = PdfReader(path)
        pages: list[str] = []
        for index, page in enumerate(reader.pages):
            token.checkpoint()
            pages.append(f"[Page {index + 1}]\n{page.extract_text() or ''}")
        return ExtractionResult(
            manifest.attachment_id,
            manifest.content_hash,
            "pypdf",
            getattr(__import__("pypdf"), "__version__", "unknown"),
            "completed",
            text="\n\n".join(pages),
            quality="medium",
            source_locator="page",
        )

    @staticmethod
    def _image_metadata(path: Path) -> dict[str, object]:
        raw = path.read_bytes()[:32]
        if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
            width, height = struct.unpack(">II", raw[16:24])
            return {"format": "png", "width": width, "height": height}
        if raw.startswith(b"\xff\xd8"):
            return {"format": "jpeg", "byte_size": path.stat().st_size}
        return {
            "format": path.suffix.lower().lstrip(".") or "unknown",
            "byte_size": path.stat().st_size,
        }

    @staticmethod
    def _audio_metadata(path: Path) -> dict[str, object]:
        if path.suffix.lower() != ".wav":
            return {
                "format": path.suffix.lower().lstrip(".") or "unknown",
                "byte_size": path.stat().st_size,
            }
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            return {
                "format": "wav",
                "duration_seconds": frames / rate if rate else None,
                "sample_rate": rate,
                "channels": audio.getnchannels(),
            }
