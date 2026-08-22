# Deferred: a project section in the filter drawer

**Status:** deferred on purpose. Decide after using All-projects mode for a
while. Written 2026-08-22 so the analysis does not have to be redone.

## What it would be

A second section in the dashboard's filter drawer — beside the existing tag
filter — that narrows the board to one project when `?project=__all__` has
merged them all.

## Why it is not built yet

It is not needed to *reach* a single project: the scope picker already does
that. It only makes reaching one **cheaper**. Whether that is worth ~50 lines
in `index.html` depends on how the merged board actually gets used, and that
is not knowable in advance.

The cost is specific. The scope work touches `index.html` in 29 lines, kept
deliberately small because that file is 327 KB of upstream UI we do not want
to own. A project section roughly triples that footprint. Rule 3 of
`INTEGRATION.md` — every feature branch touches as little of the original as
possible — is what makes this a decision rather than an obvious yes.

## What would justify building it

Concrete signals, in rough order of strength:

1. **Reload fatigue.** You find yourself switching projects through the picker
   many times in one sitting. Each switch is a full `location.reload()`,
   because changing the data source invalidates every cached panel. A drawer
   filter narrows the already-merged array with no round-trip.
2. **All mode is where you start.** If the merged board is the default view
   and single-project mode is the exception, the filter belongs where you
   already are.
3. **Comparing two or three projects.** Repeated A/B switching between the
   same few boards is the case the picker serves worst.

Signals it is *not* worth it:

- You mostly work in one project and use All mode only as a weekly overview.
- Tag filtering across the merged board already answers your questions —
  tags cross projects, and that may be the more natural axis.
- You reach for `lattice aggregate --list-projects` in a terminal instead.

## The plan

The drawer's pattern is regular; this is a near-copy of the tag section.

| Piece | Where | Approx |
|---|---|---|
| Section markup | `#filter-panel-body`, beside `#filter-section-tag` | 3 lines |
| `renderProjectFilter()` | mirror of `renderFilterPanel()` | 25 |
| `setProjectFilter()` | mirror of `setTagFilter()` | 12 |
| Board predicate | extend `visibleTasks` in `renderBoard()` | 3 |
| List predicate | one clause in `applyListFilters()` | 3 |
| Badge counter | `updateFiltersBtnAffordance()` hardcodes `· 1`; must count | 4 |

The existing pieces to copy:

- `renderFilterPanel()` — derives options from the loaded `tasks` array,
  renders a `<select>`, hides the section when there is nothing to offer.
- `setTagFilter()` — sets state, mirrors to the URL with
  `history.replaceState`, updates the button badge, re-renders the current
  view (`renderBoard()` for board, `applyListFilters()` for list).
- The board applies it as `visibleTasks = tasks.filter(...)`.

Rows already carry what is needed: merged rows have `project`, `project_code`
and `project_root` (that is how card actions route to the right board), so no
API change is required.

It should **self-hide** in single-project mode, where every row shares one
`project` value — the same way the tag section hides when no task has tags.
That behaviour is already in `renderFilterPanel()` and comes free.

## Decide these first

- **The URL key cannot be `project`.** That name is already the API/scope
  parameter; using it in the page URL would mean two different things
  depending on who reads it. Use `?board=`. (The page URL currently uses
  `?tag=` and no `project` key.)
- **Single-select, at least to begin with.** Multi-select is more useful —
  "these three repos" — but it breaks the single-`<select>` idiom, the URL
  mirroring, and the badge counter, all of which assume one value. Matching
  the existing idiom keeps the diff honest; multi is a separate, larger
  change and probably wants a different control.

## What it will not fix

Graph, structure and activity are per-project endpoints; in All mode they
fall back to the default project. A drawer filter narrows rows in the board
and list views only. For those other views the scope picker remains the way
to move, and no amount of client-side filtering changes that.

## Where it belongs

On `feat/aggregate`. It depends only on scope, which that branch introduces,
and not at all on completion — so it stays independently upstreamable and is
not an integration-only commit. Adding it means one more commit there, then
an `INTEGRATION.md` rebuild.

## Background

`docs/user-reference.md` § "Working across projects" describes the shipped
behaviour. The relevant distinction: the scope selector is **server-side** and
chooses *which board a request reads*, while the drawer is **client-side** and
narrows *rows already fetched*. They compose without conflict — which is why
the existing tag filter already works across projects in All mode, with no
change at all.
