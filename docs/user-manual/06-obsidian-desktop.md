[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)

# Obsidian Desktop Cockpit

Obsidian is the normal LifeOS interface. The local Python engine starts automatically and
performs every validated read or write. The CLI remains a recovery and developer interface.

## First run

1. Install the plugin folder containing `manifest.json`, `main.js`, and `styles.css` into
   `.obsidian/plugins/lifeos/`.
2. In **Settings → Community plugins**, enable **LifeOS**.
3. Open **LifeOS Settings** and choose **lifeos.yml**, the trusted Python executable, and
   your local actor display name.
4. Enable **Start LifeOS when Obsidian opens**.
5. Click the LifeOS ribbon icon. The connection indicator should show **Connected**.

## Today

The **Today** view combines check-in state, proposed actions, due study work, active
experiments, inbox captures, proposals, attention items, and serious diagnostics. Change
available time, energy, motivation, or mode to refresh the deterministic menu.

Use **Quick Capture** for thoughts, plan tasks, project seeds, journal observations,
flashcards, and metrics. Use **Start**, **Complete**, **Partial**, **Skip**, **Defer**, or
**Cancel** to record what actually happened. Silence remains **unaccounted**, never skipped.

## Attention and reconciliation

Attention cards explain their evidence and offer bounded actions. **Ask tomorrow** snoozes
an item; **Dismiss** hides that stable item; **Stop tracking** changes the routine rather
than blaming the user. Optional background notifications use generic text by default.

## Reviews and proposals

The review wizard saves progress and writes a readable note under `reviews/`. Generated
facts stay inside a managed block while your reflection remains human-owned.

Proposal screens show exact operations and a Python-computed digest. **Approve** and
**Apply** require separate explicit confirmations. A changed proposal invalidates the UI
review immediately.

[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)
