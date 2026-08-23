from __future__ import annotations
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manual = root / "docs" / "user-manual"
missing = []
for source in manual.glob("*.md"):
    for target in re.findall(r"\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)", source.read_text()):
        if not (source.parent / target).resolve().exists():
            missing.append(f"{source.name}: {target}")
if missing:
    raise SystemExit("Broken manual links:\n" + "\n".join(missing))
print(f"Validated manual links in {len(list(manual.glob('*.md')))} chapters.")
