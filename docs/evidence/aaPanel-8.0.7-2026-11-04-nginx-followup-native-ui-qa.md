# Native Nginx follow-up — real QEMU UI acceptance evidence (2026-11-04)

**Scope:** stacked visual/UI follow-up, branched from PR #16 HEAD `f5832b5ec8556c0e4bc57db36f092256070adddb`. Repository `AChWorks/ach-aapanel-customizer`; Issue #17. This evidence is produced by the **development Master**, not the independent reviewer or a release approval.

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

No actual Nginx reload, restart, config Save, service switch, PHP-FPM Apply/Restore, branding Save, production change, auth reset, alternate login, or Main merge. Tests do not establish restricted-role acceptance or exhaustive accessibility. The pending independent review of original PR #16 is a different exact-HEAD gate; this follow-up must receive its own review before integration. No screenshot showing host/user/secret config was committed.

## Stacked-parent Monitor remediation addendum (same date; later exact candidate)

The PR #16 branch advanced from `f5832b5` to `316a9f4c80d48be72962816dae20cf8451099141`, adding fail-closed Monitor uncertainty and website-inventory invalidation repairs required by its **separate independent re-review**. The new parent was merged into the PR #18 feature branch with an ordinary, **non-force**, conflict-free Git merge `910ae18156e35e530fa625accb8440e687e168bb`. This changes the combined candidate envelope; the prior PR18 `APPROVE` is still useful evidence for the unchanged form/skeleton delta but **does not independently approve the newer combined head or the repaired Monitor interactions**.

Combined source checks: **181 Python**, **122 JavaScript** (PR18's 117 + five focused Monitor uncertainty cases), **25** Chromium section/viewport, **5** simulated-layer, **5** native-launcher and **2** mobile reduced-motion skeletons PASS. Deterministic combined 0.1.7 lab ZIP was built twice, SHA-256 `cc08af27d3d62bc8c956f4421f29d6e05cc4d4689b9d5b9dd1837787382fc59a`.

**Actual authorized QEMU native import and browser response tests:** The combined ZIP was imported via `App Store → Third-party Plug-ins → Import plugins`, and Setting reopened normally. At the start of both independent synthetic probes the real backend Monitor revision was **0**, Overall Monitor **enabled**. First, the browser locally intercepted the next `set_control` and returned a synthetic `monitor_state_write` conflict **without forwarding it to the guest backend**: controls stayed disabled, revision 0 and the last confirmed checkbox value were retained, and a previously loaded **two-website** inventory was immediately cleared and marked as requiring Refresh. A subsequent **real read-only** `get_overview` returned revision 0 and re-enabled controls. Second, another browser-local `set_control` interception supplied a **contradictory success** (`changed:true`, revision 1 but unchanged Overall Monitor flag): the panel rejected the acknowledgment, kept controls locked and displayed the prior revision 0; a genuine read-only `get_overview` then restored interactive state. **Neither synthetic write reached the backend**, and no actual Monitor setting, website, PHP-FPM service or host configuration was changed.

These two scoped probes verify **rendered frontend fail-closed behavior and recovery on the combined candidate**, not guest file-by-file hash attestation, proof of every failure scenario, or independent review approval. All corresponding source regression tests still apply. Until fresh review and target integration, the project remains unreleased and no Production action is authorized.
