# DOGFOOD — ansi-editor

_Session: 2026-04-23T13:36:29, driver: pty, duration: 3.0 min_

**PASS** — ran for 1.8m, captured 22 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found no findings worth flagging. Game reached 116 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`. 1 coverage note(s) — see Coverage section.

## Findings

### Blockers

_None._

### Majors

_None._

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)

_None._

## Coverage

- Driver backend: `pty`
- Keys pressed: 799 (unique: 58)
- State samples: 148 (unique: 116)
- Score samples: 0
- Milestones captured: 1
- Phase durations (s): A=66.5, B=21.3, C=18.1
- Snapshots: `/home/brian/AI/projects/tui-dogfood/reports/snaps/ansi-editor-20260423-133441`

Unique keys exercised: +, ,, -, ., /, 0, 1, 2, 3, 4, 5, :, ;, =, ?, H, R, [, ], a, b, backspace, c, ctrl+l, d, delete, down, end, enter, escape, f1, f2, h, home, j, k, l, left, m, n ...

### Coverage notes

- **[CN1] Phase A exited early due to saturation**
  - State hash unchanged for 10 consecutive samples after 88 golden-path loop(s); no further learning expected.

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.3 | 0.0 | `ansi-editor-20260423-133441/milestones/first_input.txt` | key=right |
