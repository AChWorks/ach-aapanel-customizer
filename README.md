# ACh aaPanel Customizer

A **native aaPanel plugin** for inspecting, applying, rechecking and restoring
administrator-approved website and service customizations **inside aaPanel**.
It is not a standalone dashboard, a server-wide unattended enforcement agent,
or a WordPress-only plugin.

## Distribution, source and tested state

| Layer | Verified reference (2026-11-21; check live systems) | What it proves |
| --- | --- | --- |
| **Published package** | [v0.1.51 pre-release](https://github.com/AChWorks/ach-aapanel-customizer/releases/tag/v0.1.51), native `0.1.51` and optional Bridge `0.1.8` | The previously verified public package; always recheck [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) before claiming latest |
| **Merged source** | `main` native `0.1.72` after [PR #114](https://github.com/AChWorks/ach-aapanel-customizer/pull/114); Bridge `0.1.8` | Development source, **not** a published package or installed QA proof. Verify the [native manifest](plugin/ach_customizer/info.json) and [Bridge](wordpress/ach-aapanel-bridge/ach-aapanel-bridge.php) |
| **Retained native QA VM** | `ach-aapanel-qa/aac-native-qa-20261118`, aaPanel `8.0.7`, installed native `0.1.69` at the 2026-11-21 check | **One persistent Running VM**, not a fresh guest. See [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) for binding, test scope and actual current runtime |

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
to the persistent VM or infer current source is installed there. Neither
Merge nor QA authorizes public Release or Production.
The broader open functional work remains in [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2).

## Capabilities in the merged development source

| Native section | Operator tasks and important boundary |
| --- | --- |
| **Overview / Monitor** | Read component availability, diagnostics and packaged versus resident **entrypoint** version; matching entrypoints do not certify every imported helper. |
| **Website list** | Discover paginated native websites and bound domains, compare drift, and save selected-site or all-site observation baselines without changing website configuration. |
| **Routing & Nginx** | View current local loopback aliases and remove an **exact chosen hostname with one administrator click**, with no site-selection or watcher prerequisite. Inspect site-owned VHosts and optionally manage source-verified Nginx sensitive-path protection; **Hosts removal is never unattended**. |
| **PHP-FPM** | Inspect installed PHP files, service/pool mapping and affected sites. Guarded shared `[www]` Apply/Restore is implemented for validated **8.1/8.5** adapters; discover other installed versions rather than treating these adapters as a universal version allowlist. Separately opt in to compatible post-WordPress-setup automatic policy repair. |
| **Status Pages** | Preview the bundled 11 English/LTR and 11 Persian/RTL offline templates, edit scoped branding, and use verified site/global Nginx delivery and Restore modes. Global unknown-host **HTTPS/443 TLS/SNI remains an Owner decision** in [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10). |
| **FastCGI Cache** | Inspect and explicitly Apply/Recheck/Restore site-owned policy; clear selected URLs or independently verified site-owned cache files. Private-session isolation and Nginx Helper integration have **bounded** non-production proofs, not generic safety certification. |
| **Activity & Logs** | Inspect operation stage, outcome, error and Operation/Recovery IDs for diagnosis and safe reconciliation. |

The separately installed, optional [WordPress Bridge](wordpress/ach-aapanel-bridge/README.md)
(version `0.1.8` at this checkpoint) defaults to **disconnected**. After
administrator provisioning of a generation-bound manifest it can assist
Nginx Helper with **eligible per-URL GET/HEAD invalidation**; it does not
install Nginx Helper, intercept its vendor **Purge All**, or provide a
cross-site-safe recursive purge. The installed WordPress package ships its
own [WordPress `readme.txt`](wordpress/ach-aapanel-bridge/readme.txt).

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
