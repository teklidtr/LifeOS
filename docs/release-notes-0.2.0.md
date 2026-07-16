# LifeOS 0.2.0

LifeOS 0.2.0 ships the Obsidian-native daily interaction layer and the adaptive
planning feedback loop.

Highlights:

- Today dashboard, capture, check-ins, execution outcomes, attention, reviews,
  study controls, proposal UI, and optional background notifications;
- canonical execution history and adaptive preferences;
- duration calibration, separate energy and motivation evidence, repeated
  avoidance questions, and baseline-visible Off, Shadow, and Active modes;
- historical replay with no same-day outcome leakage and no universal score;
- explicit outcome correction, exclusion, diagnosis dismissal, signal disable,
  reset boundaries, and derived-state rebuilds;
- reviewable feedback-driven plan proposals using existing stale-write and
  recovery guarantees;
- preference migration preview and conservative legacy migration to Shadow;
- Python package and Obsidian plugin version 0.2.0 with protocol 1.x
  compatibility.

Limitations:

- desktop Obsidian only;
- no mobile parity;
- no cloud synchronization service;
- adaptive evidence remains descriptive and noncausal;
- the system cannot know whether physical-world work occurred without a record.
