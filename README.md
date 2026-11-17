# ACh aaPanel Customizer

A native, modular **aaPanel customization plugin** for keeping operator-approved changes to aaPanel, its modules/plugins, websites, and managed services visible, durable, and recoverable.

**Current merged source (not yet published):** Native **v0.1.49** and optional WordPress Bridge **v0.1.8**. The latter includes the independently reviewed term-only, recursive and partial-`WP_Error` corrections from [PR #91](https://github.com/AChWorks/ach-aapanel-customizer/pull/91). The most recent public [v0.1.48 development Pre-release](https://github.com/AChWorks/ach-aapanel-customizer/releases/tag/v0.1.48) still contains Native **0.1.48** and Bridge **0.1.4**; it does **not** distribute these merged-source versions. No new public Release or Production installation is implied.

**Validated first-release scope (bounded):** Native primary-admin UI and guarded Monitor/Apply/Recheck/Restore, installed PHP 8.1/8.5 supported workflows, site-scoped FastCGI Cache HIT/MISS and private WooCommerce BYPASS, exact URL Clear and native selected-site full-tree Clear, Status Pages and supervised source-drift recovery. Real aaPanel 8.0.7 installed acceptance and exact recovery evidence are recorded in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21); these tests are not universal compatibility or Production certification. Native selected-site Clear is **not** Nginx Helper's independent recursive vendor `Purge All`, which remains **OFF / not certified** for shared physical Cache roots.

**Supported optional integration:** Merged Bridge **v0.1.8** preserves generation-verified current-site GET/HEAD HTTP/HTTPS per-URL invalidation via Nginx Helper's `unlink_files`. It handles public post/homepage and first-page taxonomy archives, including actual standalone and nested term relationship changes, category-dependent previous/current permalinks and partial WordPress insertion failure. The exact merged Bridge ZIP was previously verified in installed WordPress 7.1.4 / Nginx Helper 2.4.1 [QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6932568043). This is opt-in and requires separate site-specific Helper/manifest configuration, not a blanket purge or an automatic installation.

**Not certified:** Vendor `Purge All`, shared WordPress cache roots, alternate Host aliases, query/encoded paths, author/date or paginated archive invalidation, unattended VHost reconciliation, general HTTPS/443 unknown-host Status Pages interception, and untested aaPanel/PHP/Nginx/WordPress combinations. These accepted limits remain tracked under [#2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [#17](https://github.com/AChWorks/ach-aapanel-customizer/issues/17) and [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21); unsupported paths must not be presented as safe Apply operations.

### Optional WordPress companion: Bridge v0.1.8 (merged; published v0.1.4)

The WordPress plugin is maintained in [`wordpress/ach-aapanel-bridge/`](wordpress/ach-aapanel-bridge/README.md) with its **own version and separate installable ZIP**. Native provisioning of its root-owned manifest is an explicit administrator action after a freshly verified site-owned Cache Apply/Recheck; the Bridge does not install/configure Nginx Helper, modify WordPress options, turn on vendor Purge All, or auto-install itself. Configure Helper's **site-specific** cache path and PHP-FPM `open_basedir` access without widening the shared root. Its independent `Update URI` avoids WordPress.org slug collisions but does not provide automatic updates.

For native manual installation/update and tested recovery boundaries, follow [aaPanel native integration](docs/aapanel-integration.md) and [upgrade/rollback instructions](docs/aapanel-upgrade-recovery.md). Build Native with `scripts/build_plugin.py` and Bridge separately with `scripts/build_wordpress_bridge.py`; check each ZIP SHA256 before using the aaPanel **App Store → Third-party Plugins → Import Plug-ins** or WordPress **Plugins → Add New → Upload Plugin** path on an authorized nonproduction/Production target. A source commit, ZIP or green CI alone is not a public Release or a target deployment.

**Integrated v0.1.5 source (PR #85):** Published, viewable posts now have their public permalink captured before permanent deletion; the same current-generation, site-owned per-URL invalidation runs only after successful deletion. The exact delta received independent `COMPLETE / APPROVE`, and source tests plus real WordPress 7.1.4 deletion-hook QA passed ([Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6913445128)). **Full installed v0.1.5 deletion-to-Nginx-file-unlink QA subsequently PASSED in isolated aaPanel 8.0.7/WordPress 7.1.4** ([exact success, abort and recovery evidence](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6914874554)); the **v0.1.6 GET/HEAD source subsequently passed live installed QA and independent review** ([QA evidence](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6915689796), [PR #87](https://github.com/AChWorks/ach-aapanel-customizer/pull/87)). Native v0.1.48, the published Bridge v0.1.4, vendor Purge All and Production are unchanged.

### v0.1.48 merged: opt-in generation-aware URL invalidation (Issue #2)

The [exact-reviewed source](https://github.com/AChWorks/ach-aapanel-customizer/pull/82) passed 788 Python, 322 JavaScript, 35 Chromium layout tests and [exact-head CI](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/43825854052). Live nonproduction WordPress/Gutenberg QA produced HTTP and HTTPS `MISS → HIT` with updated content while the peer site's Cache stayed `HIT`; all test-specific WordPress configuration and plugins were subsequently restored. Native v0.1.48 remains on the isolated QA guest for follow-up read-only inspection. Review found no blocker; the suggested additional deterministic `afterPostSaved` behavioral tests remain optional future coverage.

**Later live QA supersedes the old read-only v0.1.46 snapshot below:** the exact merged native ZIP was installed and fully checked, real two-customer WooCommerce HTTP/HTTPS cache isolation passed, and the selected QA site was subsequently Restored. See the [final Issue #21 acceptance receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6900380336).

### v0.1.46 merged: historical restored Cache re-Apply (Issues #2/#21)

The source-only package now permits an **explicitly reapproved new Cache generation**
when an older, fully **Restored** schema-2 recovery journal belongs to the same
native site ID but predates an aaPanel site-key rename or a verified
stock → wpfastcgi PHP-handler change **on the same PHP version**.
This is not a general journal-migration, orphan-recovery or ownership
override. Before readiness is offered, the adapter regenerates the **old**
policy and checks its proposal hash, byte-identical retired global/extension
fragments under the current native site's verified Extension directory, the
saved Cache directory's physical identity, and the fresh native site/source
preflight. Only the supported stock→wpfastcgi handler direction can change.
Legacy unpinned, prepared/applied, physically drifted, conflicting,
nonmatching or already-reused generations still fail closed. Manual Apply
requires fresh source/proposal/generation approval, archives the **original**
Restored journal, and uses a distinct new key generation; no old Cache
objects are deleted. Preview explicitly warns that matching ownership
evidence does **not** prove application continuity.

**Historical pre-PR78 read-only QA snapshot (superseded by the later installed acceptance above):** On isolated aaPanel
8.0.7, current Site #10 is qa21-woocommerce-native.digikalashop.top,
while its intact **Restored** journal records
qa21-woocommerce-native.test and the former stock PHP85 adapter.
An isolated, SHA-matched v0.1.46 source preview verified the real Retained
fragments/directory, observed source WORDPRESS with zero unresolved peer
sites and returned Ready for Review. Its journal bytes remained unchanged;
the installed plugin was then v0.1.44. **This earlier read-only snapshot did not include a new Apply or native browser acceptance.** The subsequent real native QA did; it still does not certify site-owned Purge All, public Release or Production deployment. Site #17 remains
applied under its prior recovery ID and was never adopted/restored/cleaned.
See Issues [#2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2)
and [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
for live QA and independent-review gates. See the
[read-only v0.1.46 native QA evidence](docs/evidence/aaPanel-8.0.7-2026-11-15-restored-site-key-v046.json).

### Native WooCommerce A/B acceptance runner: wpfastcgi source parity (Issues #2/#21)

The **nonproduction-only** real-customer QA runner
[`scripts/qa_woocommerce_native_cache_runtime.py`](scripts/qa_woocommerce_native_cache_runtime.py)
now reads the **current Applied schema-2 journal** to select the exact previously
approved `stock` or `wpfastcgi` PHP handler. Its pre-account checks verify
the saved generation/proposal, site Cache directory identity, native
Cache-manager ownership and read-only file-layout rules (including no-follow
ancestors, permissions and mount checks), active native handler/include ordering,
actual required PHP parameter sources, optional native rewrite content,
managed fragments and Nginx syntax. It repeats the complete source/ownership
snapshot immediately before account creation, after any HTTPS preflight.
Changed or Restored/unapproved sources reject **before** customer creation. The runner
still creates only two uniquely tagged QA customers, requires actual
logged-in account/cart/checkout/Store API isolation and verifies exact
cleanup/recovery; it never performs Cache Apply, Nginx reload or Restore.
Regression tests cover both handlers and rejected drift/identity paths.
A [real native read-only handler preflight](docs/evidence/aaPanel-8.0.7-2026-11-15-native-woo-qa-runner-preflight.json)
independently verified Site #17 Applied wpfastcgi and Site #10 Restored refusal
without altering either site's journal or VHost.

**No new native customer/session acceptance is claimed by this runner change.**
The preserved real QA Site #10 is still in its *older Restored* generation;
it must first pass a separate fresh, explicitly authorized native Cache
Apply → Recheck and source/identity verification before this runner can
exercise the actual WooCommerce store. Site #17 remains Applied and is
a synthetic PHP81 fixture, **not** a WordPress store. Follow the
[exact QA preconditions](docs/aapanel-integration.md#native-woocommerce-ab-qa-runner-current-handlers-issues-221)
and Issue #21; no production/release action is implied.

### v0.1.45 merged: trust managed WordPress source-audit precedence (Issues #2/#21)

The read-only FastCGI Cache source observation now detects an active Nginx
Regex location inserted **before** the journal-owned WordPress Cache extension,
including `location ~` and `location ~*`. Such source drift must report
`Needs Review`, not confidently attribute the current PHP Cache to
`ACHFC_<site-id>`. This aligns the source-only diagnostic with the existing
stronger guarded Apply/Restore/Clear ownership checks; it does not change
Cache keys, mutation authorization, Nginx routing, any purge operation or
supported PHP versions. The accepted, unchanged source and inert comments
retain their former behavior.

**Bounded native PHP 8.1 QA:** A separately registered generic PHP fixture
(site #17, `qa-wp81cache-20261114.test`) exercised the real native PHP 8.1
`-wpfastcgi.conf` routing using a synthetic `index.php` (not a WordPress
installation). The exact v0.1.45 source was unpacked for backend tests;
the installed native plugin remains v0.1.44. A guarded Preview, explicit
QA-backend Apply and Recheck observed `ACHFC_17`, public GET `MISS → HIT`,
Authorization/Cookie/query `BYPASS`, and manual exact `/` URL Clear of
one object followed by `MISS → HIT`. Editing only the test site's VHost
source to add an earlier competing `location ~` or `location ~*` made
both standalone Audit and guarded Recheck report `Needs Review`; the VHost
was byte-restored and Recheck confirmed `Applied`. Neighboring WP/Woo
VHost, journals, shared Cache source and main Nginx source SHA values matched
their baselines, and `nginx -t` passed.

**QA retention/limitations:** Site #17 has no WordPress database (native
optional database creation failed and no database was created), so this
test does not certify a real logged-in PHP 8.1 WordPress installation,
WooCommerce private sessions or Nginx Helper. The isolated Browser primary
admin login was not confirmed. A QA Restore invocation was blocked by tool
safety checks before mutation: **site #17 remains intentionally Applied**
with recovery ID `4a1d0b84669b42a5a16d8e05943ac3d6` until an authorized
native Restore/Recheck can finish it. Do not remove journal, cache snippets
or the retained directory manually. Exact evidence and source integrity
are in the [v0.1.45 QA manifest](docs/evidence/aaPanel-8.0.7-2026-11-14-php81-wpfastcgi-audit-v045.json).
No public Release or Production mutation was performed.

### v0.1.44 merged: source-matched native WordPress `wpfastcgi` Cache (Issues #2/#21)

The guarded, opt-in site-owned Cache Apply/Recheck/Restore and exact-URL Clear
now support the **exact verified aaPanel 8.0.7 Nginx `enable-php-81/85-wpfastcgi.conf`**
source, not just the previously accepted stock-PHP handler. The native PHP
snippet must match a fixed source grammar including its `$skip_cache` rules,
WordPress `try_files $uri $uri/ /index.php?$args`, versioned PHP socket,
`fastcgi.conf`, response/security headers, legacy shared `WORDPRESS` Cache
and loopback `/purge` directive. Unknown edits or alternate PHP versions
remain `Needs Review`. Both native PHP 8.1 and 8.5 source shapes were
inspected in QA; live requests exercised PHP 8.5.

The managed per-site Extension include runs **before** the native PHP snippet
and supplies a source-bound first-matching PHP regex location. It retains
native WordPress routing and literal PHP-level security response headers,
including its HSTS directive; the native server HSTS is not incorrectly
copied into the WP PHP location. The original native snippet and `/purge`
remain in place. The selected site's effective Cache is physically isolated
by zone `ACHFC_<site-id>`, its own directory and per-Apply generation.
The ownership-aware source audit recognizes precedence only for the verified
journal-owned extension. Existing stock-PHP fragment digests and legacy
recovery records are unchanged, and failed source checks preserve the
`Needs Review`/recovery workflow.

**Bounded native QA:** An isolated aaPanel 8.0.7 WordPress PHP 8.5 site
(#9) completed authenticated primary-admin Preview, explicitly approved
Apply → Recheck Applied → exact `/` Clear (2 current-generation files)
→ Recheck → Restore → Recheck Restored. HTTP/80 and HTTPS/443 public GET
`MISS → HIT`, synthetic invalid Authorization and Cookie requests, and
`/wp-json/`, `/cart/`, `/checkout/` and query requests were `BYPASS`.
The legacy WooCommerce peer (#10) remained on its original shared Cache;
all five files in the shared `WORDPRESS` Cache retained their SHA256 through
the exact-URL Clear. Original VHost, top-level shared Cache and main Nginx
sources matched their pre-Apply hashes after Restore. QA HTTPS skipped
test-certificate trust verification. Synthetic requests are *not* real
authenticated WooCommerce session/cart/checkout/order/payment proof. A
second native WooCommerce site (#10) refused Preview due to a historical
restored journal under an older site identity; this recovery boundary was
preserved, not silently bypassed.

Nginx Helper 2.4.1 file presence does not prove runtime activation or
generation-aware automatic invalidation. Automatic `unlink_files`,
the old shared `WORDPRESS` cache, legacy `/purge`, `get_request`,
site-owned `Purge All`, real WooCommerce private-session testing, and
broad aaPanel VHost regeneration remain **outside this v0.1.44 development integration**.
Generic Purge All remains OFF. The exact native-installed v0.1.44
55-member ZIP SHA256 is
`d5471444dc5fa8359061186d7681d6efb34583d4506106d548729562906f9def`;
the [structured native acceptance](docs/evidence/aaPanel-8.0.7-2026-11-14-native-wpfastcgi-cache-v044.json)
records the selected site, restored recovery ID, source hashes, shared Cache
integrity and bounded limitations. An independent read-only review later
found those five historical shared Cache object paths absent and could not
identify why; SHA preservation was verified **at the time of the URL Clear**,
not again at review time. This does not establish that URL Clear removed them.

v0.1.44 received `COMPLETE / APPROVE` independent review with no blocking
findings and one optional read-only audit diagnostic improvement. The Owner
authorized integration of [PR #71](https://github.com/AChWorks/ach-aapanel-customizer/pull/71)
at [main@f246438](https://github.com/AChWorks/ach-aapanel-customizer/commit/f2464389913fd5bfbf43e582a8c6d13a8affacc1);
[exact reviewed-HEAD CI](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/43581672488)
succeeded with 752 Python and 319 JavaScript tests. Public Release and
Production remain separately gated.

### v0.1.43 merged: preserve native server HSTS in isolated Cache PHP handlers (Issue #2)

aaPanel's stock PHP 8.1/8.5 VHost can have a direct server-level
`add_header Strict-Transport-Security` (including its native TLS/443
binding). The managed PHP Cache location defines its own diagnostic
`add_header` directives; on Nginx 1.28 this suppresses otherwise inherited
server headers. A bounded source-matched adapter now copies **the exact one
recognized native HSTS directive** into that managed PHP location. The
operator's preview visibly identifies whether it was preserved; the selected native source,
generated proposal and recovery journal pin the bytes and detect subsequent
changes before Apply, Recheck, Clear or Restore. Older Cache recovery records
without the optional HSTS field remain readable.

This enables a narrowly proven path for genuine HTTPS-enabled *stock PHP*
aaPanel websites without weakening response-header protections. At v0.1.43, unrecognized
security headers, multiple headers, alternate scopes, unexpected PHP/rewrite
layout and native `enable-php-*-wpfastcgi.conf` (shared `WORDPRESS` Cache,
extra PHP rewrite and purge semantics) still require **Needs Review**.
The adapter does not certify WordPress/WooCommerce privacy, Nginx Helper
`unlink_files`, generic Purge All, automatic invalidation, VHost regeneration
or Production. **Exact v0.1.43 native QA** (55/55 installed source members,
ZIP SHA256 `0e9dee31ada3d7714e73dada4c302b66124858984dc7ff3cecb76b28d778c984`)
passed an actual aaPanel 8.0.7 primary-admin Apply/Recheck/Restore/Recheck on
isolated native HTTPS/HTTP stock-PHP site #8. Both transports preserved HSTS
through `MISS -> HIT` public GETs and `BYPASS` Authorization/Cookie GETs;
post-Restore, the original VHost/global Nginx hashes matched, the temporary
PHP fixture was removed, and the original response returned. See the
[exact bounded native QA record](docs/evidence/aaPanel-8.0.7-2026-11-14-native-hsts-cache-v043.json).
This is not a TLS trust-chain certification (isolated QA used `curl -k`),
nor real WordPress/WooCommerce private-session acceptance. v0.1.43 received
`COMPLETE / APPROVE` independent review and Owner-authorized integration
([PR #69](https://github.com/AChWorks/ach-aapanel-customizer/pull/69),
[main@8cdc1ec](https://github.com/AChWorks/ach-aapanel-customizer/commit/8cdc1ec8435ac64a17d9fac2a76a3cb7b576cc2a));
[exact merge CI](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/43578787669)
succeeded. Public Release and Production remain separately gated.

### v0.1.42 merged: exact URL invalidation for an already managed site Cache (Issue #2)

The native **FastCGI Cache** panel adds a **Clear selected URL Cache** action
for an existing, freshly **Applied** and Rechecked site-owned Cache generation.
It is a narrow alternative to clearing the entire selected site's files. The
primary aaPanel administrator selects the registered website, enters **one
canonical absolute URL path** (e.g. `/news/`, not an external URL, query,
fragment or percent-encoded path), reviews the target and explicitly approves.
The backend uses the **saved site and generation**, not a browser-supplied
cache root, zone, Host, key, scheme or file path. It hashes the exact Nginx
`$scheme$request_method$host$request_uri|generation` key and checks up to
four `http`/`https` and `GET`/`HEAD` candidate cache objects. Each existing
object must have the exact native Nginx cache `KEY:` header, owned path and
file identity before it can be unlinked.

The existing full site identity, recovery journal, Nginx source and native
registered-peer **physical isolation** checks are unchanged and run before
unlinking. Missing candidates return **0 removed**; unexpected objects or
uncertain removal require Recheck and preserve the recovery identity. No Nginx
reload, shared `WORDPRESS` purge, WP/Nginx Helper hook, automatic
invalidation, PHP policy change or cache key migration occurs. Other URL
paths and Host aliases are intentionally untouched; new requests can
immediately recreate the entry. Invalid/noncanonical URLs, percent-encoded
Persian slugs and query-specific variants are not covered by the current
reference cache policy (which bypasses queries and `%` paths). The feature
is **not** a general/automatic WordPress invalidation solution, nor evidence
that native `-wpfastcgi.conf` site-owned Apply or Purge All is supported.

Source tests and exact native aaPanel 8.0.7 ZIP installation passed
(**55/55** source members, matched UI and Python entrypoint).
A source-pinned native **Applied** Cache on HTTP-only QA test site #16
passed manual exact-URL Clear (one removed, repeat zero, target MISS/HIT,
another URL and independent WordPress peer HIT), fresh Recheck and approved
Restore. The earlier copied-file-only record
[remains historical](docs/evidence/aapanel-8.0.7-2026-11-14-native-url-clear-v042.json);
the [actual native acceptance](https://github.com/AChWorks/ach-aapanel-customizer/pull/68#issuecomment-6870008305)
resolved the independent review's missing evidence. PR #68 received
`COMPLETE / APPROVE` and Owner-authorized Merge to
[`main@71612cfe`](https://github.com/AChWorks/ach-aapanel-customizer/commit/71612cfedcf4d63c91f894921e25dac0d85ac085)
with [post-merge CI success](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/43547225404).
No public Release or Production deployment was performed.

### v0.1.41 candidate: native ZIP upgrade resident-worker observation (Issues #21/#2)

After native aaPanel ZIP installation, the current HTML may load before its
Python workers re-import changed modules. **Overview** now compares the UI's
packaged source version against an import-time `get_overview` entrypoint
version. An older/missing value prompts a visible **Upgrade needs review**
notice, pointing operators to Activity/Operation ID and a **controlled,
operator-authorized** panel reload only when justified; no automatic reload
or changes to Nginx/PHP/cache, login, authorization, or update lifecycle.
A match only covers the Python entrypoint, **not** all imported helpers or
active Nginx workers. An unavailable/invalid Overview response remains
**unverified**, not falsely diagnosed as a stale worker. See the
[native upgrade recovery runbook](docs/aapanel-upgrade-recovery.md) for the
verified v0.1.40 QA incident, evidence to collect and post-reload checks.
The exact v0.1.41 ZIP passed native aaPanel matching-entrypoint QA (no stale
worker reproduced), [independent APPROVE](https://github.com/AChWorks/ach-aapanel-customizer/pull/67)
and Owner-authorized Merge to
[`main@ad842d9`](https://github.com/AChWorks/ach-aapanel-customizer/commit/ad842d9767ed2269f094f07558c6d99401f9715a);
[post-merge CI](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/43538882119)
was successful. See the [exact evidence](docs/evidence/aapanel-8.0.7-2026-11-14-native-zip-worker-v041.json).
The negative stale-worker/reload scenario remains **unverified** for v0.1.41.
No public Release or Production deployment occurred.

### v0.1.40 candidate: repeatable default WooCommerce guest-route Cache observations (Issues #21/#2)

The native **FastCGI Cache** screen now offers **Probe default WooCommerce
guest Cache routes** beside the existing WordPress diagnostic. This is a
distinct **read-only, primary-admin-only native POST/CSRF profile** bound to
the selected registered native site's ID, root, Host, domain bindings and
complete source audit. The operator cannot submit URLs, arbitrary routes,
headers, credentials or a remote address. The allowed `probe_profile`
is strictly `wordpress` (existing four requests, schema 1) or
`woocommerce_default` (schema 2): four synthetic invalid Authorization /
Cookie WordPress `HEAD` requests plus **five additional anonymous HEAD**
requests to these exact default paths:

- `/cart/`, `/checkout/`, `/my-account/`;
- `/wp-json/wc/store/v1/cart/` and `/wp-json/wc/store/v1/checkout/`.

All requests use literal `127.0.0.1:80`, the registered native Host, no
real session cookies or authentication, no response bodies, redirects,
DNS, external requests, Nginx reload, source writes or purge. Each local
request has a 4-second timeout and the native UI request has a dedicated
45-second timeout for the bounded nine-request set. A defective cache
configuration can warm an *anonymous public response* during HEAD.

`Observed BYPASS` requires **all 9** exact HTTP 200 responses with
`X-Cache: BYPASS From <registered Host>`; a successful request showing
`HIT`/`MISS`/other recognized non-BYPASS signals `Needs Review`.
Missing/unrecognized headers, redirects, missing default pages, transport
failure and unsupported/missing source never produce positive evidence.
After success, the full native site identity and source audit are rechecked;
changed evidence revokes the result. The UI validates the complete ordered
response and ignores stale results after switching sites. No approval or
state is persisted by the observation, and the existing Apply, Restore, Clear
and Purge All gates are unchanged.

**Boundary:** This matrix verifies only those **anonymous HTTP/80 HEAD
response headers**, not actual WooCommerce installation, custom/localized
cart/checkout page slugs, real authenticated/guest sessions, cookies,
POST/GET semantics, HTTPS edge, responding Nginx VHost identity (the
`From $host` header is request-derived), worker adoption, or physical
cache/purge isolation. Default WooCommerce URLs can be configured
differently; a missing/redirecting route is `Unavailable`, not an
assertion that a website is unsafe or lacks WooCommerce. Site-owned
`wpfastcgi` Apply, Nginx Helper automatic invalidation and safe
Purge All remain separate open acceptance. The previously accepted
v0.1.39 WordPress four-request behavior is preserved.

### v0.1.39 candidate: local synthetic WordPress Cache header probe (Issue #21)

The native **FastCGI Cache** screen adds `Probe local private-request Cache
headers`, a separate, bounded observation for a running registered aaPanel
8.0.7 Nginx site with one native PHP 8.1/8.5 `-wpfastcgi.conf` include and
a completed source audit. Only the full primary aaPanel administrator through
the existing POST/CSRF site-selection endpoint can invoke it. Four fixed
`HEAD` requests to literal `127.0.0.1:80` use the registered Host and
**synthetic invalid** Authorization or Cookie headers against `/` and
`/wp-json/`. The probe never accepts request URLs, user cookies, headers,
cache directories or remote hosts from the browser; it does not follow
redirects, edit Nginx, purge cache, or change WordPress. Defective Nginx
rules might cache a public response as a side effect of the HEAD request.

A positive result means only those four actual Nginx `X-Cache` responses
were HTTP 200 and `BYPASS From <selected host>`, with the site identity and
source snapshot checked before/after. `HIT`/`MISS` for a synthetic identity
request requires review; missing headers, redirects, unsupported handlers
and unavailable local HTTP never certify safety. This **is not** a real
logged-in session/anonymous Woo Cart/Checkout or HTTPS-edge proof, does not
make a shared physical Cache safe to `Purge All`, and does not unlock
`Apply`/`Restore` or change the current Nginx Helper default. Existing
native WordPress `wpfastcgi` remains unsupported by the separate
site-owned Cache Apply; its guarded `Needs Review` stays intact.

**0.1.22 guarded native stopped-site HTTP503 candidate (unreleased):** On aaPanel 8.0.7 Nginx only, select a native running website, the `stopped` EN/FA template, then explicitly Recheck and approve a site-scoped Nginx Apply. A plugin-owned inline server rewrite survives aaPanel's native SiteStop/Start include-commenting and root substitutions; it serves **actual HTTP 503 with HTML MIME** only while the site is stopped, without editing aaPanel core or the shared `/www/server/stop/index.html`. The saved root-owned original VHost and recovery journal stay outside plugin source. An explicitly approved Restore removes only the validated managed block and reloads shared Nginx; unknown or edited ownership fails to recovery review rather than overwriting an operator's changes. The rule checks the raw request Host (including verified native aliases) together with the native stopped root, so an unknown or absent Host does not accidentally inherit a selected default VHost's 503. After Nginx reload, the selected VHost's current bytes and Nginx -T source are rechecked before journal success; uncertain results retain recovery, and the UI separates prepared, observed HTTP503 and restored-route evidence. This is neither automatic enforcement nor a claim of generic 50x/HTTPS unknown-host coverage. The earlier R1 ZIP passed isolated native HTTP/HTTPS, Stop/Start and Restore testing; the final R2 proof-contract correction passed source tests and independent review, but its exact ZIP was not replayed in native aaPanel. The change was merged in PR #38; Release/Production and real authenticated Browser Phase B remain separate gates.

**0.1.23 contextual Status Pages workflow (unreleased source):** After selecting a global or native website scope and a page template, the UI presents only applicable read-only checks and guarded delivery/recovery controls. A website `404`/`502` shows its source inspection and supported site delivery modes; `50x` uses the Nginx extension only; native `stopped` has its own recovery action; global `404`/`502`/`new-site` and `unbound` expose their separate guarded operations. Other combinations are offline preview-only. Successful sandbox previews appear beside Preview, not after all recovery controls; no empty preview iframe is shown before a successful response. Changing selection still revokes stale operation evidence and does not bypass saved-recovery Recheck or explicit approvals. Native authenticated browser/lifecycle verification remains Phase B in #21.

**0.1.21 UI workflow candidate (unreleased):** Retains each native section's reading position across tab changes, uses orientation-correct keyboard navigation and limits horizontal tab scrolling to narrow layouts. Status Pages native HTTP/80 unbound operations now refresh Activity evidence after completion/uncertainty, use the Nginx-operation request timeout and warn explicitly when a write's outcome is unknown. These are UI/diagnostic changes only; no new Nginx adapter, HTTPS/443 handler or stopped-site HTTP503 behavior is claimed. The real authenticated aaPanel Browser/CSRF/lifecycle campaign remains pending Issue #21.

## 0.1.24 development: selected-site Nginx candidate and local HTTP/80 observation

The **Websites** tab adds a separate read-only check for the selected, freshly revalidated native aaPanel 8.0.7 Nginx site. A bounded, direct `nginx -T -c /www/server/nginx/conf/nginx.conf` checks the **on-disk configuration a future Nginx load would read**. A positive inclusion result requires both a verified direct aaPanel `http`-level native VHost glob in the stably read main Nginx source and a matching complete selected-file section in the dump; a header-shaped comment elsewhere in the dump cannot establish inclusion by itself. A single dumped section is not a claim that the file was included only once. It reports the candidate-configuration digest, exact selected VHost content digest and whether the selected native VHost is present. This is intentionally separate from the existing generated-VHost-vs-native-database comparison and the FastCGI source audit.

When the selected native site has a valid HTTP/80 Host binding, the check independently sends `HEAD /` to `127.0.0.1:80`, using only that registered Host. It reports the observed HTTP status or an unavailable result without redirects, public DNS or external requests. An HTTP response **does not identify which server/location supplied it** (default servers can answer for an unbound hostname). Likewise, `nginx -T` **does not confirm the configuration held by existing Nginx workers**, and this action does not inspect loaded FastCGI route/cache behavior, prove private-data isolation, or authorize any purge/reload/Apply. Unsupported or changed sources stay `Needs Review`; a primary administrator must use a valid native CSRF-protected POST and a stable selected-site snapshot. Both backend and frontend revoke stale evidence on selection changes.

This candidate is a development-only evidence step toward Issue #2, **not completed P0 policy reconciliation, actual loaded-Nginx proof or general cache safety**. Native three-site aaPanel 8.0.7/Nginx 1.28.3 read-only source smoke passed ([source-only evidence](docs/evidence/aaPanel-8.0.7-2026-11-09-nginx-candidate-observation-qa.json)), and subsequent **exact 0.1.24 installed-ZIP authenticated Browser QA passed**, as separately documented in [PR #45](https://github.com/AChWorks/ach-aapanel-customizer/pull/45) and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6742429899). PR #45 completed its independent review and merged integration; public Release and Production deployment remain separately gated.

## Unreleased 0.1.28: operator-reviewed PHP-FPM desired policy (PR #46, Issue #2)

The **PHP-FPM** tab provides **Recheck saved policy (read-only)**, **Load saved desired values** and **Save desired policy (Monitor)** for an installed PHP 8.1+ native shared `[www]` service. The operator selects a PHP version, enters the five desired `pm.*` settings, runs **Preview drift (read-only)**, explicitly acknowledges the shared-service impact, then saves against a fresh fingerprint of the actual native pool and main configuration, current Monitor revision and current policy revision. Saved policies are **version-specific plugin-owned intent**, kept in `/www/server/panel/data/ach_customizer.fpm-policy.json` outside the replaceable plugin directory. Recheck reads the **saved policy on the server**, never browser-supplied desired values; it shows current file/default Match/Drift/Needs Review and native impacted-site file mappings independently of the operator's draft form. To recover drift, Load fills the form, then the operator must **Preview → Prepare → approve → Apply** through the independently guarded PHP81/85 workflow, followed by site/service checks; other discovered versions remain Monitor only. Loading never approves a write. Backend rejects stale, conflicting, unsupported and nonprimary/temporary-admin requests; Activity contains a per-request correlation ID.

The preview compares desired settings to the **file/default state**. This does not prove the running PHP master has adopted the file values, attribute a site-creation change to aaPanel, poll automatically, schedule a reconciliation job, or authorize host writes. It does **not** change any PHP file, restart/reload PHP-FPM, alter Manual Apply/Restore gates, or implicitly enable auto-enforcement. The existing guarded PHP 8.1/8.5 shared-pool Apply remains an independent explicit workflow with its original approval and recovery contract. A direct invocation of the native WordPress optimizer's actual shared-PHP reset path, followed by saved-policy Recheck and guarded Manual Apply/Restore, has now been tested on the exact R2 installed ZIP with three healthy named QA websites. A **full WordPress provisioning request**, timed/automatic drift observation, loaded PHP master/worker configuration and broad affected-traffic proof remain separate acceptance under [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2). The following 0.1.28 details describe a historical candidate; PRs #45 and #46 have since merged into `main`. The exact current 51-member 0.1.28 ZIP (SHA256 `9fd52355730818b9c64105ed066dab7836db0287d16a440595095b647177300d`) passed bounded native PHP 8.1/8.5 **source/backend** QA for versioned saving, drift, site-file mapping, revision rejection and unchanged host files using isolated temporary state; this is **not** an authenticated App Store install, current-package UI acceptance or current-package guarded Apply/Restore replay. The historical exact 0.1.25 **R2 ZIP** passed native primary-admin aaPanel installed-ZIP testing, including the actual aaPanel WordPress optimizer reset, File Drift detection, guarded Manual Apply and byte-identical Restore. PR #46 was independently approved and merged into main at `209064a598a5063dff17e93d28fdc363af4f669f`; the separate Release/Production gate and exact-current ZIP native install/Browser acceptance remain open; see [PR #46 exact candidate and QA evidence](https://github.com/AChWorks/ach-aapanel-customizer/pull/46) and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6744217319).

## Guarded selected-site Cache file clear (merged PR #56; historical QA progression)

A newly proposed **Clear selected-site Cache files** control is separate from
Nginx Helper's shared-directory **Purge All**, which remains **OFF**. It can
only be enabled after a fresh, site-bound `Applied` Cache Recheck and a
separate confirmation. The existing primary-admin/CSRF native POST and
stable site-ID/root/domain snapshot are revalidated. The backend takes the
existing Cache mutation lock, requires the exact saved recovery ID and
schema-2 physical cache identity, repeats native source/worker verification,
then checks that no other registered website uses the selected directory or
zone. It inspects the selected site-owned physical tree, refusing unexpected
filenames, symlinks, mount aliases, hardlinks, foreign ownership, changed
inodes and non-Nginx `levels=1:2` objects **before** unlinking any verified
files. It leaves the physical directory and recovery journals intact. A
partial/uncertain clear returns a recovery ID and requires another Recheck;
there is no blind retry, Nginx reload, vendor-file edit, cache bypass, or
shared `WORDPRESS` directory mutation.

A first isolated aaPanel QA Nginx test used two scratch loopback listeners and
independent zones/directories. Both produced MISS then HIT, and removing only
the first site's object produced A=MISS and B=HIT. This scratch experiment
is separately documented in
[the original two-site record](docs/evidence/aaPanel-8.0.7-2026-11-11-two-site-cache-file-clear-qa.json).

The exact PR #56 **54-member** ZIP (SHA-256
`e1cb9d151e8ebfa54d334a9721f4c7ec8c687f525e11b8ab23264d68f9d20600`)
was subsequently imported through the actual aaPanel 8.0.7
`panelPlugin.update_zip/input_zip` path, with 54/54 installed-byte matches,
a controlled BT-Panel reload, and an authenticated primary-admin Browser test.
Native sites #6 (PHP 8.1) and #7 (PHP 8.5) each passed consented
Apply / fresh Recheck Applied and real HTTP 200 MISS -> HIT -> HIT.
A deliberately unexpected site #6 cache filename caused the new Clear to
refuse without deleting the valid generation object. On a separate fresh
Applied Recheck, an approved site #6 Clear removed three cache files
(then zero present); site #6 returned MISS while site #7 stayed HIT and
its generation-object SHA-256 remained byte-identical. Both sites then passed
separately approved Restore and Recheck Restored. All nine original native
websites remained HTTP 200; original source VHost/main/shared Nginx config
hashes were retained and `nginx -t` passed. Recovery ZIPs/snapshots were
preserved. See
[installed-package native evidence](docs/evidence/aaPanel-8.0.7-2026-11-11-pr56-native-cache-clear-qa.json).

**PR #56 physical-peer delta after independent review:** The original
review found that different canonical peer-cache paths could still be
the same physical directory through an external bind mount. The amended
Clear now obtains all registered peer zone-to-directory mappings from the
existing twice-verified source audit and checks actual device/inode
identities through component-wise no-follow directory descriptors. Direct
aliases, parent/descendant overlaps, symlinks and unresolved peer roots
cannot authorize deletion; changed peer topology is rechecked before
the first unlink and afterward. A source-only `purge_scope=Unknown` is not
an automatic rejection when physically distinct directories can be
verified. The correction passed local focused/full source regressions
and a **real external bind-mount** identity test on the isolated aaPanel
8.0.7 guest; an ordinary native site with two other cache-using peers
also passed this physical preflight despite source-only
`purge_scope=Unknown`. See the
[review-remediation QA record](docs/evidence/aaPanel-8.0.7-2026-11-11-pr56-physical-peer-delta-qa.json).
**Validation boundary:** The amended ZIP was imported as a Python
module for the focused native filesystem test, but was **not installed
into the running aaPanel plugin** due to execution-tool restrictions.
The earlier native Browser Clear acceptance belongs to the pre-delta
candidate; no new installed-R1 Browser replay is claimed. Independent
delta re-review and Owner authorization remain required.

**PR #56 second physical-isolation delta (nested bind mounts):** A second
independent review found that distinct Cache roots could still share
the selected site's `levels=1:2` object subtree through an external
bind mount, such as `site-6/8` exposed through `fastcgi_cache/8`.
The guarded Clear now inspects Linux `mountinfo` targets within, at,
or exclusively above registered peer Cache roots and cross-checks their
anchored inode identities against the selected root ancestor chain and
its streamed actual Nginx Cache subdirectories **and files**.
Shared nested subtrees or individual objects block unlink, while
independently mounted objects remain supported when physically
distinct. Mount IDs join the repeated physical-isolation signature.
Actual native guest bind-mount QA verified refusal of root, nested
directory and single-file aliases; preservation of Cache proof bytes;
acceptance of unrelated mounted trees; and unchanged nine-site
HTTP/Nginx health. See
[nested-bind native evidence](docs/evidence/aaPanel-8.0.7-2026-11-11-pr56-nested-peer-bind-r2-qa.json).
This exact R2 ZIP was executed directly in a fresh native guest Python
process but was **not installed into the running aaPanel plugin**;
current-HEAD Browser Clear/Restore is not claimed. Exact completed CI,
independent delta re-review and Owner integration approval remain gates.

**PR #56 R3 physical-isolation delta (peer Cache symlinks):** A
subsequent independent review identified ordinary symlinks below
registered peer Cache roots as another potential physical alias.
The guarded Clear now reads relevant peer `levels=1:2` entries
through pinned directory descriptors, checks symlink target
device/inode against selected-site Cache ancestor, subtree and
file identities, and refuses dangerous or unresolved aliases
before unlinking. An independent peer symlink remains eligible.
The symlink identity signature joins existing repeated preflight
and recovery uncertainty checks. The exact corrected ZIP passed
native first-/second-level, Cache-file, multi-hop, independent
and dangling-symlink experiments without changing the proof
file hash; see [R3 peer symlink evidence](docs/evidence/aaPanel-8.0.7-2026-11-11-pr56-peer-symlink-r3-qa.json).
The ZIP was executed in fresh native QA guest Python but was
**not installed into running aaPanel**; this is not a new
authenticated Browser Clear/Restore acceptance. Completed
current-HEAD CI, independent delta review and Owner Merge approval
remain required.

This does **not** establish all-worker HTTPS, logged-in WooCommerce
cross-customer privacy, Nginx Helper URL invalidation or a safe Purge All.
Issues #2 and #21 remain open. PR #56 subsequently received independent
approval and Owner-authorized Merge; exact installed-R3 native Browser
Apply/Clear/Restore acceptance is recorded in [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2#issuecomment-6810312183).
The review-stage limitations above describe their original candidates.

## Unreleased 0.1.36: verified native regenerated-VHost shape (Issues #2 / #10 / #21)

After the native aaPanel 8.0.7 VHost is regenerated, the generated server block can add a per-site `sub_dir/<site>/*.conf` wildcard alongside the existing `extension/<site>/*.conf`; it may also append one trailing `/` to the declared document root. The Status Pages extension/file adapters recognize that exact normal shape only while the optional subdirectory glob is absent or contains no active `.conf` file. The shared PHP source mapper and registered-site Cache source/peer audit apply the same bounded, no-follow inspection: a foreign subdirectory route, symlink, duplicate or unsupported include produces `Needs Review`/`Partial`, not an Apply, Cache Clear or false physical-isolation authorization. These changes never invoke native regeneration, write a VHost, enable Purge All, or grant automatic enforcement. The generated-VHost comparison now accepts identical literal document roots differing by at most one terminal `/`, while rejecting repeated separators, dot/traversal segments and different roots; Cache readiness still requires a real `File Match`, not an override. Native subdirectory and Status extension includes must be **direct children of the selected server block** under quote-, escape-, braced-variable- and comment-aware lexical scope checks: an include nested inside `location` or `if` cannot be authorized by quoted braces that confuse raw counts. These are source-level checks, not a fresh native installed-ZIP or all-worker acceptance result.

## Unreleased 0.1.35: fresh aaPanel site Extension compatibility diagnosis (Issues #2 / #21)

A real aaPanel 8.0.7 **Website → Add site** operation produces a stock PHP85 VHost without `include /www/server/panel/vhost/nginx/extension/<site>/*.conf;`, although the separate native config-regeneration template contains it. The guarded Cache Apply preflight already correctly refused this newly created site's unsupported include order. The development candidate adds a specific read-only `native_extension_include_missing` diagnostic **only** for a clearly missing per-site Extension glob with exactly one expected PHP handler, no competing Extension/Cache directives, and an **independently inspected, compatible prospective on-disk Extension glob** (safely absent, empty, or native inert `site_total.conf`). Foreign, linked, unreadable or routing-bearing Extension sources require manual review without recommending activation of a wildcard include. The native UI **first** advises a fresh Config read and Cache readiness recheck: in isolated aaPanel 8.0.7 QA, the installed `site_total` service subsequently generated `site_total.conf` and the previously missing Extension include at the same VHost modification timestamp, about five minutes after actual site creation. This delayed reconciliation is observed, **not guaranteed on other installations**. Only when the freshly loaded Config still lacks the line does the UI explain using **Website → selected site → Config** to add one server-level include before `#PHP-INFO-START`, Save with Nginx syntax validation, then run **another fresh Cache readiness check**. An editor opened before the native rewrite must not be saved with stale contents. It does not edit a vendor-generated VHost, grant Apply permission, run regeneration, enable Purge All or change recovery semantics. Ambiguous/foreign/commented extension includes still fail closed. This is a supervised compatibility step, **not automatic onboarding** or confirmation that all aaPanel versions and templates preserve that edit. [Native new-site reproduction](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6792970143).

## Unreleased 0.1.34: native PHP drift and conflicting-include refusal (Issues #2 / #21)

In an exact installed `0.1.33` Cache session on aaPanel 8.0.7, native **Website → PHP version → PHP-85 to PHP-81** edited only one source include while the journal still pinned PHP 8.5. Fresh Recheck correctly returned **Needs Review**, saved recovery ID read-only and **Restore locked**, but the reason was a generic unsupported VHost include. After reconciling PHP to 8.5, new Recheck returned **Applied** and separately approved Restore returned **Restored** with byte-identical source and all nine sites healthy. [Native QA evidence](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6792490364).

The `0.1.34` candidate reports the **expected saved Cache PHP version** and the **single observed native PHP include** (8.1 versus 8.5), directing the operator to reconcile the site's PHP setting in aaPanel and run a fresh Recheck before Restore. Mixed, duplicate and unrecognized native PHP includes remain unsupported rather than accepted merely because the expected include appears anywhere in a VHost. Site identity, journal recovery, ownership checks, reload/consent gates and the Purge All prohibition remain unchanged. This is diagnostic/refusal logic, **not automatic PHP-switch monitoring, immediate Cache invalidation or Production readiness**.

## Unreleased 0.1.33: Cache recovery evidence during native site drift (Issues #2 / #21)

A validated Cache **Recheck** in `Needs Review` now displays a well-formed
saved recovery ID explicitly as **read-only evidence**, plus the saved journal
phase when available. It offers an actionable next step: inspect the changed
native source/ownership, reconcile only the intended change through aaPanel or
supervised recovery, and Recheck. The UI **never** authorizes Restore solely
because an ID exists: **even a successful Apply acknowledgement is diagnostic
only**. A separately initiated, current `Applied`/`Recovery Required` Recheck
must validate the selected site's saved journal before Restore consent becomes
available; a fresh explicit operator approval is still required.
Malformed/stale replies remain rejected; the read-only result is rendered
as text, not trusted markup. There is **no**
Nginx/PHP/WordPress write, Purge All, new API or changed backend adapter.

The real [aaPanel 8.0.7, installed 0.1.32 site #7 QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/2#issuecomment-6787853322)
observed a one-line vendor Domain Manager VHost change while Cache was active:
`Needs Review` denied Restore, removing only the test alias restored the exact
source identity, and an explicit approved Restore returned all nine sites
to HTTP200. This is the evidence motivating the **0.1.33 UI regression tests**,
not proof that this new source package is itself installed or released.

## Unreleased 0.1.32: task-based native management UX (Issues #17 / #2)

The aaPanel modal now has clear destinations: **Overview**, **Website list**,
**Routing & Nginx**, **FastCGI Cache**, **PHP-FPM**, **Status Pages** and
**Activity & Logs**. A shared **Website being inspected** selector stays visible
while moving between Website list, Routing and Cache, preserving a fresh native
site snapshot; its list comes from the current page of aaPanel records. From
a direct visit to Routing or Cache, inventory loads once, and a **Browse
websites** action returns to pagination for more entries. Selection changes
revoke previously rendered source evidence and Cache operation approvals.
This is a frontend organization of **existing endpoints**, not an added
write, policy or cache purge method.

The read-only local hosts, VHost, Nginx next-load candidate, FastCGI cache,
and PHP runtime reports now put a **plain-language outcome** first, followed
by expandable **Technical evidence** containing the existing exact source
details, SHA-256 identities and diagnostics. The operator can still expand
raw evidence before/after an incident; it is not dropped or redacted.
Status is conveyed by **words and semantic color** (observed source,
review required, failed), never color alone. Disabled confirmations now show
**inline, state-aware prerequisites** immediately beside the control: what
the approval means, which read-only Compare/Preview/Recheck must be run,
whether saved site recovery exists, and what changes are or are not
authorized. The source result remains visible even when the checkbox is
locked. Status Pages uses separate guidance for Apply versus Restore;
checkboxes alone do not bypass its existing evidence checks. The PHP
version selector appears **before** the runtime inspection and remains
associated with the existing settings form; the operator can choose
PHP, Inspect runtime, Preview values and then review a guarded action in
natural order. Activity explains severity, stage, operation and recovery IDs.
The website baseline now displays an ordinary-language summary before
its expandable source digest, with the site comparison table retained. Green does not mean production
or WooCommerce safety. The Cache summary prioritizes shared-directory purge
risk, ignored response headers, private-route runtime acceptance, and Nginx
Helper **plugin-header version**, not verified vendor-byte identity or active
settings. Workflow guidance explains what each page checks, how to proceed
and when Apply/Restore affects shared services. A concise PHP-FPM parameter
guide explains the effect of each `pm.*` field. Read-only preview buttons
retain neutral styling; dangerous/explicit Apply and Restore controls remain
independently gated.

Preserve existing enabled/disabled state, backend validation, native CSRF,
per-tab scroll, unsaved Status Page drafts, saved recovery IDs and full
primary-admin authority. No destructive action, disabled safety guard,
new backend API or live Nginx reload is performed by these UX changes.
Source/UI tests and a static Chromium render at 1280, 720 and 390 px showed
no horizontal content overflow in the redesigned sections; this is **not**
a substitute for exact-candidate authenticated installed-ZIP visual and
interaction acceptance inside native aaPanel (#21).
Actual WooCommerce session/cart/checkout/payment/webhook and safe, site-owned
physical purge with active Nginx Helper remain separately unproven (#2).

## Unreleased 0.1.31: read-only Nginx Helper compatibility evidence (Issue #2)

In **Websites → Inspect selected website FastCGI cache**, the native source
report now independently checks the exact aaPanel-selected document root for
a conventional WordPress core marker and the installed
`wp-content/plugins/nginx-helper/nginx-helper.php` file. It performs two
bounded, descriptor-anchored, no-symlink file observations; it does **not**
bootstrap WordPress, read credentials or `wp-config.php`, contact the
database, run PHP, purge any cache, or change the website. It distinguishes
`Not Observed`, `Not Installed`, `Installed` and `Needs Review`. Even
`Installed` provides **file/version evidence only**: WordPress activation,
selected Nginx Helper purge method, runtime cache path, loaded Nginx workers
and actual compatibility are all unverified. A source change/symlink/unknown
layout yields `Needs Review`, not a claim that the plugin is absent.

For the inspected upstream Nginx Helper **v2.4.1**, its standard
`unlink_files` URL hash omits Customizer's per-Apply 128-bit cache generation;
`get_request` assumes a separately verified Nginx purge route, which
Customizer does not install; ordinary FastCGI `Purge All` recursively deletes
the effective `RT_WP_NGINX_HELPER_CACHE_PATH` even when `get_request` is
selected. A directory shared with another website is therefore not safe to
assume site-scoped. The native UI reports these concrete incompatibilities
without asserting the helper is active or automatically blocking existing
approved Cache operations. Other Helper versions remain unverified until
independently assessed. Physical site-scoped Purge All and actual
WordPress/WooCommerce/Nginx Helper behavior remain separate native acceptance
work, not silently satisfied by this read-only feature.

A later **test-only**, exact-source-pinned Nginx Helper 2.4.1 isolated QA run
verified its supported `rt_nginx_helper_purge_cached_file` filter can remap a
URL to the active generation-specific cache file in a private fixture,
without editing vendor code. It also proved that vendor Purge All is strictly
*configured-path-scoped*: an independent sibling site's cache survives,
while misconfigured peer entries under the same path do not. This is not a
production WordPress bridge or permission to enable Purge All; effective
per-site runtime configuration and native integration remain open. See the
[reproducible source and bounded QA evidence](docs/evidence/aaPanel-8.0.7-2026-11-13-nginx-helper-scope-hook-qa.json).

## Unreleased 0.1.30: guarded native per-site FastCGI Cache operations (Issue #2)

The native **Websites** tab adds a separate, explicitly reviewed workflow: **Check site-specific Cache Apply readiness**, **Recheck Cache / recovery**, **Apply site-specific Cache (reload Nginx)**, and **Restore saved Cache / recovery**. The original **Preview isolated cache policy** remains read-only and unchanged in meaning; it still cannot authorize an Apply. The new readiness endpoint is a primary-administrator/CSRF-protected POST bound to a stable aaPanel website ID, document root, running status and domain/port bindings, and a two-pass native Nginx source audit. It allows only a matching aaPanel 8.0.7 Nginx **HTTP/80**, verified stock **PHP 8.1/8.5** handler (including native PATH_INFO processing), no incompatible inherited security response headers, and a matching generated VHost before presenting the exact site zone, physical cache directory and source/proposal digests. The read-only preflight also sends a bounded loopback HEAD to the registered PHP route and rejects sites that return 4xx/5xx or an unexpected managed marker before approval. Readiness is NOT a loaded-worker safety or application-behavior verdict. An unrelated native Static site is counted as a verified non-consumer only when its exact `enable-php-00.conf` source is empty or a strict PHP-404 handler, with inert rewrite/extension sources and no FastCGI cache directives; unknown or altered static routing remains unresolved. Static sites themselves are **not** eligible for Cache Apply, which still requires a working PHP 8.1/8.5 route. On any modified/unsupported source, the operator must resolve **Needs Review** rather than force Apply.

Approved Apply serializes the operation, saves a root-owned persistent recovery record outside the replaceable ZIP, creates only `/www/server/ach-customizer-fastcgi/site-<native-id>`, and publishes two separately owned Nginx include fragments: one verified `http`-scope zone under the existing native VHost glob and one site-specific extension PHP handler **before** the stock aaPanel PHP include. It never edits vendor/aaPanel core files, generated native VHost, the shared `WORDPRESS` zone, or another site's cache. It checks native sources and ownership, requires `nginx -t`, signals **one deliberate Nginx reload**, and compares a registered Host-only loopback `HEAD /index.php` with an upstream FastCGI/cache marker. The observed marker is **narrow** evidence of one working PHP route; it is not proof of all loaded workers, WordPress/WooCommerce session safety or cross-site isolation under real visitor traffic. **A site without a healthy PHP `/index.php` is not eligible for the current operational Apply.** The native site selector revokes stale approvals, and Apply/Restore each require a separate deliberate checkbox. Uncertain reload results retain their journal and source files for explicit Recheck/Restore; they are **not blindly retried**.

Recheck compares the saved VHost/rewrite, main Nginx and PHP-parameter source hashes, managed fragment bytes, the physical cache directory's owner/device/inode and the origin-local PHP marker. Changed sources or physical aliases are **Needs Review** with the original recovery ID; Recheck never reloads or repairs the site. An exact schema-2 **prepared** crash checkpoint before physical directory/snippet creation instead returns **Recovery Required**: explicitly approved Restore finalizes the unactivated journal **without a reload** (`changed=false`, `runtime_verified=false`), and subsequent read-only Recheck reports **Restored** with explicit `prepublication` scope, never a falsely activated Cache. Unexpected directories/partial snippets remain **Needs Review** and cannot be silently adopted. Recovery now also checks the complete native site-extension `*.conf` inventory with the existing bounded source scanner: a differently named routing fragment blocks Recheck/Restore even when the exact managed Cache filename is absent. For a never-published schema-2 operation, the original full two-pass source fingerprint must still match; for ordinary Apply/Restore, managed and retained file changes are intentional, so only relevant live-source safety is rechecked rather than comparing an obsolete baseline hash. A **restored** journal whose previous active snippets reappear is also **Needs Review**, never **Applied** or an actionable normal Restore. For a genuinely activated operation, approved Restore retires only that operation's byte-identical managed fragments (retained for forensic/recovery inspection), checks/reloads Nginx, verifies the original PHP route marker is gone, and commits the restored journal. Reapplying after a completed Restore requires **another fresh preview and separate approval**, byte-identical retained fragments, the same generator policy/version, and a verified existing physical cache directory. A **fresh per-Apply 128-bit cache generation** is included in the exact previewed and approved Nginx `fastcgi_cache_key`, so a new generation cannot reuse stale objects written by a previous one even though the site's physical cache directory is preserved. The server rejects any cache generation used by the current journal or an intact older restored-journal archive **before** writing or reloading; prior restored journals are archived before starting a new operation ID. It **preserves already-generated site-specific cache bytes** rather than purging them. **Site-specific Purge All is deliberately unavailable** until the complete, physical ownership/alias and aaPanel Nginx Helper `get_request` / `unlink_files` integration has native acceptance. Ordinary uninstall preserves host-side changes and recovery evidence; it must not silently assume all cache policy is gone.

The existing Incus guest `ach-aapanel-qa/aac-native-qa` provided **isolated** Nginx 1.28.3/PHP 8.1 and 8.5 acceptance with the actual stock aaPanel PHP include placed after the generated handler: syntax passed; independent A/B `MISS→HIT`; private request, Cookie, Authorization, encoded and normalized URI bypass; upstream cache controls; and task-owned A-only cache file removal leaving B at `HIT`. This harness uses a *separate temporary Nginx instance*, not an installed aaPanel Apply, not a real application login, and not Nginx Helper verification. The separate **real native Nginx reload** acceptance on the same guest, without installing/activating the development ZIP in aaPanel, used registered WordPress site `wpqa21.test` (ID2, PHP8.5). Following an initially ambiguous one-shot reload that returned before new worker adoption, the implementation was fixed to **poll only read-only origin PHP status** after one reload (never reload twice implicitly). Its persisted recovery ID allowed independently verified Restore. A subsequent explicitly approved **Reapply → Recheck → Restore** cycle passed with real Nginx reloads, PHP marker and separate `X-ACh-Cache` status: root page `HIT`, `wp-login.php`, `wp-admin/` and query-string traffic `BYPASS`; all three QA websites remained HTTP200 and native Nginx/global-cache/WordPress VHost SHA256 remained unchanged. Restored sources were retained outside the active Nginx `*.conf` glob, and previous journals archived. This does **not** establish all WooCommerce/private-state cases, safe Nginx Helper Purge All, a production contract, or authenticated installed-plugin Browser validation.

A follow-up native test exercised **two different cache-generation keys** on the existing WordPress QA site: each generation began `MISS` then `HIT` for public `GET /`, while login/admin/query remained `BYPASS`. Both completed Apply/Recheck/Restore, and generation 2 did not reuse cached objects from generation 1 despite the preserved physical directory. A read-only preflight now also verifies the live `HEAD /index.php` handler before allowing operator approval; this prevents the existing static QA sites (whose PHP route returned HTTP404) from appearing eligible. Exact native details and limitations live in [the aaPanel integration guide](docs/aapanel-integration.md#guarded-site-owned-native-fastcgi-cache-lifecycle-candidate-0130-issue-2).

**Latest exact native installed-ZIP QA (2026-11-10, Issue #21):** The protected primary-admin account authenticated successfully in the existing aaPanel 8.0.7 Browser. The `0.1.30` ZIP was imported through **App Store → Third-party Plug-ins → Import plugins**, upgrading installed `0.1.24`; all **53/53 package members** matched exact installed bytes (runtime `__pycache__` excluded). The real Browser surfaced a reserved aaPanel POST `action` routing collision, corrected in `manage_cache_policy` to use `cache_action`; after re-import, a controlled **QA panel-service restart** loaded new Python modules. Verified native CSRF rejection without `x-http-token`, stale-site approval invalidation, PHP404 preflight denial, read-only `Unmanaged`/`Needs Review` states, and a complete explicitly approved **PHP81 site #4 Apply → Recheck → Restore** via Browser. Live Nginx public `GET /index.php` produced `MISS → HIT`, while cookie, Authorization, query, and synthetic login routes returned `BYPASS`; three registered QA sites remained HTTP200 and original Nginx main/shared-cache/VHost byte hashes unchanged. A second fresh generation began `MISS → HIT` despite retained first-generation objects. Concurrent QA VHost drift was correctly reported `Needs Review`, not silently repaired; a separate QA activity later completed the second recovery journal to `restored`, with no active managed snippets afterward. Preserve concurrent QA artifacts and do not attribute the second Restore to this Browser session. This is **not** WooCommerce/Nginx Helper Purge All, all-worker, Production or full lifecycle acceptance. This historical candidate was subsequently approved and merged as [PR #49](https://github.com/AChWorks/ach-aapanel-customizer/pull/49); exact R7 installed QA and post-merge evidence are in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21). The broader Cache acceptance remains open.

## Unreleased 0.1.29: isolated FastCGI cache safety reference (Issue #2)

The **Websites** tab now adds **Preview isolated cache policy** beside the existing read-only audit. It requires the current native website ID/root/domain binding snapshot, a full primary aaPanel administrator's CSRF-protected POST and a complete, stable aaPanel 8.0.7 Nginx source audit proving that the selected site directly references a FastCGI cache zone via a known PHP 8.1/8.5 include. An incomplete, changed or non-cache site receives **Needs Review** with no fragments. This is **not** an Apply operation: the response explicitly marks `installed=false`, `runtime_verified=false`, `safe_verified=false`, `apply_supported=false` and `purge_supported=false`. Changing the native website selection invalidates in-flight previews; generated fragments are displayed as text rather than HTML or executable buttons.

The deterministic reference uses a separate per-site physical cache root and Nginx keys zone, independent of aaPanel's shared `/www/server/fastcgi_cache`. It uses distinct per-site variables, `fastcgi_cache_bypass` **and** `fastcgi_no_cache` for unsafe methods, Authorization, all Cookie-bearing requests, query strings, private WordPress/WooCommerce/admin/REST/API paths and explicit response guards for `Set-Cookie`, `Cache-Control: private/no-store/no-cache/max-age=0`, `Vary`, `WWW-Authenticate` and `X-Accel-Expires: 0`. Public REST still works but is conservatively not cached by this reference. It also bypasses encoded and noncanonical original request URIs (percent-escapes, repeated slashes and dot segments) that Nginx may normalize into a private route: checking only literal `$request_uri` path names misses these aliases, while relying exclusively on the mutable `$uri` would lose the original target after internal redirects. The proposed PHP handler overrides the aaPanel-style inherited `fastcgi_ignore_headers Cache-Control Expires Set-Cookie` with `fastcgi_ignore_headers Set-Cookie`, so Nginx again honors ordinary `Cache-Control` and `Expires` while the independent `$upstream_http_set_cookie` write guard remains. It does not rewrite vendor PHP snippets, create physical cache dirs, edit any generated aaPanel VHost, reload Nginx or provide a purge endpoint.

**Representative native QA PASSED** against aaPanel 8.0.7 / Nginx 1.28.3 and independently for **PHP 8.1 and PHP 8.5**: `nginx -t`, two synthetic site-specific zones and directories with public `MISS→HIT`, private `BYPASS→BYPASS`, response `MISS→MISS`, encoded/dot-segment/slash-normalized private alias `BYPASS→BYPASS` with backend-confirmed private routing, `Expires` past `MISS→MISS` and future `MISS→HIT` (without upstream `Cache-Control`/`Set-Cookie`), canonical public `MISS→HIT`, and physical A-only test-cache file removal leaving site B at byte-identical `HIT`. The bounded harness is `scripts/qa_fastcgi_cache_reference.py` and must be run only as root inside an authorized disposable aaPanel QA guest: `python3 -B scripts/qa_fastcgi_cache_reference.py --php-version 81` and the same command with `85`. Test Nginx listens only on a temporary localhost port, with synthetic PHP body/data; the harness retires its own process, fixtures and cache directories. Installed aaPanel config, cache, native site VHosts, PHP-FPM services and the installed plugin are unchanged. This **does not demonstrate actual WooCommerce behavior, Nginx Helper `get_request`/`unlink_files`, exact-ZIP installed Browser/CSRF, native site application of the reference, loaded worker equivalence or an approved Restore**. Only a separately verified guarded site-specific Apply/Restore and safe Helper integration can make this a usable automatic cache policy. See Issue #2 for completion and Issue #21 for native acceptance.

## Why

aaPanel and its plugins can regenerate configuration when sites are created, modules are changed, or the panel is upgraded. This project aims to manage those intentional customizations *inside aaPanel* instead of relying on repeated manual edits or a second management interface.

The intended experience includes normal aaPanel plugin install/update/uninstall; a built-in management screen; plugin/module enable/disable; site and service discovery; monitored configuration drift; previewed, authorized changes; verification and reliable recovery.

It is **not WordPress-only** and does not imply every aaPanel subsystem will be supported immediately.

## Project map

- [Canonical product specification](docs/PROJECT-SPEC.md) — mission, accepted requirements, scope, constraints, lifecycle and first acceptance criteria.
- [Native aaPanel integration and test gates](docs/aapanel-integration.md) — official source references, safety boundaries, and open runtime compatibility checks.
- [Issue #10: Status Pages module](https://github.com/AChWorks/ach-aapanel-customizer/issues/10) — owner-approved EN/FA references, white-label controls, delivered bounded site methods, and remaining stopped/HTTPS/50x acceptance.
- [AChWorks descriptor](achworks.yaml) — concise project discovery metadata.
- GitHub [Issues](https://github.com/AChWorks/ach-aapanel-customizer/issues) — active research and implementation work after issue creation.
- GitHub [PRs](https://github.com/AChWorks/ach-aapanel-customizer/pulls) — proposed code/documentation changes and review evidence.

The unreleased Customizer UI follows a **real, authenticated inspection of every Nginx 1.28.3 management section in the same aaPanel 8.0.7 QEMU guest** ([seven-tab measured inspection and decisions](https://github.com/AChWorks/ach-aapanel-customizer/issues/17#issuecomment-6622156377)). The earlier [official-Demo study](docs/evidence/aaPanel-demo-8.0.7-nginx-1.24.0-2026-11-04-study.md) and [historical guest QA](docs/evidence/aaPanel-8.0.7-2026-11-04-native-ui-pr16-qa.md) remain contextual evidence; their former `Official Installed Total 0` visibility limitation was later resolved by allowing the asynchronous list to finish. The stacked follow-up refines label/input alignment and provides truthful per-request skeletons for Websites and Activity. Switching tabs preserves validated data and unsaved Status Pages text unless a related Monitor/branding/PHP-FPM operation invalidates a snapshot; explicit Refresh remains available.
See [the native UI source/evidence contract](docs/aapanel-integration.md#native-aapanel-dialog-ui-unreleased-ui-refinement) and [focused independent-review remediation](docs/evidence/aaPanel-8.0.7-2026-11-04-pr16-review-remediation.md).
This is an unreleased development change and does not authorize Production use.

The merged-source [PHP 8.1+ read-only discovery (PR #15)](https://github.com/AChWorks/ach-aapanel-customizer/pull/15), now reconciled with unreleased `0.1.13` source on `main`, detects aaPanel installation-file candidates and offers a bounded native selector for file-only monitoring. That historical discovery slice did **not** broaden Manual Apply beyond PHP 8.5; the separate unreleased 0.1.17 candidate now adds bounded PHP 8.1 Prepare/Apply/Restore, still subject to exact candidate QA and independent review. Inventory alone never authorizes a write. See [the PHP inventory acceptance boundary](docs/aapanel-integration.md#installed-php-inventory-and-read-only-version-selector).

**PHP-FPM 8.1+ runtime observation (new 0.1.14 development-only source):** After **Refresh installed PHP** selects a recognized version, **Inspect selected PHP master/socket** performs a separate **read-only, primary-admin-only** Linux procfs check. It matches the exact installed versioned PHP-FPM executable identity with one master process whose title names the exact native PHP-FPM configuration file, verifies the configured 'www' Unix socket path is a real socket, correlates the listener in /proc/net/unix with an open master-process file descriptor, and rechecks source, process start identity and socket bindings before reporting **Observed**. Missing sockets and inaccessible/multiple/unrecognized processes are **Partial** or **Needs Review**; a missing matching master is not proof the service is stopped. The UI invalidates stale responses when the selected PHP version or inventory changes. This shows a point-in-time master/listener relationship, **not effective pool values, worker health, successful PHP HTTP requests, site-to-process proof, or Apply eligibility**. No binaries are executed and no services or files are changed. A separately bounded, primary-admin-only **native site-to-versioned PHP socket FILE map** now runs alongside that inspection, checking the actual per-version installed [www] socket (rather than guessing /tmp/php-cgi-NN.sock), PHP include, VHost, rewrite and inert extension sources for up to 100 native sites. The plugin displays matched, other-version/no-PHP and unresolved sites and never infers Apply or live request routing; in-flight source changes or uninstalled PHP versions fail to Needs Review / incomplete attribution. The earlier runtime-observer slice had only synthetic source/Chromium tests; later native PHP81 Manual Apply evidence now exists, while full installed-native PHP81/PHP85 browser/lifecycle acceptance remains in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21). See [the exact runtime evidence contract](docs/aapanel-integration.md#native-php-81-read-only-master-and-socket-observation-source-only).

### Native website change Monitor (unmerged Phase A source candidate, Issue #1)

The Websites section now includes a **manual, read-only site lifecycle comparison** against a plugin-owned, separately confirmed baseline outside replaceable plugin code. It compares up to 100 aaPanel SQLite site IDs, site keys, document roots, panel-status values and actual native bound domain/port records. It detects additions, deletions and changes only on operator-triggered Compare; the initial candidate records and before/after values are rendered as plain text for explicit review. Saving a reviewed baseline requires a full primary administrator POST, explicit checkbox approval, current source SHA-256 and optimistic baseline **and Monitor-policy** revisions. Saving changes **only** the root-owned plugin observation file, not sites or server configuration; stale inventories, unsupported row shapes and concurrent regeneration require another Compare. The baseline survives normal plugin reinstall/uninstall.

This is **source-only Monitor evidence**, not proof of effective Nginx routing, site availability, WordPress/PHP runtime, missing sites outside native inventory or unchanged records reused under the same site ID. No scheduled reconciling, Auto-enforce, automatic website repair or host Apply is enabled. The native guest and authenticated browser/CSRF acceptance remain part of consolidated [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

### Guarded PHP 8.1 shared-pool adapter — Issue #2 (unreleased 0.1.17)

The existing explicit, full-primary-admin **Prepare → Approve → Apply → Inspect recovery → Approve Restore** workflow now has an independently scoped PHP81-www-shared-service adapter in addition to unchanged PHP85-www-shared-service. It targets only verified aaPanel 8.0.7/Nginx single [www] pool layouts with an unambiguous native site-to-socket file map; other PHP versions remain Monitor/Preview only. The new PHP 8.1 root-owned snapshot and journal use ach_customizer.fpm81.recovery.*; the existing PHP 8.5 recovery filenames remain unchanged and the existing operation lock is shared. Both versions require current SHA-256/impact evidence, FPM syntax validation, version-specific reload/verification and explicit baseline-specific Restore. A second version's saved recovery cannot authorize a cross-version Restore. This is **not Auto-enforce** or permission to reload Production.

Source-level tests cover cross-version independence, recovery, failing reload restoration, permissions and Frontend version-bound responses. The [exact-package 0.1.17 native QA](docs/evidence/aaPanel-8.0.7-2026-11-07-php81-guarded-native-qa.json) now verifies real aaPanel ZIP import (46/46 files), a native PHP 8.1.35 site returning HTTP 200, versioned PHP81 Apply/Reload, explicit exact Restore, injected reload failure restoration, unchanged PHP85/three WordPress VHosts, and a verified cold VM restore to the original 0.1.12 plugin baseline. This guest used synthetic Flask administrator POSTs; real authenticated aaPanel Browser/CSRF, full lifecycle and consolidated Issue #21 acceptance remain pending. See [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2) and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

**PR #33 R1 review remediation:** The PHP81 manual writer now rejects a mismatched or ambiguous [global] pid or [www] listen before Prepare, recovery journal creation, file replacement or service reload. Only the exact native /www/server/php/81/var/run/php-fpm.pid and /tmp/php-cgi-81.sock layout matches the current runtime hooks; no extra PHP versions or generic service parser are added. Operators can independently select **PHP81** or **PHP85** under **Saved recovery service** even if normal PHP inventory fails. Recovery identity/manual guidance remain visible; automatic Restore still requires fresh site/source evidence and explicit approval. Existing PHP85 recovery names, schema and shared lock remain unchanged.

[PR #33 R1 exact-package native and source regression evidence](docs/evidence/aaPanel-8.0.7-2026-11-07-php81-pr33-r1-remediation-qa.json) documents 451 Python and 208 JavaScript source tests, the corrected 46-member native ZIP, real fail-closed alternate PID/socket acceptance checks, PHP81 Apply/Restore/fault recovery and the independently verified cold guest restore. The original 0.1.17 QA link above documents the earlier candidate and must not be confused with this R1 package. Independent delta re-review, authenticated-browser/CSRF and Production/release approval remain outstanding.

### Site-scoped Nginx 50x error pages — Issue #10 (unreleased 0.1.20)

For an aaPanel 8.0.7 Nginx website whose **running** native VHost loads its own exact `extension/<site>/*.conf` and has the standard `error_page 502 /502.html;`, select **50x Generic** with **Nginx extension** delivery. The full primary administrator explicitly inspects the existing native 502 source, reviews the selected site/template/branding and approves the Nginx reload. The adapter installs a plugin-owned immutable HTML file and a site-specific extension: it retains the native 502 mapping while supplying the `/502.html` asset, and adds Nginx-generated `500`, `503` and `504` mappings. Explicit local-only proof requests must observe all four statuses (500/502/503/504), the exact rendered body SHA-256 and the operation nonce; the full verified route is journaled for guarded Recheck/Restore. A site may not run the overlapping 502-specific and 50x extension modes together. Preexisting explicit 500/503/504 mappings in the selected native VHost are preserved by refusing this mode.

The adapter **does not** enable `fastcgi_intercept_errors` or `proxy_intercept_errors`, change PHP/WordPress error bodies, create missing native includes, modify generated VHosts, change stopped-site HTTP status, or control unknown-host HTTPS. Source-only preflight cannot assert effective 50x; only a successful explicit Apply with Nginx proof can. Interrupted Apply/Restore, site-stop and VHost drift retain saved recovery and require explicit reconciliation. No automatic policy enforcement or Production deployment is authorized.

### Native per-site 404/502 file delivery — Issue #10 (unreleased 0.1.19)

For native aaPanel 8.0.7 PHP websites whose Nginx VHost already declares the conventional error_page 404 /404.html and error_page 502 /502.html, and has either no extension include or exactly one verified native aaPanel `extension/<site>/*.conf` include containing only a log-only `site_total.conf`, Status Pages now offers an explicit **Existing native 404.html / 502.html (no reload)** delivery choice. A primary administrator first checks the selected site's existing source/HTTP evidence, approves the exact scope/mode, and obtains an immutable root-owned original-byte backup and Recovery ID. Apply atomically replaces only the existing site status HTML while retaining uid/gid/mode; Restore requires the matching saved operation and returns the exact previous bytes. No vendor VHost edit or Nginx reload is made. Real HTTP 404 status/body is checked; 502 remains **source-only**, not a claim of live 502 verification. Stopped sites and drifted active recoveries remain read-only until safe reconciliation; completed Restore history does not block a fresh operation when the current route, original bytes and ownership are revalidated.

This mode does **not** add missing status files or modify WordPress/application routes. Sites with an active Customizer-owned or unrecognized Nginx extension route remain ineligible for native site-file delivery; the separate extension mode retains its own explicit checked reload. The isolated [aaPanel native lifecycle test evidence](docs/aapanel-integration.md#native-site-file-404502-delivery-without-nginx-reload-issue-10-unreleased-0119) and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) document the remaining authenticated browser and broader delivery gates. The native aaPanel log-only extension compatibility remains guarded; full exact-ZIP/browser, role/CSRF, and lifecycle acceptance is still tracked in Issue #21.

### Site status recovery across native Stop/Start — Issue #10 (unreleased 0.1.18)

When aaPanel stops a site, it rewrites its Nginx VHost root to the shared stop directory and comments extension includes. A previously applied plugin-owned site 404/502 extension may then be unobservable even though the saved recovery journal remains intact. A full primary administrator can now **Recheck** the selected stopped site's saved operation ID, phase and hashes without claiming that the current Nginx/HTTP response matches them. The UI reports **Suspended** for stopped sites and **Needs Review** for changed or missing native VHost sources, both as saved-journal-only evidence. Apply and Restore stay unavailable until the site is running, native source and impact are compatible and fresh verified checks permit a new explicit approval.

This bounded 0.1.18 change was checked against a [real isolated aaPanel 8.0.7 Stop/Start and 404/502 Apply/Restore campaign](docs/evidence/aaPanel-8.0.7-2026-11-07-status-recovery-lifecycle-qa.json). Native Stop still serves its stop page with HTTP 200 rather than 503; this package does not change that semantics. New aaPanel PHP sites lacking the exact native extension include remain ineligible for guarded site Apply. HTTPS unknown-Host and generic 50x routing, native browser/CSRF and complete Issue #21 lifecycle remain open. This is unreleased work, not Production authorization.

### Global HTTP/80 unbound routing — Issue #10 (unreleased 0.1.16)

For aaPanel 8.0.7 with Nginx, choose the Unbound template and global branding scope. A separately approved Recheck / Apply / Restore workflow manages a plugin-owned HTTP/80 default_server for IPv4 and IPv6. Unknown Host headers receive the selected offline-rendered EN/FA page with actual HTTP 404. Apply and Restore run a checked shared Nginx reload and verify fresh loopback HTTP status, body hash, and a per-operation proof nonce. The original aaPanel VHost, running websites, website stop/start templates and TLS/443 are untouched. Existing explicit HTTP default-server ownership is not overwritten. A persistent root-owned recovery identity survives plugin uninstall; Restore is required before uninstall when the route is active.

A real isolated aaPanel 8.0.7 guest accepted an exact candidate via the native panelPlugin ZIP importer, verified 46/46 installed files, then passed both EN and FA Apply → Recheck → Restore on IPv4 and IPv6. Original WordPress websites and their VHosts remained intact. The guest was subsequently cold-restored from the verified baseline. This evidence uses a synthetic primary-administrator Flask POST, not a real authenticated browser/CSRF session. HTTPS unknown-host selection, stopped-site 503 and generic 50x behavior remain open; no Stable/Production action is authorized. See Issue #10 native test evidence and docs/aapanel-integration.md.

### New-site source defaults — Issue #10 (unreleased 0.1.15)

With **Global defaults** branding selected in Status Pages, choose **New site**, **404** or **502** and explicitly **Recheck new-site default source**. The guarded source adapter for native aaPanel 8.0.7 + Nginx can replace precisely one of the three panel-data files: defaultDoc.html, 404.html or 502.html. The previous bytes and mode plus recovery identity are retained in root-owned persistent panel data, separate from the replaceable plugin ZIP. **Restore** requires the saved recovery ID; file drift or incomplete publication requires a fresh Recheck. Neither operation reloads Nginx, rewrites a running site's files, or configures catch-all routing.

These are **future-site creation sources**, not existing-site or effective error response controls. They are copied by native aaPanel site creation only when the destination is absent. Other global Nginx error routes, stopped-site behavior, unbound HTTPS/443, authenticated Browser/CSRF, site regeneration, and full Issue #10/#21 release acceptance remain separately open. A focused exact-package native aaPanel 8.0.7 QA has verified all three source Apply/Restore actions and real native site creation; remaining Browser/role/CSRF, lifecycle and independent review gates are still open.

## Development and installation

**aaPanel development update note:** Replacing a native plugin ZIP may leave an older Python helper loaded in the panel process. In an authorized isolated guest, if the backend reports a module-version mismatch, use **Restart → Restart panel** (not **Restart server**) in aaPanel, reopen the plugin, and verify Overview/Website inventory. A missing newer Hosts helper is now isolated to that diagnostic, instead of preventing unrelated plugin pages from loading. Do not apply this operational procedure to Production without separate approval. [Actual 8.0.7 QEMU evidence](docs/evidence/aaPanel-8.0.7-2026-11-04-native-hosts-qa.md).


A provisional native plugin source lives at `plugin/ach_customizer/`. Run `python3 -B -m unittest discover -s tests -p "test_*.py" -v` for source-only tests and `python3 -B scripts/build_plugin.py` to construct a **local development ZIP**. On an **isolated Debian 12 + aaPanel 8.0.7 lab**, the exact merged 0.1.0 ZIP passed real browser file-picker upload, installation, Settings, website inventory, Uninstall and Reinstall. The unmerged 0.1.1 candidate also passed browser update and reinstall with preserved Monitor flags. Its later optimistic-revision correction was independently re-executed through a real authenticated guest session: a stale action was rejected without changing the latest state. See the [source-bound browser evidence](docs/evidence/aaPanel-8.0.7-2026-11-02-native-browser-lifecycle-state.json) and [integration details](docs/aapanel-integration.md). A real static website was subsequently created, served via Nginx 1.28.3 and discovered dynamically in the isolated aaPanel 8.0.7 guest; site deletion and VHost regeneration/extension interactions were also examined. See the [runtime integration evidence](docs/aapanel-integration.md#actual-native-website-and-nginx-lifecycle-isolated-guest-2026-11-02). A real native shared PHP-FPM 8.5 pool and two-site HTTP mapping were then tested in the same isolated guest, exposing and correcting the omitted `pm.max_requests=0` default in the read-only monitor (see the [PHP-FPM integration evidence](docs/aapanel-integration.md#actual-php-85-native-pool-verification-and-bounded-monitor-correction-isolated-guest-2026-11-02)). The isolated guest additionally reproduced aaPanel's native WordPress `optimize_php` shared PHP-FPM reset (including the historical 80/10/10/30 branch with only RAM measurement simulated), verified real syntax/runtime health and an exact test-owned baseline restore. The unreleased `0.1.2` development candidate also identified two native websites sharing PHP 85 through bounded, read-only Nginx/PHP socket **file attribution**; see the [sanitized reset/impact evidence](docs/evidence/aaPanel-8.0.7-2026-11-02-native-fpm-reset-impact.json). Restricted-role real-browser authorization/CSRF, canonical website/VHost rename, Nginx extension durability, policy migrations and other panel versions remain unverified. The separate **unreleased 0.1.3** integration candidate has an isolated native ZIP import and real two-site FPM Apply/reload/failure-recovery/rollback test; see the [sanitized manual-FPM integration evidence](docs/evidence/aaPanel-8.0.7-2026-11-02-integrated-manual-fpm-qa.json). This is not an authorized production installation path or supported public release. **Do not deploy this repository to production as a plugin.**

The **unreleased 0.1.5 Status Pages module** bundles all 22 owner-approved EN/FA HTML reference pages (11 variants per language), verifies source SHA-256 against a versioned manifest, and uses a native plugin tab for sandboxed offline preview, white-label palette/identity selection and explicit global/per-website preference saves. With built-in ACh defaults it emits source-identical pages. Per-site choices are scoped to actual aaPanel site IDs; unfamiliar IDs fail safely. Branding is stored in a root-owned schema-v1 state file outside replaceable plugin files. Writes require a full primary administrator POST and the exact saved revision. Uninstall does not delete this state, and Reset changes only the selected branding preferences. The separately gated admin-only read-only site comparison hashes a selected 404/502 document-root file, scans bounded native VHost/extension source for potential routing conflicts, and offers a **size-limited, escaped current-versus-preview HTML diff** or a clear unavailable/new/identical state. This is a display-only excerpt, not an executable patch or proof that Nginx serves the page. Missing, changed, symlinked or ambiguous resources return conservative diagnostic states. **The historical 0.1.5 module is preview-only.** The historical file-only 404 prototype has been removed from the current unreleased 0.1.14 package. The candidate now provides separately approved **native Nginx site-extension 404/502 Apply/Recheck/Restore**; no offline preview or preference save activates a service. The 0.1.15 version added only future new-site source defaults (defaultDoc, 404, 502) with guarded Apply/Restore. The newer unreleased 0.1.16 candidate additionally implements unbound HTTP/80 default routing, not HTTPS or stopped-site routing. This new development source still requires exact-candidate independent review and native acceptance. See [the Status Pages integration and limitations](docs/aapanel-integration.md#offline-status-pages-branding-and-preview-initial-slice-issue-10).

The **source-integrated, unreleased 0.1.13 Status Pages HTTP/80 probe** adds one explicit primary-administrator action to check a selected, aaPanel-bound site's current 404 over **127.0.0.1:80**. It binds the request to the exact operator-loaded native website identity/domain snapshot, compares the response status/body hash with complete bounded/rechecked 404-site/VHost/extension source identities, and enforces one cumulative 3-second HTTP deadline. Results are `HTTP Match`, `HTTP Mismatch` or `Needs Review`, without exposing response HTML or following redirects. It is not a Nginx loaded-configuration test, HTTPS/public-delivery check, a 502 test, or an Apply/Restore action. Dynamic applications may log or process the one requested URL; the operator triggers it deliberately. See [the HTTP/80 source and test boundary](docs/aapanel-integration.md#explicit-bounded-site-404-http80-evidence-source-integrated-unreleased). Its source is merged but not installed as an exact attested QA package, independently accepted for native runtime behavior, publicly released, or authorized for Production.

**Status Pages 404 adoption preflight (unreleased source):** The read-only site-file inspector now distinguishes the textual source of a selected error_page rule (Native VHost, extension, duplicate/ambiguous, alternate or absent). The bounded local 404 probe additionally reports whether the current page already matches the selected rendering or whether an **explicitly approved, durable backup and checked Restore** would be required before replacing existing operator-owned bytes. The new report is deliberately **non-authorizing** (apply_supported=false, ownership and recovery unverified): it neither modifies a site nor establishes loaded Nginx routing, compatibility across regeneration, or actual Apply/Restore support. See [Status Pages evidence boundaries](docs/aapanel-integration.md#read-only-status-404-adoption-evidence-not-apply).

**Native Status Pages extension (draft, 404/502):** The Status Pages tab provides bundled EN/FA templates, branded previews and independent site file/HTTP diagnostics. For an explicitly selected aaPanel 8.0.7 Nginx website, the new guarded **Manual Apply/Restore** adapter writes a plugin-owned `ach_customizer_<site-ID>_<code>.conf` under the site's existing aaPanel `extension/<site>/*.conf` include and a versioned, root-owned static HTML asset under `/www/server/nginx/.ach-customizer-status`. It **never overwrites** an existing document-root `404.html` or `502.html`, vendor VHost, or other-site file. Each Apply/Restore performs **one explicitly operator-approved shared Nginx reload** after syntax/source checks, then verifies a real loopback status response, HTML SHA-256 and an independent per-operation proof nonce. The 502 preview is deliberately **source-only**; it never pretends to have induced a real pre-Apply 502 response.

A root-owned durable recovery journal records the exact selected native site, VHost digest, verified previous HTTP 404 baseline **or** prior 502.html SOURCE fingerprint (not a previous HTTP 502), proposed HTML digest, extension snippet digest and operation/recovery ID. The plugin stages and verifies complete files before non-clobber atomic publication, conservatively validates the bounded native Nginx include graph, uses no-clobber retained filenames for owned source, and preserves unknown/uncertain outcomes for explicit `Recheck` and approved `Restore`. Graceful Nginx reloads may temporarily serve a previous worker generation; positive Apply requires repeated fresh HTTP proof; 404 Restore verifies the previous HTTP 404 baseline while 502 Restore reports **Source Restored**, explicitly not the previous effective HTTP 502. Final journal fsync uncertainty retains its recovery ID. Existing native file-preview evidence, primary-admin POST/CSRF, site/bound-domain and branding-revision checks remain independently enforced.

**DRAFT / not release-ready:** A real isolated Nginx + plugin-module test on the Test Server QA guest passed HTTP 404/502 Apply, Recheck, Restore, nonce and non-target preservation, with isolated Nginx stopped and temporary files removed. This **does not prove installed plugin QA** against live aaPanel/Nginx configuration and three existing WordPress sites, authenticated browser, HTTPS, failed reload, site regeneration, global/default/status-onboarding adapters or power-loss durability. A native QA rollback plan and exact-candidate independent review are required before integration. The Owner selected **Option A**: genuinely safe Apply/Restore is required for initial release; do not defer it or consider source CI alone complete. See [Issue #10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21), and [integration details](docs/aapanel-integration.md#guarded-native-status-page-extensions-source-candidate-issue-10). **NO MERGE / NO RELEASE / NO PRODUCTION**.

The **unreleased 0.1.8 local hosts diagnostic** adds a full-primary-admin-only, read-only native Website inventory-backed site selection (current page; Previous/Next for other sites) against the origin host /etc/hosts. It reports exact bound-domain IPv4/IPv6 loopback entries with line numbers and file SHA-256; unrelated hostnames are never returned. It does **not** verify external DNS, OS resolver precedence, a remote Gateway or HTTP, and never edits hosts files. See [the bounded diagnostic contract](docs/aapanel-integration.md#read-only-origin-local-hosts-inspection-issue-2).

**Generated Nginx VHost/native-database drift comparison (merged source; Issue #2):** In Websites, the full primary aaPanel administrator can select one discovered site and press **Compare selected website VHost**. The plugin validates the selected native aaPanel site ID, key, root, status and bound-domain snapshot again before and after inspection, then compares the database root and bound hostnames against a bounded, descriptor-anchored **generated Nginx server-level VHost file** on the specifically supported aaPanel 8.0.7 Nginx layout. It reports `File Match`, `File Drift` (root/hostname discrepancies), or `Needs Review` when an untrusted or ambiguous source prevents reliable comparison. Nginx listener ports are listed as **observed only**; aaPanel domain ports and SSL listener configuration are not naively equated. It makes **no** site, shared-service, cache, or generated-config changes; no auto-enforcement, adoption, runtime-verified routing, Nginx -T, vendor-toolkit ownership or policy reconciliation is claimed. User-triggered detection is not a background reconciler. Current version still has the separate native DB lifecycle baseline, PHP shared-service controls, Status Pages recovery and FastCGI source audit; these are not replaced by this diagnostic. Exact 0.1.23 ZIP primary-admin native Browser acceptance verified real site File Match/controlled File Drift and Restore; the remaining **desired-site policy, current-loaded worker/runtime reconciliation and cache-safety** work remains open under Issues #2/#21; see [the generated-file boundary](docs/aapanel-integration.md#generated-nginx-vhost-database-drift-comparison-issue-2).

**Unreleased 0.1.26 FastCGI cache inheritance and shared purge-scope extension (Issue #2):** In addition to the existing native per-site source audit, the inspector now reads and fingerprints the fixed aaPanel 8.0.7 top-level `0.fastcgi_cache.conf` only when `nginx.conf` contains the expected include. It identifies global `fastcgi_cache_path` / Zone, a shared physical directory even across different Zone names, global `fastcgi_ignore_headers` settings (including `Set-Cookie` and `Cache-Control`), and other native sites sharing the same Zone or directory. The UI reports physical-directory Purge All exposure **separately** from a Host-partitioned Cache Key. Unsupported active global directives, nested includes, non-HTTP include contexts, noncanonical path aliases and changed sources return `Needs Review`. Different canonical directory strings remain `Unknown` if their physical separation cannot be verified. All outputs remain source-only: no HTTP request, cache mutation, ownership grant, purge, Apply or loaded-worker safety claim. This historical source-only diagnostic later integrated into `main`; subsequent 0.1.29 preview and 0.1.30 operational candidate are separate, explicitly gated capabilities. A separate **real Nginx 1.28.3 + PHP 8.5 loopback-only fixture** proved public `MISS → HIT` for two host-partitioned websites even with a shared zone, private Cookie/Authorization/cart/checkout/admin/webhook `BYPASS`, query and POST exclusion, `Set-Cookie` / `no-store` `MISS → MISS`, and **site-owned directory purge** leaving the other site's prior `HIT` untouched. This is acceptance of **the isolated test policy**, not proof that unmodified site configs are safe, that Nginx Helper `unlink_files` is scoped, or that this plugin supports cache Apply/Purge.

**Unreleased 0.1.14 read-only FastCGI cache source audit (Issue #2):** The Websites tab reuses its discovered native site selector for an explicit **Inspect selected website FastCGI cache** action, requiring a full primary aaPanel administrator POST and an exact site/domain/root/status precondition. It reads bounded, descriptor-anchored text only from the aaPanel 8.0.7 Nginx VHost, conventional PHP include and recognized native rewrite/inert extension sources, known FastCGI parameter snippets, and directly inspected main Nginx cache-zone declarations. The report distinguishes cache-zone reference clues, bypass vs write-suppression statements, host-token cache key, ignored response headers, POST caching, purge directives and other registered websites referencing the same zone. Ambiguous/unsupported sources return **Needs Review** or **Partial**; no source statement authorizes a purge, reconfiguration or automatic enforcement. Source-only checks **cannot prove live HIT/MISS/BYPASS, effective Nginx inheritance, other non-aaPanel consumers, personalized content safety, or whether Nginx Helper's file deletion affects another site's cache**. Real multi-site/WooCommerce traffic and safe per-site cache ownership/purge require separate isolated-native Issue #21 acceptance. See [the precise cache audit limitations](docs/aapanel-integration.md#read-only-nginx-fastcgi-cache-source-audit-issue-2). No Production install or public release was performed.

Native `AddDomain`/`DelDomain` tests on aaPanel 8.0.7 established that bound domains can change while the site key and VHost filename remain stable; the development website inventory now shows recorded bound domains separately from the site key. The latest read-only PHP-FPM parser was also rechecked against a real guest pool by exact source SHA. See the [bounded native domain lifecycle evidence](docs/aapanel-integration.md#native-domain-binding-lifecycle-and-exact-current-helper-runtime-test-isolated-guest-2026-11-02). No production installation or Apply is implied.

The candidate uses Python for aaPanel compatibility and an English-only UI consistent with native aaPanel plugin patterns. Read-only Monitor overall/module switches persist in the owner-checked data directory outside the replaceable plugin. An administrator-only POST must supply the last-seen state revision; conflicting stale actions fail visibly rather than silently replacing new preferences. Disable does not stop websites or services, grant Apply permissions, revert a previously applied shared-service policy, or enable background enforcement. The 0.1.3 development package separately exposes guarded manual PHP 8.5 shared-pool Prepare/Apply, recovery inspection and rollback via its normal native plugin interface; it is not automatic enforcement. Successful or rejected mutation attempts are sent to aaPanel's native activity log, with logging failures surfaced separately. Real browser role/CSRF integration has not been proven for the final candidate. Specific adapter contracts, support matrix and host-writing operations are still evidence-gated.

**Native PHP-FPM attribution (in-development follow-up):** the file-only mapper is being extended to aaPanel's observed per-site `extension/*.conf` and One-click WordPress `enable-php-85-wpfastcgi.conf` layouts. A recognized native mapping must verify inert site extensions and the same literal PHP-FPM Unix socket even for the WordPress FastCGI variant. The guarded PHP **8.5** manual writer now recognizes these validated native layouts instead of blocking ordinary aaPanel sites by their layout alone. Actual shared-service Apply/Rollback and runtime acceptance on disposable QA are still required before release. See [the bounded native mapping contract](docs/aapanel-integration.md#native-qa-php-fpm-file-attribution-for-aapanel-extension-and-wordpress-fastcgi-vhosts-development-only). No Production or release authorization is implied.

## Security and scope

This repository must never contain host passwords, tokens, session material, production configuration snapshots, or restricted logs. Creating this source repository does **not** authorize changes on production aaPanel hosts.

AChWorks owns the project; relevant cross-project engineering principles and lifecycle contracts are maintained in [Koinon](https://github.com/AChWorks/koinon).
