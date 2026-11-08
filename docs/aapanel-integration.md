# aaPanel native integration - evidence and provisional boundaries

This is **technical integration guidance**, not a second product specification.
The canonical requirements remain in [PROJECT-SPEC.md](PROJECT-SPEC.md), and the active research/acceptance owner is [Issue #1](https://github.com/AChWorks/ach-aapanel-customizer/issues/1).

## Primary source evidence

1. Official [aaPanel third-party plugin documentation v1.1](https://www.aapanel.com/pkg/aaPanel_Linux_Panel_Plug-in_development_documentation_v1.1.pdf), pages 1-2: `plugin/<name>/<name>_main.py`, `index.html`, `info.json`, `icon.png`, `install.sh`; class matches `<name>_main`; conventional POST invocation uses `/plugin?action=a&name=<name>&s=<method>`.
2. The official [demo.zip](https://www.aapanel.com/pkg/demo.zip) was inspected **as data, not executed**. Its parent folder is `demo/`; its `index.html` opens inside aaPanel and requests methods through the legacy `/plugin` route. Sample SHA-256 at inspection: `52f2d7f212212a1496b91c0f96070ce83c8ea66ee63c1b755eb6d16863cfadff`. The supplied sample is not a security template.
3. Official [App Store docs](https://www.aapanel.com/docs/Function/AppStore.html) describe Third-party Plug-ins -> Import Plug-ins, but do **not** prove lifecycle/update compatibility on any specific installation.
4. Public aaPanel source [panelPlugin.py](https://github.com/aaPanel/aaPanel/blob/38bf35903b37b50d9654f47c4ad904ca3369715f/class/panelPlugin.py) recognizes `plugin/<name>/info.json` and constructs local-plugin inventory. The inspected implementation invokes uninstall scripts and removes plugin code. This is source evidence for that Git revision, **not** a cross-version contract.
5. The same official PDF documents read-only `public.M('sites')` selectors for site IDs, names, paths and status. Actual panel schemas and revision-specific API behavior still require tests.

## Important security boundary

The aaPanel PDF explicitly warns: **dynamic plugin routes do not inherit aaPanel session authorization** and require an appropriate `_check` implementation. Its sample declares `_check` returning `True`, allowing unauthenticated requests. **Never copy this sample access pattern.**

This first candidate intentionally **does not define `_check`** and only uses the conventional in-panel `/plugin?action=a` route. In the isolated aaPanel **8.0.7** test, unauthenticated requests returned HTTP 404, authenticated requests without aaPanel's `x-http-token` header returned `INIT_CSRF_ERR`, and the same read-only methods succeeded through the panel's own UI. This verifies the observed version/route, **not** a general security guarantee for other versions or future privileged methods. No Apply/write endpoint is exposed in this candidate.

### Native plugin dispatch parameter namespace (aaPanel 8.0.7)

The native `BTPanel/app.py:get_input()` merges `request.args` before
`request.form`, letting POST form fields replace same-named query keys.
Native plugin routing requires `/plugin?action=a&name=ach_customizer&s=<method>`;
a POST body named `action` therefore shadows the required router action `a`
and returns `Specific parameters are invalid!` *before the plugin method runs*.
The verified 2026-11-05 owner Save/Reset issue used `action=save|reset` in
the Status Pages POST body. The corrected plugin uses `branding_action` as an
explicitly plugin-owned form key for both actions. Keep `action`, `name`, and
`s` reserved for native aaPanel dispatch in all plugin AJAX payloads.
Retain the normal aaPanel `x-http-token`, primary-administrator authorization
and optimistic preference revision; this is not permission to weaken any gate.

## Native site lifecycle drift and reviewed baseline (Issue #1, development only)

The manual compare_site_changes full-primary-admin POST reads at most 100 native aaPanel sites identities and their bounded domain bindings through strict pre-coercion validation of the existing site inventory API. Native domain reads are paginated in bounded 20-site batches (up to 24 bindings per site; 2,400 total) with duplicate row-identity detection; two complete read passes must agree. Only site key, document root, panel status and bound-domain/port differences against a prior baseline are reported. Rows are never inferred from DNS, files, Nginx loaded configuration, PHP services or WordPress content. Invalid/unreadable/ambiguous native data and over-limit inventories fail closed without storing a partial baseline.

Initially no baseline exists: Compare displays all current candidate records (including document roots, site status and actual domain/port bindings). Existing baseline differences display before/after values rather than field names alone. The user must explicitly check review confirmation and select **Save reviewed baseline**. The save_site_baseline endpoint requires the exact source SHA-256 and optimistic baseline **and Monitor** revisions. It performs two source passes before and two while holding the shared plugin-owned state lock, and revalidates the Monitor-enabled policy and revision under that lock immediately before publishing. If another administrator disables either the Overall Monitor or Website inventory module, or changes policy revision, the write is denied. A verified save stores only ach_customizer.sites-baseline.json in the owner-checked aaPanel persistent data directory (0600), using atomic replace, fsync and no-follow file operations. Failure after rename may have committed; the UI must start with a new Compare rather than blindly retrying. No live host configuration or vendor aaPanel core is modified.

This feature is source-only and does not establish effective/healthy Nginx website routing, guarantee identification of a reused native site ID with identical records, prevent changes after the final database read, schedule automated scans or provide repair/Apply/Auto-enforce. Background reconciliation, policy migration and native installed test evidence are separate acceptance work; do not mistake Source checks for Issue #21 acceptance.

## Native aaPanel dialog UI (unreleased UI refinement)

The ACh Customizer management surface follows the compact Nginx-management
dialog pattern illustrated by the official [Nginx deployment guide](https://www.aapanel.com/docs/Function/Deployment.html):
use the **host-managed layer title**, a light side navigation, immediate in-place
section switching, compact labeled fields, and semantic primary actions.
Do not add a second dialog title, a browser-style route transition, or
unscoped styles that could alter other aaPanel layers.

The plugin CSS stays scoped under `#ach-customizer` and uses common roles for
surfaces, typography, borders, inputs, selects, buttons, focus, and dangerous
actions. Normal text inputs, selects and action buttons have consistent 32px
visual height, with 10px form-field and 6px action-button corner radii;
form labels, notes, wrapping and responsive layout share one rhythm.
The native green `#20a53a` remains a reference accent, but filled
primary controls use darker `#167a2f` / hover `#146f2b` with white text:
Chromium-computed text contrast is 5.44:1 and 6.29:1, respectively.
Keep the bounded native modal sizing fallback and small-viewport
horizontal navigation.

First-time read-only requests use stable **per-panel** pending/empty/error text
rather than a dialog-wide loading flash. Websites and Activity now display
lightweight, non-interactive table-row skeletons only during their own pending
reads, with accessible status text; a completed validated zero-row response is
distinct from pending and from an unavailable/failed response. Older canceled
requests cannot hide a newer pending skeleton. A tab retains its DOM and already
validated data on return **unless an acknowledged or uncertain related mutation
invalidates that snapshot**. A successful Monitor overall/website switch drops
pending and cached Websites results; potential Activity-producing Monitor,
branding, and PHP-FPM Apply/Restore writes (success, failure or uncertain outcome)
invalidate Activity and trigger one refresh when Activity is open. In-flight
older Activity and inventory replies are ignored. Monitor Refresh and
set_control share ticket/revision ordering so stale Overview responses cannot
replace newer acknowledged state. Operators can explicitly **Refresh state**,
**Refresh websites**, use existing Activity **Refresh**, and **Recheck saved
branding** in Status Pages when external state changes. Re-entering Status Pages never erases unsaved branding text;
explicit recheck or a deliberate scope change may reload. PHP-FPM
Apply/Restore safety, recovery and audit outcomes are unchanged.

Evidence: automated JS behavior tests and Chromium simulations measure the
shipped DOM, viewport/control geometry and navigation. A **real authenticated
Nginx management dialog** was inspected end-to-end on aaPanel's **official
public Demo** (8.0.7 / Nginx 1.24.0): all seven tabs, modal/nav/form
measurements, selected state, scrolling, network requests, narrow viewports,
and a dialog-cropped screenshot. See the [measured native Nginx UI study](evidence/aaPanel-demo-8.0.7-nginx-1.24.0-2026-11-04-study.md).
**Later direct inspection in the actual authenticated QEMU guest** (aaPanel
8.0.7 / Nginx 1.28.3) superseded an earlier `Official Installed Total 0`
observation: the native `get_soft_list` request was still loading. On its
completion the genuine Nginx `Setting` action was available. All seven tabs,
state/loading behavior, the nested alarm modal and a read-only unsaved-input
round trip were exercised **in the QEMU guest**. Exact 800×702 modal,
170px sidebar, 40px tabs and 150×32 setting wrappers are recorded in
[Issue #17 real-guest inspection](https://github.com/AChWorks/ach-aapanel-customizer/issues/17#issuecomment-6622156377).
The independent PR16 review and all remaining project gates are separate.
The refined PR16 UI **was** installed through the guest's native browser
file-picker and inspected across tabs, viewport sizes, cached data, retained
branding and synthetic network failure/retry; see the [native QEMU UI QA](evidence/aaPanel-8.0.7-2026-11-04-native-ui-pr16-qa.md).
Source tests and these focused browser probes do not establish
supported release status or production readiness. The focused independent
review's three required accessibility/Monitor-order/cache-coherence repairs
are documented in [PR16 remediation evidence](evidence/aaPanel-8.0.7-2026-11-04-pr16-review-remediation.md), including a separately controlled
QEMU browser-only synthetic response-order test.

**Native Nginx follow-up:** The Customizer retains a 980px dialog for long
PHP-FPM/Status evidence, but puts compact text fields in a consistent
label-left / 150px-input-right rhythm, normally two groups per row. At
880px viewport width groups reflow to one column, and under 460px each label
stacks above its input. The special website-scope selector keeps its helper
and paginated controls together. The form controls remain native-sized,
keyboard-visible and CSS-scoped; no undocumented aaPanel Vue component is
imported. Material shared-service warnings and safe Status Pages draft
preservation remain intact. [Read-only guest UI reference](https://github.com/AChWorks/ach-aapanel-customizer/issues/17#issuecomment-6622156377).

### In-place native upgrade and resident Python module cache (2026-11-04)

In the isolated authenticated aaPanel 8.0.7 guest, the native 0.1.8 Hosts
ZIP installed successfully but the first `get_overview` returned HTTP 500:
a resident `ach_customizer_hosts` module lacked the newly shipped
`native_site_snapshot` attribute, even though the exact ZIP contained it.
An authorized **Restart → Restart panel** (not `Restart server`) in the guest
restored real Overview, Inventory and read-only Hosts inspection.

The new entrypoint imports the added snapshot helper **only inside the
authorized Hosts diagnostic**. A stale module therefore returns an actionable,
audited fail-closed Hosts error instead of an import-time failure of unrelated
Monitor/Website endpoints. This isolates the blast radius; it does **not**
silently reload Python modules, change host services or waive operator
approval for a production panel restart. The [native Hosts lifecycle and UI
evidence](evidence/aaPanel-8.0.7-2026-11-04-native-hosts-qa.md) records exact
package checksums, observed errors, retry, and remaining limitations.

### Action feedback stays beside the affected control (0.1.12 QA refinement)

The real 2026-11-05 aaPanel 8.0.7 owner session confirmed that five
`status_save` calls were logged as successful but did not visibly acknowledge
Save: the UI's sole result paragraph appeared **after** the Status Pages
inspection/comparison and 440px preview, below the action's scroll position.
The server's unchanged default brand produces a valid **no-op** (`changed=false`,
revision unchanged), which must not be confused with either a failed write or
a newly persisted change. Show a persistent, screen-reader-live acknowledgement
directly beneath the **Save** button. Distinguish loading, saved changes,
already matching/no-op, unsaved edits, and ambiguous/rejected responses; state
the confirmed revision and never imply that any site or service was applied.
Keep Reset feedback in the same action group and gate uncertain writes on a
fresh read. Monitor switches likewise need visible local pending/confirmed/
unconfirmed feedback beside their controls. Websites, Hosts diagnostics,
PHP-FPM Preview/Apply/Recovery, and Activity have their operation status near
the applicable controls; preserve those placements. Browser layout checks
explicitly assert visible Save feedback across desktop and narrow viewports,
separately from actual authenticated native-session acceptance.

## First non-production implementation slice

`plugin/ach_customizer/` is a prototype native plugin package with an English-only in-panel read-only UI, following aaPanel conventions, and two narrowly bounded read operations:

- `get_sites`: paginated source records from aaPanel's `sites` table and a single bounded, parameterized read of the native `domain` table for only that page's website IDs. The response exposes the stable site key, recorded bound domains/ports and whether the original site key remains bound. These are **database bindings**, not confirmed DNS, TLS or effective Nginx routing. No WordPress-specific assumption or hard-coded list. Application and service relationships remain **Needs Review** until verified.
- `preview_php_fpm`: compares *operator-supplied* concurrency values to explicit `[www]` pool settings in a conventional, versioned PHP-FPM file and the supported default `pm.max_requests=0`; unsupported/ambiguous input remains **Needs Review**. The scope is **shared service**. Since unreleased development version `0.1.2`, it also attaches a **separately qualified, bounded file-only attribution** of native site IDs through aaPanel's conventional Nginx VHost PHP include and a matching `[www]` Unix socket, or `Needs Review` when that relationship cannot be proven. This does **not** establish effective Nginx routing, worker state, complete Apply ownership, or a general include-expansion model. The method NEVER writes, reloads, restarts or schedules anything.

This is **not a supported package or initial release**. `install.sh` owns no resident service or host settings. Its uninstall helper opens the complete aaPanel path hierarchy through pinned directory file descriptors with no symlink traversal; it requires root-owned, non-group/world-writable ancestor directories and byte-identical singly-linked regular icon files. Only the fixed product icon name is unlinked relative to the verified destination directory descriptor. Unsafe or unexpected ownership/layout preserves the copied icon. The lab observed **browser UI uninstall on the previous candidate** and **isolated native V2 backend uninstall/reinstall on the corrected candidate**; broader update, operator-state preservation, enable/disable, authorization for future writes, and rollback are still pending. Do not equate a source or ZIP build with release/production acceptance.

### Read-only Nginx FastCGI cache source audit (Issue #2)

The **unreleased 0.1.14 development candidate** adds a narrowly scoped diagnostic to the Websites panel. A full primary aaPanel administrator selects an already-discovered native website on the current inventory page and explicitly presses **Inspect selected website FastCGI cache**. The POST requires an exact comparison-only native site ID, key, path, panel status and sorted domain/port binding snapshot. The server independently resolves the selected ID/bindings before and after each inspection and never trusts user-provided paths, hosts, cache directories, URLs or chosen zone names. Other Monitor modules and unrelated endpoints remain operable when the new helper is not loaded in an older resident panel worker.

The source audit is limited to the **aaPanel 8.0.7 + Nginx** conventional file layout. It reads the selected native VHost, one conventional versioned PHP include (enable-php-NN.conf or enable-php-NN-wpfastcgi.conf), its recognized fastcgi.conf/pathinfo.conf dependencies, and optional bounded native rewrite/inert per-site extension sources. It also reads only the main Nginx nginx.conf text for directly declared fastcgi_cache_path keys_zone names. All file reads are bounded, no-follow, stable-source checks via existing monitor primitives; extension inventory checks fail closed on unexplained routing. A second complete bounded scan checks native SQLite site IDs/names (maximum 100), source-file fingerprints and referenced-zone clues for other registered websites; inconsistent sources invalidate positive results. Source SHA-256 is a snapshot dependency identifier, not a live Nginx configuration or cache-content hash.

**Supported diagnostic clues:** source fastcgi_cache zone/off/no-direct-statement; whether the same literal zone appears in other registered native website source snippets; direct fastcgi_cache_bypass and independent fastcgi_no_cache presence; whether a direct key includes a host variable; directly observed response-cache header ignore settings including Set-Cookie / Cache-Control / Expires / Vary / X-Accel-Expires; non-GET POST caching statements; and fastcgi_cache_purge references. The UI displays bounded category codes, site IDs and no executable configuration. Source Observed describes only complete registered native source attribution. Partial means at least one other website could not be attributed; Needs Review means the selected/native source or atomic observation is not reliable. Missing direct bypass/headers/keys or shared zone reuse is a **review signal**, never a proof of an exploitable cached private response. Presence of both bypass/write guards also **does not prove** those variables test cookies, Authorization, cart, checkout, sessions, webhooks, or other private routes correctly.

**Hard boundaries:** The helper returns read_only=true, runtime_verified=false, cache_safe_verified=false, fix_supported=false, purge_supported=false on every successful API result. It never runs nginx, sends HTTP requests, reads cache objects, follows paths supplied by the browser, writes site files, clears/reloads caches or enables Auto-enforce. Nginx fastcgi_cache_path may appear in other included files, location inheritance and map variables can change effective behavior, and unrelated apps/WordPress Nginx Helper may purge the shared cache directory outside these directives. Therefore this is not a complete cache-zone ownership graph, a route-by-route safety audit or proof that Purge All is site-scoped. Those P0 requirements remain under Issue #2: prove real authenticated/public HIT/MISS/BYPASS, WooCommerce/cart/session/webhook bypass and header semantics, cross-site cache isolation and safe per-site purge in an isolated aaPanel native setup; integrate only with an independently reviewed version-compatible adapter after authorization. Native browser roles/CSRF, source update drift, site creation and real responses remain pending consolidated Issue #21 QA. No Production or Release.

## Installed PHP inventory and read-only version selector

The PHP-FPM module no longer requires typing version codes like `85`. On opening the module, the plugin performs a **primary-aaPanel-administrator-only POST** to `get_php_versions`. It makes a bounded, no-follow walk of the configured aaPanel `/www/server/php` directory, identifies versioned directories, and checks (without executing them) for the versioned `sbin/php-fpm` executable and `etc/php-fpm.conf`. The UI offers only detected **PHP 8.1+ file-preview candidates** in a validated selector. Missing/linked/nonexecutable/unrecognized paths are shown as unsupported or **Needs Review**, never silently promoted to an installed working service. The scanner reopens the original absolute PHP path after discovery, compares the bounded directory inventory and directory/file identities (including binary and config metadata), and returns **Needs Review with no versions** if aaPanel or another actor rebounded/changed sources during the scan. This remains a point-in-time source check, not a lock against later changes. Inventory is independently readable when the optional Monitor preview is disabled, but this does not bypass the Monitor's preview policy. A failed/stale discovery response prevents a Preview request and invalidates any earlier confirmation.

This is a **filesystem-presence observation**, not proof of process state, effective pool configuration, actual PHP version identity, compatible aaPanel service reload, or HTTP health. `preview_php_fpm` still separately validates each candidate's single conventional `[www]` configuration. The historical discovery-only slice had a **PHP 8.5** Manual Apply adapter; the separate unreleased **0.1.17** source candidate adds guarded **PHP 8.1** with version-specific approval and recovery. Every candidate still requires a current Prepare/approval, ownership, aaPanel-version and native site mapping check. Every discovered version reports `apply_eligible=false` at inventory time. Newer-version source layouts and PHP 8.1 live-native QA need independent tests before declaring compatibility, especially for Apply. No change to other PHP versions, services, site files, public release or Production is authorized by this slice.

**Current evidence boundary:** PHP 8.1, PHP 8.5, PHP 8.10 (future code format), missing/symlinked paths, administrator/secondary/temporary authorization, stale Inventory selection and native-picker layout are exercised in isolated unit/Chromium tests, not via installed native aaPanel 8.1 guest sessions. Historical native PHP 8.5 source/runtime evidence below belongs to its stated candidate only. Current `main` contains unreleased development source `0.1.13` after PR #22 integration. The bounded PR #15 PHP discovery has merged to current source main, but neither these native files nor the new runtime observer have been released or authorized for Production. The earlier PR #15 discovery module was exercised read-only inside the QA guest against actual PHP 8.1 and 8.5 files, but that was a prior module identity, not authenticated installed-plugin testing of the new combined source. Exact combined-source native acceptance, independent review and separate Owner integration approval remain required.

### Native PHP 8.1+ read-only master and socket observation (source-only)

Unreleased source 0.1.14 adds inspect_php_runtime for a **currently selected, actually discovered** PHP 8.1+ version. It is separate from PHP-FPM pool-file Preview and the native PHP 8.5 guarded Manual Apply workflow. The endpoint requires a real full primary-aaPanel-administrator **POST** and reads the fixed native /www/server/php root; request-supplied paths, procfs roots and socket destinations are ignored. It imports the helper lazily to keep older installed aaPanel workers from breaking unrelated plugin endpoints after a ZIP update. Activity entries carry a bounded target/version, stage and operation ID.

**Observation semantics:** the helper first repeats the bounded no-follow versioned installation scan and accepts only a complete PHP 8.1+ binary/config file candidate. It pins a single conventional main [www] pool with one literal Unix listen address and **refuses unverified included/multiple pool layouts**. It compares the installed versioned sbin/php-fpm file identity to a Linux /proc/PID/exe process, requires exactly one matching master process title with the canonical main config, checks a single Unix filesystem socket and kernel /proc/net/unix listening stream inode with the process's open socket:[inode] file descriptor, and rechecks binary/config/socket and process start identity before claiming a point-in-time Observed. Proc scans are bounded (4096 PIDs, 8 matching masters, 256 FDs/master), read-only, and reject oversized or malformed evidence. Missing socket with verified master is Partial; ambiguous identities, denied procfs access, unknown includes, rebinds or out-of-scope versions yield Needs Review. A completed negative scan only says **No Matching Master Observed**, never 'service stopped'. The response omits raw process command lines and environment contents; UI renders only validated plain-text summary with PID, matching master/socket states, reason and limitations.

**Non-goals and QA boundary:** Observed is **NOT** runtime_verified=true; it proves neither that Nginx actually routes a site's PHP requests to this socket, nor current dynamic pool settings, worker counts, request success, TLS, production uptime, shared-site impact or suitability to write/reload any PHP service. This slice does not add Apply/Restore for PHP81 or change PHP85's guarded adapter. Positive and adversarial fake-procfs tests cover PHP81/PHP85, mismatched binary/master/config/socket, missing Unix path, duplicate listener/master, pid reuse, source drift, linked/oversized procfs and administrator authorization; Chromium/JS tests cover stale cross-version/inventory callbacks and untrusted replies. Real guest aaPanel 8.0.7 PHP81/85 installed-browser process evidence, roles/CSRF, native service state and cross-site HTTP remain **pending in Issue #21** and are required before any release or Production rollout.

### Native PHP 8.1+ file-to-site topology (unreleased source-only, Issue #2)

The same full-primary-admin POST inspect_php_runtime response now contains an independent site_mapping observation. This is an additive, read-only diagnostic, not a new Apply adapter. It maps only the selected installed PHP 8.1+ version with one conventional main [www] pool and literal Unix socket. The previous procfs master/socket observation remains a **separate point-in-time fact**, and its absence cannot be mistaken for proof that site routing is stopped.

The mapper reads actual native installed PHP-version files and **each other referenced PHP version's own [www] socket** from aaPanel's versioned PHP configuration, rather than constructing hard-coded socket destinations. Every accepted native VHost's direct PHP include, fastcgi_pass and limited nested parameters are checked against that actual version's file. Optional conventional rewrites and inert logging-only site extension globs can be source-mapped; routing-capable, ambiguous or non-native overlays and extra PHP-FPM pools/includes are classified unresolved. The native sites SQLite records, not client-supplied paths or site names, define the site set. This source adapter is scoped to the inspected **aaPanel 8.0.7 + Nginx** shape; other panel versions/web engines remain **Needs Review**.

Two bounded file/site scans (at most **100 websites**), versioned source fingerprints and installation rescan constrain race-induced false confidence. **File Mapping** requires a complete unambiguous native-site source set; **Partial** includes a bounded list of site IDs with unresolved PHP association. **Needs Review** clears all positive site attribution on global DB, version, source or site-scan drift. The UI shows each native site ID/key as matching the selected version, another version, no-PHP (00), or unresolved and revokes previous evidence on version change, inventory Refresh, and attempted PHP-FPM Apply/Restore. All displayed site information uses text-only rendering and a validated bounded response. The helper is included in the deterministic ZIP. Legacy shared PHP 8.5 Manual Apply site-impact checks retain their existing default path and authorization rules.

**Explicit limitations:** Per-site associations are **file-only**, not proof of the active Nginx configuration (nginx -T), effective per-request location routing, additional non-aaPanel consumers, live PHP requests, full service names or dynamic/FPM pool settings, or safety to reload a shared service. An Observed master/listener and File Mapping alongside each other are independent measurements, not a verified complete runtime call graph. The new response always reports apply_eligible=false and runtime_verified=false; it cannot authorize PHP81 Apply or broaden PHP85 Apply. Real installed aaPanel PHP81/PHP85, WordPress/wpfastcgi, multi-site 404/200/HTTPS routing, roles/CSRF, regeneration, and negative source drift are pending consolidated QA in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21). No Production or Release approval.

## Historical aaPanel browser and lifecycle evidence (2026-11-01; previous candidate)

Environment: a dedicated, disposable **Debian 12 (Bookworm)** VM running aaPanel **8.0.7**, verified with the installed panel's `public.get_panel_version()`. The panel's HTTPS/SSH management access was forwarded only to `127.0.0.1` on the development host. This guest had **no Nginx, Apache, managed site, or PHP-FPM runtime installed**; no production data or credentials were used. The aaPanel installer was downloaded from the official vendor and SHA-256 verified before guest execution.

**Evidence identity:** All observations below in this historical section belong to the **previous**, monitor-only source candidate `2ccbe3a2acd8a22d2153cff45991e967b01b9c32` (plugin version `0.1.0`), whose development ZIP SHA-256 was `bc790aaf9ba66835cf7f8d7e211d0e7bab286298a89c55a009c943ae3409c915`. In particular, the browser UI uninstall was performed on **that previous candidate**, not the corrected cleanup candidate. This historical digest is **not** the digest to use for the current package. The corrected ZIP's SHA-256 is `1a3379e5f2c251cc87c5cfd6ecb74e88db487eeb91424a51084925a9bd94b129`, with its separate, limited native V2 backend evidence documented below. Neither digest denotes a supported release.

- **Native package and UI:** The installed panel's own `panelPlugin.update_zip()` and `panelPlugin.input_zip()` successfully accepted the ZIP, ran `install.sh`, registered `info.json`/icon, and exposed the local plugin in the App Store's **Third-party Plug-ins** inventory. The **Setting** and **Uninstall** controls appeared in its inventory row; selecting the same plugin from **Recently used** opened the English management UI inside aaPanel. The **file-picker upload interaction itself was not exercised**; backend import methods were used on this isolated guest.
- **Authenticated read-only paths:** The in-panel UI's `Overview`, `Websites`, and `PHP-FPM Preview` tabs loaded without observed browser JavaScript errors. `get_overview` returned `mode=Monitor`; `get_sites` returned an empty but valid page on the initially empty host; and a PHP `85` preview returned `Needs Review`/`shared_service` because that PHP-FPM directory did not exist. These outcomes did not assert that any PHP service had been configured, activated, or verified.
- **Auth and CSRF:** A request without an authenticated panel session returned HTTP 404, a valid-session request without the native `x-http-token` returned `INIT_CSRF_ERR`, and in-panel requests with the native token succeeded. These checks are evidence for the observed routes on aaPanel 8.0.7 only, not a substitute for per-operation authorization when Apply is added.
- **Historical native UI uninstall/reinstall (previous candidate only):** The first native UI uninstall removed plugin code but left aaPanel's copied icon in its shared static icon directory. An initial hook on the **previous** candidate checked only final path components and byte equality. A subsequent **UI uninstall on that previous candidate** removed both plugin directory and matched icon, leaving panel and task processes running; backend reinstall succeeded. Later independent review found that the first hook **did not check symlinked ancestor directories**. These historical observations neither validate the corrected helper nor constitute a fresh UI uninstall test on the corrected candidate; its separately isolated backend test is described below.
- **Dynamic discovery integration:** Two *temporary metadata rows* were committed to the isolated panel's actual SQLite `sites` table, and native `public.M('sites')` calls through the project's monitor detected both, then a rename and deletion. All fixture rows were removed and the database returned to **zero** sites. **This is not evidence of a website created, renamed or regenerated through aaPanel's actual site-management workflow.**
- **Previous-candidate source tests:** 21 unit/package tests passed locally, including entrypoint, site pagination/change fixtures, strict PHP-FPM file-parsing and owned-icon cleanup guards. POSIX script syntax and deterministic ZIP output were verified. See [the prior candidate's exact source CI](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/41315098998) for those 21 tests.

## Corrected candidate: REQUIRED-01 remediation and isolated V2 backend retest (2026-11-01)

The independent review of PR #3 candidate `2ccbe3a2acd8a22d2153cff45991e967b01b9c32` identified a **required** ownership flaw: `-L` on the terminal icon file did not reject a symlink at an ancestor directory. The corrected candidate uses `ach_customizer_cleanup.py` with descriptor-relative `os.open(..., O_NOFOLLOW | O_DIRECTORY)` for *each* ancestor from the filesystem root, checks directory identity (owner UID 0, no group/world write, no unexpected filesystem boundary under the panel root), checks exact file ownership, regular type, single link, bounded size and byte identity, rechecks the destination inode, then calls `os.unlink` for only `ico-ach_customizer.png` relative to the verified destination directory descriptor. The uninstall shell refuses to invoke the helper through a symlinked source parent. Missing/ambiguous paths fail closed without deleting the copied icon. This deliberately does **not** add any host-configuration write capability.

- **Local tests:** 32 unit/package tests passed, including new tests for symlinked source/destination parents (including a shared panel parent), tampered/nonregular icons, final-component symlinks, hardlinks, unsafe directory permissions and idempotent normal cleanup. The development ZIP builder includes the new helper.
- **Master-executed isolated runtime recheck (not rerun by the independent reviewer):** In the same Debian 12 / aaPanel 8.0.7 QEMU guest, native `panelPlugin.update_zip()` / `input_zip()` accepted the new ZIP (SHA-256 `1a3379e5f2c251cc87c5cfd6ecb74e88db487eeb91424a51084925a9bd94b129`). Guest-side regression checks on **temporary directories only** passed for both symlinked parent cases, mismatched content, unsafe directory permissions, normal deletion and repeat cleanup. The *installed aaPanel V2* `panelPlugin.uninstall_plugin()` path then ran the actual product uninstall hook, and confirmed removal of both the product plugin directory and its copied icon. Finally the same ZIP was natively reinstalled; both original icon and helper were verified, aaPanel HTTPS remained listening and no lab site fixture rows remained.
- **Exact test isolation:** For this corrected-candidate V2 backend invocation, the external vendor `downloadFile` branch was suppressed and the normal cloud/plugin lookup was replaced with local plugin metadata from the **verified manifest**. This avoided executing an unrelated pre-existing vendor temp script. The actual product uninstall hook ran, but this **does not prove a fresh browser UI uninstall** on the corrected candidate or an unrestricted upstream vendor-download workflow. Earlier UI uninstall/in-panel tests remain historical observations of the previous candidate, documented separately above.
- **Retained sanitized machine evidence:** [aaPanel 8.0.7 REQUIRED-01 lab result](evidence/aaPanel-8.0.7-2026-11-01-required01.json) contains allowlisted assertions and explicit limits, **without credentials, panel URLs or session identifiers**. GitHub source CI remains separate from this physical runtime evidence.

PR #3 was independently approved and merged into `main` at `1e19cec8fd2a4cadfb0d4021b2e7f6baf1842565`. This confirms source integration only: no supported release or production installation is implied.

## aaPanel 8.0.7 V2 Nginx site sources (non-production inspection, 2026-11-02)

The installed `class_v2/panel_site_v2.py` in the retained Debian 12 guest provides additional **version-specific source evidence**, not cross-version compatibility:

- `panelSite.AddSite()` calls `nginxAdd()`, which rewrites `/www/server/panel/vhost/nginx/<site>.conf` using an aaPanel-owned template. The template directly includes `enable-php-<version>.conf`, the per-site rewrite file and (when selected/enabled) aaPanel's built-in global-rule block. It does **not itself** add an unconditional `nginx/extension/<site>/*.conf` include. Effective expanded configuration and any extension injected by other installed components still require runtime verification.
- `_get_global_rule_include()` gates aaPanel's `global_rule/global.conf` to PHP sites using panel-maintained global metadata. `_apply_global_rule()` iterates through site configurations and writes a shared rule and relevant VHosts. This is a **panel-owned, potentially multi-site** feature; it is not a plugin-owned per-site fragment API, nor permission for our plugin to replace operator global rules.
- `DeleteSite()` can remove the site's `nginx/extension/<site>` directory. Extension paths cannot be treated as durable user-state storage or assumed to survive deletion/renaming.

Do not infer extension-file effectiveness, persistence after regeneration, or safe Apply from source inspection alone. Record actual behavior in a real managed-site test before selecting an adapter.

## Actual native website and Nginx lifecycle (isolated guest, 2026-11-02)

**Tested combination:** Debian 12, aaPanel **8.0.7**, Nginx **1.28.3**, QEMU TCG overlay on the retained non-production lab. The official aaPanel installer completed with exit code 0. Nginx passed its syntax test. No Production host was accessed.

1. **Real creation/discovery/HTTP:** `panel_site_v2.panelSite.AddSite()` created the static (`PHP 00`) site `site-a.ach-customizer.invalid` as real aaPanel site ID **3**, with Nginx VHost, document root and index. Without any SQLite fixture insertion, the installed `ach_customizer` endpoint discovered the new site with `Needs Review`. The actual server returned **HTTP 200** using its `Host` header, and `nginx -t` passed. This does not establish PHP-FPM functionality.

2. **Regeneration/extension:** The V2 `nginxAdd()` template has no unconditional per-site extension include. A test-only fragment in `vhost/nginx/extension/<site>/` initially had no effect. Adding an explicit include inside this test VHost made an HTTP header appear; native regeneration then **removed the include** (while retaining the fragment file), and the header disappeared. **Later**, the aaPanel/vendor `site_total` service created its own `site_total.conf` and asynchronously reinserted the extension include, making the lab header appear again. Therefore both temporary loss and later repair are observed; the recovery timing and behavior must **not** be treated as a durable plugin-owned extension contract. Our fragment was deleted while the `site_total`-owned file was preserved. Nginx syntax and HTTP 200 still passed.

3. **Native SQLite contention/partial provisioning:** A second `AddSite()` initially returned outer `status: 0`, with `siteId` equal to **`error: database is locked`**. The VHost and root were created but the actual database/monitor had no second site. Process and `/proc/locks` inspection showed `BT-Task` holding a reserved SQLite write lock while awaiting the auxiliary flock held by the `make_suer_ssl_task` child. Only this verified exact child was terminated **inside the disposable guest**; locks cleared and `PRAGMA quick_check` was `ok`. Retrying the native site-add then succeeded with site ID **4** and visible dynamic inventory. The observation illustrates an uncertain-outcome native API, but is not proof of every possible lock cause; a future Apply must reconcile actual DB/files/service state, not trust just outer success status.

4. **Backend deletion:** Direct standalone V2 `DeleteSite(path=1)` removed the second test VHost and extension directory but failed importing `BTPanel` from `files_v2`, because the bare probe lacked the actual panel request module context. Its database record remained at that point. Guarded `DeleteSite(path=0)` completed and removed site **4** from the actual database and monitor, retaining site **3** and HTTP 200. The deliberately retained test-only document root was then removed using exact-path, ownership/content checks. This **does not** establish that aaPanel browser UI deletion with root removal fails or succeeds.

**Unverified gates:** true site rename; corrected-candidate browser file-picker and uninstall; actual PHP-FPM pools; extension durability across aaPanel upgrades or without `site_total`; supported scope ownership, Apply, reload/rollback and state migration. No release/merge/Production approval follows from these tests.

Sanitized machine evidence: [aaPanel 8.0.7 native site/Nginx lifecycle](evidence/aaPanel-8.0.7-2026-11-02-site-nginx-lifecycle.json). Reproducible non-production test scripts/overlay remain in the existing AI Server Agent lab; never publish guest credentials or raw log files.

## Actual PHP 8.5 native-pool verification and bounded monitor correction (isolated guest, 2026-11-02)

The same isolated aaPanel 8.0.7 / Nginx 1.28.3 guest was reused with its prior qcow2 overlay. The **native aaPanel PHP 8.5 installer** exited successfully; the installed `php-fpm` binary reports **PHP 8.5.12**. The `www` pool was running in `dynamic` mode, `php-fpm -t` passed and the real FastCGI socket `/tmp/php-cgi-85.sock` existed. This is **one observed environment**, not a declared PHP version compatibility matrix.

The generated `/www/server/php/85/etc/php-fpm.conf` explicitly sets `pm.max_children=50`, `pm.start_servers=5`, `pm.min_spare_servers=5`, `pm.max_spare_servers=20`, but **omits `pm.max_requests`**. The installed PHP-FPM's `-tt` config dump reports **`pm.max_requests=0`**, consistent with the [official PHP-FPM configuration reference](https://www.php.net/manual/en/install.fpm.configuration.php) documenting an omitted `pm.max_requests` default of 0. Before the correction, the plugin returned `Needs Review` with `Missing explicit settings: pm.max_requests` for this valid native layout.

The **candidate monitor correction** infers *only* the documented optional `pm.max_requests=0` when absent from the single accepted `[www]` pool. The response exposes this as `implicit_defaults`, distinguishes file/default comparisons from effective live runtime, and continues to fail closed for omitted mandatory dynamic-pool values, unsupported modes/includes, duplicates and symlinked configuration. **No config writes, FPM reload, Apply or auto-enforcement** were added. The preview UI labels its source as `Configured / PHP default` rather than implying an explicit file value.


A focused independent review of the original candidate identified an unsafe ambiguity: a bare `pm.max_requests` line (or another malformed directive without `=`) could be silently skipped and mistaken for a genuine omission. The follow-up parser change **fails closed** for missing `=`, unsupported INI key syntax and unrecognized `pm.*` settings in the selected pool, while continuing to accept known non-policy settings and valid explicit values. Source regression tests cover both valid and malformed cases, including unchanged configuration bytes. This remains a conservative **partial file parser**, not a general certification that every accepted PHP-FPM directive is valid. The subsequent parser delta has **not** been re-executed in the guest; the earlier guest evidence concerns the pre-delta helper identified in the JSON record.

A further high-assurance review of candidate `de8217fd2f842e9a1706eb78feff8ae7ae7b9ecc` found two more false-`File Match` paths: PHP-FPM directive names are case-insensitive, and `include` can inherit the active pool context. The follow-up source correction compares normalized ordinary directive names for policy values, duplicates, `pm` mode and known passthrough keys while preserving original spelling and array suffixes. A later independent review identified the special **case-sensitive** PHP-FPM `include` recognition, distinct from ordinary directive handling ([upstream FPM parser](https://github.com/php/php-src/blob/master/sapi/fpm/fpm/fpm_conf.c), `fpm_conf_ini_parser_entry`). The monitor now accepts only lowercase `include` and rejects mixed-case variants as `Needs Review` in both root preflight and per-file parsing, rather than interpreting directives PHP-FPM itself may reject as active includes. Inspected configuration files are never changed. Ambiguous mixed-case `[www]` sections are rejected. Because include expansion is **not** modeled with PHP-FPM's section/order semantics, the monitor fails closed for `include` inside `[www]` and unscoped process-manager settings in fragments. Conventional root-level includes containing an explicit standalone `[www]` pool remain supported. This bounded parser is not a substitute for PHP-FPM's own syntax validation. The follow-up parser correction has **not** been rerun inside the guest; only the historically identified earlier helper was guest-executed.

Against the actual guest pool, the corrected candidate returned `File Match` for the desired `pm.max_requests=0`, and `File Drift` (desired 300, actual/default 0) for the alternative. The pool file SHA-256 was unchanged by previews. Native `SetPHPVersion` linked real site ID **3** to `enable-php-85.conf` and a real PHP HTTP request returned `PHP-8.5 / HTTP 200`. A second native website, ID **5**, used the **same include and FPM socket** and also served real PHP 8.5 via HTTP 200. Native site creation did not alter the shared pool file hash in this experiment. The second test site was removed through aaPanel's backend plus guarded disposable-root cleanup; site ID 3, Nginx syntax and HTTP 200 remained healthy.

**Remaining limits:** this does not reproduce the historical aaPanel/WP Toolkit settings reset, demonstrate a different per-site PHP pool, prove the live daemon always matches a subsequently edited file, establish browser authorization, implement reload/rollback or authorize production mutation. It supports a *read-only* shared-pool preview and evidence-based adapter selection only. Sanitized facts: [Native aaPanel 8.0.7 PHP 8.5 FPM evidence](evidence/aaPanel-8.0.7-2026-11-02-php85-native-pool.json).

## Native domain-binding lifecycle and exact current-helper runtime test (isolated guest, 2026-11-02)

**Environment and exactness:** Disposable copy-on-write overlay of the retained Debian 12 guest, aaPanel **8.0.7**, Nginx **1.28.3**, PHP-FPM **8.5.12**. Guest execution was performed with the panel's Python environment and aaPanel's real V2 website/database APIs. The current candidate `ach_customizer_monitor.py` (SHA-256 `97f2c1cddb311bef1ecf15069863efcd70934d943d95b20e00ac29fbcca3fe2a`) and unchanged `ach_customizer_main.py` (SHA-256 `6d30413a7e3b3df1046f29e48cb73ae95c76d88a519dd95d5180f01437db9a20`) were verified byte-identical inside the guest and executed from a temporary candidate path. This is not evidence that the new package ZIP or browser UI was installed/retested.

1. **Real domain lifecycle, not a canonical rename:** Native `AddSite` created disposable site ID **6** (`native-domain-probe.ach-customizer.invalid`). Native `AddDomain` added `native-domain-new.ach-customizer.invalid`; native `DelDomain` then unbound the original domain (all returned status 0). The site's ID, `sites.name`, VHost filename and document-root path **remained unchanged**. The `domain` database table and Nginx `server_name` reflected only the new domain. An HTTP request using the new `Host` returned **200** with an exact test-owned marker, while the unbound original `Host` returned **404**. Nginx syntax passed and the other site's VHost hash was unchanged. This verifies an operational **domain-binding change**, **not** a supported true canonical site/VHost rename; no cross-version claim is made.
2. **Candidate read-only inventory:** A single bounded, parameterized `domain` table query keyed by the selected `sites.id` page augments the stable site key with recorded `bound_domains` and `canonical_domain_bound` (a database-derived flag). The guest monitor returned site ID **3** with its site key still bound and ID **6** with its original key unbound and only the new domain present. Unexpected/malformed or over-limit domain results fail the request rather than invent an empty binding list. The UI labels these values as aaPanel records, **not** independently verified DNS, effective Nginx routing or certificate state. No site/profile policies are written.
3. **Current FPM parser source, not historical helper:** The exact updated candidate `ach_customizer_monitor.py` guest runtime returned `File Match` for the real native PHP 8.5 pool's omitted `pm.max_requests` = documented default `0` and `File Drift` for the operator-provided alternative `300` (actual/default `0`). The PHP-FPM configuration and both inspected VHost hashes were identical before/after these reads; `nginx -t` passed. This closes the **source-identity/runtime regression check** left open after PR #5; it does **not** validate live daemon reload, Apply, update or the historical WP Toolkit reset.
4. **Safe disposal:** The native backend deleted the exact disposable site, DB row and VHost. Its retained test document root was removed only after exact identity/content checks; aaPanel had marked its test-generated `.user.ini` immutable, which was confirmed with `lsattr` and cleared only for that test-owned file. Site **3** retained HTTP **200**, Nginx syntax passed, temporary guest candidate sources were removed, and QEMU exited cleanly after guest shutdown. The reusable base/backing images remain retained separately.
5. **Local source quality:** 47/47 unit/package tests passed, including five new website-binding/limits/error tests; this does not substitute for package import, browser lifecycle, role authorization or future Apply testing.

Sanitized evidence: [aaPanel 8.0.7 native domain binding and exact candidate helper](evidence/aaPanel-8.0.7-2026-11-02-domain-binding-lifecycle.json). Treat the previous paragraphs' former claim that the newest parser had not been guest-executed as a *historical checkpoint before this later source-identified test*, not as a current unresolved parser-runtime gap.

## Installed native update: frontend/backend version skew (isolated guest, 2026-11-02)

The native aaPanel 8.0.7 `panelPlugin.update_zip` + `input_zip` path can replace
`index.html` and plugin source files while an already-running panel Python
worker continues serving previously imported `ach_customizer_monitor` code.
This was **reproduced**, not inferred: after importing the exact merged PR #6
package, the new browser table showed `None (review required)` for a real
domain row. The aaPanel SQLite `domain` table and a freshly started Python
entrypoint confirmed the binding. Restarting only the **isolated test panel**
then returned the correct bindings in the browser.

The follow-up monitor response now includes an explicit
`inventory_schema=2` marker; the UI rejects missing/mismatched versions or
missing binding fields and displays **Inventory API mismatch** instead of
fabricating an unbound website. Under this verified case, a controlled panel
backend restart in a suitable maintenance window and reopening the native
plugin UI restored the expected view. The plugin does **not** silently
restart aaPanel and does not mutate host website/FPM configurations.

The same bounded change also rejects domain names longer than 1024 UTF-8
bytes, malformed UTF-8 encodings and aggregate domain name text exceeding
256 KiB per site page (in addition to the existing 1000 domain-row limit);
ordinary wildcard domains, Unicode names and non-default ports remain
supported. These limits are *domain-name payload* bounds, not a global
response-size cap. Truncated or invalid inventories fail visibly rather
than claiming successful discovery.

The inventory UI additionally validates the **entire rendered response shape**
before rendering any row: the requested page/page size and boolean pagination
flag, bounded site records and unique positive IDs, required display strings,
binding-object names and integer ports, and a canonical-binding flag consistent
with the returned domains. An invalid response clears prior rows, disables
pagination and displays **Invalid inventory response**; a missing or incorrect
schema still displays the distinct stale-backend warning. The DOM renderer
continues to use jQuery `.text()` for untrusted site/domain strings. An
executable, dependency-free Node regression harness runs the **shipped inline
script** against both valid and malformed API responses in CI
(`node --test tests/test_inventory_ui.cjs`), rather than asserting merely
that a validation snippet is present in source.

**Evidence boundary:** The aaPanel guest/browser observations linked below
were made against the earlier inventory-schema candidate and remain valid only
for the functionality and source hashes stated in that record. The expanded
malformed-schema response handling has executable JavaScript regression
evidence, not a new aaPanel browser replay or cross-version guarantee.

**Actual candidate native integration and browser evidence:** Debian 12,
aaPanel **8.0.7**, Nginx **1.28.3**, PHP-FPM **8.5.12** in a disposable
non-production QEMU guest. Exact candidate SHA-256 values, A/B browser
assertions, unchanged VHost/pool hashes and limitations:
[aaPanel 8.0.7 inventory update compatibility](evidence/aaPanel-8.0.7-2026-11-02-inventory-update-contract.json).
Native update and existing administrator UI were exercised; native
browser ZIP-picker upload, browser uninstall, restricted-account access,
state migration, shared-FPM reset, cross-version compatibility, Apply,
rollback and Production remain unverified or unimplemented.

## Native browser lifecycle and durable Monitor controls (isolated guest, 2026-11-02)

**Exact candidate environment:** Debian 12, aaPanel **8.0.7**, Nginx 1.28.3,
PHP-FPM 8.5.12 in a disposable QEMU overlay. The merged 0.1.0 ZIP passed
real third-party-plugin browser file-picker upload, Install, Settings,
site/domain inventory, Uninstall, and Reinstall. The unmerged 0.1.1 candidate
also passed a native browser in-place upgrade, Uninstall, and Reinstall.
Installed source hashes matched the corresponding development ZIPs.

The new controls affect **read-only Monitor operations only**. The overall
switch denies website/FPM reads without touching hosted services. Independent
module switches deny only their matching read-only endpoints. Their schema-v1
JSON preferences live in /www/server/panel/data/ach_customizer.state.json
outside aaPanel's replaceable plugin folder; the state file and lock are
root-owned mode 0600. Reads do not create files. Native browser Uninstall
removed code and plugin icon while preserving the disabled state and revision;
Reinstall recovered the exact saved flags and enabled later reactivation.

**Concurrency root-cause correction:** a file lock alone serialized writers
but could allow a tab with a stale UI snapshot to overwrite a newer operator
decision. Each administrator-only POST now sends its last-seen expected_revision.
The backend checks this against the persisted revision **under the same lock**
and rejects mismatches without writes. A controlled native ZIP update and
guest-only panel restart loaded the corrected source. Through a real
authenticated aaPanel browser session, a revision-3 update advanced to
revision 4; a subsequent stale revision-3 request was rejected visibly with
stage monitor_state_write and the saved revision remained 4.

**Temporary-login authorization (focused review remediation; source-only):**
aaPanel's [upstream `userlogin.py`](https://github.com/aaPanel/aaPanel/blob/master/class/userlogin.py)
shows a temporary-token route that can set `login=True`, `uid=1` and
`tmp_login=True`, as well as a separate temporary identity carrying
`tmp_login_id` and `tmp_login_expire`. The plugin's original UID-1-only
check would not distinguish such sessions from a full administrator session.
The state-mutation gate now **also denies** truthy `tmp_login` and any
present `tmp_login_id` or `tmp_login_expire`, before it calls the writer.
Native aaPanel authentication and CSRF remain unchanged. Focused unit tests
verify ordinary UID-1 POST success and rejection of both temporary forms,
non-primary users, GET and missing context, against absent and existing
persistent state. Rejected requests do not enter the state writer, create
settings files or advance the revision. These **new tests are not a browser
replay** of aaPanel 8.0.7's actual temporary-token issuance; the cited
upstream source is the current version, not an immutable 8.0.7 snapshot.

Atomic replacement, strict state schema, finite read bounds, ownership/mode
checks, no-follow file opens, conflict reporting and fail-closed error
handling are exercised in source tests. Earlier browser and guest checks confirm
no inspected VHost or PHP-FPM configuration changes, successful nginx -t,
and HTTP 200 from the retained site. A missing/invalid frontend state schema
leaves all controls disabled rather than inferring preferences.

**Native aaPanel caveat:** its V2 Uninstall implementation tries to fetch
a vendor install.sh before invoking the local plugin uninstall hook. Only
inside the disposable guest, outbound TCP 80/443 was temporarily rejected
for IPv4 and IPv6 during Uninstall and restored afterward with rule absence
verified. The vendor script was not retrieved. This is a native-panel
compatibility boundary; the plugin does not alter aaPanel core.

**Still outside proof:** real browser restricted-account testing, persistent
state schema migration, cross-version compatibility, Nginx include durability,
PHP-FPM reset reproduction, Apply, rollback, production and public release.
Update can leave older Python modules cached in the aaPanel worker; controlled
panel restart is an operator action and was performed only in the guest.

Full version-specific identities, original and corrected candidate source
SHA-256 values, UI observations, host-file hashes and test limitations:
[sanitized native browser evidence](evidence/aaPanel-8.0.7-2026-11-02-native-browser-lifecycle-state.json).

## Native WordPress shared PHP-FPM reset and site attribution (isolated guest, 2026-11-02)

**Observed aaPanel writer/root cause:** The actual installed aaPanel 8.0.7 `one_key_wp.deploy_wp()` invokes `optimize_php().optimize_php()` after WordPress extraction; it selects FPM concurrency by total host RAM and delegates to `config.config().setFpmConfig()`. That method rewrites `/www/server/php/<version>/etc/php-fpm.conf`, then calls `public.phpReload(version)`. This is a **shared pool**, not a website-specific change. The RAM interval `2048 < total MB <= 4098` selects `pm.max_children=80`, `pm.start_servers=10`, `pm.min_spare_servers=10`, and `pm.max_spare_servers=30`, matching the historical Issue #2 symptom. This code path was inspected in the installed guest, not assumed from an unrelated revision.

**Real native-write and rollback experiment:** A fresh disposable overlay with Debian 12, aaPanel 8.0.7, Nginx 1.28.3, and PHP-FPM 8.5.12 contained two real native aaPanel sites, IDs 3 and 6. The second site was created through `panel_site_v2.panelSite.AddSite` and assigned PHP 85 through `SetPHPVersion`. Both sites' conventional VHosts referenced the same PHP-85 Nginx include and `/tmp/php-cgi-85.sock`; both successfully served temporary PHP HTTP probes. The guest initially had `50/5/5/20`. The **real** `one_key_wp.optimize_php().optimize_php()` and underlying `setFpmConfig()`/reload on the guest's actual RAM changed `pm.max_spare_servers` from 20 to 30. Repeating that genuine write/reload path with **only the test-scoped RAM measurement mocked to 3072 MB** reproduced the exact historical `80/10/10/30`. The plugin detected all four differences as `File Drift`. `php-fpm -tt` reported the rewritten settings, `php-fpm -t` and `nginx -t` passed, and both sites' PHP HTTP checks passed in both states.

The controlled test retained a private baseline, restored the exact initial `php-fpm.conf` bytes with a checked atomic replacement, called versioned PHP-FPM reload, and verified original SHA-256, `php-fpm -tt/-t`, `nginx -t`, and PHP HTTP responses for both sites. Test PHP probes and the temporary rollback backup were removed after checks passed. **This proves the native write mechanism and a lab-script rollback, not a plugin Apply/rollback endpoint, full WordPress deployment, or cross-version durability.**

**New read-only impact preview (development candidate `0.1.2`):** The existing `preview_php_fpm` endpoint now returns `shared_impact` with an explicit schema, observed site IDs/keys, matching conventional file assignments, other-PHP count, and unresolved sites. It checks the `[www]` Unix socket against the native global `enable-php-<version>.conf` FastCGI target, then examines up to 100 authoritative aaPanel site IDs and their regular, bounded VHost files. Indirect includes, missing/linked/noncanonical VHosts, alternate FastCGI targets and incomplete inventories are reported as `Needs Review` instead of inferred site ownership. The in-panel UI renders IDs/site keys as text (not HTML) and warns that these are **file assignments only**, not verified effective runtime or Apply authority.

In the same guest, the **exact candidate Python source** first returned `File Match`, `File Mapping`, IDs `3` and `6`, zero unresolved site assignments, and identical inspected source-file hashes before/after the read. The development `0.1.2` ZIP (SHA-256 `95ffefe8d7386896e01d4f3f7fd417097f2985951f5ad4ed3083d2462d7bf6e2`) was then successfully imported via aaPanel's actual `panelPlugin.update_zip()/input_zip()` over installed `0.1.1`; the four main installed source hashes matched the candidate. After a controlled **guest-only** panel restart, the installed entrypoint returned the same mapping with source files unchanged. The source-unit suite includes negative tests for mismatched sockets, duplicate site IDs, symlinks, oversized VHosts, unsupported include modes, ambiguous direct FastCGI and site inventory limits. **This does not replay the 0.1.2 browser UI nor browser-session authorization.**

[Sanitized and explicitly scoped native writer/rollback/site-mapping evidence](evidence/aaPanel-8.0.7-2026-11-02-native-fpm-reset-impact.json).

**Still open:** Real temporary-token/restricted-user browser rejection; support independent of `site_total` for Nginx regeneration; compatible bounded Manual Apply with preflight/approval/conflict handling, actual syntax/runtime verification, persistent recoverable rollback; canonical website rename; expanded supported-version acceptance. No production action or public release is authorized.

## Compatibility and outstanding acceptance

| Required proof | Observed status |
| --- | --- |
| Official plugin layout, request syntax and ZIP extraction | Source-verified and isolated runtime accepted on aaPanel 8.0.7 |
| Real in-panel management and read-only API | **Browser-tested on aaPanel 8.0.7:** Settings, bound-domain inventory, overall/module Monitor controls, disabled-read behavior, stale-update conflict refusal. Restricted-role browser authorization untested |
| Native ZIP import/backend, uninstall and reinstall | **Browser-confirmed on aaPanel 8.0.7:** actual ZIP picker, Install, Settings, Uninstall and Reinstall for merged 0.1.0 and unmerged 0.1.1 candidate; installed source hashes checked. No production use |
| Dynamic website source inventory | Real native create/delete and AddDomain/DelDomain verified; stable site key can differ from active bound domain. Exact updated monitor tested against actual sites and domain records; true canonical site/VHost rename and browser lifecycle remain untested |
| PHP-FPM preview, shared scope and observed native writer | **Native writer reset and lab-script rollback verified:** real `one_key_wp.optimize_php()` rewrites and reloads shared PHP 8.5 pool; monitored drift, `php-fpm -tt/-t`, both sites' PHP responses and baseline recovery passed. Candidate 0.1.2 read-only socket/file site attribution identified both sites. **Not yet** a plugin Apply, durable extension, or verified runtime mapping under every configuration |
| Nginx virtual-host extension durability and panel regeneration | **Nginx 1.28.3 tested:** native generator removes custom include; separate asynchronous `site_total` later reinserts it. No stable plugin-owned extension contract established |
| Overall/per-module enable-disable, persistent policy/state migration | **Monitor-only overall/module switches and external schema-v1 state preservation browser-confirmed** across update, uninstall and reinstall; stale-revision writes rejected. Policy migrations and enforcement unimplemented |
| Manual Apply/Auto-enforce, syntax validation, recovery/rollback | **Manual Apply/rollback implemented only as a guarded development candidate**, with prior exact-source native guest evidence; current review-remediation requires fresh exact-candidate CI/re-review. **Auto-enforce is not implemented.** |
| More aaPanel versions, Linux families, update, uninstall after nontrivial state | **Browser update/uninstall/reinstall with persisted Monitor state verified on aaPanel 8.0.7 only**; pending cross-version/restricted-role tests and schema migration. Controlled worker restart may be required after update |
| Production authorization, deployment, release | **Not authorized**; no production changes |

The remaining end-to-end acceptance in [Issue #1](https://github.com/AChWorks/ach-aapanel-customizer/issues/1) is deliberately still open. The identified native FPM writer, reset/reload and test-owned rollback narrow the original uncertainty, but do not establish plugin-owned Apply/rollback or reliable extension survivability. Remaining gates include temporary/restricted browser roles, native canonical rename if required, PHP-FPM write conflict and effective-runtime checks, Nginx regeneration independence from `site_total`, and owner-approved reversible Apply. Do not install this development package on production.

## Local source verification (safe to run without aaPanel)

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_inventory_ui.cjs
sh -n plugin/ach_customizer/install.sh
python3 -B scripts/build_plugin.py --output /tmp/ach-customizer-dev.zip
```

This ZIP is a **development artifact only**. It must not be marked compatible, released, or deployed until actual panel and lifecycle acceptance is documented.

## Architectural guardrails

- No core patching, public admin listener, background daemon or scheduler in the first slice.
- Never assume a site ID belongs to one PHP-FPM pool or that site-specific policies may write shared pool settings.
- Dynamic routing cannot be used as a privileged shortcut; server-side operator authorization at execution time is mandatory.
- Persistent future policy/recovery state must be outside the replaceable plugin directory; uninstall/purge semantics must preserve non-owned state.
- A source-defined `server` include is not proof that arbitrary Nginx `location` changes can be overridden there.
- Monitor must never perform host changes. Runtime validation, per-policy approval, preflight, locks, recovery and uncertain-effect reconciliation are prerequisites for any Apply mode.

## Initial guarded manual PHP-FPM vertical slice — isolated guest, 2026-11-02

**Development only, not Production-authorized.** The existing read-only shared-site attribution and the separately staged PHP-FPM recovery adapter are integrated into the normal `ach_customizer` native class endpoints and management UI in **unreleased `0.1.3`**. A full primary aaPanel administrator must submit a POST under the panel's normal authenticated plugin route, explicitly approve the shared `PHP85-www-shared-service` scope, and supply a current Monitor revision, before/after configuration SHA-256 and bounded site-attribution SHA-256. The server rechecks site mappings and Monitor revision immediately before the file mutation (best-effort for writes outside the plugin lock). Normal installation and Monitor remain non-mutating; there is **no scheduler, automatic enforcement or implied per-site setting**.

The only writable adapter is deliberately restricted to **aaPanel 8.0.7 + Nginx + versioned PHP 8.5 direct `[www]` pool** and its root-owned `php-fpm.conf`. Unsupported file shapes, multiple pools/includes, symbolic/hard-linked files, unsafe owner/mode or extended attributes refuse Apply. A durable root-owned backup/journal precedes atomic replacement; FPM syntax is checked, only the versioned service is reloaded, then FPM `-tt` parsed-file values and PID/socket presence are checked. The config dump is not independent proof of all running workers' effective settings. Failure after a real write triggers exact-identity restoration and **baseline-specific** runtime verification; if restoration cannot be proven, a recoverable `uncertain` journal remains. An explicit saved-operation rollback refuses intervening external edits. Mutation outcomes additionally use the observed aaPanel 8.0.7 `public.WriteLog` native activity-log API with timestamp, request correlation, action, result and recovery reference, without input payloads or secrets. Activity-log persistence is reported separately; an audit failure does not turn an actually completed host mutation into a false failure. Monitor disable or uninstall does not erase recovery evidence or silently alter host services.

**Real non-production integration:** A disposable QEMU Debian 12.15 guest had aaPanel 8.0.7, Nginx 1.28.3, PHP-FPM 8.5.12 and two native aaPanel websites IDs 3 and 6, both mapped via conventional site VHosts to the same FPM socket. The `0.1.3` ZIP was accepted by native `panelPlugin.update_zip`/`input_zip`. The installed module (fresh Python process) rejected a nonprimary session and a temporary-token session, refused stale impact approval, performed a real PHP-FPM Apply+reload, and served actual test PHP through both HTTP site VHosts. An exact saved rollback reloaded FPM, restored the original config SHA and left both sites healthy with no journal. A separate fault probe forced an exception after a genuine candidate reload, confirmed automatic original-file restoration plus FPM reload and baseline-specific verification, and completed a subsequent explicit successful Apply and rollback. The first deliberately persistent failure correctly left the journal `uncertain` rather than fabricating recovery; the test-owned journal was reconciled through the guarded rollback route. No production server was touched.

The source-bound JSON [native manual FPM QA](evidence/aaPanel-8.0.7-2026-11-02-integrated-manual-fpm-qa.json) records the exact tested ZIP identities, assertions and known gaps. The installed-class integration used a **synthetic Flask full-admin request context** and is **not evidence of successful real browser CSRF or secondary-account permission replay**. The shipped runtime health hooks check FPM syntax/config, PID and socket; two-site HTTP checks belong to the external isolated test instrumentation, not a built-in traffic monitor. Another native action or unrelated process may still overwrite aaPanel-owned shared configuration later, creating new drift. Do not extrapolate compatibility to Apache/other panel or PHP versions. A production release/installation and merge still require independent review and explicit authorization.


## Unreleased 0.1.17: PHP 8.1 guarded shared-pool Apply/Restore (Issue #2)

This **new candidate** extends the already reviewed PHP 8.5 shared [www] workflow only to the installed aaPanel 8.0.7/Nginx PHP 8.1 single-pool layout. The existing selector and runtime/socket/source inspectors continue to be read-only. Only versions 81 and 85 expose a guarded manual writer; 8.2/8.3/8.4 and any other discovered versions remain Preview-only. The same explicit POST/full-primary-admin and Monitor/impact/revision/approval gates apply; a file map does **not** establish safe traffic routing or non-aaPanel consumers.

The new PHP81-www-shared-service approval is deliberately incompatible with PHP85-www-shared-service. The PHP 8.1 recovery journal and exact backup in persistent panel data are ach_customizer.fpm81.recovery.json and ach_customizer.fpm81.recovery.before. The PHP 8.5 names and their schema are preserved for compatibility. The existing shared operation lock serializes versioned writes and recovery; each journal belongs only to its version. Apply checks syntax, reloads only /etc/init.d/php-fpm-81, verifies versioned binary -tt, PID and /tmp/php-cgi-81.sock, and preserves baseline-specific automatic restoration on failure. Saved Rollback checks exact operation/config/site impact and the selected version immediately before replacing bytes. Monitor and the installed-plugin list are not authority to write.

**Evidence boundary:** Source tests cover both versions, separate journals, cross-version Restore refusal, failed Apply restoration and UI stale-version invalidation. A real aaPanel 8.0.7 QEMU guest **now verified** native PHP 8.1.35 site creation/assignment (site ID 9), HTTP 200 PHP execution, one-site impact mapping, actual versioned config+FPM reload, exact baseline Restore, injected post-reload fault restoration, unchanged PHP85 and three pre-existing WordPress VHosts, and 46/46 native imported ZIP files. Its writable disk was then cold restored to the protected snapshot, with baseline 0.1.12 plugin hashes 39/39 and WordPress HTTP 200 verified; the protected snapshot SHA256 was unchanged. See [the source-and-guest QA evidence](evidence/aaPanel-8.0.7-2026-11-07-php81-guarded-native-qa.json) for exact SHA256, native driver paths and limits. Real authenticated aaPanel Browser/CSRF, secondary roles and consolidated plugin install/update/uninstall acceptance remain under Issue #21. This section does not authorize merging, stable release or Production deployment. Do not conflate historical PHP85 test evidence with fresh PHP81 QA.

### PR #33 R1 independent-review corrections (2026-11-07, unreleased)

**REQUIRED-01 — source/runtime identity:** Source-level PHP81 site attribution can accept an alternate literal Unix socket, but native runtime hooks only verify the fixed /tmp/php-cgi-81.sock listener and versioned /www/server/php/81/var/run/php-fpm.pid. The bounded PHP81 writer now requires an exact one-time [www] listen and [global] pid matching those paths before granting Prepare; the same source-layout contract is rechecked by the core Apply plan under the shared recovery lock, by native runtime hooks and immediately before explicit Restore. Nonconventional source layouts are rejected before any backup journal, file mutation or reload; the original PHP85 adapter and recovery schema are unchanged. A PHP81 journal with incompatible later source remains inspectable, reports an explicit manual-recovery path, and cannot authorize an automatic Restore. This guard does not prove complete effective Nginx/PHP runtime routing or external consumers.

**REQUIRED-02 — independent saved Recovery choice:** A separate two-option **Saved recovery service** selector (PHP 8.5 default, PHP 8.1 alternative) is available regardless of the ordinary PHP discovery selector or its failures. A failed/incomplete get_php_versions no longer hides PHP81 saved operation ID, phase, conflict reason or manual-recovery guidance when the backend can safely return them. Changing the recovery version invalidates pending approval, saved restore values and stale callbacks. Existing primary-admin POST authorization, fresh impact, version-specific approval, operation ID and SHA checks remain mandatory before privileged Restore; no blind write or reload follows incomplete recovery evidence.

The [corrected exact-package source/native evidence](evidence/aaPanel-8.0.7-2026-11-07-php81-pr33-r1-remediation-qa.json) records 451/451 Python and 208/208 JS tests. An exact 46-member ZIP was imported into the isolated Debian12/aaPanel 8.0.7 QEMU guest; a deliberately changed listen or pid was rejected before mutation despite the original conventional socket still present. The same installed code then passed a clean cold-start native PHP81 website/HTTP200, Apply/reload, exact Restore, injected post-reload fault restoration, unchanged PHP85 and WordPress sites, followed by verified guest cold recovery to plugin 0.1.12 with its 39/39 hashes and unchanged protected snapshot SHA256. A first native AddSite request observed a brief HTTP404 before the site's Nginx configuration became active; the test driver now waits up to 15 seconds for HTTP readiness without forcing a reload. Real authenticated browser/CSRF, full native Phase B acceptance, independent corrected-candidate review, Merge and Production authorization are separate gates.

## PR #9 high-assurance remediation: shared impact and recovery decisions

**Source candidate under correction, not a new guest validation or merge authorization.** The independent full-diff review of original candidate `513123ec988b1bdf35169b85458206b9e3c453a0` identified three REQUIRED issues: an additional Nginx include could bypass bounded routing eligibility; explicit Rollback did not bind its authorization to the *current* affected sites; and the native uninstall text incorrectly implied no host configuration could remain changed. Earlier guest observations and ZIP SHA-256 describe the **old candidate only**; do not assign them to the corrected source until tested.

- **Fail-closed Nginx attribution:** each accepted VHost must have exactly one conventional direct `enable-php-<version>.conf` include; the *only* permitted additional VHost include is that website's exact native `/www/server/panel/vhost/rewrite/<site>.conf`, which is separately read, screened for nested includes and upstream routing directives, and fingerprinted. The native PHP include may use only the explicitly inspected bounded `fastcgi.conf` and `pathinfo.conf` parameter files; other nested includes, unsafe routing directives, ambiguous paths, missing files and linked dependencies require `Needs Review`. Every accepted VHost and included dependency contributes content and file identity to `dependency_sha256`, which is bound into the approval's impact digest and refreshed before Apply or Rollback. **Follow-up for the focused review of `4f291902`:** the PHP snippet checks *all active* `fastcgi_pass` directive occurrences independently of the single accepted full-line literal Unix socket destination; named, variable, duplicate, malformed or other socket destinations fail closed, as do unsupported proxy/uwsgi/scgi/gRPC/memcached upstream routing directives. Commented-out directives do not count. The existing bounded `fastcgi.conf`/`pathinfo.conf` and native rewrite handling, ownership protections, and dependency fingerprints remain unchanged; focused negative tests also verify that ambiguous routing cannot authorize a manual Apply. This is a conservative supported *file attribution* contract, not a general Nginx parser. An aaPanel/`site_total`-injected per-site extension include, including a benign one, intentionally makes Manual Apply/automatic Rollback ineligible until a separately validated adapter supports it.
- **Uniform unsupported-upstream rejection (REQUIRED-04):** the same bounded `NGINX_UPSTREAM_DIRECTIVES` policy is now applied to the accepted direct VHost, native per-site rewrite, `fastcgi.conf`, `pathinfo.conf`, and PHP include. These surfaces reject unexpected `fastcgi_pass`, `proxy_pass`, `uwsgi_pass`, `scgi_pass`, `grpc_pass`, and `memcached_pass`; only the *main PHP include* may have the single separately verified literal `fastcgi_pass unix:<inspected [www] socket>;`. Comments are excluded consistently. A mismatched or ambiguous dependency returns `Needs Review` and cannot authorize Prepare/Apply or automatic Rollback; the old recovery journal/snapshot remain preserved. No wider Nginx syntax support is asserted. Source-level fixtures cover each accepted dependency and fail-closed mutation decisions; real guest validation for the new candidate remains outstanding.
- **Nginx comment/argument lexical safety (REQUIRED-05):** `_active_nginx_text` now strips `#` comments only at token boundaries, preserving literal `#` inside single/double quotes, unquoted argument tokens, escaped hashes, and further active directives on the same line. The bounded scanner follows the relevant token-boundary/escape rules in upstream `ngx_conf_read_token()`; unterminated quotes, trailing escapes and unsupported post-quote text are rejected rather than silently ignored. The same helper is used for every accepted dependency, so an active FastCGI or other upstream route after a literal hash invalidates mapping and cannot authorize Apply or stale Rollback. This is a conservative source inspection, **not** a complete Nginx runtime parser; acceptance on the exact guest/package remains outstanding.
- **Rollback is a new privileged decision:** `fpm_recovery` remains read-only and accessible to a full primary administrator even if ordinary Monitor is disabled. It shows five numeric baseline/current PHP-FPM policy values, SHA-256 identities, and a freshly inspected shared-site file mapping. The UI displays affected website IDs/keys and the restoration values before enabling its explicit approval. `fpm_rollback` requires both `expected_recovery` (hash binding operation, config identities, restoration effect and impact) and `expected_impact`. The backend repeats those checks under its recovery lock immediately before any config change or versioned reload. A newly created, deleted, reassigned or ambiguous site, or any changed inspected dependency, invalidates the previous approval; no file mutation occurs and the journal/snapshot are retained.
- **Manual recovery when automatic Rollback is unsafe:** do not delete the persistent records `/www/server/panel/data/ach_customizer.fpm85.recovery.json` and `/www/server/panel/data/ach_customizer.fpm85.recovery.before`. First inspect the reason, current aaPanel site assignments/VHosts, actual PHP-FPM config and health. Reinstall a compatible plugin to regain its guarded recovery UI after uninstall. If the supported mapping cannot be reestablished, an authorized operator must preserve a separate copy of the *current* FPM configuration, verify the journal's operation and SHA-256 against the exact saved snapshot, reconcile conflicting writer/site effects and supervise any emergency restoration with PHP-FPM syntax/reload checks and website-level health verification. Preserve journal evidence until restoration is actually verified; no automatic or blind replacement is justified by the existence of a snapshot.
- **Uninstall remains non-destructive:** aaPanel removes the plugin's replaceable code while the hook attempts only positively owned icon cleanup. It neither changes PHP-FPM nor deletes operator state, saved recovery bytes, or previously applied settings. Operator-facing output now warns that changes may remain active and describes the recovery/reinstallation path.

These constraints are not evidence of a generic PHP-FPM runtime or Nginx effective-routing contract. Subsequent exact-candidate CI and a focused independent re-review are required; production hosts and release are outside this development authorization.

## Offline Status Pages branding and preview (initial slice, Issue #10)

**Unreleased development candidate 0.1.4; no public release and no Production authorization.** The native **Status Pages** tab is an initial portion of [Issue #10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), **not** the eventual website/panel Apply, Restore or verified lifecycle functionality. The source design reference branch (reference/ach-status-pages-v1-20261103, exact commit 6c9412f3b220a563b64b82ce3d8ee65ff324fbbe) holds the owner-approved originals. The plugin ZIP bundles **all 22 original English/Persian HTML bytes exactly**, plus a SHA-256 manifest checked during package build and preview. No remote fonts, JavaScript, CSS, CDN or runtime network dependency.

- **Preview only:** Select among 11 templates and English/LTR or Persian/RTL, optionally preview unsaved white-label settings, and view a fully self-contained page inside a sandboxed, no-referrer iframe. Native read-only endpoints status_preferences/status_preview return source and rendered SHA-256. Built-in ACh identity/palette reproduce original source bytes. The 404 homepage action remains site-local (/) regardless of independent brand URL. A preview cannot change actual HTTP status.
- **Bounded inputs:** HTML text and attribute escaping; brand URLs must be safe HTTP(S) with non-local hosts requiring HTTPS. Control/CRLF and unsafe URLs are rejected; canonical six-digit hex colors, text/background contrast of at least 4.5:1 and accent/background at least 3:1, bounded text lengths. No arbitrary JS/CSS/HTML/filepath/template upload.
- **Preferences:** A separate schema-v1 root-owned mode-0600 state file ach_customizer.status_pages.json within /www/server/panel/data stores global defaults and up to 100 explicitly selected site-ID overrides. Reads do not create state. A normal native aaPanel plugin POST plus independent full-primary-admin/temporary-token-denial gate is required for status_save. Revision checked under a bounded file lock prevents stale overwrites. Writes use ownership/mode/ancestor checks, no-follow file operations, fsync and atomic rename. Reset requires explicit confirmation and changes only the selected branding scope. Sites are resolved against the native aaPanel sites table; no inferred or auto-assigned site policy.
- **Durability:** Preferences are outside aaPanel's replaceable plugin folder; normal uninstall does not purge preferences. Monitor and FPM schemas remain unchanged. Updating bundled template files does not write website files or reset site choices.
- **Source verification:** tests/test_status_pages.py validates exact source assets, default/custom outputs for both languages, HTML/URL/color threats, independent scoped preferences/revisions, and mocked native endpoint role gates. tests/test_inventory_ui.cjs executes the deployed inline script to verify preview-only UI, visible errors, revision-bound Save, per-site Reset and iframe isolation. Validate source checks on the final exact candidate; source tests **do not** prove real browser aaPanel session/CSRF or native import.

**Native deterministic-ZIP bytecode compatibility (verified):** aaPanel's plugin ZIP import preserves member timestamps on installed Python source. A historical constant 1980 timestamp allowed CPython to load stale bytecode when a same-size source file changed: file bytes contained the updated 3:1 color guard, but a **new** interpreter executed the old 2.7 guard from existing bytecode cache. The deterministic ZIP builder now derives each member's two-second DOS timestamp from that member's source SHA-256; regression tests require different timestamps for known equal-length edits and prove the ZIP is reproducible. A real same-version isolated aaPanel 8.0.7 native ZIP update to the corrected package, without manually removing bytecode caches, then executed the new guard correctly. **An already running aaPanel worker may still have an old imported module**; a controlled guest-only panel worker restart can still be needed to refresh loaded modules. ZIP times are deterministic content fingerprints, **not** real file creation or publication dates. Do not restart Production panels automatically.

**Current native 0.1.4 evidence (exact development ZIP):** In the isolated Debian 12/aaPanel 8.0.7 + Nginx/PHP85 guest, native panelPlugin ZIP update imported the source; all 34 installed files matched the exact development ZIP, all 22 default pages rendered from the installed plugin, Status Pages preferences saved/rechecked/resetted both globally and for native website IDs 7/8, with stale revision, non-primary and temporary-token session attempts refused under **synthetic** Flask request context. A same-version corrected ZIP update preserved revision-3 global branding and prior Monitor state, did not modify either site's VHost or PHP-FPM config, and both real sites returned HTTP 200 afterward; nginx -t succeeded. Guest shutdown and copy-on-write image integrity were verified. **These are installed-class and real-site HTTP checks, NOT authenticated browser/CSRF checks**, not live page Apply and not cross-version/Production assurance.

[Source-bound native Status Pages test evidence](evidence/aaPanel-8.0.7-2026-11-03-status-pages-preview-qa.json).

### 0.1.5 development candidate: native site-file comparison, not live Apply

This is a read-only, fail-closed diagnostic extension of Issue #10. In the Status Pages tab a **full primary aaPanel administrator** can select a native website (by current aaPanel sites.id) and inspect only its 404 or 502 template; global scope and other page variants cannot use this action. Optional unsaved branding from the same validated offline renderer computes the **selected rendered SHA-256**. The read-only status_inspect endpoint also checks the native site ID and its database record immediately before and after inspection. Neither a read-only result nor a matching hash authorizes any installation.
The comparison also reports whether the selected rendered HTML is **new, byte-identical, different or unavailable** relative to the on-disk 404/502 file. For valid UTF-8 text within bounded byte and line limits, a clipped, plain-text unified diff excerpt (max 6 KiB) is displayed for human inspection; long lines and longer diffs are explicitly truncated, while binary/control/bidi-ambiguous or oversized content returns **Unavailable** without leaking raw file contents. C0/C1, Unicode formatting/directional marks and line/paragraph separators are refused in both changed text inputs; CR/LF/TAB and ordinary Persian ZWNJ are retained. The frontend independently rejects excerpts over 6,144 **UTF-8 bytes**, diffs exceeding 240 source lines per input, or malformed unified headers/hunks. Clipped output lines including the marker are at most 360 Unicode characters. The excerpt is not an Apply-ready patch; it never writes a site file, modifies a VHost, reloads Nginx or proves effective HTTP routing. Editing a branding field, switching template/site/locale or an incompatible backend response clears stale comparison evidence. Explicit Apply/Restore remains separately gated and unimplemented for Status Pages.


The bounded source inspector reads without following symbolic links on any path component, using an anchored directory walk and stable regular-file descriptors: the selected native document root 404.html or 502.html, the native Nginx /www/server/panel/vhost/nginx/<site-key>.conf, and up to 32 .conf fragments under the conventional site-extension directory. Each inspected file is limited to 64 KiB. Its response exposes the selected/current page hash (or missing), a VHost hash, observed textual site-extension include, filenames of scanned extensions, and potential error_page declarations. It does **not** expose page/VHost contents to the UI. After each bounded read, the inspector re-resolves the original absolute document-root, VHost and extension directory path from the filesystem root, checks directory identity, file identity and observed extension filenames, and refuses detached or replaced paths without retaining a stale page SHA or diff. The final re-resolution is a point-in-time check, not a claim that a file can never change afterward. Invalid, missing, oversized, symbolic-linked, changed-during-read or ambiguous resources are refused or explicitly classified without inventing a successful state. Conflict can identify a differing existing page or potential competing error_page, Unmanaged means no selected site file found, and File Match means *only* byte-equivalent content. Needs Review and Unsupported are conservative states; they are not enforcement decisions.

**Unreleased native diagnostic precision correction (PR #20 continuation):** The inspector no longer classifies every existing `error_page` as a conflict. It distinguishes only directives referring to the *selected* 404 or 502 status, ignores unrelated standard 497 HTTPS redirects, and recognizes the literal aaPanel `error_page 404 /404.html;` / `error_page 502 /502.html;` as an **existing source reference requiring review** rather than a competing target. A different literal selected-status target remains `Conflict`; duplicate, embedded, multi-code or unsupported forms remain `Needs Review` **unless the separately verified existing site page has different bytes, in which case `Conflict` takes precedence and the additional routing ambiguity stays in the diagnostic reason and source list**. Supported unrelated Nginx `=response` forms (such as `error_page 497 =301 https://$host$request_uri;`) are excluded after identifying their leading source status codes; selected-status overrides remain uncertain. Incomplete or unstable file inspection still fails closed as `Needs Review`. `File Match` remains exclusively an on-disk byte comparison, not Nginx route/owner proof. Status Pages branding Save and Reset emit **distinct** local Activity actions (`status_save` / `status_reset`) and accurate operator-facing success messages. The source parser does not imply that a directive was loaded, inherited, or effective; this inspector is still read-only and cannot authorize the newer narrowly gated existing-site 404 file manager. Earlier candidate QA results and their historical classifications remain scoped to their recorded versions.

**Hard boundary:** Source text and a disk SHA are not a loaded Nginx configuration (nginx -T), a running website HTTP response, an ownership grant, or proof that a site-extension include survives aaPanel regeneration. Potential conflicts may be over-reported deliberately. This package **does not** install HTML, edit Nginx, start a reload, create backups, perform HTTP checks, or enable Apply/Restore/Auto-enforce. Those remain Issue #10 acceptance requirements and require separate native adapter evidence, live HTTP 404/502 status checks, ownership and recovery gates. The native endpoint is gated for a full primary admin POST, and the browser UI accepts only matching site/template/locale, correctly typed hashes, and explicitly non-Apply results.

**Exact non-production native QA (2026-11-03):** In a disposable child QEMU overlay of the existing Debian 12 / aaPanel 8.0.7 / Nginx 1.28.3 / PHP-FPM 8.5.12 lab, the native panelPlugin update_zip/input_zip flow installed the unreleased 0.1.5 development ZIP (SHA-256 f4cf90f2661d68e1ecb3dc270aed59cb7e96dcca23788caaef631e3fa1f558aa); all 35 installed files matched the package. The installed endpoint ran in a fresh panel Python process. Both real site IDs 7 and 8 had existing site-owned 404/502 HTML files with bytes different from the selected original templates; the source inspector correctly reported Conflict and detected existing error_page directives. A temporary 404.html test fixture exactly matched the selected bundled HTML digest, which the endpoint reported as Same bytes *without* asserting Nginx runtime or safe Apply. The fixture was restored byte-for-byte. Synthetic Flask POST tests denied nonprimary and temporary identities, and GET. Both site VHosts, PHP-FPM config, 404/502 files and previously saved plugin settings were unchanged by the whole test; nginx -t passed and both sites returned HTTP 200 before/after. The guest powered off gracefully and qemu-img check found no errors. This is **not** live 404/502 HTTP routing, CSRF/authenticated-browser or cross-version acceptance. [Sanitized bounded native evidence](evidence/aaPanel-8.0.7-2026-11-03-status-pages-site-inspect-qa.json).

**Remaining verification boundary:** Source unit/UI tests prove fixture and deployed-script behavior; the non-production native QA above exercises the installed backend and existing site files in a fresh Python process. Real authenticated browser session/CSRF, VHost regeneration timing for this exact candidate, cross-version support, and effective Nginx error-page routing remain unverified. No public release or Production deployment is authorized.

### Read-only Status 404 adoption evidence (not Apply)

Issue #10's source-level 404/502 inspector now identifies the origin of a **textual** selected-status directive as None, Native VHost, Referenced Extension, Unreferenced Extension, Alternate, Ambiguous or Uninspected. A Native VHost designation means only that one syntactically conventional literal mapping was found in the inspected VHost *text*, with no duplicate selected-status mapping found in the bounded extension source scan. It is **not** proof of the directive's effective Nginx context, the loaded worker config or aaPanel ownership. A referenced extension can disappear from a generated VHost while its file remains on disk; the unreferenced state prevents mistaking the orphan for a live mapping.

The explicit localhost HTTP/80 404 probe now returns adoption_preview (schema 1). It cross-checks the observed 404 status/body with the exact inspected site file and original operator-selected render SHA-256. Matches Preview means the single observed response and selected bytes agree; ownership remains unverified. Backup Required means the observed current site 404 bytes match the current file but differ from the proposed rendered HTML and the source contained one native VHost-text mapping; replacing the file would require **explicit operator adoption, recoverable backup, crash-safe atomic change and verified Restore**. Every mismatch, unsupported/ambiguous origin, timeout or missing evidence remains Needs Review. All outcomes have apply_supported=false, ownership_verified=false and recovery_verified=false; no action or permission token is produced. The browser validates these constraints, renders text only, and invalidates results when site/template/branding selection changes.

This read-only adoption preflight has no write permissions. The earlier **existing-file 404** transaction was superseded and removed from the unreleased 0.1.14 build. A guarded Nginx extension for site-level **404 and 502** is described next; **global/default, missing-file/new-site onboarding, and full native/role/regeneration acceptance** remain P0 work. Effective-routing and cross-site correctness must be checked before any production activation; do not induce 502 failures on shared hosts. This adoption report is a non-authorizing prerequisite, not a native-acceptance result.

### Guarded native status page extensions (source candidate, Issue #10)

**Accepted requirement:** Owner selected Option A — real native Status Pages Apply/Restore in the initial release, without silently overwriting an operator-owned document-root file or unrelated aaPanel configuration. This is a source candidate until installed-native, rollback, role/CSRF, cross-site and independent review gates pass. The old `RENAME_EXCHANGE` document-root manager and disk-to-worker timestamp heuristic were removed from the shipped package as an unsuitable ownership architecture.

**Target and scope:** A confirmed primary aaPanel administrator selects an exact running site and a 404 or 502 EN/FA render with a current branding revision. Backend independently verifies native `sites` registration, exact bound domains on port 80, aaPanel 8.0.7 + Nginx, unique native document root and one literal site VHost with exactly one matching `root`, `server_name`, `error_page 404 /404.html` or `error_page 502 /502.html`, and one native `extension/<site>/*.conf` include. All relevant source directories, existing assets and recovery state require trusted root ownership and safe modes; the **bounded effective include-file graph** is walked from the active nginx.conf, with only conventional per-site glob imports and the native top-level site import accepted; broader/indirect imports, aliasable wildcard prefixes and ambiguous server contexts are rejected. Real aaPanel can include empty rewrite files, which are valid but never considered plugin-managed partial .conf files. No direct edit of an existing website `404.html`, `502.html`, Nginx core/vendor VHost, PHP, WordPress or another site's extension is authorized.

**Operator-controlled Apply:** Explicit `apply_exact_site_<code>_reload` approval for this site, content and known shared Nginx reload is required. The plugin stages complete HTML and .conf bytes under uniquely named **non-active .stage** files, confirms their bytes and file fsync, then uses Linux no-clobber atomic rename and directory fsync to publish. Staging errors retain the prepared journal and recovery ID for Recheck/Restore; no incomplete *.conf is exposed to Nginx. The plugin stores an exact-version immutable HTML asset under `/www/server/nginx/.ach-customizer-status/<siteID>/<code>-<sha>.html` and writes one root-owned 0600 Nginx extension snippet under `/www/server/panel/vhost/nginx/extension/<site>/ach_customizer_<siteID>_<code>.conf`. The snippet adds `location = /<code>.html { internal; alias ...; add_header X-ACh-Status-Proof <nonce> always; }` and a localhost-only independent proof location. The original native `error_page` directive remains in the VHost. Source/HTML identity and a root-owned durable prepared journal are persisted **before** source activation. `nginx -t -c /www/server/nginx/conf/nginx.conf` must succeed. The plugin invokes `nginx -s reload -c /www/server/nginx/conf/nginx.conf` only after syntax/ownership checks, then confirms the actual selected-site status code, HTML SHA-256 and fresh nonce on three distinct loopback HTTP requests. An unacknowledged or incomplete reload is **uncertain** and retains evidence, not a retry authorization.

**Recheck and Restore:** `Recheck` is read-only and returns the current journal/recovery identity; `Recovery Required` blocks blind re-Apply. Explicit `restore_exact_site_<code>_reload` approval requires the exact recovery ID, trusted source and matching managed snippet. The snippet is atomically renamed to a unique, non-clobber `*.retained` entry rather than discarded (preventing silent data loss through an open file descriptor). After syntax validation and one controlled reload, three independent loopback observations confirm the prior nonce is gone. For 404, restored HTTP status/body must match the recorded pre-Apply HTTP baseline. **502 Restore reports `Source Restored`, not `Restored`:** the native 502.html source fingerprint and managed source removal are checked, and repeated live proof probes show the old nonce has gone, but an actual previous HTTP 502 status/body was not safely induced or verified. The `502` preview is **configured-source-only**. A final journal-save failure *after* Nginx activation is explicitly `uncertain` with the known recovery ID; Recheck is required before any subsequent action. A failed/ambiguous Apply/Restore preserves the durable journal, asset and retained snippet for explicit recovery. No automatic pruning of retained evidence is performed.

**Evidence and remaining native gates:** The prior integrated PR #29 HEAD `38b10dd` was installed on the isolated aaPanel 8.0.7 QA guest and demonstrated HTTP/80 + HTTPS/443 real 404/502 Apply/Restore, three non-target WordPress sites remaining healthy, recovery after lost Nginx reload acknowledgement, and cold verified rollback to plugin 0.1.12; see [Issue #21 checkpoint](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6702443173). That evidence belongs to the **prior** HEAD and does **not** prove the new publication/include-graph remediation. The updated source graph was inspected read-only against the same native aaPanel layout, including valid empty native rewrite includes. Complete exact-remediation native fault/recovery acceptance, authenticated browser roles/CSRF, update/reinstall persistence, static/PHP sites, global/default/new-site templates, aaPanel regeneration and other Owner Option A scope remain open. No Merge/Release/Production authorization follows from source tests.

**Release gates:** Source tests/CI alone cannot certify file safety or normal site behavior. Do not merge/release/deploy this draft before full native acceptance, exact current independent HIGH_ASSURANCE review and separate Owner authorization.

### Native site-scoped Nginx-generated 50x (Issue #10, unreleased 0.1.20)

This optional **generic `50x`** delivery reuses the independently scoped `native_status_extension` on a running native aaPanel 8.0.7 Nginx site. The site must have a verified server-level extension glob and standard native `error_page 502 /502.html;`. The preflight reads the original 502.html file only as a **source/Restore baseline**; no 50x response is induced or claimed before Apply. The operator selects the 50x EN/FA render and authorizes `apply_exact_site_50x_reload`, with the normal site snapshot, revision and VHost/source SHA guards.

The plugin-owned extension binds `/502.html` to the immutable 50x asset, preserves the native 502 error_page directive and adds the missing Nginx-generated `error_page 500 503 504` mapping. Four localhost-only proof locations each generate its exact status using Nginx `try_files ... =<code>`; *all four* must return their original HTTP status, identical rendered body digest and the operation nonce on fresh HTTP connections before Applied can be asserted. Unknown/partial generations remain unconfirmed; **a single remaining old-generation nonce prevents claiming Restore completion**. A second active 502 or 50x extension on the same site is rejected before publication. Existing 500/503/504 mappings in the native VHost also prevent conflicting Apply, including multiline, nested and quoted/comment-adjacent Nginx directive forms; unreadable/ambiguous statements are refused before publication. The source-independent original 502.html is never modified.

Restore requires the saved operation ID, checks the exact managed extension SHA, retires the managed include, reloads with Nginx syntax validation and proves that none of the former 50x error routes still serves the old nonce. Recheck on stopped/drifted sites remains saved-journal-only, not runtime proof. This does not install a global HTTP 50x route, intercept application/PHP/FastCGI/Proxy error bodies, change native SiteStop's soft HTTP200, handle HTTPS unknown hosts, or rewrite vendor-generated VHosts. Full authenticated Browser/CSRF and native plugin lifecycle acceptance remain Issue #21.

### Native site-file 404/502 delivery without Nginx reload (Issue #10, unreleased 0.1.19)

**Supported native target:** a real aaPanel 8.0.7/Nginx site bound on HTTP/80 with a unique native document root, existing safe regular file 404.html or 502.html, exactly the native selected error_page code mapping to the matching HTML filename, and no competing site-specific extension import or incompatible source. This mode enables **existing files only**, not arbitrary path creation or a VHost rewrite. A site with a proven extension include instead keeps using the independently selected *Native Nginx extension* delivery mode. A newly created aaPanel PHP site may have the correct native HTML/error_page mapping while lacking the extension include; that is the main purpose of file mode.

**Operator flow:** Select the website, locale, 404 or 502 and **Existing native 404.html / 502.html** delivery mode. Run explicit read-only Check selected 404/502 source, review exact current HTTP 404 and file SHA-256 (502 source-only, never a synthetic HTTP 502), approve the mode-specific Apply and its exact expected site/VHost/current/render hashes. The primary-administrator-only status_manage endpoint revalidates current native site/domain bindings, existing file ownership/mode, source and branding revision, and the correct mode-specific approval. It saves a root-owned per-site per-code backup and durable Recovery ID, then atomically replaces only the owned existing status HTML with matching uid/gid/mode. No Nginx configuration is patched and **no Nginx reload** is requested. For 404 the adapter checks actual status and body SHA through the selected site's bound loopback Host before and after the operation; for 502 verification_scope=source_only and runtime_verified=false, without misrepresenting a live 502. File contents remain self-contained/offline EN or FA.

**Recovery:** Recheck is read-only and shows Applied/Restored or source-only Source Restored where proven; Suspended if native site is stopped, or saved-only Needs Review for changed/incompatible VHost. These journal-only views do not grant a write. Restore requires original operation ID, exact source/mode and existing file integrity, then republishes the saved original bytes and reports actual 404 HTTP status/body or 502 source-only status. An interrupted prepared Apply with a complete inert staged file is recoverable by a separately authorized Restore; a staged file is retired only if it belongs to that exact operation and matches the expected content/ownership. Independent edits, unexpected file types, symlinks and non-exclusive or inaccessible native targets cause denial rather than overwrite. Existing Nginx extension Apply/Restore is unchanged.

**Acceptance evidence:** [Exact native aaPanel 8.0.7 site-file QA ledger](evidence/aaPanel-8.0.7-2026-11-07-native-site-file-qa.json) records the versioned exact ZIP/CI identities, real newly created native PHP test site, installed member hashes, 404/502 Apply/Recheck/Restore, stopped site, incompatible VHost, three non-target WordPress sites, file mode and recovery denials, and protected guest cold restoration. Tests use synthetic Flask full-primary-admin POST, not authenticated Browser/CSRF. No Production/Stable release authorized. Generic stopped-site HTTP 503, unknown-host HTTPS/443, generic 50x and comprehensive browser/lifecycle Phase B remain Issue #10/#21 work.

**Independent-review correction (PR #35, 2026-11-07):** The native-file writer now uses exactly the same supported permission predicate as its saved recovery journal; unsupported setuid/setgid or low modes are rejected *before* backup, journal or live publication. The bounded native VHost source check also verifies that the selected site root, canonical server name and status-specific error_page mapping are direct server-scope declarations: nested-only location rules do not qualify, while conventional aaPanel PHP includes/locations remain supported. The [exact remediation QA ledger](evidence/aaPanel-8.0.7-2026-11-07-native-site-file-review-delta-qa.json) records 473 Python and 214 JavaScript passing tests, all 64 admitted permission modes round-tripped, wrong-mode/ambiguous-scope rejection and a full isolated aaPanel native Apply/Restore rerun against a deterministic 47-file ZIP. The QA guest was returned to its intact pre-test baseline; an independent **delta re-review** is required before Merge. This evidence is not authenticated-browser acceptance or a Production release.

### Native SiteStop/Start saved Status Pages recovery — Issue #10 (unreleased 0.1.18)

**Verified incompatibility:** aaPanel 8.0.7 Nginx native SiteStop rewrites the exact selected website's VHost root to /www/server/stop, comments its native extension includes, records site status 0 and reloads Nginx. In the isolated guest, native stopped-site GET /index.html eventually served the shared stop HTML as **HTTP 200**, not 503, even while a plugin-owned 404/502 operation remained saved. SiteStart restored the previous VHost bytes and eventually the managed error routes. These aaPanel service reloads are asynchronous; an immediate HTTP 200 or an early negative Recheck does not prove a settled Nginx generation.

**Bounded recovery read:** The full-primary-admin native POST status_manage accepts a stopped site's Recheck bound to its exact current native inventory/site/domain snapshot; it still denies Apply and Restore. The fixed root-owned journal is read using the existing no-follow identity and permission checks. A matching saved site ID/key with operation data returns Suspended while stopped, or Needs Review if a running site's VHost is replaced, missing or cannot satisfy the original source/record hash contract. The response contains the saved operation ID and phase, original and applied SHA-256 identities, a clear manual next step, runtime_verified=false, read_only=true and verification_scope=saved_journal_only. These hashes are **journal metadata, not current live HTTP evidence**. No saved journal yields no fabricated recovery. The UI accepts only this exact typed read-only shape, displays it as saved-only, and cannot enable Restore on a stopped site or a source-drifted snapshot.

**Write gates unchanged:** The existing source and authorization checks for a running, exclusively mapped native website remain mandatory before Apply or Restore. A stopped or independently rewritten VHost is never automatically repaired. After aaPanel SiteStart or manually reconciled source, refresh native inventory, execute a fresh Recheck, verify the actual selected-site HTTP result and explicit saved operation identity, and only then authorize manual Restore. A fresh Nginx reload is never initiated by saved-journal Recheck.

**Evidence:** The [exact isolated aaPanel 8.0.7 QA ledger](evidence/aaPanel-8.0.7-2026-11-07-status-recovery-lifecycle-qa.json) documents 456 Python and 210 JavaScript source tests; deterministic native package 0.1.18 with 46/46 installed file hashes; real WP1 site ID6 404 and 502 Apply/HTTP status/body/nonce; SiteStop saved-only recovery for both; denied stopped writes; SiteStart and bounded live proof verification; changed-VHost read-only inspection/Restore denial; exact source reconciliation and 404 Restore/502 Source Restored. WP1/WP2/WP3 HTTP200 and original VHost/status-file SHA-256 were preserved. The isolated QEMU guest was cold-restored to its original 0.1.12 package (39/39 file hashes), three WordPress HTTP200, Nginx syntax and PHP81/85 healthy. Protected golden snapshot SHA was unchanged, task disposable overlays were removed. This native test uses a synthetic Flask primary-admin POST context, **not an authenticated aaPanel Browser/CSRF session**.

**Unresolved accepted surfaces:** A brand-new native aaPanel PHP site lacked an extension/<site>/*.conf import entirely, so existing guarded site Apply correctly rejected it instead of editing aaPanel core/generated VHost. Its proper adapter is not delivered here. Native stopped homepage still returns soft HTTP 200, HTTPS/443 unknown-host and generic 50x routes remain unsupported, and complete real browser/roles/uninstall/regeneration/multi-PHP acceptance is Issue #21 Phase B. No Stable release or Production deployment is authorized.

### Explicit bounded site 404 HTTP/80 evidence (source-integrated, unreleased)

After selecting a native website and an English/Persian 404 template, the primary administrator may explicitly choose **Check live HTTP/80 site 404**. The endpoint binds the explicit action to the **exact validated site selection last loaded in the native inventory** (site ID, name, document root, status, and sorted domain/port bindings). The browser-supplied snapshot is only a comparison precondition, never a network destination or filesystem path. Any rename, reassignment, rebinding, stopped site, or missing record before the request produces a refresh-required error **without opening the HTTP connection**. Native site and domain bindings are also rechecked after the request; the UI independently compares the returned verified identity to its own selected inventory record. Nginx must be the configured aaPanel web engine, and the selected source HTML/hash is resolved offline. The preflight refuses missing, symlinked, unreadable, changed or empty page sources.

An explicit one-time Python `HTTPConnection` sends an unauthenticated `GET /ach-status-probe-<random-token>` to **127.0.0.1:80 only**, with the fixed native-bound `Host` header. The UI/API accept **no URL, path, host, IP or port** override. It sends neither cookies nor panel credentials, will not follow redirects, requests an uncompressed response, and caps decoded body bytes at **64 KiB** and raw incoming bytes at **256 KiB**. An internal monotonic **3-second absolute HTTP deadline** covers connection, send, status/headers and *all* response-body reads, including chunked/no-length and slow trickle: `HTTPResponse` still owns HTTP framing but reads through a bounded nonblocking socket facade. Timeout/error produces `Needs Review` and closes the socket.

The pre/post read-only source fingerprints include anchored ancestor directory bindings, original absolute paths, site-page and VHost file identities and digests, all inspected extension fragment identities and digests, extension directory inventory and missing-directory bindings. The fingerprint is internal to the probe and is **not exposed to the browser**. Replacements with identical bytes, extension rewrites with unchanged directive classification, and directory rebinding invalidate positive claims. The native site/domain inventory, aaPanel engine, and branding revision are likewise rechecked across the request. This is point-in-time source comparison, not a guarantee after the response. Outcomes distinguish `HTTP Match` (actual status 404 and byte-identical site 404.html), `HTTP Mismatch` (soft 404, redirect, other status/body, or divergent site page), and `Needs Review` (missing/unsafe source, connection failure, timeout or changed source). Independent `body_matches_render` indicates whether the matched site file equals the selected locale/brand snapshot; the frontend refuses contradictory status/hash evidence. Response HTML is **not returned** to the browser.

**Limitations:** This is **one local plain-HTTP request** for one random URL. It cannot prove loaded Nginx config versus on-disk files, unique VHost ownership, HTTPS/TLS, Cloudflare or public clients, 502 generation, non-tested routes, WordPress/API/ACME behavior, regeneration durability, or safety of future Apply/Restore. Even observational GET requests may be logged or handled by dynamic application code; the operator must choose to run the probe. No Nginx reload, service restart, website/configuration-file mutation or host configuration Apply is implemented. The plugin may still record a bounded Activity/Diagnostics event for the operator's explicit probe. Source-level isolated loopback-HTTP tests are not native aaPanel guest acceptance; additional source-bound native tests and independent review remain gates. Do not enable automatic health probes or auto-enforcement based on this evidence.

## Read-only origin-local hosts inspection (Issue #2)

**Unreleased development candidate 0.1.8; no Production, file/DNS edits or auto-correction.** The Websites tab provides an inventory-backed website selector for the current page (with Previous/Next pagination), rather than free-form site ID typing, for the origin-local diagnostic for the historic WordPress Toolkit hosts-override symptom recorded in Issue #2. The primary-aaPanel-admin-only POST requires a **comparison-only snapshot of the exact selected native site record** from the validated inventory (ID, site key, document root, panel status, and the complete canonical sorted domain/port bindings), as well as its site key; client data never supplies file paths or domains to inspect. The backend independently re-resolves the native site and its bound-domain table, rejects pre-request binding changes, reassignments, renames, site-status or document-root changes *before* reading the file, and rechecks the same native identity/bindings after inspection. Snapshot inputs are bounded and reject malformed, oversized or missing selections; sites with more than 100 domain bindings are not offered for this operation. Nonprimary/temporary and GET sessions are refused before file access; no client-supplied hostname or file path is accepted.

The inspector reads only origin-local /etc/hosts with descriptor-anchored O_NOFOLLOW and O_RDONLY, rejects untrusted/multiply linked/group-writable/symlinked sources, caps file size to 64 KiB, line count to 2048 and matching entries to 100, and verifies file metadata before/after the bounded read. It also rechecks the fixed final filename through the same pinned parent directory with no symlink following, rejecting an atomic rename or symlink replacement that would leave the opened descriptor pointing to superseded source content. The last pathname check is the observation boundary; a later operating-system mutation cannot be excluded. IDNA, IPv4 loopback, IPv6 loopback and IPv4-mapped IPv6 loopback are handled. Wildcard domains are not resolved as exact hosts aliases. The frontend shows only the matched native domains, local addresses and line numbers, plus file SHA-256; it never exposes unrelated hosts-file lines.

**Meaning:** Local Loopback Entry is an origin-local source observation, not evidence of a Gateway DNS or reachability error. No Local Loopback Entry excludes only explicit loopback records for the exact inspected domains in that file snapshot, not hidden resolver/caching mechanisms. Needs Review applies to uninspected wildcard domains or unsupported inputs. No writer is attributed; an intentional hosts override is not changed. Local NSS resolution, public DNS, Cloudflare, TLS/HTTP from origin and a genuinely separate remote Gateway path still require independent evidence before any proposed fix. No repair or Apply API exists.

**Verification boundary:** Source tests exercise native site/domain identity, authorization with synthetic Flask context, file bounds, symlinks, parser semantics and deployed frontend validation. Authenticated real-browser/CSRF and cross-version results are not claimed without separate guest testing. Related tracking stays in Issue #2.

### Review REQUIRED-01: contrast-safe customized themes (2026-11-03)

The independent exact-source review of PR #11 at HEAD ccd9f23ed4cdd33f4e5de1e0b88fbe519997f96f found that the first custom palette path validated only foreground/background and accent/background. The original CSS included hard-coded light-theme text and control colors: a white foreground over a black background produced white-on-white button text, and the descriptions and secondary links dropped below 4.5:1. This is a genuine accessibility defect in the white-label preview, even though original-reference rendering remained correct.

**Correction:** The 22 owner-approved HTML reference files and their SHA-256 manifest remain byte-identical. Only custom branding output receives a derived, explicitly bounded semantic CSS override. Normal/muted text and secondary links are checked to at least 4.5:1 against the actual page background. Normal and hover primary-button foreground/background are separately checked at 4.5:1; the button's text uses the contrasting page color instead of fixed white. Visual-panel labels remain at least 4.5:1 against both derived gradient endpoints. Focus and meaningful panel border colors remain at least 3:1 against their background. All CSS variable values derive exclusively from already validated six-digit hexadecimal input colors, never raw user-supplied CSS or markup. Unsupported relationships fail closed. Default ACh branding still emits identical reference bytes and source SHA-256 without injected overrides.

**Computed-style evidence:** An isolated Chromium run loaded 24 custom-themed EN/FA files across 404, 502, and stopped page types, at 375px and 1280px: 48 rendered checks, zero computed-style contrast failures or horizontal overflow. The reported dark theme now has normal primary-button contrast 21:1, actual reduced-motion hover contrast 15.908:1, description contrast 4.558:1, secondary link contrast 19.556:1, and actual keyboard-focus ring contrast 19.556:1. The same checks cover light, navy-dark and low-contrast-accent fallback themes. These are representative source-output browser tests, not a universal WCAG audit or an authenticated aaPanel browser session.

**Native exact-source update:** A fresh task-owned child QEMU overlay of the existing Debian 12/aaPanel 8.0.7 lab ran native panelPlugin ZIP update with the corrected 0.1.4 development ZIP SHA-256 7cf00cd1f71c770873cd30233fd9eee148e436fca53a07b335478ebc7ad0cc1c. All 34 installed files hash-matched the ZIP. The native status_preview endpoint rendered the corrected dark palette across all 22 EN/FA templates without saving preferences, while invalid contrast was rejected. Saved branding revision 3, Monitor settings, FPM config, and two website VHosts were unchanged. nginx -t and both existing HTTP 200 site checks passed. Guest shutdown was graceful, and the child QCOW2 check found no errors. Native authenticated-browser CSRF/role and live website Apply remain outside this slice.

**Approval gates:** Source, native, and computed-style checks are evidence for review remediation only; exact-current-head CI plus focused independent re-review must still succeed before an Owner-authorized Merge.

**Not implemented in this slice:** Nginx error_page/alias Apply, modifying panel default templates, live site 404/502 installation, automatic onboarding, HTTP status verification, actual installed-file conflict/drift checks, backups and Rollback for live pages. Any host-writing adapter must independently prove version support, target ownership and path safety, operator authorization, live HTTP response correctness, conflict detection, rollback and independent review before being exposed.

### Unreleased operator UI and plugin-owned Activity diagnostics

The Status Pages site selector uses a dedicated native `status_sites`
POST action requiring a full primary aaPanel administrator session, returning
bounded, paginated native inventory with the `status_site_selection`
purpose marker. It works even when optional Website Monitor is disabled.
This listing authorizes only operator choice; `status_preferences`,
`status_save`, and `status_inspect` recheck native site identity,
authorization and operation. The Monitor `get_sites` endpoint retains
its own enable/disable policy. No global/502 Status Pages Apply/Restore is implied.

Plugin-owned Activity is stored under aaPanel's panel data directory
(`/www/server/panel/data/ach_customizer.activity.jsonl`), with a
rotated `.1` segment and a lock. Files use panel-process ownership,
private 0600 mode, no-follow opens and a serializing lock. Retention is
bounded to 256 KiB per active/rotated segment; the full-primary-admin
`get_activity` POST action returns at most 100 records (UI requests 50).

Process environment `ACH_CUSTOMIZER_ACTIVITY_LEVEL` selects DEBUG,
INFO (default), WARNING or ERROR. High-volume successful read-only
queries are DEBUG-only; deliberate state changes and guarded PHP actions
are INFO, PHP pool/site mapping that needs review is WARNING, and
classified failures are ERROR. Filtering an event by verbosity is not
a persistence failure. Records retain bounded time, module, action,
severity, stage, outcome, target and request/recovery IDs, but not
request payloads, cookies, tokens or arbitrary unexpected exception text.
Absent recovery IDs stay empty. Unexpected exceptions yield a generic
browser error and only the private exception class/stage for diagnostics.
Existing native aaPanel audit logging for consequential PHP-FPM actions
remains separate. Failed audit/Activity persistence never reverses or
falsifies an already completed operation.

These are source-level contracts for unreleased development. Native aaPanel
installation of the exact candidate, authenticated browser/CSRF and real
service/site impact require independent verification before release.


### Independent-review remediation: native UI sequencing and lifecycle evidence

The read-only PHP-FPM shared-impact secondary inspector must never emit raw
unexpected exception text to the browser. It returns a bounded Needs Review
reason with the request operation ID; a WARNING Activity record retains
the actual exception class and stage, never its untrusted message. This
prevents a successful file-only preview from becoming a covert exception
detail transport.

**Native aaPanel modal viewport safety (exact aaPanel 8.0.7 guest evidence):**
aaPanel's plugin launcher initially positions its fixed .layui-layer at
top:20% even when the lower part of the 672 px modal exceeds the browser
viewport. At 1280x720/100% zoom, the original modal bottom reached 816 px
(96 px offscreen), despite the static layout and mocked layer tests passing.
The plugin uses a strictly scoped .layui-layer:has(#ach-customizer) rule
to constrain this one native launcher horizontally and vertically and keep
its internal scrollbar visible without requiring a browser resize. The
existing fitNativeLayer() resize helper remains as a fallback for
browsers without :has() support; the CSS does not target unrelated
aaPanel dialogs. The exact launcher top:20% overflow has an
explicit five-viewport Chromium regression case in
tests/manual/layout_browser.cjs.

The native PHP-FPM form uses a generation and immutable field snapshot for
each Preview/Prepare request. Editing fields or starting another Preview,
including a byte-identical repeated Preview, invalidates ALL pending Prepare
tickets and approvals. A stale Prepare cannot restore an approval panel,
unlock a different pending request, or authorize Apply, and duplicate pending
Prepare clicks do not start another request. The server-side
revalidation/hash/authorization gates remain independent and mandatory.

Only operation-specific, schema-compatible PHP-FPM Apply/Restore results
can display a confirmed host mutation: Apply must return the supported PHP
8.5 shared-[www] source and expected before/after SHA-256 values together
with an actual durable operation ID. Restore must return the approved
operation ID and a valid restored SHA-256 matching the inspected baseline.
A structurally valid "No Change" with null operation ID and matching
before/after hashes is explicitly non-mutating, never an Applied result.
Unknown, incomplete, mismatched and transport-uncertain results always
require saved-recovery inspection before considering any retry.

Confirmed shared-service Apply/Restore results and missing native-audit or
plugin-Activity persistence are displayed in a dedicated PHP-FPM panel notice.
Concurrent Website/Activity/other panel requests must not hide or clear
these consequential warnings. Existing backend authorization, revision,
impact, re-prepare, expected-hash and recovery gates are unchanged.

The native install/uninstall shell hook uses fixed plugin-local paths and a
strict allowlisted Python lifecycle logger. Repeated install invocations
are recorded as install-hook registrations: the hook cannot reliably claim
whether aaPanel called it for first install or update/reinstall. Uninstall
records verified icon-copy removal, preserved icon-copy on cleanup failure,
or unavailable cleanup as distinct outcomes. The cleanup helper's exit
status reflects actual verification rather than a false success. Activity
logging errors produce an explicit installer warning but cannot corrupt
plugin install/uninstall behavior. Retained Monitor state, site branding,
existing manually applied PHP-FPM configuration and durable recovery files
remain outside the replaceable plugin source and are never purged by
these hooks. Lifecycle records use the same bounded private JSONL
rotation and no-follow, descriptor-anchored directory ancestry, with action,
stage, severity, UTC time, error classification
and a generated operation ID. Verbosity filtering is reported as filtering,
not a persistence failure.

**Evidence boundary:** isolated source/unit and simulated native-layer
browser checks verify these contracts but do not by themselves establish
aaPanel authenticated-browser, upgrade/uninstall hook timing, CSRF,
actual PHP-FPM service reload or on-host lifecycle retention. Native QA
requires the exact built ZIP and an explicitly isolated aaPanel guest.

## Native QA PHP-FPM file attribution for aaPanel extension and WordPress FastCGI VHosts (development-only)

The isolated aaPanel 8.0.7 QA VM (2026-11-06, current state owned by Issue #21) contains three PHP 8.5 websites. Its generated Nginx VHosts use a per-site `extension/<site>/*.conf` include and site rewrite; the One-click WordPress website uses `enable-php-85-wpfastcgi.conf`, while the other two use `enable-php-85.conf`. The older conservative inspector labeled **all three** `Needs Review` because those native shapes were not modeled. This was a useful conservative refusal, not an indication of three broken websites.

The focused, unreleased Issue #2 implementation extends **read-only file attribution** to exact native VHost shapes: it binds the aaPanel site ID, VHost and native rewrite, the complete inert logging-only extension directory inventory and file identities, the selected PHP snippet (including the WordPress cache variant), bounded FastCGI parameter fragments, and the literal `[www]` Unix socket. Unknown routing, extra destinations, symlinked or changed dependencies, noncanonical extension files, or different socket/pool relationships still produce `Needs Review`. It does not claim complete Nginx `-T` routing proof, actual worker runtime, per-site cache isolation, or newly supported PHP 8.1 writes.

**Native PHP 8.5 manual eligibility (unreleased):** verified, inert `extension/<site>/*.conf` logging fragments and a literal `enable-php-85-wpfastcgi.conf` source bound to the same `[www]` Unix socket no longer automatically disqualify every ordinary aaPanel site. The complete native site inventory, source fingerprints, socket links, explicit operator approval, current Monitor revision, shared-service impact identity, FPM syntax/reload and durable Rollback remain mandatory. Unknown/active extension routing, extra FastCGI destinations, another pool, uninspectable sources and changed dependencies still refuse manual Apply. Only PHP **8.5** can be eligible; PHP 8.1+ topology discovery remains read-only.

This is still **file attribution**, not conclusive proof of all effective client traffic. Execute real shared PHP 8.5 Apply/Rollback, three-site HTTP/PHP health and fault recovery on the existing **task-owned QA guest after verifying its cold rollback**, and obtain independent review before any Merge or Release. The QA guest's disk must return to its original state after testing; no Production change is authorized.

Exact source tests include positive native shapes and negative hidden upstream/include/route, distinct PHP version socket, extension file changes/rebinding, concurrent mutation and manual mutation-gate cases. Record current candidate identity, CI and actual guest read-only results in the owning PR/Issue, not as timeless version guarantees here. Neither this source change nor documentation authorizes Production or public Release.

### New-site default source adapter — unreleased 0.1.15 candidate (Issue #10)

Native aaPanel 8.0.7 panelSite.py and panel_site_v2.py create a new site's index.html, 404.html, and 502.html by copying root-owned sources in /www/server/panel/data/defaultDoc.html, 404.html and 502.html only when each destination is missing. Isolated QA confirms these three files exist with mode 0600. Changing a panel source **does not alter existing sites, Nginx live routing, a stopped site, or an unbound domain**.

The Status Pages UI provides an explicit global-scope Recheck / Apply / Restore flow for those three sources, using the offline EN/FA renderer, global branding revision and full primary-aaPanel-admin gate. Status Pages' existing lock serializes operations. Apply retains original bytes and permissions in a persistent root-owned journal and backup outside the plugin, with full staged-source publication. Uncertain commits retain recovery evidence for explicit Recheck/Restore; changed source hashes or ownership refuse overwrite. Restore requires the exact recovery ID and refuses changed external bytes. The adapter does not edit VHosts/document roots or reload Nginx.

**Release boundary:** No panel-global catch-all routing, other status-code activation, implicit future-site policy, or existing-site mutation. The isolated native aaPanel 8.0.7 QA installed the 0.1.15 development ZIP through panelPlugin.update_zip/input_zip and verified 45/45 installed member hashes. All three source defaults were applied with SHA-256 proof; real native panelSite.AddSite created site ID 9, whose index.html, 404.html and 502.html exactly matched the three selected renders. Real existing WordPress sites stayed HTTP 200 and their original VHost/PHP/Nginx configuration hashes were unchanged by the three source Applies. Each default restored original exact bytes/mode; the newly created site's copied HTML remained unchanged. Guest was cold-restored from a verified pretest qcow2 snapshot, returned to plugin 0.1.12 (39/39 member checks), with all three WordPress sites HTTP 200 and WP1 HTTPS 200. QA artifacts and test drivers are retained under the task-owned Test Server workspace /srv/ai-workspace/ach-aapanel-rebuild-20261105/artifacts/qa_0115_*. This is backend-native QA under a synthetic Flask primary-admin POST context, NOT real authenticated Browser/CSRF or a loaded global Nginx fallback acceptance. Independent exact-candidate review, browser roles and lifecycle/reinstall are still open under Issue #21/#10. No Stable release or Production authorization.

## Global HTTP/80 unbound routing — unreleased 0.1.16 / Issue #10

**Observed source behavior (task-owned Debian 12, aaPanel 8.0.7, Nginx guest):** Native 0.default.conf sends unmatched IPv4 HTTP Host / to /www/server/nginx/html/index.html with status 200. IPv6 can fall through to a different named site's default HTTP virtual host. The native SiteStop replaces the selected site's VHost root with /www/server/stop and serves its index.html with status 200; merely swapping HTML bytes cannot fix the status semantics. See Issue #10 comment 6704560476.

**Supported bounded adapter:** A plugin-owned 00.ach_customizer_unbound.conf in the existing aaPanel Nginx VHost include glob, plus root-owned _ach_customizer_unbound.html static asset, adds explicit default_server on IPv4 and IPv6 port 80 and a real 404/error_page mapping. The implementation does not modify aaPanel's 0.default.conf, named-site VHosts, stopped page, copied new-site defaults, or HTTPS/443 listeners. Full primary-admin POST, exact global/unbound selection, compatible aaPanel/Nginx version and explicitly approved shared reload are required. Before Apply the adapter confirms Nginx's included VHost source, checks collision-free default-server ownership, renders selected EN/FA branded HTML and binds approval to the current source hash and prior HTTP statuses. Operations use a durable recovery journal in panel-data, checked new files, nginx -t, Nginx reload and repeated fresh IPv4+IPv6 loopback checks of HTTP 404, HTML SHA256 and nonce. Restore detaches only the managed config and then verifies the previous handler is no longer responding with that nonce. Unrelated VHost changes after Apply do not indefinitely block Restore. Interrupted writes are explicitly recoverable; unknown outcomes require Recheck rather than blind repeat.

**Native evidence boundary:** Exact ZIP candidate v0.1.16 was imported through panelPlugin on the isolated aaPanel guest with 46/46 file SHA256 checks; source-only/native-reload experiments and EN/FA Apply → Recheck → Restore passed on IPv4 and IPv6 while all three WordPress named sites continued HTTP 200 and VHost/config hashes were preserved. The native test used a synthetic primary-admin Flask POST; real browser session/CSRF and secondary/temporary user browser coverage remain unverified. Guest was cold-restored to baseline 0.1.12 after each destructive QA sequence. Subsequent source revisions require exact-candidate rerun before review/merge. HTTPS unknown-host, stopped-site status semantics and generic 50x remain independently open.

### Guarded native stopped-site HTTP503 (Issue #10, unreleased 0.1.22)

The native aaPanel 8.0.7 Nginx `SiteStop` mutates the selected VHost's server-root path and comments all `include` directives; `SiteStart` reverses them. Therefore a normal extension snippet or a customized `/www/server/stop/index.html` alone cannot ensure real HTTP503. In the isolated aaPanel8.0.7 lab, a bounded **server-scope conditional** that checks the aaPanel stop root survived native Stop/Start and returned 503 while stopped, with the original website restored when restarted. Nginx's default response type for a direct server `return 503` was `application/octet-stream`, **not** suitable HTML; a private internal HTML location and guarded Nginx rewrite were verified to return `text/html` with the byte-identical bundled English/Persian stop page. The managed fragment is deliberately split into short Nginx `set` string segments to avoid its lexer limit for 9+ KiB HTML.

The separately authorized `status_stopped` endpoint requires a full primary-admin POST, selected native site ID plus current canonical site/binding snapshot and branding revision, explicit site-scoped Apply or Restore approval, exact source/render hashes and recovery ID. Apply is only allowed while the site is running. The adapter writes one selected, root-owned native VHost with an inline owned block, checks syntax, loaded source and shared Nginx activation, and retains a root-owned original VHost backup/journal outside the removable plugin. A stopped-site Recheck verifies **actual HTTP503 status, byte SHA256 and text/html content type**. Restore removes only a byte-verified managed block from the current native VHost, preserving unrelated operator changes and using source hashes/authorization to prevent blind writes. Stopped and restarted sites require refreshing current native inventory before a new Recheck; neither cached website IDs nor generic Status Pages Recheck authorizes an Apply.

This narrow adapter intentionally does not edit aaPanel vendor files, shared stop HTML, other VHosts, SSL certificates, new-site sources, or unknown-host TLS/443. Nginx is a shared service, so reload impacts and rollback require real guest verification. The full independently reviewed, authenticated browser/CSRF and lifecycle matrix remains owned by Issue #21. This text specifies the **0.1.22 unreleased candidate**; [the exact-package native QA ledger](evidence/aaPanel-8.0.7-2026-11-08-native-stop503-qa.json) records 48/48 installed-member verification and real HTTP/HTTPS EN/FA Stop/Start/Restore acceptance. Independent review remains required before integration, and Production requires explicit Owner approval.
