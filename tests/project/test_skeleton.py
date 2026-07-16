from pathlib import Path


def test_bootstrap_repository_contains_core_documents() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        "README.md",
        "AGENTS.md",
        "docs/vision.md",
        "docs/architecture.md",
        "docs/design-decisions.md",
        "docs/roadmap.md",
        "tasks/README.md",
        "src/lifeos/__init__.py",
    ]
    missing = [path for path in required if not (root / path).exists()]
    assert not missing, f"Missing bootstrap entries: {missing}"
