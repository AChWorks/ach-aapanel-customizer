# Native aaPanel Customizer UI — authenticated QEMU browser QA (2026-11-04)

**Environment:** isolated reusable Debian 12 guest, aaPanel **8.0.7**, Nginx **1.28.3** installed, Customizer **0.1.7**, authenticated Chromium in the approved aaPanel test lab through its existing browser session and HTTPS loopback forwarding. No production host or privileged service mutation was accessed. The aaPanel native **App Store → Third-party Plug-ins → Import plugins** file picker and the **Setting** action were used; no raw credential/HTTP/session workaround was used.

**Local non-release candidate source:** PR #16 worktree `feat/native-panel-visual-ux-20261103`. Reproducible local ZIP (generated twice, identical bytes): SHA-256 `62a5489ed9e283c4b238adc1f4b716e886bda4dac8ee3ade89e65f7becda9cfe`, version `0.1.7`. A separate baseline `main` 0.1.7 rollback ZIP was prepared locally with SHA-256 `24e83f6f055d1a8eeb6fdebfaba3163506e5377cd0b8b703ad968bd1ef211ba6`. These are **development artifacts**, not releases or authorization to Production. After successful replacement via the native import dialog, the installed panel was reopened: the new concise Overview copy, computed style values and new toolbar layout were visible, confirming that the UI changed. The guest's installed file hashes were **not independently attested**; do not infer them solely from upload success.

## Observed DOM / visual acceptance (actual guest, not synthetic)

| Check | Result |
| --- | --- |
| Layer from Setting, 1440×900 | x230 y70, **980×760px**, host-provided title 42px, scoped white title |
| Left navigation | **170px**, `rgb(240,240,241)`, 5 logical tabs, no duplicate group labels |
| Current content | 810px pane, 13px readable text, independent vertical scrolling |
| Controls in Websites/PHP-FPM/Status Pages/Activity | Standard visible non-checkbox buttons, inputs and selects measured **32px** tall in each section |
| Heading | The host-managed `ACh aaPanel Customizer` remains the only visible top title; repeated Overview/Websites/Activity headings visually hidden while preserved as accessible text |
| Overview toolbar after update | `Refresh state` stays on **the same row** as monitor status at 1440×900; new concise safety text and plain introductory note visible |
| Native section transitions | Overview/Websites/PHP-FPM/Status Pages/Activity all activate in-place inside the same modal; no page navigation or global flash observed |
| Requests on first tab entry | Websites: `get_sites`; Status Pages: `status_preferences`; Activity: `get_activity`; PHP-FPM landing itself: none |
| Requests on returning to previously loaded tabs | **Zero** for Overview/Websites/Status Pages/Activity during tested route; explicit Refresh remains available |
| Unsaved Status Pages values | Set a disposable, unsaved Brand name in UI; switched to Websites, then back; value was preserved; no Save invoked |
| Keyboard navigation | Focused Status Pages tab, pressed ArrowRight: active tab changed to Activity |
| 1440×900 | 980×760 modal, within viewport, vertical sidebar |
| 1024×768 | 980×720 modal, within viewport, vertical sidebar |
| 768×700 | 736×652 modal, within viewport, vertical sidebar |
| 600×660 | 568×612 modal, within viewport, horizontal scrollable nav |
| 375×650 | 343×602 modal, within viewport, horizontal scrollable nav |
| Overflow | No document-level horizontal overflow in the five tested viewport sizes; independent pane scroll retained |

**Resilience probe (browser-only, host unchanged).** A Playwright route intercepted **only** the UI's first read-only `get_sites` POST and returned synthetic HTTP 503. The Websites panel showed `Website inventory unavailable. Refresh to retry.`; its Next pagination was disabled and its Refresh button remained enabled, rather than accepting an old list. Removing that interception and pressing **Refresh websites** returned the real first page with 2 native site records, `Page 1 · 2 website(s) · Last page`, no stale invalid page state and Refresh re-enabled. No service/website configuration change was triggered by this synthetic failure.

**Source tests on the post-polish source:** `181/181` Python unit tests, `97/97` Node UI behavior tests, `25` Chromium section/viewport combinations plus `5` simulated-layer and `5` aaPanel-launcher checks. `git diff --check` passed. These complement, but do not replace, guest-side mutation/role/Apply authorization validation or independent review.

## Explicitly not verified / not performed

- Guest's **Nginx manager**: Official App → Installed remains empty / `Total 0`. Its actual Nginx modal could **not** be opened in the guest. A *separate* authenticated official public-Demo Nginx study covers visual reference, not guest acceptance: [source measurements](aaPanel-demo-8.0.7-nginx-1.24.0-2026-11-04-study.md).
- Host-installed file digests, fresh secondary/restricted accounts, all error/pending branches under real unstable networks, and exhaustive accessibility across assistive technologies were not proven.
- No PHP-FPM Apply, Restore, Nginx restart, website modifications, native config Save, branding Save or Reset, or Production change was performed.
- PR #13 and PR #15 were **not** included in this PR #16 native ZIP; their source interaction and the PHP-inventory refresh rule require a combined exact integration candidate before merging them together.
- Final GitHub CI and independent HIGH_ASSURANCE review must be tied to the later **exact committed/pushed PR head**. This QA alone does not approve Merge/Release/Production.

**Operational note:** The QEMU guest now has the refined, unreleased 0.1.7 UI candidate installed via its native import dialog for continued testing. Its test state has not been reverted. The verified local main-source rollback archive remains in the existing PR16 Dev worktree `dist/` (gitignored), not in a repository/release; treat it as a backup artifact, not proof that all original guest bytes are identical.
