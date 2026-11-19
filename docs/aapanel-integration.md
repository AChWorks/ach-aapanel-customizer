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

The verified installed nonproduction reference is **aaPanel 8.0.7 / Nginx /
PHP-FPM 8.1 and 8.5**, with specific site, native ZIP and recovery
tests recorded under #21. The guest currently reports **Nginx 1.30.6**
(2026-11-19); earlier QA receipts used Nginx 1.28.3. These are observations,
not a general Nginx-version support guarantee. A reported source-file match, permitted read-only
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

## Native aaPanel request authorization and parameter namespace

The verified aaPanel **8.0.7** native plugin dispatch uses the ordinary
authenticated panel route (`/plugin?action=a&name=ach_customizer&s=<method>`),
with the normal primary-administrator authorization and `x-http-token`.
Never copy aaPanel's example dynamic-route `_check` implementation that
returns unconditional success: dynamic routes need separate authorization,
and this plugin's observed route/session behavior must not be generalized
to untested aaPanel versions.

aaPanel's input merger can allow POST fields to shadow query parameters
used by its router. Treat `action`, `name` and `s` as **reserved** in all
native plugin AJAX bodies: a submitted POST `action=save` can overwrite
the router's required `action=a` and fail before Customizer dispatch.
Use plugin-owned `branding_action` for Status Pages Save/Reset and
`cache_action` for Cache Apply/Recheck/Restore/Clear. Preserve the
same native session/CSRF and backend write/approval gates; renamed form
fields are **not** an authorization workaround.

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
   cache-privacy guarantee. The **explicit local HTTP GET** may trigger
   application work/log entries; it is not an automatic health probe.
   Regeneration, missing extension or source drift must not silently
   adopt changed files.

Site discovery is bounded by the current implementation's verified inventory
shape; unsupported layouts show `Needs Review` rather than permission to
repair. No scheduled per-site enforcement or automatic VHost reconciliation
is implemented.

## Non-default website roots and source ownership

Do **not** assume "/www/wwwroot" for a site's Document Root. Native aaPanel
`sites.path` is the source for current site-root identity and `sites.id`
anchors ownership; native domain bindings and the actual site VHost must be
re-resolved independently. A root move is material drift even when site ID
and hostname are unchanged. Any pending preview, cache manifest, recovery,
status-page write or site policy that references the former root must be
rechecked before it may act. Operations must not silently migrate/rewrite
paths or follow symlinks to make a changed root look compatible.

Different **native-supported** roots may coexist under `/www/acdomains`,
`/www/other-sites`, `/home/websites`, or elsewhere. The aaPanel website
creation API may reject some otherwise-valid absolute directories as system
paths, and the legacy One-Click WordPress frontend may supply a default
`/www/wwwroot/<domain>` path. Neither is a reason for Customizer to hard-code
its own document root or bypass aaPanel's path safety decisions. Distinguish
native site API fixture creation from actual WP Toolkit provisioning when
reporting QA. Read-only Website/VHost/Status/Cache discovery does not prove
per-module Apply/Restore, URL routing, automatic drift correction, or all
arbitrary Nginx path syntaxes. Unsupported paths should return a precise
`Needs Review` / conflict state without creating or touching files.

Static aaPanel application/service paths (panel data, Nginx binary/config,
PHP-FPM installs, plugin-owned cache) are different from **per-site roots**.
They must be discovered/validated through version-compatible service adapters
before claiming alternate aaPanel installation-prefix support. See Issue #21
for current custom-root and native WP Toolkit success/failure evidence.
Automatic post-terminal Hosts/FPM reconciliation remains a separate P0 requirement.

## Selected-site Nginx sensitive-path guard (merged source 0.1.53; not released)

The full primary administrator may choose a **native website** in Routing &
Nginx and review a fixed, opt-in, per-site protective source. Customizer reads
the selected ID, domain bindings and current Document Root from aaPanel itself,
then verifies the corresponding generated VHost and the **exclusive server-scoped
native `extension/<site>/*.conf` include graph**; `/www/wwwroot` is never a
site-root assumption. The supported implementation targets the source-matched
aaPanel 8.0.7 Nginx/HTTP-80 layout; no blanket Nginx-version claim.

**Protection semantics:** After a fresh Preview and explicit one-site approval,
an immutable policy fragment is atomically installed into that site's existing
Nginx extension directory, validated with `nginx -t` and applied with a
shared-service reload. Three fixed, server-rewrite `if ($uri ~* ...)` +
`return 403` conditions block nested sensitive dotfiles (including
`.env`, `.htaccess`, `.user.ini`), accesses below common backup directory
names and PHP/PHTML/PHAR requests below common uploads/media/tmp directories.
These **server rewrite-phase** returns run before Nginx Location selection:
native `location ^~ /wp-content/uploads/` cannot silently bypass the filter.
Safe `if` usage is limited to static server-scope **return-only** directives;
no rewrite or application PHP is executed. The response includes a
per-generation proof in a short body on matched requests (not in benign
response headers); exact HTTP/80 403+proof is observed on ten bounded paths
over three consecutive fresh request batches. This verifies *those* paths,
not arbitrary path aliases or origin HTTPS/cached edge behavior.

**Exceptions and scope:** No restriction is added to legitimate `.well-known`
ACME/OAuth paths, the site homepage, ordinary public static downloads, or other
sites. The policy is intentionally **not** a global block on all .zip/.sql,
a replacement for Fail2ban, or complete protection for every custom upload/
backup directory. A site with unsupported VHost/include, symlinked Document Root,
missing native identity, unrecognized owner, changed foreign include or
incompatible active Nginx workers must fail closed with `Needs Review` rather
than claim protection. Custom shared Nginx/global security rules need
environment-specific audit; browser/Caddy HTTPS is additional acceptance.

**Lifecycle / recovery:** Under the same authorized site/source lock, Apply
records an immutable root-owned journal before publication. Recheck can
distinguish `Unmanaged`, `Applied`, `Recovery Required`, `Needs Review`
and `Restored`. An uncertain Apply must NOT be automatically retried;
an explicit saved Recovery ID permits narrowly retiring the owned include,
revalidating and reloading Nginx, and checking that its proof disappeared.
Changed site ID/root/domain, native VHost or another extension invalidates
stale approvals. Other files, users and site configurations are not modified.
After uninstall, saved policy/recovery may still be active: reinstall and
use guarded Restore rather than delete Nginx files manually. No background
enforcement/automatic regeneration repair is yet implemented.

**Evidence boundary:** QA source-only and real manager transaction tests were
run on the **new** isolated aaPanel 8.0.7 machine, including
`/www/acdomains/paths85.aitest.gotohell.top` and
`/www/other-sites/paths81.aitest.gotohell.top`. Refer to Issue #21 for
exact test identity, status, and future rechecks. PR #99 was independently
approved and merged into main; no public Release or Production deployment is
authorized. The QA-installed earlier 0.1.53 ZIP is not byte-identical to the
final merged ZIP; see Issue #21 for exact evidence.

## Selected-site origin-local Hosts inspection (read-only)

Under **Routing & Nginx → Inspect local hosts file**, the primary
administrator can inspect the selected, validated native site's exact
bound names against the origin server's **`/etc/hosts`**. The backend
re-resolves the site and its full domain/port bindings **before and
after** the read. The browser supplies no file path or arbitrary domain
to inspect; source access is descriptor-anchored, read-only, no-follow
and identity-checked. Only matching native site names, address/line
evidence and a source fingerprint are returned — not unrelated Hosts
file contents. Wildcard bindings cannot be treated as exact aliases.

Results distinguish `Local Loopback Entry`, `No Local Loopback Entry`,
and `Needs Review` for partial wildcard inspection. A matching
127.0.0.0/8, ::1 or mapped loopback entry establishes **only an
origin-local file observation**, not a broken Gateway, DNS, resolver
precedence, proxy route or external HTTPS request. The inspection itself
does **not** modify `/etc/hosts`, call a resolver, offer automatic
repair, change routing or prove the origin's effective NSS lookup.

**Merged manual feature (introduced in source 0.1.52): selected alias removal and
recovery.** After a fresh inspection, the primary administrator may select
one exact bound hostname that has a loopback entry, expressly confirm it is
unwanted, and choose **Remove selected loopback alias**. The native endpoint
revalidates the selected site, stored file SHA-256, file identity, ownership,
absence of symlinks and the exact matching loopback alias. A root-owned backup
and prepared journal are persisted before an atomic same-directory file
replacement. Only this alias's loopback records are removed; unrelated hosts
and comments are preserved. After an independent **Inspect local hosts file**
check, the exact saved Recovery ID can restore the previous complete file
only if no other write has since changed it. An uncommitted/uncertain write
requires recovery inspection; do not blindly retry. If a provisioning tool
recreates an alias, a new separately reviewed removal retains previous
recovery material for forensics rather than overwriting it invisibly.

The manual tool alone cannot identify the writer, guarantee external
DNS/Gateway health or prevent repeat insertion. **Candidate source 0.1.54**
adds a **separate, expressly approved, narrow native WP Toolkit failure
reconciler** described immediately below. The manual 0.1.52 capability is
**not** available in published native 0.1.51. Installed-package/native
acceptance for the new candidate is still required; this is not Production
authorization.
If a stale Python helper prevents inspection after an upgrade,
use the [controlled worker recovery flow](aapanel-upgrade-recovery.md),
not a blind server restart.

## Native WordPress Toolkit failed-install Hosts cleanup (unpublished 0.1.54)

A **primary-admin POST** exposes the independent **Routing & Nginx → Native
WordPress failed-install Hosts cleanup** opt-in. Ordinary native plugin ZIP
install/reinstall does **not** activate it. The single supported writer is the
observed native **aaPanel 8.0.7 / Nginx** `AddWPSite → add_sites → deploy_wp`
progress path, with exact version and source SHA-256 checks of the native
`one_key_wp_v2.py`, `panel_site_v2.py` and panel version. These fixed-source
checks deliberately fail closed after a vendor upgrade. Do not modify
`/www/server/panel/class_v2` or deploy this candidate on Production.

After explicit approval, plugin-owned systemd `.path` and `.timer` units run a
bounded one-shot watcher on changes to `/tmp/wp_aapanel_deploy.log`, with a
30-second fallback tick to detect native lock release. It is **not** a
persistent polling daemon. While a **fresh single-site** progress record is
active and its lock is present, the worker stores a root-owned witness of the
current `/etc/hosts` bytes **only when the intended domain has no prior
Hosts alias**. When the same native progress inode/domain reaches terminal
`status=1`, `initialize_wp_website.status=-1`, and no WP/batch lock exists,
the worker checks that `/etc/hosts` equals the witness **plus exactly**
`\n127.0.0.1 domain`. A prepared journal and recovery backup precede the
existing descriptor-anchored, same-directory atomic CAS replacement.
Successful installs and unrelated or changed Hosts never trigger a write.

If the watcher misses setup before terminality, the native progress file is
replaced, aaPanel source changes, the domain already had any alias, a bulk
install runs, or the file is edited externally, **no automatic repair** occurs.
The watcher never edits shared PHP-FPM settings, deleted site records,
third-party mappings, general loopback aliases, or unobserved operations.
No network, DNS or HTTPS health is inferred. `Emergency disable` stores
**disabled** before attempting to stop the plugin-owned units; an
interrupted `prepared` journal refuses automatic retry. `Recheck interrupted
recovery` is read-only for `/etc/hosts` and reconciles only verified
before/after digests, then a separately consented **Restore** can restore
exact original bytes if the file still matches the saved after-state.
A stale witness whose original progress was overwritten can be discarded only
by an explicit **Disable → Recheck → Discard stale witness** sequence with an
additional operator checkbox, no active native lock and **no** prepared
journal; no Hosts edit occurs. The initial implementation intentionally
limits automatic recoveries to 64 per retained policy for bounded evidence;
a later policy/journal-retention design is required before that threshold.

The worker stores state/recovery under aaPanel's private plugin state
directory, bounded Activity records and root-owned systemd unit files.
Uninstall disables verified plugin-owned units but retains already-applied
file changes and recovery material; never delete a foreign unit. Verify
systemd unit readiness, active source writer fingerprint, worker logs,
current site functionality and previously successful WP peers on isolated
native QA before declaring operational acceptance. The initial source tests
and simulated filesystem cases do **not** prove real native event timing.

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
regardless of configured brand URL. Custom palettes check text, link,
button, focus and border contrast (4.5:1 for readable text; 3:1 for
meaningful boundaries) before rendering; unsupported combinations fail
review. Default reference HTML remains byte-identical.

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

For native full-tree `clear_files`, the implementation first validates
the complete selected site's cache hierarchy and peer identities. It
accepts only the expected Nginx `levels=1:2` tree of site-owned
regular objects (with the current required directory/file permissions),
refusing foreign objects, symlinks, hardlinks, bind mounts or physically
shared peer trees. A separate peer-identity check runs before and after
unlinks. The site's cache directory and operation journal remain in place;
a partially completed removal or changed topology is **uncertain**
and requires a fresh Recheck before retry, not a reported successful
complete purge. This is a guarded deletion of cache **files**, not a
recursive vendor Purge All or a request to reload Nginx.

## Optional WordPress Bridge: operator prerequisites

[WordPress Bridge](../wordpress/ach-aapanel-bridge/README.md) is an
**independent**, manually installed WordPress plugin. Its ZIP includes a
[WordPress-format `readme.txt`](../wordpress/ach-aapanel-bridge/readme.txt),
while the linked Markdown guide is repository-only. Without an explicit
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
