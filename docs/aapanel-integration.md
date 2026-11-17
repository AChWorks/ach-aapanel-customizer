# Native aaPanel integration and operating boundaries

This is the **technical/operator guide**, not another product specification,
release timeline or QA activity log. The durable product requirements live in
[PROJECT-SPEC.md](PROJECT-SPEC.md). The authoritative current distribution is
[GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases);
unfinished compatibility and acceptance live in
[Issues #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2),
[#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10) and
[#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

## Evidence versus support

The verified installed nonproduction reference is **aaPanel 8.0.7 / Nginx
1.28.3 / PHP-FPM 8.1 and 8.5**, with specific site, native ZIP and recovery
tests recorded under #21. A reported source-file match, permitted read-only
inventory, synthetic HTTP probe or matching entrypoint version proves only
its named observation. It does **not** certify every runtime worker, another
PHP layout, real customer/private-data safety, DNS/TLS, aaPanel version or
Production installation.

The latest [public native 0.1.51 ZIP installed QA receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6937217273)
records 57/57 exact installed bytes and bounded native lifecycle checks. A
[separate real WooCommerce A/B test](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6938476216)
passed two independent customer sessions on HTTP/80 and strict-TLS HTTPS/443
with site-specific, manually Applied Cache, then Restored that site to its
original VHost. This **does not** exercise live payments/gateway callbacks,
every extension, general vendor Purge All or other host topologies.

## Native packaging, identity and lifecycle

The native ZIP is constructed from `plugin/ach_customizer/` by
[`scripts/build_plugin.py`](../scripts/build_plugin.py). aaPanel imports a
`ach_customizer/` directory with `info.json`, `index.html`,
`ach_customizer_main.py` and `install.sh` through
**App Store → Third-party Plugins → Import Plug-ins**. This is
an **observed aaPanel integration**, not a cross-version vendor guarantee.

- Plugin-owned scripts may be replaced/removed by aaPanel import/uninstall;
  saved operator settings and recovery evidence are outside this replaceable
  directory. Never erase journals merely to make an import succeed.
- Reopen **Overview → Refresh state** after upgrades. The UI compares
  packaged metadata with the resident Python **entrypoint** version. Even
  a match does **not** prove all imported helpers were refreshed. One
  genuine QA upgrade retained an older imported helper until a **separately
  approved panel-only reload**.
- If actions fail or version is unverified, read **Activity & Logs**,
  check installed package bytes and original operation/journal first. Never
  automatically restart aaPanel, Nginx or PHP-FPM as a response to import.
- Preserve site, service and recovery identities through enable/disable,
  upgrade, uninstall and reinstall. After any such lifecycle action,
  independently Recheck the affected module and representative site health.

For the supported investigation sequence, impact, service commands and
rollback requirements use the [upgrade/recovery runbook](aapanel-upgrade-recovery.md).

## Native interface contract

The Customizer opens **inside** aaPanel. Its seven operator destinations are
Overview, Website list, Routing & Nginx, FastCGI Cache, PHP-FPM, Status Pages,
and Activity & Logs. The single shared selected-site context must not be
replaced with a second raw-ID field. Readiness, errors and recovery steps
belong **beside their action**, with the technical report available on demand.

Current [independently reviewed UI contract](https://github.com/AChWorks/ach-aapanel-customizer/issues/80):
use scoped `#ach-customizer` styles, task-based sidebar, independently
scrollable content, actual buttons, semantic notes and availability states,
visible keyboard focus and preserved unsaved form state. Render validated
worker-version warnings persistently when relevant, but keep a matching
version unobtrusive. Source-level frontend checks and actual mounted native
Browser tests at 390/768/1280 px cover different things; neither substitutes
for the other.

Do not enable Apply merely because a checkbox is ticked or the UI looks
valid. Refreshing or changing a selected site, version, branding, policy,
VHost or relevant source revokes stale selection/preview/approval evidence.

## Website onboarding, identity and review

1. **Website list → Refresh websites** reads native site identities, roots,
   status and bound domains. Site IDs, bindings, real VHosts and display
   aliases are different facts. Native `sites.rname` is a display alias; an
   AddDomain/DelDomain event can change HTTP routing without changing
   `sites.name` or the VHost filename.
2. **Compare website records** reports additions, removals and changes
   against the separately stored observation baseline. To accept **one**
   reviewed native site without overwriting other pending differences,
   select it, review its current identity, consent and choose
   **Save only selected website baseline**. This writes observation state,
   not a live website or policy.
3. **Save baseline for ALL websites** is a distinct and consequential action:
   after reviewing the complete snapshot it accepts all records, including
   removals. A removed site cannot be silently accepted by the single-site
   path. Reused IDs, ambiguous bindings and conflicting revisions require
   fresh review.
4. **Routing & Nginx → Review selected site & recovery** combines a
   point-in-time observed site baseline, generated VHost, per-site Cache
   source/recovery and shared PHP desired state. It is **read-only** and
   cannot Apply, Restore or certify loaded workers. Use the original
   module's independently authorized Recheck/Recovery ID for any mutation.
5. **Compare VHost** and the prospective **Nginx candidate / local HTTP**
   inspection inspect file/loopback behavior only. A generated VHost
   `File Match` is not a live-worker, external DNS, TLS, PHP-processing or
   cache-privacy guarantee. Regeneration, missing extension or source drift
   must not silently adopt changed files.

Site discovery is bounded by the current implementation's verified inventory
shape; unsupported layouts show `Needs Review` rather than permission to
repair. No scheduled per-site enforcement or automatic VHost reconciliation
is implemented.

## PHP-FPM scope and guarded change

- **Inspection:** Discover installed PHP versions, native config, master,
  socket and site mapping. A source/single-process match is not proof of
  effective pool values or every live request. Unknown/multiple pool
  layouts remain read-only.
- **Desired service state:** Monitor the saved, version-scoped shared
  `[www]` policy independently from native-generated file values. Saving
  desired policy does not change the service. A shared PHP-FPM pool affects
  multiple websites; a selected-site report cannot authorize changing peers.
- **Guarded adapters:** Explicit **Load → Preview → Prepare → approve →
  Apply → independent after-state / Restore** is implemented for the
  evidenced native PHP 8.1 and PHP 8.5 single-pool shapes. Verify the
  *actual* installed version, PID/socket identity, source and every affected
  site, run that version's FPM syntax check, make the scoped approved reload,
  verify health and retain the exact recovery evidence. A different version
  or incompatible pool cannot reuse another adapter/journal.
- **Faults and drift:** Preserve the operation ID and original backup,
  distinguish a failed/uncertain reload from successful worker adoption,
  and never blindly repeat Apply or cross-version Restore.

PHP 8.1+ is a **product discovery/compatibility target**, not a promise of
guarded Apply on every newer version or nonstandard pool.

## Status Pages: static assets and distinct delivery modes

The package contains **11 templates × English/Persian = 22** versioned,
self-contained static HTML assets under
[`plugin/ach_customizer/status_pages/`](../plugin/ach_customizer/status_pages/).
The [manifest](../plugin/ach_customizer/status_pages/manifest.json) records
their original asset hashes. Preview uses validated, escaped brand URL/text,
palette and target/site scope; site-local home links must remain site-local
regardless of configured brand URL.

| Delivery | Supported meaning and prerequisites |
| --- | --- |
| **Offline Preview** | Shows rendered HTML only; no host effect. |
| **Future-site source defaults** | Explicitly replace one recognized aaPanel default document/404/502 **source**; affects future creations, not existing sites or Nginx routing. |
| **Existing site 404/502 file** | Guarded replacement of the existing owned site HTML, preserving exact original bytes/mode; no Nginx reload. An HTTP 404 body/status can be probed, 502 cannot be inferred from just a copied file. |
| **Site Nginx extension 404/502** | Checked site-specific native include, source/ownership validation, approved Nginx reload, observed HTTP response and exact Restore. |
| **Site Nginx-generated 50x** | Verified extension route for **Nginx-generated** 500/502/503/504; not intercepted application/PHP responses. Conflicting `error_page` mappings refuse Apply. |
| **Stopped website HTTP503** | Opt-in, source/proof-checked lifecycle operation where native aaPanel stop would otherwise serve a 200; native site Stop/Start can suspend other applied status routes. |
| **Global unknown Host HTTP/80** | Independently approved Nginx-owned default_server on IPv4/IPv6, genuine HTTP 404, checked reload and Restore. Never claim HTTPS/443 support. |

A given route can conflict with existing per-site mapping, generated
includes, `site_total` or aaPanel stop handling. Never assume that changing
an HTML file changes the HTTP status. Do not globally enable
`fastcgi_intercept_errors` or `proxy_intercept_errors`, override a
WordPress-owned 404, break ACME or overwrite another owner's fragment.
Saved status journals remain meaningful after a site stops/regenerates;
`Suspended` / `Needs Review` is **not** approval to Restore.

**Still an Owner policy decision:** unknown-Host HTTPS/443 needs a TLS/SNI,
certificate and operator exposure design; an HTTP/80 404 implementation cannot
simply intercept TLS handshakes. Keep [Issue #10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10)
open until that decision and subsequent scoped acceptance.

## FastCGI Cache: privacy, ownership and recovery

A safe per-site Nginx Cache needs an owned, separate physical tree and key
zone, exact site/VHost/native PHP include ordering, syntax and runtime
checks. An IP/Host-partitioned key within a **shared filesystem** does
**not** make recursive deletion site-scoped. Native PHP `wpfastcgi` and
stock-handler shapes differ; inspect actual source, inherited directives,
regex precedence, original request URI and current handler before proposing
an Apply.

The reference policy conservatively excludes unsafe methods, authenticated
or Cookie-bearing requests, query strings, noncanonical paths, private
WordPress/WooCommerce routes and upstream response indications such as
`Set-Cookie` or `Cache-Control: private/no-store`. It must honor the
actual upstream cache directives and guard both
`fastcgi_cache_bypass` **and** `fastcgi_no_cache`. A source-only preview,
synthetic private-header HEAD probe or one public `MISS→HIT` does
**not** certify customer isolation. Real logged-in WooCommerce account,
cart, checkout and Store API behavior is independently tested only for the
explicit observed configuration.

**Operator flow:** FastCGI Cache → inspect actual source and physical peer
roots → Check site-specific Apply readiness → review one exact site, PHP
handler, proposal and recovery scope → explicit consent/Apply → fresh
Recheck/HTTP response proof. A generated VHost edit, extension drift,
stale journal, moved/ambiguous Cache directory or new peer invalidates
old authorization. A **Restored** historical generation may allow a new
Apply only through the adapter's independently verified legacy identity
and source checks; it does not transfer old ownership blindly.

**Do not conflate these actions:**

| Action | Exact boundary |
| --- | --- |
| **Native `clear_url`** | Explicitly approved, fresh current-generation **canonical primary-Host** HTTP(S) GET/HEAD file(s). Query/noncanonical/alias routes are not guessed. |
| **Native `clear_files`** | Separately approved **full-tree file Clear** of the physically verified *site-owned* Cache tree, potentially including older generations. Recheck actual registered peers, device/inode/symlink/mount ownership and rollback/uncertain outcomes. No Nginx Helper call or Nginx reload. |
| **Nginx Helper `purge_url` / `unlink_files`** | Vendor per-URL behavior; optional Bridge constrains **only supported current-generation URL-file mapping** when provisioned. |
| **Nginx Helper `purge_all()`** | Vendor recursive deletion of its **configured cache root**, bypasses Bridge's URL filter; **not certified/authorized** for a shared or ambiguous root. |

One successful site-owned Clear is **not** permission to turn on vendor
Purge All. Concurrent clients can refill objects after any Clear; verify
actual resulting Cache behavior and separate external request effects.

## Optional WordPress Bridge: operator prerequisites

[WordPress Bridge](../wordpress/ach-aapanel-bridge/README.md) is an
**independent**, manually installed WordPress plugin. Without an explicit
native-generated site-owned manifest it reports diagnostics but does **not**
alter Nginx Helper hooks or cache state.

1. On one verified native WordPress site complete **Cache Apply → Recheck
   Applied**, confirm physical peer separation, and separately approve
   **Provision URL mapping**. The root-owned, generation-bound manifest in
   `wp-content/ach-customizer-bridge/cache.php` is read-only to WordPress
   and binds exact site/host/root, cache directory identity and Recovery ID.
2. Nginx Helper must be installed/activated/configured by the **operator**
   for automatic `unlink_files` per-URL purging and the **same site-owned**
   path. Its `get_request` / unrelated vendor modes and `Purge All`
   are not silently enabled or controlled by Customizer.
3. The site's PHP-FPM worker must have filesystem access to that **exact
   site** Cache path. When the site's `.user.ini` uses `open_basedir`,
   update only that site's permitted path after separate operator approval,
   retaining existing site/temp entries. Verify with the WordPress Tools
   diagnostics **under FPM**, not a root CLI. Never broaden to a shared root.
4. Current Bridge invalidation is limited to source-verified canonical
   public post/homepage and eligible first-page public taxonomy archive
   URLs across **HTTP/HTTPS × GET/HEAD**, including supported term-only,
   nested relationship and permanent-delete changes. Term mutation snapshots
   are balanced for nested/reentrant callbacks and partially committed
   `WP_Error` paths; unchanged/unsupported URLs remain no-ops. No recursive
   purge, direct filesystem unlink or new public endpoint.
5. Native Cache **Restore revokes** its manifest before retirement.
   **Disable URL mapping** removes only the native-owned manifest; future
   generations require fresh operator opt-in. Reverse site-specific
   Helper/PHP access changes through their own authorized procedures.

No alternate Host aliases, query-style permalinks, encoded original paths,
pagination, author/date archives or vendor-wide Purge All certification.
Actual Nginx worker and personalized-data safety remain separately proved
only where acceptance evidence exists.

## Observability and QA

The plugin's **Activity & Logs** supplies useful UTC time, action/stage,
target, outcome/error classification, Operation/Recovery IDs and bounded
diagnostics. Keep secrets, cookies, credentials and raw private request
bodies out of general logs without discarding the root cause. A write
denial, audit failure and uncertain worker reload are distinct outcomes;
never report them as a successful Apply.

- **Source:** run the current [CI checks](../.github/workflows/ci.yml),
  packaging builders and targeted regression tests for the changed module.
- **Real native QA:** check exact installed ZIP file hashes **including
  obsolete extras**, active aaPanel Python helper freshness, authenticated
  primary-admin UI/CSRF paths, Nginx and PHP syntax/services, actual HTTP
  status/body/Cache behavior, independent peer-site preservation and saved
  exact Restore. Do not claim universal support from one guest.
- **Fault injection:** only on an owned isolated QA guest with verified
  rollback. Unknown write outcome requires read-only reconciliation before
  any retry. Full physical service/VM disruption needs stronger isolation,
  explicit scope and recovery evidence.
- **Latest evidence:** [#21 release ZIP/lifecycle receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6937217273),
  [#21 real two-customer native Woo acceptance](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6938476216),
  [#2 functional backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2),
  and archived, bounded, file-based [QA evidence](evidence/).

## Verified source references and history

The [official aaPanel plugin-development guide](https://www.aapanel.com/pkg/aaPanel_Linux_Panel_Plug-in_development_documentation_v1.1.pdf),
[aaPanel App Store documentation](https://www.aapanel.com/docs/Function/AppStore.html)
and inspected [aaPanel panelPlugin.py revision](https://github.com/aaPanel/aaPanel/blob/38bf35903b37b50d9654f47c4ad904ca3369715f/class/panelPlugin.py)
are starting references, **not** universal current compatibility contracts.
Real adapter truth is in current source, runtime, guarded QA and saved
operator state. The original EN/FA design snapshots are retained under
[the reference-only preservation tag](https://github.com/AChWorks/ach-aapanel-customizer/tree/reference/ach-status-pages-v1-20261103/design-references/ach-status-pages-v1)
and their 22 HTML bytes match the packaged assets.

**Historical per-candidate experiments, earlier PR review deltas and
superseded “unreleased” checkpoints are not current instructions.** For
forensics, the [integration guide before consolidation](https://github.com/AChWorks/ach-aapanel-customizer/blob/b0aebaf418404e43717a74b6085411edeaa2c84b/docs/aapanel-integration.md)
and its original section anchors remain permanently available in Git
history; current authoritative acceptance is in native GitHub PR/CI/Issue
receipts and retained `docs/evidence/`. Do not add another rolling
per-version status feed to this operator guide.
