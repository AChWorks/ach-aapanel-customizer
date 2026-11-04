# PR #16 focused independent-review remediation — 2026-11-04

**Work item:** [Issue #17](https://github.com/AChWorks/ach-aapanel-customizer/issues/17). **Review target:** [PR #16](https://github.com/AChWorks/ach-aapanel-customizer/pull/16), `feat/native-panel-visual-ux-20261103`, based on `main` at `8f677d92b28bb28752c286a3a56286e540c10215`. **Previously reviewed HEAD:** `62eaafd8f8411cf1df88df4b9edaa0baeebd4ff5`; previous independent report: `INCOMPLETE / NO_VERDICT`. This file documents remediation evidence but **is not independent approval**.

## REQUIRED-01: readable primary actions

The official Nginx Demo's `#20a53a` was not sufficiently dark for white 13px button text. Retain `--ach-green:#20a53a` as the native accent; add dedicated filled button tokens `--ach-primary-fill:#167a2f` and `--ach-primary-fill-hover:#146f2b`. Do not change unrelated color roles.

| State | Text | Effective fill | WCAG relative contrast |
| --- | --- | --- | --- |
| Normal | white `#fff` | `#167a2f` | **5.442:1** |
| Hover | white `#fff` | `#146f2b` | **6.290:1** |

The ratios were measured against **actual Chromium-computed styles** both in the local layout renderer and after installing the development ZIP in the authenticated isolated aaPanel guest. The relevant form button remained 32px tall with a 6px radius. A source-level regression test computes luminance for both declared tokens; `tests/manual/layout_browser.cjs` validates actual computed normal/hover colors and requires >= 4.5:1. The native Demo's green is a **visual reference, not an accessibility exemption**.

## REQUIRED-02: Monitor revision/read/write ordering

The previously independent `overviewBusy` and `controlBusy` states allowed an in-flight `get_overview` read to redraw older controls after a later acknowledged `set_control` write.

Correction: `overviewTicket` identifies the most recent eligible read. Starting `set_control` invalidates any previous read and disables manual Refresh during the pending write. Responses carry the **backend state_revision**; a read or acknowledgement below the last accepted revision is refused. Malformed/stale successful write replies display only the last known controls, with edits disabled until a fresh Refresh; no success is claimed. A failed write preserves known controls and explicitly asks for a fresh read. Normal Refresh remains available once no mutation is pending.

Regression coverage includes both old-read completion orders (before and after write acknowledgement), a cached older backend read after acknowledgement, a stale/malformed acknowledged revision, timeout, revision conflict, repeated Refresh, duplicate-write prevention and recovery from a newer revision.

**Actual QEMU browser, synthetic network-only probe:** in the authenticated guest, an existing state at revision 0 was inspected. Playwright intercepted and **fulfilled without forwarding** exactly one `get_overview` response and one `set_control` POST; it held the former and returned synthetic acknowledged revision 1 from the latter. The visible controls advanced to revision 1, then the late old revision 0 response was released; revision 1 and its switch state remained visible. **No real Monitor set_control reached the guest**, no backend state was modified, and no privileged operation was performed. This is a controlled UI concurrency probe, **not a real host mutation or independent reviewer replay**.

## REQUIRED-03: event-aware panel cache invalidation

The prior `sectionsLoaded` booleans made successfully loaded Websites and Activity snapshots remain cached across related actions. The correction introduces only narrow invalidation:

- **Monitor overall / website inventory** acknowledged change: invalidate the Websites snapshot, clear stale table/pagination, invalidate any pending old `get_sites` reply with `siteTicket`, and fetch once on next entrance (or refresh immediately if the panel is already open). Unrelated monitor-module switches leave Websites cached.
- **Monitor writes, Status Pages save/reset and PHP-FPM Apply/Restore** (confirmed, refused, or uncertain outcome): invalidate the Activity snapshot because a new event or failure may be present. Clear stale rows; invalidate in-flight Activity replies with `activityTicket`. One fresh read is sent when Activity is visible, otherwise on next entry. Existing filter selection is retained.
- Ordinary navigation keeps successfully loaded, unmodified views and unsaved Status Pages edits. Only same-filter/same-scope pending Status and Activity reads are deduplicated on tab reentry; deliberate Refresh, scope and filter changes continue to supersede previous reads.

Regressions cover in-flight and loaded Websites reads before/after Monitor changes; failed inventory after monitoring is disabled; one clean cache reuse; Activity changed after Monitor, Status Save/Reset (success and failure), PHP-FPM Apply/Restore (success, timeout, logging warning), a mutation completing while Activity is already open, and pending read deduplication.

No PHP-FPM backend, authorization, Prepare/Apply/Restore implementation, native activity persistence or website lifecycle logic was changed. The warning surfaced after an uncertain Apply or failed Activity persistence remains independent in the PHP-FPM operation notice.

## Verification and current gate

- Python unit tests, Node UI tests, Chromium section/viewport and launcher checks must be rerun on the final committed exact source.
- The development ZIP must be reproducible and installed through the isolated guest's native Third-party **Import plugins** path; no install source SHA is itself proof of guest file-by-file identity.
- Native QEMU guest aaPanel **8.0.7** / Nginx **1.28.3**: the management page in **Official App → Installed** was re-inspected via the authorized browser after the candidate upload; still **Total 0**, no native Nginx `Setting` to open. The separate authenticated official Demo Nginx **1.24.0** study remains valid as a *different environment*. [Measured Demo study](aaPanel-demo-8.0.7-nginx-1.24.0-2026-11-04-study.md).
- The original Issue #17 mandatory **guest Nginx UI** reference is therefore **unresolved** without a legitimately available QEMU installed Nginx manager or an **explicit Owner choice** accepting the public Demo as the substitute. Do not silently waive this acceptance requirement.
- [PR #13](https://github.com/AChWorks/ach-aapanel-customizer/pull/13) and [PR #15](https://github.com/AChWorks/ach-aapanel-customizer/pull/15) remain separate. Their future UI/inventory overlap and PHP-version refresh-on-reentry need reconciliation when integrating.
- Require independent **focused delta re-review** of the exact corrected HEAD and affected interactions, plus required CI and separate Owner Merge authorization. No Merge, Release or Production deployment follows from these notes.
