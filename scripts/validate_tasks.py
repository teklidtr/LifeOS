from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = REPO_ROOT / "tasks"
TASK_STATES = ("backlog", "ready", "in-progress", "completed")
_TASK_ID_PATTERN = re.compile(r"LIFEOS-[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_INLINE_COMMENT_PATTERN = re.compile(r"\s+#")

# Closed baseline captured from master before LIFEOS-1718. These completed task
# identities predate the dependency contract and have no depends_on field. The
# expected form is recorded explicitly so editing one into a different legacy
# shape does not silently broaden the exemption.
_LEGACY_DEPENDENCY_BASELINE = {
    "LIFEOS-107.1": "missing",
    "LIFEOS-107.2": "missing",
    "LIFEOS-107.3": "missing",
    "LIFEOS-107.4": "missing",
    "LIFEOS-107.5": "missing",
    "LIFEOS-107.6": "missing",
    "LIFEOS-110": "missing",
    "LIFEOS-116": "missing",
    "LIFEOS-300": "missing",
    "LIFEOS-400": "missing",
    "LIFEOS-500": "missing",
    "LIFEOS-600": "missing",
    "LIFEOS-700": "missing",
    "LIFEOS-800": "missing",
}


@dataclass(frozen=True)
class TaskMetadata:
    path: Path
    task_id: str
    status: str
    depends_on: tuple[str, ...]
    dependency_form: str
    dependency_error: str | None


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if not value:
        return value

    if value[0] in {"'", '"'}:
        quote = value[0]
        closing = value.rfind(quote)
        if closing > 0:
            suffix = value[closing + 1 :].strip()
            if not suffix or suffix.startswith("#"):
                value = value[: closing + 1]
    else:
        comment = _INLINE_COMMENT_PATTERN.search(value)
        if comment is not None:
            value = value[: comment.start()].rstrip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _frontmatter_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening frontmatter delimiter")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    raise ValueError("missing closing frontmatter delimiter")


def _scalar_value(lines: list[str], key: str) -> str:
    prefix = f"{key}:"
    matches = [line for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"frontmatter must contain exactly one {key!r} field")
    value = _strip_scalar(matches[0][len(prefix) :])
    if not value:
        raise ValueError(f"frontmatter field {key!r} must not be empty")
    return value


def _task_id(value: str, *, field: str) -> str:
    task_id = _strip_scalar(value)
    if _TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise ValueError(f"frontmatter field {field!r} must resolve to LIFEOS-* task-ID syntax")
    return task_id


def _task_id_value(lines: list[str]) -> str:
    return _task_id(_scalar_value(lines, "id"), field="id")


def _inline_dependency_list(raw: str) -> tuple[str, ...] | None:
    normalized = _strip_scalar(raw)
    if not (normalized.startswith("[") and normalized.endswith("]")):
        return None
    body = normalized[1:-1].strip()
    if not body:
        return ()
    return tuple(_task_id(item, field="depends_on") for item in body.split(","))


def _dependency_metadata(lines: list[str]) -> tuple[tuple[str, ...], str]:
    prefix = "depends_on:"
    indexes = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if not indexes:
        return (), "missing"
    if len(indexes) != 1:
        raise ValueError("frontmatter must contain at most one 'depends_on' field")

    index = indexes[0]
    raw = lines[index][len(prefix) :].strip()
    if raw:
        dependencies = _inline_dependency_list(raw)
        if dependencies is not None:
            return dependencies, "list"

        scalar = _strip_scalar(raw)
        if _TASK_ID_PATTERN.fullmatch(scalar) is not None:
            return (scalar,), "legacy-scalar"
        return (), "legacy-opaque"

    indented: list[str] = []
    for line in lines[index + 1 :]:
        if not line.startswith((" ", "\t")):
            break
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            indented.append(stripped)

    if not indented:
        return (), "legacy-opaque"
    if indented == ["[]"]:
        return (), "list"
    if all(line.startswith("- ") for line in indented):
        dependencies = tuple(_task_id(line[2:], field="depends_on") for line in indented)
        return dependencies, "list"
    return (), "legacy-opaque"


def parse_task_metadata(path: Path) -> TaskMetadata:
    lines = _frontmatter_lines(path)
    task_id = _task_id_value(lines)
    status = _scalar_value(lines, "status")
    try:
        dependencies, dependency_form = _dependency_metadata(lines)
        dependency_error = None
    except ValueError as exc:
        dependencies = ()
        dependency_form = "invalid"
        dependency_error = str(exc)
    return TaskMetadata(
        path=path,
        task_id=task_id,
        status=status,
        depends_on=dependencies,
        dependency_form=dependency_form,
        dependency_error=dependency_error,
    )


def _dependency_contract_error(state: str, metadata: TaskMetadata) -> str | None:
    if metadata.dependency_error is not None:
        return metadata.dependency_error
    if metadata.dependency_form == "list":
        return None

    if state == "completed":
        inventoried_form = _LEGACY_DEPENDENCY_BASELINE.get(metadata.task_id)
        if inventoried_form == metadata.dependency_form:
            return None
        if inventoried_form is not None:
            return (
                f"completed task dependency form {metadata.dependency_form!r} does not match "
                f"inventoried legacy form {inventoried_form!r}"
            )
        return (
            "completed task 'depends_on' must be a YAML-style task-ID list; "
            "non-list historical forms require an explicit legacy inventory entry"
        )

    return "active task 'depends_on' must be a YAML-style task-ID list"


def validate_task_tree(task_root: Path) -> tuple[str, ...]:
    parsed: list[tuple[str, TaskMetadata]] = []
    errors: list[str] = []

    for state in TASK_STATES:
        state_root = task_root / state
        if not state_root.is_dir():
            errors.append(f"{state_root}: missing task-state directory")
            continue
        for path in sorted(state_root.rglob("*.md")):
            relative = path.relative_to(task_root.parent)
            try:
                metadata = parse_task_metadata(path)
            except (OSError, ValueError) as exc:
                errors.append(f"{relative}: {exc}")
                continue
            parsed.append((state, metadata))
            if metadata.status != state:
                errors.append(
                    f"{relative}: status {metadata.status!r} does not match directory {state!r}"
                )
            dependency_error = _dependency_contract_error(state, metadata)
            if dependency_error is not None:
                errors.append(f"{relative}: {dependency_error}")

    by_id: dict[str, list[Path]] = {}
    for _state, metadata in parsed:
        by_id.setdefault(metadata.task_id, []).append(metadata.path)

    for task_id, paths in sorted(by_id.items()):
        if len(paths) > 1:
            rendered = ", ".join(str(path.relative_to(task_root.parent)) for path in sorted(paths))
            errors.append(f"duplicate task id {task_id!r}: {rendered}")

    known_ids = set(by_id)
    for _state, metadata in parsed:
        relative = metadata.path.relative_to(task_root.parent)
        for dependency in metadata.depends_on:
            if dependency not in known_ids:
                errors.append(f"{relative}: dependency {dependency!r} does not match any task id")

    return tuple(errors)


def main() -> int:
    errors = validate_task_tree(TASK_ROOT)
    if errors:
        print("Task workflow validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Task workflow validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
