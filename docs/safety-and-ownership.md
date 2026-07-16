# Safety and Ownership

## Ownership categories

### Human-owned

Agents may read but not directly overwrite journals, user interpretations, personal profiles, important wiki claims, health conclusions, goals, or purpose statements.

### Agent-managed blocks

Agents may replace only content inside valid managed markers.

### Fully generated files

A generator may replace the whole file only when ownership is recorded in the canonical Git-tracked manifest at `system/generated-ownership.json`.

### System policy

Policy and instruction changes require explicit proposal approval.

## Minimum patch checks

- target exists
- target hash matches
- stable ID is preserved
- note type is preserved unless explicitly approved
- citations are not silently removed
- changes stay inside authorized regions
- managed markers remain valid
- source references resolve
- proposal is explicitly approved
