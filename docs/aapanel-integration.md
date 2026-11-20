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
   against the separately stored observation baseline. Select one changed
   native site and click **Save only selected website baseline** to accept
   only that site's observed state. The displayed before/after values are
   optional review guidance: the explicit Save click is consent, with
   no extra approval checkbox. No live website or policy is changed.
3. **Save baseline for ALL websites** is a separate explicit action accepting
   every compared record, including removals. Explain that scope beside
   the button and allow direct Save after a fresh comparison; never force
   another checkbox. A removed site is not silently accepted by the
   single-site path. Reused IDs, ambiguous bindings and stale revisions
   still require current identity rather than an unverified DB overwrite.
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
Automatic post-terminal, lossless Hosts cleanup remains open. Native PHP-FPM
auto-repair is merged in unpublished v0.1.62 source after recorded systemd
success/failure acceptance on native aaPanel 8.0.7. Fresh authenticated Browser
acceptance and Production qualification remain separate. The Hosts witness
still does not autonomously edit Hosts.

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
DNS/Gateway health or prevent repeat insertion. **Candidate source 0.1.60**
adds a **separate, opt-in, observer-only native WP Toolkit failed-install
witness** described immediately below. The Owner explicitly **rejected**
observer-only reporting as a substitute for automatic correction. No-loss
Hosts cleanup remains OPEN P0; the native PHP-FPM automatic correction
in merged but unpublished v0.1.62 passed source-bound native systemd
success/failure acceptance.
The manual 0.1.52 capability is **not**
available in published native 0.1.51. Installed-package fixture QA has
passed, but authenticated resident-watcher/end-to-end acceptance remains
incomplete; this is not Production authorization.
If a stale Python helper prevents inspection after an upgrade,
use the [controlled worker recovery flow](aapanel-upgrade-recovery.md),
not a blind server restart.

## Native WordPress Toolkit failed-install witness (unpublished 0.1.60)

The primary admin can explicitly enable **Routing & Nginx → Native WordPress
failed-install witness**. Native ZIP installation/reinstallation does not enable
it. Supported source: the verified **aaPanel 8.0.7 / Nginx** asynchronous
`AddWPSite → add_sites → deploy_wp` lifecycle, pinned to the actual SHA-256
fingerprints of `one_key_wp_v2.py`, `panel_site_v2.py` and panel version.
An upgraded/mismatched native writer fails closed. Vendor source is never patched.

A plugin-owned systemd `.path` and `.timer` schedule a bounded `.service`
run on native progress changes, plus a 30-second lock-release fallback. Only
an **active, pre-terminal** single-site progress event with a clean Hosts
baseline can establish a root-owned witness. When the same native operation
finishes with `status=1`, `initialize_wp_website.status=-1` and no native
setup/batch lock, the worker compares current Hosts with the exact witnessed
bytes plus `\n127.0.0.1 domain`. If the old alias was intentional or the file
was changed independently, it reports a guarded refusal; for an exact new
orphan alias it reports **Manual Review Required** with typed stage, operation ID and
safe reason in the `wp_terminal_manual_review` Activity event. **It never edits /etc/hosts automatically**, never
modifies shared PHP-FPM and never infers a missed pre-terminal event as safe.
An OS operator must inspect the exact domain recorded in Activity and verify
that the native setup is no longer active before making a manual Hosts change.
Because aaPanel may delete failed-site records, the selected-site manual Hosts
editor is not necessarily available for this case.

**Why observation only:** Linux `F_SETLEASE/F_WRLCK` may be forcibly broken
(`/proc/sys/fs/lease-break-time`). A worker suspended after its last
`F_GETLEASE` check can resume after a foreign writer appends to the same
inode. In-place `ftruncate` would then erase that foreign data, even if a
later hash or journal identifies a conflict. Another pre-write check, process
`flock` or optimistic file `rename` does not prove a no-loss invariant against
uncoordinated writers. The old automatic deletion path is removed from the
candidate; a safe, owner-approved transaction design remains a P0 future
requirement. Do not describe prior successful 0.1.54 QA cleanup from the older
candidate as evidence that this revised witness continues to delete aliases.

**Historical recovery compatibility:** root-owned applied/prepared cleanup
journals created by earlier QA candidates are retained through uninstall
and reinstall. `Recheck historical recovery` is **read-only for Hosts** and
reconciles an interrupted applied/policy write or `restore_prepared` crash
using journal phase and verified before/after digests. An exact alias
reappearing after phase `applied` **without `restore_prepared`** is external
activity and returns Needs Review; it is not labelled a completed Restore.
A separate primary-admin-approved legacy `Restore` requires an unchanged
post-cleanup source and uses `O_APPEND` with a write lease; even if the
lease expires and a competing writer appends first, the legacy Restore never
writes over that writer's bytes at a stale file offset. Such an uncertain
result retains `restore_prepared` and needs explicit Recheck. No new
recovery journal is created by the read-only witness, and existing journals
are not discarded by clearing the observation policy.

**Durable manual-review delivery:** a detected exact terminal alias first
creates a private, root-owned, bounded `*.manual-review.json` event with
the canonical hostname, stable operation ID, timestamp, classification and
delivery receipt. File and directory are synced *before* the terminal token
is committed. This source-of-truth survives a crash between token and JSONL
delivery, a failed Activity append, a disabled watcher and log rotation.
Pending delivery retries on subsequent worker invocations without replaying
Hosts edits. The Activity writer bypasses
`ACH_CUSTOMIZER_ACTIVITY_LEVEL=ERROR` for this one essential WARNING and
checks both retained JSONL generations under its lock before appending,
preventing duplicate delivery after a crash between log fsync and receipt.
The primary-admin Activity endpoint projects the private records exactly
once, independently of rolling JSONL. General Activity filesystem read
failures are reported as unavailable history (not admin authorization
failure), preserving valid private Outbox events with an Activity warning.
A verified canonical hostname is preserved in full (up to 253 ASCII characters after IDNA normalization),
without the descriptive Activity target's 120-character shortening.
Initial Outbox publication is atomic: a private fsynced staging file is
atomically renamed to the canonical name using Linux RENAME_NOREPLACE without replacing any existing report or leaving a second hard link,
then the directory is synced. An incomplete staging file is never an
authoritative record. If the general log is corrupted or
unavailable, the endpoint still shows durable manual-review evidence with
a bounded warning. Routing Inspect shows the latest domain, Operation ID
and delivery state after subsequent worker updates. An older malformed
canonical record is preserved, not replaced. Other valid reports still
appear, while Routing and primary-admin Activity report the first affected
Operation ID and a `Needs Review` warning. Processing the matching active
witness is blocked until separately reviewed recovery. Records remain
private and retained; a separate future retention policy must not silently
discard actionable manual-review evidence.

**Recovery of malformed canonical evidence — OS-operator procedure only:**
1. Disable the watcher, check native WP task and lock state, and identify
   the exact affected Operation ID and the matching saved witness.
2. Under separately authorized root maintenance, confirm regular-file
   ownership and mode, inspect the exact file
   `/www/server/panel/data/ach_customizer.wp-terminal.<operation-id>.manual-review.json`,
   and preserve a verified protected byte-for-byte copy.
3. After establishing that this **canonical** file is malformed, move that
   exact file to a distinct private quarantine filename without overwriting
   another file; sync the directory. Never delete the forensic copy, another
   operation's report, or a historical recovery journal.
4. Reinspect policy and original native progress. Resume the watcher only
   through its separately authorized controls, and only when all normal
   source/lock/timing guards remain satisfied. If stale, retain evidence and
   arrange manual OS remediation instead of forcing replay.

After ZIP upgrades, the resident aaPanel Python process may retain a
previous `ach_customizer_wp_terminal` module despite exact installed bytes
and a matching entrypoint version. The original v0.1.60 endpoint checks the
**loaded helper's** durable-review contract before non-emergency actions,
refuses stale helpers with `resident_wp_helper_stale`, and leaves Emergency
disable available. Ordinary general Activity remains readable with a
bounded warning if outbox projection cannot be verified. A controlled
panel-only reload requires separate target-specific operator approval; see
[upgrade/recovery runbook](aapanel-upgrade-recovery.md).

The status UI distinguishes policy **Enabled** from watcher **Ready** and
explicitly says **Unattended Hosts edits: OFF**. Unsupported sources,
malformed progress and external Hosts mismatches produce bounded,
deduplicated lifecycle Activity; sensitive WordPress progress and credentials
are not logged. `Emergency disable` persists the disabled policy before
stopping plugin-owned systemd units. A stale witness is discarded only after
Disable, Recheck, separately reviewed `Discard stale witness`, no native
locks and no prepared recovery. Uninstall removes only verified owned units
and retains root-owned recovery state. The former 64-recovery lifetime cap
applies only to historical repair journal accounting, not to observation.

Independent native QA previously established watcher timing, authentic
WordPress success/failure and recovery on the old automatic candidate.
Revised observation-only behavior requires fresh exact-source validation;
previous native QA is not a source of approval for unattended writes.

## Simplification and operator choice (merged source v0.1.63; unpublished)

Merged PR #103 removed arbitrary maximum totals on observed
native site records, PHP-FPM site attribution, Cache audit website lists,
read-only Hosts matching and Status Pages branding scopes. Native site and
domain queries are paginated; exact targets and page-level query budgets
remain verified rather than silently losing results.

For plugin-owned observation baselines and Status Pages branding Reset,
the operator's direct Save/Reset click replaces redundant approval
checkboxes. Displayed scope/impact explanations remain. Existing
authentication, fresh selection identity and revision checks remain in
the backend. Low-contrast Status Pages colors are allowed: preview and Save
show accessibility advice instead of rejecting the user's chosen palette.
This source package has not yet passed new-version native installed UI
acceptance or been published; it is not a Production deployment.

A second cross-layer limit audit additionally removes stale frontend
ceilings on large Hosts/VHost/Cache peer results, the 32-installation/128-root
PHP inventory limits, artificial Linux process/FD count stops, the 32-profile
Monitor-only PHP intent cap, the 32-fragment Nginx/PHP source reader caps,
and the 64-event historical WordPress recovery count stop. Inspection
of installed older PHP versions and newer aaPanel Nginx sources uses
observed readable files rather than version-text bans. The explicitly
implemented 8.1/8.5 PHP-FPM and Cache write adapters, native WP watcher
source fingerprint and data-ownership boundaries remain unchanged.
Large-source handling still retains per-file/resource budgets and current
target/ownership validation; these are not absolute support ceilings.

The saved shared PHP-FPM Monitor policy also uses the current Preview and
direct Save click without requiring an additional checkbox. This only writes
plugin-owned desired values, not shared service configuration.

**Independent-review F1-F3 remediation (PR #103, merged after APPROVE):**
the PHP-FPM Manual/Auto shared-impact consumer now accepts complete native
mappings with 101+ sites rather than stopping at a fixed count. The
selected-site Hosts, VHost, Cache and Status Pages endpoints also accept
complete binding snapshots with 101, 135 and 1001 domains instead of the
old 100-binding or 110000-character restrictions. The website is always
re-read from aaPanel by native ID; stale names, roots and domain bindings
remain rejection conditions, and supplied client paths/domains are never
authoritative. The read-only Nginx candidate observer evaluates the actual
Nginx source and retains a stable panel-version/webserver observation rather
than rejecting recognizable sources solely by aaPanel version string.
These changes did **not** extend Nginx/PHP-FPM/Cache writer eligibility.
The exact v0.1.63 candidate passed CI and independent review before its
Owner-authorized Merge. Installed native QA, public Release and Production
remain separate, still-unverified gates.

## Native Nginx writer source completeness (proposed v0.1.64; unpublished)

Two existing *write* workflows — selected-site sensitive-path protection and
Status Pages extension Apply/Restore — still blocked otherwise valid native
installations solely for having more than 24 site domain bindings, 128 native
VHost sources, 32 peer extension fragments, or 128 included files. A second
Status Pages parked-VHost scan independently stopped at 128 entries. Proposed
v0.1.64 removes those collection-count stops from the actual downstream
writer preflights. It also streams native peer and include-graph enumeration,
rather than building whole-directory candidate lists or retaining an arbitrary
aggregate source-byte ceiling on otherwise individually validated files.

**Unchanged correctness boundaries:** the selected site's current native
identity/binding SHA; the exact server-scoped Nginx include ownership graph;
complete peer checks, including parked VHosts; per-file bounded reads with
owner, mode, inode, symlink and content-stability checks; source revalidation,
versioned/recovery-backed publication, Nginx syntax/reload/HTTP probe and
explicit Apply/Restore authorization. Unknown, cyclic, too-deep or
multiply-imported source graphs still refuse a write. External aaPanel/Nginx
writers are not atomically serialized by this observation; no new universal
Nginx layout or Production certification is claimed.

Targeted fixture acceptance covers 141 native bound domains, 136 parked peer
VHosts, 40/41 extension fragments, more than 1 MiB of sibling extension
sources and more than 2 MiB of included native configuration; it verifies
Apply/Recheck/Restore, last-peer ownership conflicts, stale preview refusal
and no changes to unrelated peer bytes. Fresh native installed v0.1.64
acceptance and independent review remain separate requirements.

## Native automatic PHP-FPM repair (merged source v0.1.62; unpublished)

The 0.1.62 candidate fixes the standalone systemd worker's missing
root-owned aaPanel Python import roots. Its existing path-triggered worker
now rechecks verified native install progress in a bounded 20-second window
(200 ms interval) so the native optimizer cannot as easily outrun the
initial witness. The existing timer remains the longer-install fallback.
There is no new daemon, native source patch, or unattended Hosts edit.

**Native QA (2026-11-19):** The exact 0.1.62 ZIP SHA256
0b18ff8eb0a8c3ca1dd2029de10085ff06087ef47968e4407013d021b3dd8d1d
was installed with 63/63 byte-identical payload members using the real
aaPanel importer. Two independent isolated aaPanel 8.0.7 guests exercised
the unchanged native optimizer with the standard systemd path/timer/service
already active, and no external high-frequency observer or manual repair:

- **PHP 8.1 successful installation:** native AddWPSite completed
  [1,1,1,1], created a real WordPress 7.1.4 OneKey site (ID 12), and
  reset shared pm.max_spare_servers from 20 to 30. The watcher had
  witnessed its start, then returned the value to the saved 20
  (pm.max_requests=300). Recovery ID:
  418d944918894f7c8698823a4279e19c.
  The installed site and three existing peer origins returned HTTP 200.
- **PHP 8.5 failed initialization:** on a separate new VM, a test-only
  restricted CLI staging permission caused a native WP initialization
  failure after the optimizer completed. Native progress finished
  [1,1,1,-1]; site/domain/binding rows were all removed. The same
  ordinary watcher returned Applied and recovered the shared pool from
  native 30 to saved 20, with the PHP 8.1 source byte-identical.
  Recovery ID: 25493fc8377d4cc5bb521050dc5df8f9.
  Three peer sites retained HTTP 200.
- Native Recovery Journal SHA, PHP/Nginx syntax, live services,
  idempotent repeat worker run, and actual Emergency Disable were
  verified; turning off both watcher policies preserved corrected FPM
  files and stopped the owned path/timer units.

All three task-owned QA VMs were stopped after validation. Production
was untouched; the existing primary QA guest was not modified by these
tests. These two concrete source-verified lifecycles do not prove general
compatibility with other aaPanel versions, arbitrary external writers or
unexpectedly delayed native starts. Exact-source CI and independent review passed and PR #102 was merged.
Fresh authenticated Browser QA and Production rollout remain distinct gates.
The detailed reproducible source identity and native QA results are in
[the 0.1.62 native systemd QA evidence](evidence/aaPanel-8.0.7-2026-11-19-fpm-auto-v062-native-systemd-qa.json).

This addresses automatic correction, not additional detection-only reporting.
In native PHP-FPM, save the desired PHP 8.1 or PHP 8.5 shared `[www]` settings,
select the same version, **Recheck saved policy**, review the complete
shared-site mapping, **Inspect automatic repair**, explicitly approve the
shared-service effect and **Enable automatic repair**. A separate managed
`ach-customizer-fpm-auto.path`, `.timer` and `.service` are installed
only on this opt-in; an ordinary plugin ZIP import creates no such units.

The worker is source-pinned to the verified aaPanel 8.0.7 Nginx single-site
native WP Toolkit path. The installed native source checks
`php-fpm.conf_record` before invoking `setFpmConfig` and writes its
single-space completion marker only after success. An already-present marker
at the witnessed task start **prevents automatic repair**: the verified
vendor path will skip FPM optimization. The worker must witness an absent
marker and capture the FPM source hash before a later matching terminal
result with that exact valid marker newly present. Failed installs before
optimization are retired without FPM writes. No marker is created or
removed by the Customizer, and no exact nanosecond timestamp match is
assumed for differently clocked filesystems. The
terminal must be successful or failed at the exact relevant step, with
native locks absent and within the verified freshness bound. If the file
was not changed during that witnessed operation, the worker performs no
FPM write or reload: an earlier intentional administrator edit is retained.
When the file changed, the saved versioned desired policy, Monitor status,
native service adapter, source fingerprints and shared-site attribution
are revalidated, including immediately before a guarded file write.
If native WP initialization failed *after* optimization and native cleanup
removed the site, a narrow fallback additionally proves exact terminal
identity, a newly present optimizer marker, source-pinned RAM-derived
vendor values, and absence of the precise native site/domain/binding records.
The remaining shared-pool consumers must still map successfully.
A successful native task, surviving/reassigned site or mismatched source
cannot use this path. These checks repeat at the final guarded write.
The existing FPM transaction validates syntax, reloads, verifies the service
and restores the former bytes on a verified failure when possible.

### Independent-review R1–R4 control-flow remediation (candidate only)

- **Reviewed-site consent (R1):** Enable carries the exact versioned
  `impact_sha256` from saved-policy Recheck plus the saved policy and
  Monitor revisions. The server recomputes the **same** site-impact digest
  used by guarded Manual Apply under its Monitor state lock. Added,
  removed or reassigned PHP consumers and changed file dependencies force
  a new review; Emergency Disable remains independent of this gate.
- **Native writer attribution (R2):** In addition to the existing
  absent-before/present-after optimizer completion marker, the worker
  verifies the installed root-owned aaPanel `class/config.py`
  `setFpmConfig` source SHA256. It records native physical RAM and the
  original `pm.max_requests` at the witnessed start. The four values
  rewritten by the source-pinned native optimizer must still equal its
  RAM-derived output **immediately before the guarded CAS replacement**.
  If an administrator edited one of those values afterward, or modified
  `pm.max_requests` (not written by the native optimizer), no automatic
  write is allowed. Unrelated directives remain preserved by the exact
  current-file plan, and ambiguous ownership is refused.
- **Crash acknowledgment (R3):** Newly committed schema-2 automatic
  recovery journals bind the exact terminal `event_token` in addition
  to owner, saved-policy digest, PHP version, Operation ID and before/after
  file SHA256. A restarted worker reconciles that private applied journal
  and snapshot *before* treating the terminal as a no-op; a matching
  completed repair is acknowledged with its original Operation ID **without
  another write or reload**. Older schema-2 journals without a token
  remain readable, but cannot impersonate a new event. Malformed,
  conflicting or uncertain recovery still blocks repair.
- **Emergency Disable (R4):** The authenticated per-version Disable first
  atomically publishes a root-owned, fsynced, no-clobber revocation request
  independently of the three-second Monitor lock. A busy transaction may
  finish safely while the API truthfully returns **Pending Disable**.
  The running worker consumes the request before releasing its shared
  lock, or the existing systemd timer finishes it on a later invocation
  without another operator action. A completed request durably disables
  the affected version and stops owned watcher units when no other
  PHP version remains enabled. Other enabled version policies and
  existing recovery files are preserved. A crash after the durable
  policy-off commit but before unlink/fsync of the canonical request
  **still displays Pending Disable even with enabled=false**. Both
  worker shutdown and uninstall must retain the owned retry mechanism
  until the canonical request is actually consumed and durably removed;
  a subsequent worker invocation cleans it up idempotently without
  any host Apply/reload. A failed revocation-directory fsync also prevents
  shutdown; the next worker must successfully sync and recheck the state
  directory before stopping the retry timer. Only then does Disabled permit
  fresh Enable. Cancellation never kills PHP-FPM.

A successful auto repair leaves a current per-version journal and pre-image,
allowing the existing explicitly approved Rollback flow. On a later genuine
native WP operation, an older *verified automatic* applied journal is
moved into an immutable operation-ID archive before the next guarded
repair; manual/uncertain/malformed recovery is never automatically retired.
A crash between archive renames leaves incomplete state requiring supervised
recovery, not discarded files. The saved policy hash is part of each
automatic recovery identity; a changed policy requires explicit re-enable.
Emergency Disable clears future authority before stopping the owned watcher,
potentially waiting on an existing guarded operation. Uninstall preserves
host PHP settings, snapshots, archived recovery and desired policy.

This is a **development candidate**, not a claim of operational acceptance:
real start/terminal event timing under a resident enabled watcher, end-to-end
PHP 8.1/8.5 corrections, peer-site health, restart/duplicate behavior, and
browser authorization must be verified in isolated native QA. It is not
automated Hosts cleanup, nor does it cover unrelated aaPanel PHP operations.

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

Installed native PHP versions are read-only discovery and inspection candidates
when their actual files and service shapes can be understood, including
older installations. The currently implemented PHP 8.1/8.5 **write adapters**
are not a claim of guarded Apply on every other version or pool.

## Status Pages: static assets and distinct delivery modes

The package contains **11 templates × English/Persian = 22** versioned,
self-contained static HTML assets under
[`plugin/ach_customizer/status_pages/`](../plugin/ach_customizer/status_pages/).
The [manifest](../plugin/ach_customizer/status_pages/manifest.json) records
their original asset hashes. Preview uses validated, escaped brand URL/text,
palette and target/site scope; site-local home links must remain site-local
regardless of configured brand URL. Custom palettes retain the administrator's chosen colors. Text/background
contrast below 4.5:1 or accent/background contrast below 3:1 produces
nonblocking accessibility advice, not a save prohibition. Valid color syntax,
safe escaping and site scope remain required. Default reference HTML
remains byte-identical.

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
