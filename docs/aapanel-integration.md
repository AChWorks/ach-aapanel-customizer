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

## First non-production implementation slice

`plugin/ach_customizer/` is a prototype native plugin package with an English-only in-panel read-only UI, following aaPanel conventions, and two narrowly bounded read operations:

- `get_sites`: paginated source records from aaPanel's `sites` table and a single bounded, parameterized read of the native `domain` table for only that page's website IDs. The response exposes the stable site key, recorded bound domains/ports and whether the original site key remains bound. These are **database bindings**, not confirmed DNS, TLS or effective Nginx routing. No WordPress-specific assumption or hard-coded list. Application and service relationships remain **Needs Review** until verified.
- `preview_php_fpm`: compares *operator-supplied* concurrency values to explicit `[www]` pool settings in a single, conventional, versioned PHP-FPM configuration file. Rejects missing/ambiguous/duplicate/unreadable configuration. The result's scope is **shared service**. It does not infer sites sharing a pool, include-expanded config, effective runtime, or what aaPanel would write. It NEVER writes, reloads, restarts or schedules anything.

This is **not a supported package or initial release**. `install.sh` owns no resident service or host settings. Its uninstall helper opens the complete aaPanel path hierarchy through pinned directory file descriptors with no symlink traversal; it requires root-owned, non-group/world-writable ancestor directories and byte-identical singly-linked regular icon files. Only the fixed product icon name is unlinked relative to the verified destination directory descriptor. Unsafe or unexpected ownership/layout preserves the copied icon. The lab observed **browser UI uninstall on the previous candidate** and **isolated native V2 backend uninstall/reinstall on the corrected candidate**; broader update, operator-state preservation, enable/disable, authorization for future writes, and rollback are still pending. Do not equate a source or ZIP build with release/production acceptance.

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

Atomic replacement, strict state schema, finite read bounds, ownership/mode
checks, no-follow file opens, conflict reporting and fail-closed error
handling are exercised in source tests. Browser and guest checks confirm
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

## Compatibility and outstanding acceptance

| Required proof | Observed status |
| --- | --- |
| Official plugin layout, request syntax and ZIP extraction | Source-verified and isolated runtime accepted on aaPanel 8.0.7 |
| Real in-panel management and read-only API | **Browser-tested on aaPanel 8.0.7:** Settings, bound-domain inventory, overall/module Monitor controls, disabled-read behavior, stale-update conflict refusal. Restricted-role browser authorization untested |
| Native ZIP import/backend, uninstall and reinstall | **Browser-confirmed on aaPanel 8.0.7:** actual ZIP picker, Install, Settings, Uninstall and Reinstall for merged 0.1.0 and unmerged 0.1.1 candidate; installed source hashes checked. No production use |
| Dynamic website source inventory | Real native create/delete and AddDomain/DelDomain verified; stable site key can differ from active bound domain. Exact updated monitor tested against actual sites and domain records; true canonical site/VHost rename and browser lifecycle remain untested |
| PHP-FPM file-only preview and runtime truth | **Native PHP 8.5.12 pool and exact corrected parser guest-tested:** omitted `pm.max_requests=0` default and desired 300 drift confirmed. Preview is file/default-only; no live configuration-change/rollback proof |
| Nginx virtual-host extension durability and panel regeneration | **Nginx 1.28.3 tested:** native generator removes custom include; separate asynchronous `site_total` later reinserts it. No stable plugin-owned extension contract established |
| Overall/per-module enable-disable, persistent policy/state migration | **Monitor-only overall/module switches and external schema-v1 state preservation browser-confirmed** across update, uninstall and reinstall; stale-revision writes rejected. Policy migrations and enforcement unimplemented |
| Manual Apply/Auto-enforce, syntax validation, recovery/rollback | **Not implemented or verified**; monitor-only prototype |
| More aaPanel versions, Linux families, update, uninstall after nontrivial state | **Browser update/uninstall/reinstall with persisted Monitor state verified on aaPanel 8.0.7 only**; pending cross-version/restricted-role tests and schema migration. Controlled worker restart may be required after update |
| Production authorization, deployment, release | **Not authorized**; no production changes |

The remaining end-to-end acceptance in [Issue #1](https://github.com/AChWorks/ach-aapanel-customizer/issues/1) is deliberately still open. Before selecting a reversible Nginx/PHP-FPM adapter, verify native canonical rename support separately if required, PHP-FPM configuration resets/reloads and conflict behavior, independence from `site_total`, and ownership-aware Apply/validation/rollback. The real site/regen evidence above narrows but does not close these gates. Do not install this development package on production.

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
