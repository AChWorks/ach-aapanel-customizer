# Native Nginx follow-up — real QEMU UI acceptance evidence (2026-11-04)

**Historical first QA scope:** stacked visual/UI follow-up originally branched from PR #16 HEAD `f5832b5ec8556c0e4bc57db36f092256070adddb`. The final reconciled, still-unreleased evidence is at the end of this file. Repository `AChWorks/ach-aapanel-customizer`; Issue #17. This evidence is produced by the **development Master**, not the independent reviewer or a release approval.

## Reference directly observed, not assumed

The authorized Chromium session opened the **actual Nginx 1.28.3 Setting modal** in the **same Debian 12 / aaPanel 8.0.7 isolated QEMU guest**, from normal Official App navigation. The complete seven-section native browser inspection, measured modal and 150×32 optimization field wrappers, 170px sidebar, 40px tabs, service dialogs, loading skeletons and editor are grounded in [Issue #17's direct-QEMU report](https://github.com/AChWorks/ach-aapanel-customizer/issues/17#issuecomment-6622156377).

## Change boundaries

- Keep Customizer's 980×760 maximum modal and 170px/40px navigation as previously justified by guarded PHP-FPM tables and Status Pages preview.
- For ordinary PHP-FPM and branding settings, use **label-left, 150px input-right** rows, two setting groups per row on wider screens; reflow at **880px** and stack labels above controls under **460px**. Keep website scope and associated pagination/help grouped.
- Use a native-style, lightweight table skeleton while **Websites** or **Activity** network reads remain genuinely pending. Table headers remain visible; existing rows are concealed while reloading. A validated empty response, an unavailable response and a pending response are visually and semantically distinct. Each panel exposes readable live status text; placeholders are `aria-hidden`.
- Tie skeleton termination to existing request tickets so superseded results cannot close newer loading states. Disable website pagination during pending inventory reads; preserve explicit retry. No global loading flash.
- Retain safe, already-reviewed Monitor revision ordering, meaningful PHP-FPM Apply/Restore warnings, no automatic changes, Status Pages unsaved-input preservation and CSS scoping.
- Shorten duplicate introductory copy without removing aaPanel database-vs-live-DNS caveats, Nginx/site/HTTP write boundary or PHP-FPM shared-service impact warning.

## Exact observed guest interaction

The local **development-only** 0.1.7 ZIP was generated twice reproducibly with SHA-256 `d1c8b3fd6fd2332bff4b8c89490d9dada3c7f4512a44dc909accbdbd2d234e61`. It was installed through the ordinary **App Store → Third-party Plug-ins → Import plugins → Install** replacement flow into the disposable QEMU aaPanel, which still displayed the installed Customizer row and could reopen Setting. This does not independently attest individual installed file digests.

After actual UI reopen:

- Customizer dialog **980×760 px**, native sidebar **170 px**.
- First PHP-FPM setting: left label ends x=632; input starts x=642, wrapper **150×32 px**, full row **40 px**.
- First Status Pages branding input: same x=632→642 and **150×32 px** dimensions.
- Websites pending read: `#ach-sites-loading` displayed, existing table body hidden, accessible status **Loading website inventory...**.
- Browser-only **synthetic HTTP 503**, intercepted locally for one read-only `get_sites`: loading skeleton removed and accessible **Website inventory unavailable. Refresh to retry.** displayed, table body restored. No guest host mutations. A subsequent **fresh normal browser run without route interception** loaded **2 native websites**, last page, skeleton hidden.
- A fresh normal Activity read loaded **38 plugin-owned Activity records** with skeleton hidden (single non-production snapshot; not a stable retention count).
- Narrow and large layouts separately verified by Chromium simulation; new CSS and skeletons do not depend on undocumented aaPanel Vue internals.

**Automated QA:** Python source unit tests 181 PASS; shipped JavaScript UI harness 117 PASS including 6 focused new cases for pending/success/error, stale invalidation and Activity filter ordering; Chromium renders **25** section×viewport layouts, **5** simulated native-layer layouts, **5** native-launcher layouts, **2** mobile reduced-motion skeletons, plus computed color-contrast verification.

## Exclusions

At this historical checkpoint, no actual Nginx reload, restart, config Save, service switch, PHP-FPM Apply/Restore, branding Save, production change, auth reset, alternate login, or Main merge. Tests do not establish restricted-role acceptance or exhaustive accessibility. The pending independent review of original PR #16 is a different exact-HEAD gate; this follow-up must receive its own review before integration. No screenshot showing host/user/secret config was committed.

## Stacked-parent Monitor remediation addendum (same date; later exact candidate)

The PR #16 branch advanced from `f5832b5` to `316a9f4c80d48be72962816dae20cf8451099141`, adding fail-closed Monitor uncertainty and website-inventory invalidation repairs required by its **separate independent re-review**. The new parent was merged into the PR #18 feature branch with an ordinary, **non-force**, conflict-free Git merge `910ae18156e35e530fa625accb8440e687e168bb`. This changes the combined candidate envelope; the prior PR18 `APPROVE` is still useful evidence for the unchanged form/skeleton delta but **does not independently approve the newer combined head or the repaired Monitor interactions**.

Combined source checks: **181 Python**, **122 JavaScript** (PR18's 117 + five focused Monitor uncertainty cases), **25** Chromium section/viewport, **5** simulated-layer, **5** native-launcher and **2** mobile reduced-motion skeletons PASS. Deterministic combined 0.1.7 lab ZIP was built twice, SHA-256 `cc08af27d3d62bc8c956f4421f29d6e05cc4d4689b9d5b9dd1837787382fc59a`.

**Actual authorized QEMU native import and browser response tests:** The combined ZIP was imported via `App Store → Third-party Plug-ins → Import plugins`, and Setting reopened normally. At the start of both independent synthetic probes the real backend Monitor revision was **0**, Overall Monitor **enabled**. First, the browser locally intercepted the next `set_control` and returned a synthetic `monitor_state_write` conflict **without forwarding it to the guest backend**: controls stayed disabled, revision 0 and the last confirmed checkbox value were retained, and a previously loaded **two-website** inventory was immediately cleared and marked as requiring Refresh. A subsequent **real read-only** `get_overview` returned revision 0 and re-enabled controls. Second, another browser-local `set_control` interception supplied a **contradictory success** (`changed:true`, revision 1 but unchanged Overall Monitor flag): the panel rejected the acknowledgment, kept controls locked and displayed the prior revision 0; a genuine read-only `get_overview` then restored interactive state. **Neither synthetic write reached the backend**, and no actual Monitor setting, website, PHP-FPM service or host configuration was changed.

These two scoped probes verify **rendered frontend fail-closed behavior and recovery on the combined candidate**, not guest file-by-file hash attestation, proof of every failure scenario, or independent review approval. All corresponding source regression tests still apply. Until fresh review and target integration, the project remains unreleased and no Production action is authorized.

## Current post-PR16-main native acceptance addendum — 2026-11-04

**This supersedes only the historical candidate/validation state above.** The independently approved [PR #16](https://github.com/AChWorks/ach-aapanel-customizer/pull/16) was integrated into `main` by merge commit `81713ff391e24f5d59fa48f2d36673ed096fd905` (source tree `778c214399e8acca06cc2e760fdf8654e862c414`). The PR #18 worktree incorporated that exact `main` via a **normal, conflict-free, non-force merge** `f9b36a1840b55807c2e103014b153e16da38f52b`. The effective child delta against main remains the same **seven UI/docs/test files**, **287 additions / 27 deletions** before the small validation-fixture correction and this addendum. PR #13/#15 were not imported.

**One necessary post-merge test-contract repair:** The existing test `Old invalidated Website read cannot cancel current request skeleton` used a `get_overview`-shaped fixture for a successful `set_control` write. The now-merged R2 contract correctly requires a boolean `changed` field, so that fixture was not a valid write acknowledgment; the erroneous test expectation failed, not the accepted frontend implementation. The test now supplies `monitorAck(...)` and a separate regression covers truthful skeleton state while the Monitor policy is pending/unverified, including timeout, invalid recheck and recovery. No backend, authorization or UI production source was changed for this correction.

**Combined-source verification:** Python **181/181 PASS**; shipped JS **128/128 PASS**, including **14/14 focused R3**; Chromium **25 panel/viewport + 5 simulated native layer + 5 launcher + 2 reduced-motion skeleton = 37 PASS**; inline JavaScript parse, installer shell syntax and diff checks PASS. Exact current **plugin source** was packaged into a deterministic unreleased 0.1.7 ZIP twice with byte-identical results, **37 members**, SHA-256 `179d1c1783bd6a356baa2d5e1849aa5c2cf7ded36b098bb9c0be1bb5aa6d182c`. Source and package are identical across the later test/evidence-only changes; these checks do not replace exact final-HEAD CI.

**Same genuine QEMU aaPanel 8.0.7 guest, authenticated native browser and official import:** Replaced the guest's previous candidate using `App Store → Third-party Plug-ins → Import plugins → Install`; aaPanel displayed `Installation succeeded!`. Reopened native Customizer. **Read-only Websites request** held by a browser-only response interception displayed the skeleton and concealed table body, disabled Refresh/pagination and showed `Loading website inventory...`. A synthetic HTTP 503 (not forwarded) ended the skeleton and showed `Website inventory unavailable. Refresh to retry.`; a subsequent genuine read-only Refresh loaded **2 lab sites**, with no stale rows or false empty state.

**Native form and layout:** PHP-FPM fields were directly measured at **150×32 px**. The guest Customizer modal was **980×760** at 1440×900; **980×720** at 1024×768; **736×652** at 768×700; **343×602** at 375×650; no document overflow, horizontal navigation at narrow width. An unsaved Status Pages name survived a cross-tab trip and was restored without saving. The Activity section and native modal remained accessible.

**Latest R3 on combined installed frontend:** One browser-only `set_control` interception was held while switching to Websites; **zero** `get_sites` requests started during the pending policy transition, no old rows remained and the now-nonpending skeleton stayed hidden. Synthetic conflict kept Websites policy `unverified`; a real read-only `get_overview` at unchanged revision 0 restored controls and allowed one fresh read-only Website request returning the **2** lab records. The intercepted write never reached the backend. No Nginx, PHP-FPM, actual Monitor, branding Save or Production operation was performed.

**Remaining gates:** No independent review of the exact *new reconciled child candidate*, no child Merge, Release or Production approval. The guest's individual installed-file digests were not directly attested; success and frontend behavior were verified via native import/rendering. The prior independent approval of the old visual-only delta is not approval of the new combined HEAD. Issue #17 remains open.
