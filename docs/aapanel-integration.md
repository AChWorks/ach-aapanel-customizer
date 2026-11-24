# Native aaPanel integration and operating boundaries

This is the **technical/operator guide**, not another product specification,
release timeline or QA activity log. The durable product requirements live in
[PROJECT-SPEC.md](PROJECT-SPEC.md). The authoritative current distribution is
[GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases);
unfinished compatibility and acceptance live in
[Issues #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2),
[#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10) and
[#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

## Active QA environment — read before native testing

**Owner decision:** Keep the single existing Running aaPanel QA VM at `ach-aapanel-qa/aac-native-qa-20261118` on AI Test Server. Its identity, authorized credential workflow, scope and verified state are maintained in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21). Do not provision, clone, replace, stop or delete that VM, reset its existing credential or create disposable snapshots. Use only reversible task-owned fixtures on that VM and preserve unrelated websites and Recovery records. Prior guests and snapshots are historical evidence, not reusable targets.

The [Native 0.1.98 installed acceptance receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7083011262) proves official aaPanel 8.0.7 import, **69/69 source file identity**, authenticated UI and bounded Guard Apply/Restore/source-drift recovery. A resident Python helper initially remained stale despite the official import and matching entrypoint/manifest version; a verified panel-only reload resolved that specific mismatch. This is not a license to restart every aaPanel installation or to claim untested modules were retested. Consult the [upgrade runbook](aapanel-upgrade-recovery.md).

## Evidence versus support

The reference non-production environment uses **aaPanel 8.0.7**, Nginx and PHP-FPM **8.1/8.5**. Actual eligible writers depend on current native site/service ownership, Nginx include graph, PHP pool topology and available CLI/runtime behavior, not an arbitrary string-version allowlist. Historical installed QA is bound to its source, package, guest, site and real exercised behavior. Exact installed source bytes and a matching version label alone do not establish fresh imported helpers, TLS, customer Cache isolation, vendor Purge All safety, other host layouts or Production qualification.

Use [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) and [the archived QA evidence](evidence/) for version-bound results, [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2) for open compatibility work and [Issue #10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10) for unknown-SNI HTTPS policy. Real customer/site or shared-service mutations remain separately scoped and require actual inspected ownership and explicit administrator action.

## WordPress per-site HTTPS URLs, Debug, system Cron and XML-RPC (manual)

Routing & Nginx uses the same selected native Website ID, document root,
bindings, and full-primary-admin POST checks as other site operations.
`Recheck WordPress setting` is read-only; `Apply selected setting` is
the explicit operator approval and `Restore saved WordPress setting`
uses the durable site-specific Recovery ID. No automatic policy is created
on install or when aaPanel adds a site.

**One-time WordPress HTTPS `home`/`siteurl`:** On a single selected native
WordPress site, a primary administrator selects **WordPress HTTPS home/siteurl**
and runs Recheck to inspect the **actual WordPress database options** and
one proposed HTTP-to-HTTPS conversion. It preserves each already-registered
native hostname, URL path and existing HTTPS URL; it removes an explicit
`:80` port, but never edits external DNS, certificates, Nginx or WordPress
configuration files. Set up and check working site HTTPS **before** clicking
Apply to avoid locking out WordPress administration. The custom PHP bridge
uses the selected native PHP CLI as `www` and WordPress's own `update_option`;
WP-CLI is not installed or required. The connector uses the real CLI
context, not WP_ADMIN or a simulated authenticated browser user. It
reports an early bootstrap exit or missing result distinctly from an
option-update failure. The shared selected-site source reader recognizes
both native stock and wpfastcgi PHP assignments at server scope without
requiring Cache writer compatibility for independent Debug, Cron, HTTPS
or XML-RPC operations. This action refuses multisite, PHP
`WP_HOME`/`WP_SITEURL` overrides, foreign/filtered or unknown host values.
Its journal records the original and target options and the exact Recovery ID.
An interrupted partial DB update can be **Rechecked and Restored** only while
each field still equals its own original or managed target; foreign edits
are not overwritten. A later independent WP_DEBUG edit or PHP assignment
change does not invalidate an otherwise safe option-pair Restore. A fresh
WordPress/PHP subprocess verifies actual option persistence, **not public
HTTPS reachability, certificate validity, redirects or other-site behavior**.
After an outside change, manually Recheck; no watcher or automated URL sync
is created. Restored operations can be reapplied against newly inspected
site URLs.

**Debug:** a literal single `WP_DEBUG` Boolean in `wp-config.php` may
be changed or inserted before WordPress bootstrap. It is syntax-checked
with the actual native PHP CLI before atomic replacement. The backup
records only the original matched line (if any) in root-owned state; Restore
removes or replaces the exact managed line and preserves unrelated changes
elsewhere in the WordPress file. Dynamic/multiple PHP definitions, including comma-separated global `const`
declarations of the managed key, and additional pre-bootstrap `include` or
`require` sources are refused with an actionable compatibility error.
Unrelated constants, inert comments/strings, stale site identity and foreign
managed markers are handled without silently asserting effective runtime state. No live PHP setting
is claimed until the application is separately inspected.

**XML-RPC request gate:** An independent opt-in site policy creates one
site-owned must-use WordPress plugin
`wp-content/mu-plugins/ach-customizer-xmlrpc.php`, after confirming the
native selected site, PHP handler, WordPress core files and live HTTP/80
`/xmlrpc.php` baseline. The static MU-plugin checks the WordPress-defined
`XMLRPC_REQUEST` and returns HTTP **403** with a nonsecret, generation-bound
`X-ACh-XMLRPC-Proof` header. This is an application-level block **after
PHP bootstrap**, not a pre-PHP Nginx/edge block. Nginx files, WordPress
database, Cache, and unrelated MU plugins are untouched. It is recoverable
through the same selected-site primary-admin Recheck/Apply/Restore UI; the
journal contains the exact managed file hash and recovery identity. Original
foreign files are never overwritten; an absent MU-plugin folder is created
with the site's own ownership and removed after Restore only if still empty.
Live POST/403/proof and absence after Restore are verified repeatedly.
The source fingerprint deliberately excludes the separately owned MU-plugin:
`wp-config.php` and WordPress core are **unchanged** by XML-RPC Apply.
The native UI must therefore accept the same verified source SHA before/after
this operation while still requiring changed=true, expected 403/proof,
exact Recovery ID and its own explicit admin action. An installed 0.1.84
test found and corrected a prior UI-only false `Uncertain` report: the
backend actually applied the policy and returned `Applied`; the UI
mistakenly assumed wp-config.php had to change. Recheck/Restore reconciled
that original operation without a repeated Apply, and the UI validation
was corrected in Native 0.1.85.

If the site no longer serves its expected WordPress route or the file drifts,
report a concrete source/recovery failure, not a fictional success.

**System WP-Cron:** a unique root-owned `/etc/cron.d/ach-customizer-wp-cron-<site_id>`
task is created and verified before adding the literal
`DISABLE_WP_CRON=true` setting. An active system Cron service, verified
native PHP CLI, WordPress entrypoint and system logger are required.
The task executes `wp-cron.php` as `www`, logs output via `logger`,
and uses the operator-selected minute step (cron's minute field restarts
each hour). A foreign task is never overwritten, and Restore removes
only the task with the saved byte identity. An interrupted operation keeps
its root-only Recovery journal; do not blindly reapply. Restoring Debug
must not remove Cron or erase unrelated administrator config changes.
These operations do not change WordPress URL/SSL, XML-RPC or Nginx rules.

Exact native installed-runtime checks, Cron execution and the full
site-identity/peer matrix belong to [QA Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

**Optional pre-PHP Nginx XML-RPC block:** The existing selected-site Nginx
sensitive-file Guard has an optional **Also block `/xmlrpc.php` before PHP-FPM**
checkbox. Its current default ruleset is `site-sensitive-files-v1`; when
selected, the full site guard uses `site-sensitive-files-xmlrpc-v1`.
Both options use the **same site-owned Nginx include and current-generation
Recovery journal**, with source-checked Preview/Apply/Recheck/Restore.
The extra server-rewrite condition blocks `/xmlrpc.php` before PHP
location dispatch. Live local proof checks 14 Guard paths by default and
15 with XML-RPC. No previous pre-Stable ruleset adapters or migration path
are supported. No watcher or global rule. The separately available WordPress
MU-plugin XML-RPC gate runs at the application layer; its proof is not proof
of the Nginx variant, and both gates need not be stacked on the same site.
Native installed HTTP POST/GET and peer tests belong to Issue #21; source
tests alone are not installed proof.

## Unknown-SNI HTTPS/443 rejection (Owner Option A)

This independent **opt-in** Status Pages operation uses a managed
`00.ach_customizer_unknown_tls.conf` default_server with
`ssl_reject_handshake on` only for existing Nginx wildcard TCP/443
listener families (IPv4/IPv6 discovered from the actual loaded source).
Without a configured HTTPS listener, **Recheck reports Not Applicable and
Apply cannot create a new listener**. If another default_server, explicit
address binding, stream/QUIC listener or unverified TLS source conflicts,
the operator receives an actionable refusal; no foreign source is edited.
Recheck/Apply/Restore each use the existing primary-admin session, global
unbound selection, persisted own Recovery ID, source fingerprint, managed
file ownership and the shared Nginx configuration lock.

Apply compares the previously working default TLS handshake with an
existing configured website witness on each socket family; after the
guarded syntax check and reload, an unknown SNI and a connection without
SNI must be rejected, while the configured witness still negotiates TLS.
Nginx workers can briefly serve a previous generation after `nginx -s
reload` succeeds. The post-reload verifier therefore waits for three
consecutive correct real TLS handshake rounds within a bounded ten-second
window for each IPv4/IPv6 family, retains the exact Recovery ID on failure
and includes the original typed failure stage instead of presenting only a
generic uncertain outcome. The first 0.1.82 installed QA caught this
transition before the 0.1.83 correction.
Restore removes only the exact journal-owned configuration and verifies
the prior handshake behavior, or a confirmed TCP refusal if the entire
native HTTPS family was removed. Source/CI tests and an installed-browser/
real TLS check are **distinct** evidence. On errors or uncertain reloads,
keep the Recovery ID; Recheck before attempting Restore or any retry.
This module does not affect HTTP/80 Status Pages, issue certificates,
automate ACME, or change Production until separately authorized.
Owner policy and version-bound installed-native testing: [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10)
and [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

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

The Customizer opens **inside** aaPanel. Task-first Native source/package
identity 0.1.101+ exposes Home, Websites, Server, Error pages, and
Activity & recovery. Website and
server tasks have contextual stages; the shared selected-site context is not
replaced with a raw-ID field. The earlier official Native v0.1.100 ZIP
has Overview, Website list, Routing & Nginx, FastCGI Cache, PHP-FPM,
Status Pages, and Activity & Logs. Use the instructions matching the actual
installed package; the [redesign contract](UX-REDESIGN.md) maps source tasks. Readiness, errors and recovery steps
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

### Isolated browser regression

Run the actual bundled UI in Chromium (no panel login or live API). Provide
Playwright through `NODE_PATH`, the Chromium executable via
`CHROMIUM_EXECUTABLE`, and the original aaPanel jQuery 2.2.4 file through
`ACH_NATIVE_JQUERY`. The test fixture validates the exact SHA-256 of the
observed 85,578-byte jQuery file
(`05b85d96f41fff14d8f608dad03ab71e2c1017c2da0914d7c59291bad7a54f8e`).
The same upstream file is available from
`https://code.jquery.com/jquery-2.2.4.min.js`; do not add it to the shipped ZIP.

```bash
node tests/manual/layout_browser.cjs
node tests/manual/status_50x_browser.cjs
node tests/manual/disabled_help_browser.cjs
```

The layout runner follows real destination/task/stage controls at seven
viewport widths from 320 to 1280 px, including selected-site and no-site
states, keyboard focus, mixed label/input/button alignment, local editor
feedback, loading states, contrast, and the contained source-diff surface. The 0.1.103 composition checks cover compact website context, desktop first action, checkbox text-column geometry, conditional HTTPS warning and global-scope selector, exact Activity evidence disclosure, a single Browse websites action, typed unsupported Guard recovery guidance, and a named keyboard-scrollable offline preview.
The Issue #138 regression extends the same walk with actual vertical text
containment and inter-item gap measurements for every native checkbox,
including expanded advanced details and valid mocked PHP Prepare/Recovery
responses with approval toggled (no Apply or Restore dispatched). It detects
the 0.1.106 wrapped Cache Clear overlap even when the nominal flex gap
remains correct. Vertical content must retain its intrinsic height.
`tests/manual/control_alignment_browser.cjs` is the same layout entrypoint
for the documented form-row contract. The 50x runner tests the real DOM's
preflight/approval/Apply request contract and invalidation paths. All native
responses in these runners are explicitly mocked; the fixture intercepts
every network request. They are not installed-native, live HTTP/reload, or
human usability evidence.

## Native authenticated Browser QA runbook (aaPanel 8.0.7)

This is the **working, actually exercised** login path for the isolated
native QA guest, not a general aaPanel login contract. The current guest,
protected credential reference, source/installed versions and full test
receipts are maintained in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7045862216).
If the target, aaPanel version or login template changes, inspect its actual
form and post-login DOM instead of blindly reusing these selectors.

### Recover target and credential metadata (no secret access)

1. On the **AI Test Server**, recover the existing `ach-aapanel-qa` guest
   `aac-native-qa-20261118` with `managed_environment.inspect` and check its
   current native UUID/status. Check the existing **aaPanel** credential with
   `service_access.inspect`; its host, project, guest and guest UUID must match,
   and its status must be `ready` and not expired. Get the opaque
   `credential_ref` from the live protected service metadata / Issue #21;
   do not export its value, invent a replacement login or reveal passwords.
2. Verify the current registered aaPanel form origin. For the tested guest it
   was `https://aapanelai.gotohell.top/manage`, corresponding to its actual
   `data/admin_path.pl`. This is a **test-only reverse-proxy origin**, not a
   Production endpoint. Use the actual registered origin, not `localhost`,
   the raw backend port or a different QA hostname.
3. Check `browser_status` for an available isolated Browser slot. Use an
   **isolated session** on the same Test Server, not a shared profile or a
   separate unrelated Browser tool. The demonstrated Browser workspace was
   `/srv/ai-workspace`. A new Master must recheck that workspace exists.

### Protected login: exact verified selectors and success criterion

Use the managed Browser-session tools so the protected credential is consumed
by the authorized adapter and never enters a script, a log or the response:

```js
// Tool calls within functions.exec on the same AI Test Server.
// Inspect guest and service-access metadata FIRST, as above.
const workspace = "/srv/ai-workspace";
const formUrl = "https://aapanelai.gotohell.top/manage";
const credentialRef = "<existing guest-bound protected credential ref>";
const opened = await tools.mcp__AI_Test_Server__browser_session_open({
  workspace, profile_mode: "isolated"
});
const session_id = opened.session_id;
try {
  await tools.mcp__AI_Test_Server__browser_session_flow({
    workspace, session_id, steps: [{ action: "goto", url: formUrl }]
  });
  const login = await tools.mcp__AI_Test_Server__browser_session_credential_login({
    workspace, session_id, credential_ref: credentialRef,
    username_selector: "#username",
    secret_selector: "#password",
    submit_selector: ".login_btn",
    success_selector: "#app"
  });
  if (login.status !== "authenticated") throw new Error("Login not confirmed");
  // Continue REAL plugin UI checks through browser_session_script / flow
  // using this SAME authenticated session; never export cookies or tokens.
} finally {
  await tools.mcp__AI_Test_Server__browser_session_close({ workspace, session_id });
}
```

**Critical correction:** The installed aaPanel 8.0.7 **new** panel uses
`BTPanel/templates/default/index_new.html` with the actual post-login root
`#app`. The older `index.html` has `.main-content`; using that legacy element
as `success_selector` yielded **`credential_login_not_confirmed` even when
login succeeded**. The official guest login Activity recorded a successful
administrator login during one such false-negative attempt. The real frontend
sets a session-scoped `/apsess_.../` route after login; do **not** paste its
value, use its dynamic suffix as a tool argument, record it in logs or require
a static post-login URL. The verified `success_selector: "#app"` produced
`status: "authenticated"`. A generic `success_url` root prefix is not a
replacement for an actual post-login-only DOM criterion.

If this check does not confirm Login, **do not infer a bad password or an
identity mismatch from the helper outcome alone**. Check the response code,
the exact guest/credential binding, current login-page DOM, whether a
challenge/MFA is present, protected aaPanel Activity and reverse-proxy
routing. If the adapter is rejected *before* a login result, retain its
request/error code and verify its declared call schema, guest/credential UUID
binding, isolated session ownership, actual form origin and selectors before
classifying it as a target-wide access block. A single rejected call does
not prove that the account, runbook or whole Browser capability is unusable.
Correct a concrete invocation or prerequisite error and retry through the
same protected adapter; do not bypass an actual platform-policy denial.
A `browser_session_script` after an *unverified* credential-login
attempt may itself be rejected; close that isolated session, then use a new
pre-login diagnostic session for read-only inspection. Never bypass the
protected login adapter or reset credentials to work around a wrong selector.
Avoid unrelated `AI Server Agent` host-control-plane probes: one such root
check triggered an unnecessary `approval_required`, unrelated to the plugin.

### Verify real operator actions, not just login or package bytes

- Confirm the authenticated aaPanel app and installed plugin version through
  its real UI. Open the installed **ACh aaPanel Customizer** plugin, then use
  the semantic tab selector `getByRole('tab', {name:'Routing & Nginx'})`,
  not ambiguous `getByText('Routing & Nginx', {exact:true})` (which also
  matches the page heading). The UI's Overview can report matching
  **Python entrypoint** and UI versions; this alone does **not** certify all
  resident Python helpers or running Nginx workers.
- For **Local Hosts**: on the isolated guest, preserve the exact pre-test
  `/etc/hosts` bytes/hash, confirm a unique task-owned harmless loopback
  alias is absent, create that fixture only, then click **Refresh local
  aliases → select the exact hostname → Remove selected hostname** in the
  authenticated plugin. The real button is the authorization; no extra
  checkbox is required. Verify the chosen alias disappears, unrelated
  aliases remain, and `/etc/hosts` is byte-for-byte equal to its original
  contents. Verify **Activity & Logs** has the matching
  `websites / remove_hosts_alias` event and an Operation ID; run actual
  Nginx syntax and WP/Woo/peer-site health checks. Do not delete unknown
  host mappings or use synthetic backend POST as a substitute for the click.
- The verified installed **native 0.1.69** exercise on 2026-11-20 returned
  `authenticated`, removed exactly one task-owned alias, restored the original
  Hosts SHA256, logged `Alias Removed / complete`, and passed
  `ACCEPTANCE_GUEST_PASSED`. Read-only authenticated UI checks also exercised
  13-site Website inventory/Refresh, PHP 8.1/8.5 discovery and PHP85
  site mapping, site #7 Restored Cache Recheck + stock-PHP Preview, and the
  offline **Persian 404** preview with `html lang=fa dir=rtl`.
- **Negative authorization:** a fresh unauthenticated isolated Browser POST
  to the read-only plugin endpoint served login HTML rather than privileged
  JSON. Separately, a successfully authenticated Browser request to
  `remove_hosts_alias` **without the required CSRF token** returned JSON
  `status:false`, `msg:"INIT_CSRF_ERR"` and did not alter Hosts. The normal
  plugin UI supplies its authenticated CSRF context; never simulate success
  by stripping or fabricating it. The resulting original Hosts bytes and
  service health were rechecked.

### Boundaries, recovery and handoff

These specific login/Local Hosts/CSRF checks are **complete**, not a new P0
blocker. Earlier Issue #21 comments describing `credential_guest_identity_mismatch`,
`credential_login_not_confirmed`, or missing real Browser acceptance are
**historical** and have been superseded for this installed 0.1.69 QA guest.
`dom_too_large` from a broad Browser snapshot is not an auth failure; use
scoped selectors. A failed login attempt can lock further inspection of
that session; explicitly close it instead of retrying uncertain writes.

The same QA login does **not** prove every Status Pages/Nginx Guard/PHP-FPM
Apply/Restore, all imported helpers, other aaPanel versions, public Release
or Production deployment. Keep Issue #21 open for its *remaining specific*
acceptance matrix and Issue #10 open for the unknown-host HTTPS/443
TLS/SNI decision. The protected guest retains native source/backup and
Browser/CSRF test evidence under `/root/achqa/`; do not purge recovery files
for convenience. The tested disposable sessions were all explicitly closed.

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
The earlier automatic post-terminal Hosts cleanup requirement was superseded
by the Owner's 2026-11-20 decision: offer administrator-click removal of a
selected hostname found in the current local Hosts file after successful or
failed WP setup, including when aaPanel has no site record. No unattended
Hosts deletion is required; the existing failed-install witness remains
observation-only. Native PHP-FPM repair is available only by separate opt-in after a saved
reviewed policy. Installed, authenticated and Production acceptance remain
separate; inspect the current scope in Issue #21.

## Selected-site Nginx sensitive-path guard

The full primary administrator may choose a **native website** in Routing &
Nginx and review a fixed, opt-in, per-site protective source. Customizer reads
the selected ID, domain bindings and current Document Root from aaPanel itself,
then verifies the corresponding generated VHost and the **exclusive server-scoped
native `extension/<site>/*.conf` include graph**; `/www/wwwroot` is never a
site-root assumption. The supported implementation targets the source-matched
aaPanel 8.0.7 Nginx/HTTP-80 layout; no blanket Nginx-version claim.

**Protection semantics:** After a fresh Preview and explicit one-site **Enable** action,
an immutable policy fragment is atomically installed into that site's existing
Nginx extension directory, validated with `nginx -t` and applied with a
shared-service reload. Four fixed, server-rewrite `if ($uri ~* ...)` +
`return 403` conditions block nested sensitive dotfiles (including
`.env`, `.htaccess`, `.user.ini`), accesses below common backup directory
names, PHP/PHTML/PHAR requests below common uploads/media/tmp directories,
and common **website-local files** such as `wp-content/debug.log`,
`error_log`, `backup.sql`, `*.sql.gz` and `wp-config.php.bak`.
Optional Nginx XML-RPC adds one fixed rule in the same policy. The
pre-stable candidate uses only `site-sensitive-files-v1` or
`site-sensitive-files-xmlrpc-v1`; obsolete QA rulesets have no runtime
adapters. These **server rewrite-phase** returns run before Nginx Location selection:
native `location ^~ /wp-content/uploads/` cannot silently bypass the filter.
Safe `if` usage is limited to static server-scope **return-only** directives;
no rewrite or application PHP is executed. The response includes a
per-generation proof in a short body on matched requests (not in benign
response headers); exact HTTP/80 403+proof is observed on fourteen bounded
paths (fifteen with XML-RPC) over three consecutive fresh request batches.
This verifies *those* paths,
not arbitrary path aliases or origin HTTPS/cached edge behavior.

**Exceptions and scope:** No restriction is added to legitimate `.well-known`
ACME/OAuth paths, the site homepage, ordinary public static downloads, or other
sites. Default Nginx already prevents directory listing where `autoindex`
is off: a directory without an index returned HTTP 403 on the retained
aaPanel VM. Customizer does **not** add another autoindex rule or override
foreign `location` declarations that explicitly enable it. This new Guard
does reject raw SQL database dumps, but deliberately does **not** block all
ZIP archives, ordinary downloads or public static files. It is not a
replacement for Fail2ban or complete protection for every renamed backup,
custom upload directory or alternative web server.
A site with unsupported VHost/include, symlinked Document Root,
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
A native site ID/key or Document Root change, foreign/tampered guard,
invalid extension ownership/include, or an unresolved source conflict still
blocks writes with `Needs Review`. A native domain/VHost/extension change
always invalidates old **Apply** approval: the operator must Recheck. If the
*same native site and root* still have an exclusively imported, byte-exact
Customizer guard fragment (or its single exact retained file from an
interrupted Restore), Recheck reports **Recovery Required**, including
`native_source_drift` for a previously `applied` journal. This is **not**
a claim that the new native source or all aliases have been verified as
protected. After reviewing the site, the administrator may explicitly
Restore that one Recovery ID without undoing the foreign domain/VHost
change. Restore requires the **exact Nginx source SHA returned by the last
successful Recheck**; another VHost or sibling-extension edit rejects stale
approval before retiring the owned file or reloading shared Nginx. Even without
VHost drift, an `applied` journal with only its single byte-exact retained
file reports **Recovery Required** (`interrupted_restore`) and enables manual
Restore. A simultaneous live/retained pair, altered or missing owned file
must never be reported healthy Applied. Restore rechecks both managed
filenames immediately before retirement, verifies exact moved bytes and
file identity after no-clobber rename, and revalidates both the retained rule
and complete native source **after the final Nginx syntax check and before
shared reload**. Only byte-exact, journal-owned content with the original
moved inode may be rolled back to the live include path using no-clobber rename.
Altered content stays in the retained path for explicit manual inspection;
the unchanged journal and Recovery ID remain available. Late source drift
leaves the exact retained rule recoverable without a reload. After reload, nonce absence, source stability
and retained ownership are verified before acknowledging Restored. External
aaPanel writers do not share this plugin lock: the checks narrow, but cannot
atomically eliminate, the last check-to-reload race. Fresh **Preview -> Apply**
is a separate operator choice. No watcher, background repair or automatic
reapplication is added.

Other files, users and site configurations are not modified.
After uninstall, saved policy/recovery may still be active: reinstall and
use guarded Restore rather than delete Nginx files manually.

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

**Legacy advanced selected-site path (0.1.52):** The above site-bound
manual removal/recovery flow exists for its earlier saved recovery state.
It does not establish the writer, prove remote DNS/Gateway health or prevent
repeat insertion. The **current, simpler primary-admin workflow** reads the
actual origin Hosts file and removes one chosen hostname with a single click
**without selecting a site**; it passed installed 0.1.69 native Browser
acceptance. See [the one-click flow below](#one-click-local-hosts-alias-removal-merged-source-verified-on-native-0169-qa).
The later Owner decision **cancelled unattended Hosts cleanup**, including
the older proposed P0 automatic correction; the independent optional witness
below remains observation only. Earlier v0.1.52/v0.1.60 evidence is historical,
not the current QA or public-release status. If a stale Python helper blocks
inspection after upgrade, follow the [controlled worker recovery
flow](aapanel-upgrade-recovery.md), not a blind server restart.

## Optional WordPress Toolkit failed-install witness (observation only)

**Not an active Hosts-cleanup task.** The Owner cancelled unattended
`/etc/hosts` deletion. The current primary-admin workflow is
[one-click local Hosts alias removal](#one-click-local-hosts-alias-removal-merged-source-verified-on-native-0169-qa),
including aliases from successful or failed WordPress setup and names
without a surviving native site record. Do **not** propose recreating the
former auto-cleanup implementation from historical QA.

The optional `Routing & Nginx → Native WordPress failed-install witness`
is a source-pinned aaPanel 8.0.7 observer. A separately enabled plugin-owned
systemd path/timer/service correlates a genuinely active pre-terminal native
WordPress setup with its terminal failure and an exact newly appended
loopback alias. It emits `wp_terminal_manual_review` with the full canonical
hostname and stable Operation ID. **The witness never edits Hosts or shared
PHP-FPM.** Unknown native source, file drift, missed start, active native
locks, stale resident helper or ambiguous identity yield a truthful
refusal/Needs Review; installing or upgrading the native plugin does not
enable this observer.

**Recoverability:** Private root-owned `*.manual-review.json` records,
atomic no-clobber publication, fsync and delivery receipts keep the
manual-review event visible through Activity failure, restart or log
rotation without replaying a Hosts write. The current read-only witness
can Recheck a genuinely active native setup and clear its temporary baseline
after a verified terminal event. There is **no old automatic-cleanup journal
adapter or legacy Hosts Restore**. Actual one-click Local Hosts removal
is a separate current capability with its own current Recovery ID.

**If a canonical evidence record is malformed:** Stop/disable the witness
through its supported controls, inspect the exact Operation ID and original
native task/locks, and under separately authorized root maintenance preserve
a byte-identical protected copy before moving **only that record** to a
private non-overwriting quarantine path. Reinspect first; never delete
another operation's report, the original forensic copy or another
current-operation report. The UI distinguishes policy Enabled from watcher Ready and
provides Emergency Disable independently from stale non-emergency helpers.

## Operator choice and capability-driven inventories

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
The version-bound installed UI acceptance and remaining runtime coverage
are documented in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21);
these operator choices do not certify every adapter or authorize Production.

A second cross-layer limit audit additionally removes stale frontend
ceilings on large Hosts/VHost/Cache peer results, the 32-installation/128-root
PHP inventory limits, artificial Linux process/FD count stops, the 32-profile
Monitor-only PHP intent cap, the 32-fragment Nginx/PHP source reader caps,
and obsolete WordPress historical repair counters. Inspection
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
Exact review and historical installed acceptance are recoverable through
PR #103 and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
Release publication and Production rollout are different effects.

## Native Nginx writer source completeness

Before v0.1.64, two existing *write* workflows — selected-site
sensitive-path protection and Status Pages extension Apply/Restore — rejected
otherwise valid native inventories above former fixed counts of 24 site domain
bindings, 128 native VHosts, 32 peer extension fragments or 128 included
files. The Status Pages parked-VHost scan separately stopped at 128 entries.
Merged v0.1.64 (PR #104) removed these aggregate collection-count ceilings
and streams complete native peer/include-graph and parked-VHost enumeration,
instead of accumulating whole-directory candidate lists or imposing a
separate aggregate source-byte ceiling. These are merged source capabilities,
not a claim that every installed site topology has passed real Nginx QA.

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
and no changes to unrelated peer bytes. Broader installed site-topology acceptance remains a separate
requirement; exact-HEAD independent review and Owner-authorized Merge
were completed in PR #104. Installed native 0.1.69 and real Cache/Hosts QA
do not by themselves certify this module on every Nginx source graph.

## One-click local Hosts alias removal

The origin's current `/etc/hosts` is the source of truth, including after
successful WordPress setup and when a failed setup left no aaPanel site record.
Open **Routing & Nginx**: the new Local Hosts section loads the non-system
loopback hostnames automatically, and **Refresh local aliases** can recheck
after an installation. Select the unwanted name and choose **Remove selected
hostname**. The click itself is approval: there is no second checkbox, native
website selector, status gate, WP watcher or automatic cleanup path.

The action reads the latest local Hosts bytes at click time and removes
only the chosen exact hostname's loopback tokens. Other addresses, names,
comments and unrelated malformed lines remain untouched, including CR-only
line endings. Removing the last mapping may leave an empty Hosts file;
subsequent inspection reports `No Aliases`, and a repeat click reports
`Already Absent`. A basic
descriptor-relative source/identity check immediately before atomic replace
detects most external edits; a simultaneously writing uncoordinated OS
process is **not** covered by a universal transaction. If the alias is
already absent, the action reports that state and the UI refreshes. Source
writes remain full-primary-admin-only. The currently supported advanced selected-site Hosts Recovery remains
available for exact operations created through that active manual workflow.
The retired pre-Stable automatic WordPress Hosts cleanup Restore is **not**
available or supported. No new cleanup journal, daemon, watcher or backup
subsystem is created by one-click removal.

Source-level regressions cover successful and failed/deleted-site names,
multiple mappings, preservation of peer aliases, invalid/non-UTF-8
unrelated lines, symlink refusal, external change detection and the
authenticated UI endpoint. **Native installed aaPanel 8.0.7 / plugin 0.1.69**
primary-admin one-click deletion, Activity and original Hosts byte preservation
then passed with a real protected Browser session ([#21 receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7045862216)).
Other versions and Production delivery remain separate gates.

## Native automatic PHP-FPM repair (merged implementation and historical QA)

The original merged 0.1.62 implementation fixed the systemd worker's missing
root-owned aaPanel Python import roots. Its existing path-triggered worker
now rechecks verified native install progress in a bounded 20-second window
(200 ms interval) so the native optimizer cannot as easily outrun the
initial witness. The existing timer remains the longer-install fallback.
There is no new daemon, native source patch, or unattended Hosts edit.

**Verified native-writer source variants (2026-11-21 candidate):** A fresh
official aaPanel 8.0.7 installation on Debian 13 provides different
`class_v2/one_key_wp_v2.py` and `class_v2/panel_site_v2.py` hashes than the
earlier tested 8.0.7 guest. A whole-module AST comparison found unchanged
WordPress creation, deployment, first-time PHP optimization and native
`setFpmConfig` paths. The actual differences affect four WordPress
cache/update helpers (including an optional installation-time FastCGI cache
path) and five site backup helpers. The separate `class/config.py` PHP-FPM
setter SHA is unchanged. The source guard accepts either **complete,
byte-exact reviewed pair**, not mismatched or unknown source combinations,
and still requires native 8.0.7. The paired-source acceptance was subsequently verified in a **fresh native
2026-11-21 QA guest** using the installed 0.1.69 ZIP, a real native WordPress
7.1.5 failure *after* the first PHP-FPM optimizer, and ordinary systemd
path/timer auto-repair. The vendor set `pm.max_spare_servers=30`, then the
resident worker returned it to saved `20` and `pm.max_requests=300`.
Recovery `52d57d972a92471592bf2126f6d1c8c4` passed exact journal/snapshot
SHA checks, and the neighboring PHP site remained healthy. A second genuine
WordPress installation completed all stages, returned HTTP 200, and caused
no extra repair. Emergency Disable and owned-unit uninstall preserved the
repaired PHP pool and recovery evidence. The root causes of earlier failed
test setup (PHP `www` traverse ACL and private test-runner `UMask`) were
corrected only in the QA guest, using the native panel's established behavior.

This is **R2 native event + subsequent success acceptance**, not R3
fault-injection/crash recovery or universal source compatibility. Inspect
`docs/evidence/aaPanel-8.0.7-2026-11-21-fpm-auto-native-r2r3.json`
and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
for exact identities, checksums, reproduction and remaining gates.

**Historical native QA provenance:** The first PHP-FPM watcher/optimizer
experiments ran on older, subsequently removed test guests. Their scoped
success/failure, worker ownership and recovery proofs remain in
[the original recorded QA](evidence/aaPanel-8.0.7-2026-11-19-fpm-auto-v062-native-systemd-qa.json)
and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
They do not require new VMs and do not certify untested writer shapes.

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

### Opt-in native PHP regeneration and protection workflow

An explicit new FPM auto Enable records the selected service's original
canonical source SHA, native RAM tier, and saved pm.max_requests before any
repair. The already installed systemd timer then handles both accepted
WordPress Toolkit terminal events and post-opt-in FPM source changes whose
four managed numeric settings match the exact verified installed aaPanel
setFpmConfig writer. Foreign source changes remain Needs Review. For
recognized regeneration, the saved desired values, shared-site mapping,
Monitor status, exact source identity, recovery journal and fresh runtime
verification must agree; failure preserves diagnostic evidence and baseline
bytes. A completed host transaction is reconciled after a worker crash without
reloading PHP again. Emergency Disable prevents new lifecycle repairs.
Only current lifecycle-bearing profiles are supported for automatic repair;
each new Enable requires fresh explicit operator intent and the current source
identity. Former pre-Stable profiles and their WordPress-only fallback are
not supported or silently upgraded.

A fresh, already-completed WP progress record does not suppress later
independent PHP-FPM regeneration. The two branches are reconciled in the
same timer invocation. A source modified by the *same* native WordPress
operation is not interpreted as an independently completed aaPanel event:
its filesystem mtime must be strictly later than the native terminal log
mtime. Both native WP LOCK and BATCH_LOCK defer the independent lifecycle
before reading the source and again at the guarded Apply verification
boundary. This avoids a premature reload during early or batched install;
the next timer wakeup retains the source and policy for reconciliation.

**Activation and repeated-writer reliability:** The saved, reviewed PHP
policy is committed *before* arming its systemd path/timer; both units must
actually become active or the newly armed authority is revoked. An imported,
resident helper that lacks the policy-first contract refuses non-emergency
Enable with a concrete stale-helper reason; Emergency Disable remains
available. The next genuine native regeneration is identified by its
opt-in epoch and last acknowledged event, not just a before/after file hash.
A completed repair is reconciled after a worker crash without another PHP
reload; systemd errors retain bounded stage and reason.

These behaviors were introduced after observed historical failure/recovery
cycles. Exact version-bound native evidence (including repeated byte-identical
writer events and post-disable re-Enable) belongs to
[Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21),
not to a rotating status narrative in this guide.

### Optional temporary IP blocking — selected website (#146)

In **Websites → Protection**, select temporary blocking with the normal
sensitive-path Guard. Choose attempts, observation-window seconds and block
seconds (defaults 6 / 120 / 600), Check readiness, then explicitly Enable.
Recheck and exact Restore use the same Guard owner and journal. To change an
active policy, Recheck, Restore and enable the new selection. No second
policy owner, daemon, logfile or firewall action exists.

Nginx server-rewrite classification uses the existing sensitive-path rules.
The optional XML-RPC rule alone does not increment a scanner counter.
A single fixed 8 MiB HTTP-context shared dictionary is declared in the
native VHost include directory when first needed. Keys are scoped to site,
policy generation and Nginx's effective binary client IP. The first hit
starts a fixed observation window; reaching the threshold establishes a
temporary block; subsequent requests on that site return HTTP 429 until
expiry. Safe allocation does not evict another active block. On exhausted
memory or recoverable Lua evaluation error, static Guard denial remains;
the temporary block may not be established. A complete Nginx restart
clears ephemeral state; ordinary reload preserves the shared memory.
The declaration itself contains no site identity and may remain idle.
Restore removes the selected rule, without touching a peer or a system
Fail2ban jail. Local loopback verification is not counted.

No aaPanel access log is trusted for firewall authority. Validate actual
effective client-IP configuration behind a CDN or reverse proxy; an
unresolved shared proxy IP can affect other visitors to that same site.
HTTP/80 local source/proof is not blanket proof of all HTTPS/CDN delivery.
Native Lua syntax/capability and current exact source are checked before
activation; if unavailable, select ordinary static protection instead.
There is no old scanner adapter or automatic cleanup of historical
system data. Verify no old owned active scanner jail before upgrading;
retire an actual existing old jail using its owning release first if
necessary. Existing unrelated service jails and Recovery history stay intact.

### Automatic PHP-FPM repair — guarded control-flow invariants

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

Source/CI and installed-native acceptance have different identities.
Consult [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
for which source and mounted aaPanel workflow were actually verified.
This feature is not unattended Hosts cleanup or a universal repair path
for unrelated aaPanel/PHP writers.

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

Server-scoped Nginx sensitive-path Guard and Status Pages extension delivery
accept a native site's exact registered root or an existing canonical served
subdirectory (for example the native public/run directory). The selected
server and native domain binding, exclusive extension include graph,
registered-site identity, source fingerprint, Nginx syntax and live worker
proof remain mandatory. No per-site exception, root rewrite or customer
file is needed. The nested-root source fingerprint includes the registered
parent, while existing exact-root recovery fingerprints remain unchanged.

Extension 404 preflight observes the real local HTTP 404 body and binds
Apply/Restore to that baseline. If the actual HTTP body already matches the
render, no content Apply is needed; matching bytes do not establish extension
ownership or a saved recovery. It does **not** require an existing
`404.html` or adopt the parent directory's HTML. For 502/50x the
source-only baseline is the actual served directory's `502.html`
(including verified absence). Both source preflight and unmanaged Recheck use
that same baseline, never the body of an unrelated ordinary request or the
proposed render; uninspectable source is refused. Apply still proves the real generated error
statuses and operation nonce. A physical site-file replacement retains its
separate exact-root/existing-file/route ownership and recoverable backup
requirements. Missing or unserved files are not silently created/adopted.
The generic disk comparison reports registered-site files, not a claim that
the configured served root is identical. The stopped-site writer and
unknown-SNI TLS retain their separate native lifecycle/listener contracts;
this is not an expanded Stop/Start or TLS policy.


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
| **Global unknown Host HTTP/80** | Independent Nginx-owned default_server on the native wildcard HTTP/80 listener families (IPv4-only, IPv6-only or dual-stack), real HTTP 404 on configured families, checked reload and Restore. Absent families are not probed or enabled. Address-specific binds and IPv6 dual-mode sockets are not widened. Never claim HTTPS/443 support. |

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

## WordPress one-time Nginx Helper connection (merged PRs #113 and #114)

After installing the official **Nginx Helper** and separate **ACh aaPanel
Bridge** WordPress plugin files, the selected site's native Customizer
**Connect WordPress Cache (once)** action activates both installed plugins
and coordinates the site's isolated Nginx Cache zone/physical directory,
PHP .user.ini access, RT_WP_NGINX_HELPER_CACHE_PATH in wp-config.php,
Nginx Helper unlink_files options, and generation-bound Bridge manifest.
This is **one click per WordPress site**, not an unattended watcher or
a recurring per-post/per-update manual configuration. The original Nginx
Helper frontend **Purge Current Page** and admin **Purge All** stay in use.

After a verified Connected response the UI disables unnecessary repeat
Connect; Check WordPress connection and the applicable Disconnect remain
available. Not Connected disables redundant Disconnect; Needs Review is a
read-only warning, not a failed Setup. It includes the native recovery
identity and the appropriate Recheck guidance when native Cache is partial.
Site selection, related changes and conflicting or unconfirmed recovery
observations clear the earlier connection/manifest proof. No mandatory Check
is added before a first or repair Connect; the backend still revalidates every
requested operation.

Verified Cache Clear preserves current connection evidence, including a
confirmed zero-file no-op; failed or unconfirmed Clear invalidates that
evidence. A Bridge inspection is read-only even on a first install without
a native Cache lock; an existing journal without its lock requires review.
A completed WordPress Disconnect is independent of later native Cache
generations; inspect their recovery in Apply & restore, not by repeating
Disconnect.


The native one-click also ensures the official Nginx Helper's two
administrator-role capabilities (`Nginx Helper | Config` and
`Nginx Helper | Purge cache`) are present; CLI activation has no
logged-in WordPress administrator and does not reliably grant them.
The original **stored** role entries are journaled with their exact
absent/false/true states before changes (distinct from WordPress's
`role_has_cap`-filtered effective grants). A separate WordPress PHP process
checks both stored grants and effective permissions before reporting Connected,
and independently verifies exact persisted baseline restoration before
completing Disconnect. Interrupted writes remain retryable from the saved
journal, without overwriting the original snapshot. Only current journals with a complete persisted `admin_caps_stored`
baseline are accepted. Missing, filtered-only or otherwise incomplete
journals fail before another WordPress/PHP/Cache mutation; no migration
or guessed-role fallback is implemented.
The site-user PHP connector runs as a CLI operation, not a WordPress HTTP
admin request: do not define WP_ADMIN or spoof WP_CLI, user login, or an
authenticated request. Load the official plugin APIs explicitly. Login
protection on a real site can otherwise redirect and exit during bootstrap
even with exit code zero. A failed connector reports action, actual phase,
exit status, a controlled reason or fatal type/source line, and correlation
in Activity; do not log arbitrary site output or credentials.

Native Cache and shared PHP impact inspection recognize the observed aaPanel
per-site SSL `well-known/<site>.conf` helper only at its exact server-level
include with the complete verified template and bounded trusted file identity.
The helper is part of source fingerprinting. Edited, foreign, nested, linked
or missing helpers remain unresolved, so no shared-directory purge or
unverified routing is authorized. This is source compatibility, not a claim
about all future aaPanel SSL templates.

Bridge 0.1.9 maps a valid authenticated, nonce-checked frontend
`Purge Current Page` through the same generation-bound per-URL
GET/HEAD selector for HTTP/HTTPS cache keys, including an HTTPS public
site backed by an HTTP-origin Nginx worker. Vendor Purge Entire Cache
remains its own recursion, never intercepted or broadened by Bridge.


When native aaPanel created a VHost lacking its site extension include,
the connector adds only that line immediately after the registered site
root, matching aaPanel native regeneration, after the Cache adapter proves the
exact missing-include case. Existing Cache Apply validates/reloads Nginx;
changing .user.ini reloads the selected PHP-FPM service so site worker
access takes effect. No vendor Nginx/WordPress plugin source is rewritten.
**Disconnect and restore** first disables vendor purge before returning to
a potentially shared path, then restores recorded site settings and native
Cache recovery. A root-owned site-specific journal retains incomplete work.
An interrupted Connect or Disconnect can be repeated for that exact site.
The connector accepts only the saved original and managed values when
resuming file changes, checkpoints a pending FPM reload independently from
WordPress-option and native Cache Restore, and never treats a fresh native
Cache generation as owned by the previous connection. A completed Disconnect
followed by an explicit new Connect may attach to a previously manually
Applied Cache as **not connector-owned**; subsequent Disconnect leaves that
native Cache in place. Changed source, foreign generation or unconfirmed
native recovery yields Needs Review rather than changing arbitrary files.

The standard native site extension include is retained if this one-click
operation had to add it on an initial VHost: removing that innocuous empty
include would invalidate aaPanel Cache recovery and force another manual
setup. It is **not** the active site Cache configuration. If the selected
site had an Applied native Cache **before Connect**, Disconnect retains
that original Cache; only the WordPress integration is removed.

**Current status:** The one-click workflow entered `main` through
[PR #113](https://github.com/AChWorks/ach-aapanel-customizer/pull/113).
The native **0.1.72 corrective source was merged** in
[PR #114](https://github.com/AChWorks/ach-aapanel-customizer/pull/114).
This is **not** a published Release or Production deployment, nor proof
of any newer candidate's installed/resident status; use [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) for current VM evidence.

**Installed-native QA (earlier PR #114 0.1.72 HEAD `eb875fd2932e`):** On isolated aaPanel 8.0.7 /
WordPress 7.1.5 with official Nginx Helper 2.4.1 and ACh Bridge 0.1.8,
authenticated browser actions exercised native Connect, the vendor's
**Purge Current Page** and confirmed **Purge Entire Cache**, real Gutenberg
Page/Post publish/edit, canonical HTTP MISS/HIT transitions and private
draft/authenticated bypass. Site-specific Purge All left another site's
Cache and the shared vendor Cache byte-identical. Repeat Connect, QA VM
Stop/Start, native Disconnect/Reconnect and exact source restoration were
also verified. This supersedes earlier source-only/noncanonical-alias QA
limitations **for the recorded canonical HTTP routes**, not other aliases.
See the [exact source and acceptance matrix](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7055966635)
and [QA cleanup caveat](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7055999902).
**HTTPS and real WooCommerce customer/cart/checkout/session flows were not
tested** on that HTTP-only, non-WooCommerce site. Later review-remediation source changes (the merged PR #114 HEAD)
have separate automated/real embedded PHP CLI evidence, **not a fresh
installed-native E2E run**. That earlier guest was later removed under
the Owner one-VM policy; its historical receipts remain valid only for
that tested HEAD/guest. Public Release and Production require separate Owner authorization.

## FastCGI Cache: privacy, ownership and recovery

**Force HTTPS origin verification:** The Cache readiness/Apply/Recheck/Restore
path observes a fixed local HEAD /index.php on the registered HTTP/80 Host.
If it redirects to the exact same Host and path over HTTPS (standard 443),
the probe makes one additional loopback request using the same Host and TLS
SNI with normal certificate/hostname verification. No external DNS lookup
or arbitrary Location is followed. The final managed observation still
requires the selected-site Cache marker and FastCGI status. Both the HTTP
redirect and HTTPS application status are saved and compared for an HTTPS
activation; an HTTP-only site uses its direct HTTP status. A PHP canonical
redirect may itself be a valid terminal 3xx response when the upstream
evidence is present. Force HTTPS settings, certificates and native VHost
source are unchanged. A missing/untrusted local certificate or unobserved
upstream yields a specific failure, not repeated speculative configuration
writes. This is local route evidence, not browser/CDN/TLS-edge or complete
private-session certification.

The synthetic WordPress and WooCommerce Cache diagnostics use the same
exact same-host HTTPS upgrade criterion and SNI transport, report the
actual observed protocol per request, and never accept an application
redirect as a successful 200/BYPASS private-route observation.

**Request timing:** Cache readiness, management, private-route diagnostics
and WordPress Connect/Disconnect/Inspect await the native server result
without a separate jQuery timeout. A diagnostic can require up to 18 origin
HEAD requests; a lifecycle can include up to nine worker observations after
one reload, and the WordPress connector also invokes several independently
timed PHP subprocesses. The existing 4-second diagnostic / 5-second worker
socket timeouts, nine-observation limit, PHP command and Nginx operation
timeouts remain in force. Socket timeouts are per blocking network operation,
not a promise of a fixed total wall-clock duration. The native panel transport
and normal browser/network failure handling still apply. On a transport
failure the outcome is unconfirmed: use Activity and Recheck before retrying;
a returned server failure retains its stage and recovery correlation. No
automatic configuration-write retry or additional site-response limit is
introduced.


A safe per-site Nginx Cache needs an owned, separate physical tree and key
zone, exact site/VHost/native PHP include ordering, syntax and runtime
checks. An IP/Host-partitioned key within a **shared filesystem** does
**not** make recursive deletion site-scoped. Native PHP `wpfastcgi` and
stock-handler shapes differ; inspect actual source, inherited directives,
regex precedence, original request URI and current handler before proposing
an Apply.

Preserve native response-header semantics: the recognized wpfastcgi PHP
location already defines its own headers, so its parent HSTS/Alt-Svc are
not inherited under default Nginx inheritance. Stock PHP inherits direct
server headers; copy their exact supported statements alongside Cache
markers, preserving existing Stable HSTS-only journal bytes. Reject
unknown inheritance overrides, conflicting diagnostic markers, or
stock downstream headers that affect cache privacy and are not represented
by upstream response predicates. This is not a blanket header-name
allowlist.

A foreign peer application's verified literal local FastCGI and terminal
return/redirect locations are independently scoped. Fingerprint the real
file and its recognized parameter dependencies for physical Cache
inspection; do not admit foreign Cache directives, dynamic upstreams,
unknown nested includes or arbitrary executable routing. The selected
Cache writer remains source-checked separately. Shared PHP-FPM impact
can attribute these same inspected routes when their sockets match the
site's verified pool; a real mixed-pool assignment remains unresolved.
No application-specific path or domain exception is required.

**Mixed-host regression:** `tests/manual/mixed_host_compatibility.py`
runs on the retained authorized native QA guest. It builds sanitized
IR-shaped (six WordPress, two PHP sites) and NL-shaped (one WordPress,
five PHP sites, scoped application routes) profiles, with actual native
Nginx/PHP snippets, custom roots, HSTS/Alt-Svc, SSL/QUIC, ACME source and
legacy shared Cache directives. It checks candidate source preflights,
then launches an independent loopback-only Nginx process using temporary
config/cache and actual QA PHP-FPM. It compares stock/wpfastcgi headers
and peer routes before/after generated private Cache, checks HTTP/3,
MISS/HIT, authenticated/Cookie BYPASS and private-response nonstorage.
No actual aaPanel DB, native service config or existing site is changed.
Synthetic PHP/WordPress source fixtures are not installed WordPress
admin acceptance; real native Connect/Restore and WordPress operation
evidence must be reported separately.


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


**Native private-request Cache probe:** A twice-verified native PHP source
with a direct Cache zone may be observed with four fixed origin-local HEAD scenarios
(nine for default WooCommerce routes; one additional exact HTTPS upgrade
request per scenario when necessary). The legacy native WordPress
handler is checked against `X-Cache: BYPASS From <site-host>`; an **Applied,
exact journal-owned** Customizer Cache handler (stock or wpfastcgi) instead
requires both `X-ACh-Cache: BYPASS` and `X-ACh-Cache-Site: <site-id>`.
Reject unknown/unfinished managed recovery, changed PHP/include precedence,
wrong zone/directory and foreign markers before claiming observed BYPASS.
These are response-header observations, **not authenticated-session
isolation, verified responding VHost, HTTPS edge policy, production safety or
permission to purge any cache tree**. After a positive result the selected
native source is re-audited for drift; unknown source produces Needs Review.

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

### Cache recovery after native PHP-handler changes

A fully **Restored** site-owned Cache generation is historical recovery, not
active Cache. If aaPanel subsequently switches that site's supported native
PHP handler between **stock** and **wpfastcgi** (in either direction), the old
Recheck may report **Needs Review** because its source fingerprint is pinned
to the previous handler. A new read-only **Check site-specific Cache Apply
readiness** can establish the current exact source and show a fresh-generation
proposal; the administrator must explicitly approve **Apply** before any new
Cache activation. The old operation journal, exact retained configuration
fragments and physical Cache directory identity must still match. Unsupported
source shapes, foreign fragments, replaced directory inodes or missing saved
recovery remain blocking; neither direction automatically migrates or clears
Cache files. Verify the new generation with Recheck and use its own Recovery
ID for Restore.

## Optional WordPress Bridge: operator prerequisites

[WordPress Bridge](../wordpress/ach-aapanel-bridge/README.md) is an
**independent**, manually installed WordPress plugin. Its ZIP includes a
[WordPress-format `readme.txt`](../wordpress/ach-aapanel-bridge/readme.txt),
while the linked Markdown guide is repository-only. Without an explicit
native-generated site-owned manifest it reports diagnostics but does **not**
alter Nginx Helper hooks or cache state.

1. On one verified native WordPress site complete **Cache Apply → Recheck
   Applied**, confirm physical peer separation, and explicitly click
   **Provision URL mapping** for that site. The button is the administrator's
   approval; no additional checkbox is required. **Disable Bridge mapping**
   similarly removes only that site's native-managed manifest, including a
   stale one, without requiring a current Applied Cache Recheck. The native
   backend still checks primary-admin authorization, exact site identity and
   recovery ownership where required. The root-owned, generation-bound manifest
   in `wp-content/ach-customizer-bridge/cache.php` is read-only to WordPress
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

Current native acceptance should use the fixed QA guest in [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21), not historical instructions to create a fresh guest or a cloned/snapshot VM. Preserve the other live QA sites and verify the actual installed plugin version.

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
- **Current acceptance and selected historical evidence:** [#21 current installed-native QA and remaining work](https://github.com/AChWorks/ach-aapanel-customizer/issues/21),
  earlier [release ZIP/lifecycle receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6937217273)
  and [two-customer native Woo receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6938476216),
  [#2 functional backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2),
  and historical, bounded, file-based [QA evidence](evidence/).

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
