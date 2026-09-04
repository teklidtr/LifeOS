from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = REPO_ROOT / "tasks"
TASK_STATES = ("backlog", "ready", "in-progress", "completed")


@dataclass(frozen=True)
class TaskMetadata:
    path: Path
    task_id: str
    status: str


def _strip_scalar(value: str) -> str:
    value = value.strip()
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


def parse_task_metadata(path: Path) -> TaskMetadata:
    lines = _frontmatter_lines(path)
    return TaskMetadata(
        path=path,
        task_id=_scalar_value(lines, "id"),
        status=_scalar_value(lines, "status"),
    )


def validate_task_tree(task_root: Path) -> tuple[str, ...]:
    parsed: list[TaskMetadata] = []
    errors: list[str] = []

    for state in TASK_STATES:
        state_root = task_root / state
        if not state_root.is_dir():
            errors.append(f"{state_root}: missing task-state directory")
            continue
        for path in sorted(state_root.glob("*.md")):
            relative = path.relative_to(task_root.parent)
            try:
                metadata = parse_task_metadata(path)
            except (OSError, ValueError) as exc:
                errors.append(f"{relative}: {exc}")
                continue
            parsed.append(metadata)
            if metadata.status != state:
                errors.append(
                    f"{relative}: status {metadata.status!r} does not match directory {state!r}"
                )

    by_id: dict[str, list[Path]] = {}
    for metadata in parsed:
        by_id.setdefault(metadata.task_id, []).append(metadata.path)

    for task_id, paths in sorted(by_id.items()):
        if len(paths) > 1:
            rendered = ", ".join(
                str(path.relative_to(task_root.parent)) for path in sorted(paths)
            )
            errors.append(f"duplicate task id {task_id!r}: {rendered}")

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
