# ACh aaPanel Customizer

A **native aaPanel plugin** for inspecting, applying, rechecking and restoring
administrator-approved website and service customizations **inside aaPanel**.
It is not a standalone dashboard, a server-wide unattended enforcement agent,
or a WordPress-only plugin.

## Distribution, source and tested state

| Layer | Verified reference (2026-11-22; check live systems) | What it proves |
| --- | --- | --- |
| **Published package** | [v0.1.51 pre-release](https://github.com/AChWorks/ach-aapanel-customizer/releases/tag/v0.1.51), native `0.1.51` and optional Bridge `0.1.8` | The previously verified public package; always recheck [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) before claiming latest |
| **Source checkout** | Native `0.1.88` candidate on Draft [PR #118](https://github.com/AChWorks/ach-aapanel-customizer/pull/118); Bridge `0.1.9` unchanged | Not yet merged or publicly released. The installed version and exact QA proof belong to [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21); prior 0.1.87 QA remains version-scoped |
| **Retained native QA VM** | `ach-aapanel-qa/aac-native-qa-20261118`, aaPanel `8.0.7`; [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) owns current installed ZIP and resident-worker verification | **One persistent Running VM**, not a fresh guest. See [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) for binding, test scope and actual current runtime |

Always check [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases),
source manifests, current PR/CI and the target installation before relying on
this dated checkpoint. **Merge, publication and deployment are separate steps.**

## Read this first: current work and QA ownership

The **three open Issues** are the active work index: [#2 product backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10 Status Pages HTTPS/443 decision](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), and [#21 installed-native QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21). Read the **top-level active contract**, then current repository code/PR checks and installed QA evidence. Dated experiments in older issue comments, manifests and test receipts are **historical evidence**, never instructions to recreate obsolete VMs or reinstate cancelled features.

**Owner QA environment policy:** Reuse the **same existing aaPanel VM** in [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) for all remaining development. Do not create, replace, stop or delete it during development; do not create disposable VM snapshots. Authenticate with its existing guest-bound protected `service_access` reference; no routine password resets. Create only explicitly scoped, recoverable *fixtures inside that VM* and preserve other sites. Before any new native E2E, compare the installed version with the reviewed source. Public Release and Production are separately gated.

## One-time WordPress Cache connection — merged source

The one-click **Connect WordPress Cache (once)** workflow merged into
`main` in [PR #113](https://github.com/AChWorks/ach-aapanel-customizer/pull/113).
[PR #114](https://github.com/AChWorks/ach-aapanel-customizer/pull/114)
**merged** the native 0.1.72 corrective implementation for fresh aaPanel
WordPress installations. Once the official Nginx Helper and ACh aaPanel
Bridge files are installed on a selected native WordPress site, one
administrator click activates/configures them, applies its isolated Cache,
sets PHP/WordPress access and provisions the generation-aware mapping.
The official **Purge Current Page** and **Purge All** remain the user
controls; no replacement purge plugin or recurring watcher is added.
**Disconnect and restore** recovers the managed setup without routine
manual file edits.

Real installed-native, authenticated **HTTP/browser acceptance** of the
[earlier 0.1.72 candidate](https://github.com/AChWorks/ach-aapanel-customizer/commit/eb875fd2932e4ae75c3d0c045f968d51836be24f)
included both vendor purge actions, WordPress Page/Post
changes, site/peer Cache isolation, VM restart and Disconnect/Reconnect.
See the [Issue #21 acceptance record](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7055966635)
and [integration guide](docs/aapanel-integration.md); HTTPS and actual
WooCommerce customer/session flows were **not exercised on that specific
HTTP-only WordPress test site**. The later PR #114 remediation passed
exact-HEAD source, regression and real embedded PHP CLI tests, **not** a
fresh installed/browser run. In particular, this evidence is from a
**different, now-removed QA guest**; do not transfer installed acceptance
to the persistent VM or infer any newer candidate is loaded and tested there. Neither
Merge nor QA authorizes public Release or Production.
The broader open functional work remains in [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2).

## Capabilities in the merged development source

| Native section | Operator tasks and important boundary |
| --- | --- |
| **Overview / Monitor** | Read component availability, diagnostics and packaged versus resident **entrypoint** version; matching entrypoints do not certify every imported helper. |
| **Website list** | Discover paginated native websites and bound domains, compare drift, and save selected-site or all-site observation baselines without changing website configuration. |
| **Routing & Nginx** | View current local loopback aliases and remove an **exact chosen hostname with one administrator click**, with no site-selection or watcher prerequisite. Inspect site VHosts, apply opt-in Nginx sensitive-path protection, and manage site-log Fail2ban scanner jails with disclosed origin-wide web-port ban scope; **Hosts removal is never unattended**. |
| **PHP-FPM** | Inspect installed PHP files, service/pool mapping and affected sites. Guarded shared `[www]` Apply/Restore is implemented for validated **8.1/8.5** adapters; discover other installed versions rather than treating these adapters as a universal version allowlist. Separately opt in to source-verified WordPress/aaPanel native PHP-FPM writer regeneration repair. |
| **Status Pages** | Preview the bundled 11 English/LTR and 11 Persian/RTL offline templates, edit scoped branding, and use verified site/global Nginx delivery and Restore modes. Global unknown-host **HTTPS/443 TLS/SNI uses approved manual Option A** in [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10). |
| **FastCGI Cache** | Inspect and explicitly Apply/Recheck/Restore site-owned policy; clear selected URLs or independently verified site-owned cache files. Private-session isolation and Nginx Helper integration have **bounded** non-production proofs, not generic safety certification. |
| **Activity & Logs** | Inspect operation stage, outcome, error and Operation/Recovery IDs for diagnosis and safe reconciliation. |

The separately installed, optional [WordPress Bridge](wordpress/ach-aapanel-bridge/README.md)
(source version `0.1.9` at this checkpoint) defaults to **disconnected**. After
administrator provisioning of a generation-bound manifest it can assist
Nginx Helper with **eligible per-URL GET/HEAD invalidation**; it does not
install Nginx Helper, intercept its vendor **Purge All**, or provide a
cross-site-safe recursive purge. The installed WordPress package ships its
own [WordPress `readme.txt`](wordpress/ach-aapanel-bridge/readme.txt).

## Native 0.1.88: basic website file protection, no duplicate directory-index rule

On the retained native aaPanel VM, a synthetic directory without an index
already returned HTTP 403 (Nginx autoindex disabled). No duplicate listing
restriction is added. But synthetic website-root `debug.log`, `error_log`,
`backup.sql` and `wp-config.php.bak` each returned HTTP 200. The **same
opt-in selected-site Nginx Guard** now denies these common debug/error logs,
database dumps and configuration/backup filenames before file download.
It neither scans/moves/deletes files nor changes permissions, aaPanel logs,
global Nginx, public images or normal ZIP downloads; no extra UI option.
This pre-stable Guard has just one current default ruleset
(`site-sensitive-files-v1`) and one optional XML-RPC variant
(`site-sensitive-files-xmlrpc-v1`); it does **not** carry earlier QA
ruleset adapters.

This is a limited additional layer, not a promise to catch every renamed
backup or an explicit per-location `autoindex on` override. Unsupported
site layouts require manual review. Native QA evidence and installed identity
are kept in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
Merge, public Release and Production still require separate authorization.

## Native 0.1.87 earlier QA milestone (historical; not publicly released)

This candidate adds one selected-site, manual, recoverable HTTPS
`home`/`siteurl` WordPress database correction, using the site's native
PHP CLI and existing Recheck/Apply/Restore UI. The selected administrator
checks that HTTPS is working first: no automatic DNS/SSL/Nginx repair or
watcher is created. Foreign WordPress URL overrides are refused, and an
interrupted two-option update retains its exact Recovery ID. Separate
WP_DEBUG/PHP changes no longer obstruct a valid URL Restore. The existing
site-owned sensitive-path Nginx Guard also has an **optional pre-PHP
XML-RPC rule** using the exact same include/journal; the old default
and pre-existing Recovery records continue to work. These **0.1.86**
features passed exact-source and real installed native QA on the one retained
VM ([receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7071383274)).
**0.1.87** additionally refuses new origin-wide Fail2ban scanner bans when
the native Nginx access-log file or its parent directory is replaceable by
a non-root process; the source report identifies the unsafe path. The plugin
does not silently change shared aaPanel log ownership or grant PHP access to
root-only recovery records. A native VHost created without its site-owned
Nginx extension include now reports the exact one-time manual prerequisite.
The 0.1.87 source was officially imported into the **same persistent nonproduction aaPanel VM**, with all 69 source files byte-verified, native Python/UI version `0.1.87` and the unsafe log-path refusal proved via the authenticated UI. [Detailed QA evidence](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7071682775). This does **not** authorize public Release or Production.
[Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2)
defines the manual-first reconciliation contract.

The same optional site-local WordPress controls also provide a **manual
XML-RPC request block**. It uses one exact, plugin-owned WordPress must-use
plugin, not an Nginx-global rewrite or blanket server deny rule. WordPress's
real `xmlrpc.php` POST must return 403 with the unique current managed proof;
all other WordPress routes continue their native behavior. Apply/Recheck and
Restore require selected-site proof, exact file ownership, a durable Recovery
ID and source compare; foreign MU plugins and other sites are preserved.
When the product created a new `mu-plugins` directory it removes it on
Restore only if empty. This only blocks requests once WordPress bootstraps;
it is **not** claimed to stop PHP-FPM entry or all proxy/edge variants.

The new site-local WordPress controls support manual WP_DEBUG and a real
system WP-Cron schedule. They revalidate the selected native site's PHP
assignment, permit only a literal unique wp-config.php setting, provide a
source-hash-gated Apply and Recovery-ID Restore, preserve unrelated config
lines, and never adopt a foreign cron task. System Cron is installed before
disabling WordPress's page-load trigger. The cron task runs as the ordinary
`www` worker, reports errors through the system logger, and can be removed
independently of Debug. A disabled/unsupported cron service or ambiguous PHP
source fails with an actionable reason. This is opt-in per site, not an
automatic new-site policy; a successful source write alone is not a live
WordPress application or cron-execution acceptance.

The current feature branch adds conservative read-only WordPress/WooCommerce
**file-based classification** to website inventory. It does not claim a live
WordPress bootstrap or WooCommerce activation from files alone; unknown
and symlinked targets remain Unclassified. The global Status Pages
**unknown SNI HTTPS/443 Option A** is separately opt-in. It creates an
owned, recoverable Nginx default TLS rejection policy only when compatible
HTTPS/443 wildcard listeners already exist, preserving named sites and
their certificates, with real handshake checks before/after shared reload.
It does not open a new listener, install a certificate, change HTTP/80
Status Pages, publish a public Release or authorize Production deployment.
The retained QA VM has no configured HTTPS/443 listener at its
original baseline. Previous exact-source 0.1.85 QA verified a temporary
two-family HTTPS fixture and its cleanup; this evidence remains source-specific; the
0.1.86 pre-PHP XML-RPC HTTP/POST+Restore path was independently exercised on
the retained guest and does not certify 0.1.87's new scanner log trust check. See [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10)
and [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

## P0 native 0.1.80 source workflow (not yet publicly released)

- PHP-FPM: Save desired [www] pool values, recheck real shared-site attribution,
  then explicitly Enable automatic repair. The existing 30-second timer handles
  witnessed WordPress Toolkit optimization and additional exact aaPanel-native
  FPM regeneration on supported service shapes. Completed WordPress progress
  does not suppress a later independent native regeneration; the same WP
  task's source change is not independently borrowed as repair authority.
  Active native WP/batch locks defer repairs and are rechecked at Apply.
  At Enable, the reviewed policy is committed before systemd starts the
  event path/timer; the worker cannot interpret a just-activated empty
  profile as Disabled and immediately stop its own timer. A failed unit
  activation revokes the newly armed version rather than claiming success.
  The privileged enable endpoint also requires the loaded helper's current
  arming protocol. An older resident helper is reported as stale and
  cannot claim Enabled merely because a newer ZIP is installed. Read-only
  inspection explains the required separately approved panel-only reload;
  Emergency Disable always remains available. Repeated byte-identical
  aaPanel writer events receive distinct opt-in/previous-acknowledgment
  tokens, with recovery journals archived between successful repairs.
  A committed repair that lost its separate profile acknowledgment is
  reconciled without a duplicate reload, even when the desired source
  equals the original opt-in baseline. Worker errors expose their
  actionable stage and reason in the systemd journal.
  Each repair uses the saved
  intent, fresh writer identity and affected-site mapping, guarded syntax/
  reload/verification and durable rollback. Foreign manual drift is not
  overwritten. Legacy enabled profiles remain WP-only until explicit re-enable.
- Scanner: In Routing & Nginx, first Apply the site-sensitive pre-PHP Nginx
  guard, then Check and Enable the selected site's Fail2ban scanner. It monitors
  that site's verified combined access log for repeated sensitive-file, backup
  and executable-upload probes rejected as HTTP 403/404. Admin-adjustable
  retry, window and ban duration use an installed Fail2ban/nftables service.
  Kernel bans are origin-wide across all sites on TCP/UDP 80/443 for both
  address families; they are NOT confined to that site's log. Do not enable
  without validating proxy/CDN source attribution and ban consequences.
  Recheck/Restore manages only the owned site jail; foreign jails survive.
  A running jail with a Prepared recovery journal remains Recovery Required
  with its original Recovery ID. After native site deletion, Routing & Nginx
  also offers **Find orphaned scanner jails → Restore selected orphan jail**,
  without needing a current website or enabled Monitor. Foreign/changed jail
  bytes are never removed. If the orphan's missing log blocks Fail2ban
  startup, the primary admin can retire only the exact journal-owned jail
  source offline. The same Recovery ID stays in `restore_pending` and
  firewall state is explicitly unverified; after Fail2ban starts, repeat
  Restore to check the absent jail and owned nftables sets before committing
  `Restored`. Never claim that an offline file unlink removed active bans.
- See Issue #21 for exact installed and live QA proof. Source checks alone do
  not prove browser acceptance. New Release/Production remain separately gated.

## Install and operate

1. For a published version, obtain the native ZIP and `SHA256SUMS.txt` from
   [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases)
   and verify the checksum. A locally built `main` ZIP is **unpublished**.
   Import the native ZIP with **aaPanel → App Store → Third-party Plugins →
   Import Plug-ins**. Install the separate Bridge ZIP through WordPress only
   when that integration is actually needed.
2. Open Customizer inside aaPanel; use **Overview → Refresh state** to check
   version/worker diagnostics, and **Website list → Refresh websites** to
   inspect the current native inventory. Select the correct site for any
   site-dependent operation; read-only Local Hosts discovery needs no site.
3. To remove an unwanted local loopback hostname, open **Routing & Nginx →
   Local Hosts**, click **Refresh local aliases**, select the exact hostname,
   then **Remove selected hostname**. The click is the authorization; no
   extra checkbox or native WordPress witness is needed. The action only
   targets that hostname's loopback mappings in the origin's `/etc/hosts`;
   it does not modify public DNS. Check the refreshed list and Activity.
4. For Cache, Status Pages, site protection, and shared PHP-FPM changes,
   follow the relevant **Preview/Readiness → explicit scoped Apply → fresh
   Recheck** path. Understand the specific target and shared-service effect;
   **Restore** uses the saved recovery identity. Never blindly retry an
   uncertain write, clear a shared Cache root, or reapply a stale preview.
5. After importing or upgrading, check **both** installed package identity
   and resident behavior. An older Python helper can survive package import;
   an actual proven mismatch may require a separately authorized, **panel-only**
   reload using the [recovery runbook](docs/aapanel-upgrade-recovery.md), not
   an automatic Nginx/PHP restart.

The optional failed-WordPress-install **witness** is an observation-only
advanced diagnostic, **not** a prerequisite for Local Hosts removal. Its
historical recovery state must be preserved; it never performs automatic
Hosts cleanup. Native PHP-FPM automatic repair is a different opt-in feature:
its systemd watcher is not enabled by ordinary plugin installation. The
[technical guide](docs/aapanel-integration.md) describes these distinct
flows and their actually verified platform boundaries.

## Known limits and release gates

- **Nginx Helper vendor `Purge All` is not certified** for shared or ambiguous
  physical Cache roots. Native site-owned full-tree Clear is a different,
  separately guarded operation. Private customer isolation, payment routes,
  query/archive permutations, extensions and other host topologies need
  their own evidence before broad claims.
- Global unknown-host HTTPS/443 error-page behavior requires an unresolved
  certificate/SNI and exposure-policy decision in [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10).
  A working origin HTTP/80 error handler does not prove TLS handshake behavior.
- Native PHP-FPM repair has non-production systemd success/failure evidence for
  specific aaPanel 8.0.7 PHP 8.1/8.5 layouts, but its full authenticated
  policy/automatic-repair UI matrix and other native service shapes remain
  open in [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
- Site roots come from native website records, **not** a hard-coded
  `/www/wwwroot`. Unrecognized Nginx writer/source layouts require fresh
  inspection; no version/provider/site-count restrictions without a real
  compatibility reason.
- **Production installation/activation is not authorized by source CI,
  an isolated QA pass, or a pre-release.** Publication, deployment and
  consequential shared-service changes require their own permissions.

## Development and native QA

Create deterministic **unpublished** ZIPs from the repository:

```bash
python3 -B scripts/build_plugin.py --output /tmp/ach-customizer.zip
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

Run the source gates from [CI](.github/workflows/ci.yml):

```bash
python3 -B -m compileall -q plugin/ach_customizer scripts tests
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_inventory_ui.cjs
sh -n plugin/ach_customizer/install.sh
```

CI also checks PHP syntax, embedded JavaScript parsing and deterministic ZIPs.
Source tests do **not** replace real installed native UI/CSRF, recovery, Nginx,
PHP, WordPress/WooCommerce and peer-site acceptance. The retained QA
guest's aaPanel 8.0.7 protected Browser login requires the **actual post-login `#app` element**
(not obsolete `.main-content`). Use the [verified protected login and UI
runbook](docs/aapanel-integration.md#native-authenticated-browser-qa-runbook-aapanel-807),
not password reset, secret export, or repeated failed Browser-tool probes.

## Authoritative project references

| Need | Source of truth |
| --- | --- |
| Purpose, accepted operating policy and constraints | [Project specification](docs/PROJECT-SPEC.md) |
| Native adapter behavior, login and operator procedures | [Technical guide](docs/aapanel-integration.md) |
| Uncertain ZIP upgrade, resident worker, rollback | [Upgrade/recovery runbook](docs/aapanel-upgrade-recovery.md) |
| Exact merged implementation and checks | [Pull requests](https://github.com/AChWorks/ach-aapanel-customizer/pulls) and [CI](https://github.com/AChWorks/ach-aapanel-customizer/actions) |
| Published ZIPs and checksums | [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) |
| Remaining work and exact native QA | [#2 functional backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10 Status Pages/TLS](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [#21 installed QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) |
| Historical source-bound evidence | [`docs/evidence/`](docs/evidence/) and original GitHub PR/Issue history |

The current project policy favors **simple, maintainable, operator-driven
workflows** over arbitrary version/host limits and redundant consent steps.
Keep real authorization, exact target ownership, recoverability, and
independent-review/Owner Merge, Release and Production gates intact.
