# ACh aaPanel Customizer

A **native aaPanel plugin** for inspecting, reviewing, applying and recovering
operator-approved website and service customizations. It runs **inside aaPanel**,
not as a separate dashboard, server daemon or WordPress-only tool.

**Distribution:** [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases)
is the authoritative source for published versions, downloadable ZIPs and
checksums. The latest published development **pre-release at this checkpoint**
is [v0.1.51](https://github.com/AChWorks/ach-aapanel-customizer/releases/tag/v0.1.51):
native Customizer **0.1.51** and optional WordPress Bridge **0.1.8**.
The native and WordPress versions are independent. A pre-release is **not**
a stable-release declaration, automatic update, Production install or general
compatibility certification. For source-tree version details, inspect
[`plugin/ach_customizer/info.json`](plugin/ach_customizer/info.json) and
[`wordpress/ach-aapanel-bridge/ach-aapanel-bridge.php`](wordpress/ach-aapanel-bridge/ach-aapanel-bridge.php).

## What is available

| Native section | Current operator capability |
| --- | --- |
| **Overview / Monitor** | Enable/disable monitoring, observe packaged vs resident entrypoint versions, see availability and diagnostics. |
| **Website list** | Refresh native website inventory, compare changes, and save either **one reviewed site's** baseline or a separately reviewed **all-sites** baseline. Saving a baseline does not reconfigure a website. |
| **Routing & Nginx** | Inspect generated VHosts, selected-site `/etc/hosts`, local HTTP and recovery context. **Unpublished source 0.1.58** includes opt-in site-owned Nginx sensitive-file guards and a separately opt-in, **read-only failed WP Toolkit Hosts witness** for the verified aaPanel 8.0.7/Nginx source. No unattended alias cleanup is promised; an authorized OS operator must coordinate manual corrections. **Published 0.1.51 lacks these features**. PHP-FPM reconciliation remains manual. |
| **PHP-FPM** | Discover installed PHP and site/socket relationships; compare version-scoped desired policies. Guarded shared-pool Apply/Restore is available only for **verified native PHP 8.1/8.5 shapes** with fresh authorization and recovery evidence. |
| **Status Pages** | Offline EN/FA templates and branding; guarded per-site 404/502 and Nginx-generated 50x delivery, future-site defaults, stopped-site HTTP503 and global unknown-Host **HTTP/80** paths where compatible. Each has its **own** approval and Restore. |
| **FastCGI Cache** | Site-specific source audit, guarded manual Cache Apply/Recheck/Restore, exact URL Clear and **site-owned** full-tree file Clear after verified physical peer isolation. Public HIT/MISS and private BYPASS depend on the actual eligible site/handler. |
| **Activity & Logs** | Operation/stage/error details, correlation IDs, scope and recovery guidance. |

These are **bounded, source- and topology-checked capabilities**, not promises
that every aaPanel release, PHP version, website type or configuration can be
modified. Unsupported or drifted situations report **Needs Review** rather than
silently replacing third-party files. Monitoring is the default; destructive
or shared-service changes require a separate, current, explicit approval.

The optional [ACh aaPanel Bridge](wordpress/ach-aapanel-bridge/README.md)
is a separate WordPress plugin whose ZIP includes a standard
[WordPress `readme.txt`](wordpress/ach-aapanel-bridge/readme.txt), not the
repository-only Markdown guide. Its default state is disconnected. Once the
operator has verified native site-owned Cache and expressly provisioned a
generation-bound manifest, it can assist Nginx Helper's **per-URL GET/HEAD**
invalidation for supported public posts, homepage and first-page taxonomy
archives. It neither installs/configures Nginx Helper nor enables vendor Purge All.

## Important limits

- **Nginx Helper `Purge All` is not certified** for shared or ambiguous physical
  Cache roots. Native **site-owned full-tree Clear** is a different, independently
  guarded operation. Neither should be confused with Bridge's per-URL filtering.
- **New unpublished 0.1.58 narrow observer:** native WP Toolkit failed-install
  `/etc/hosts` alias detection is opt-in, source-pinned to aaPanel **8.0.7 + Nginx**,
  and relies on a **pre-terminal witnessed** single-site operation plus an exact
  vendor-appended `127.0.0.1` line. **The watcher never writes to Hosts.**
  A Linux file lease may forcibly expire while the process is paused; no safe
  no-loss automatic deletion protocol against uncoordinated writers has been
  proved. Exact failure evidence is durably stored first in a private,
  per-operation manual-review record (full canonical domain up to 253
  characters, Operation ID, delivery status). Initial publication uses
  a fsynced private staging file and atomic no-clobber link; incomplete
  stages are ignored. A malformed older canonical record remains
  preserved and visibly flagged for reviewed OS quarantine, while
  other valid reports remain available. The Activity event is delivered
  idempotently, including after worker
  crashes, log failures and at ERROR verbosity. The authorized Activity
  endpoint projects these retained records even after log rotation/corruption.
  Routing also displays the most recently recorded domain and delivery state.
  The selected-site Hosts editor may be unavailable once aaPanel has deleted the
  failed site record. Historical applied recovery journals remain inspectable
  and separately approved legacy Restore uses append-only source writes.
  **Automatic Hosts remediation and shared PHP-FPM drift reconciliation remain
  unresolved P0 requirements.** The plugin also lacks general shared-cache
  purge, unsupported PHP pool rewrites, silent VHost repair and blanket
  status-page deployment. Once explicitly activated, selected-site
  Nginx guards enforce their fixed paths per request; they are not a global
  firewall, automatic scanner blocker or verified HTTP/3 edge protection.
  Native VHost regeneration and foreign Nginx rule conflicts require fresh
  inspection; never claim silently self-healing security without evidence.
- Per-site website roots are discovered from current native aaPanel records,
  not assumed under `/www/wwwroot`. Confirmed QA roots include `/www/acdomains`
  and `/www/other-sites`; unrelated aaPanel service-install prefixes and
  custom/unsupported Nginx layouts are separately gated.
- Global **unknown-Host HTTPS/443** requires an unresolved TLS/SNI and
  operator-policy decision; the tested HTTP/80 path does not authorize it.
- WordPress Bridge does not cover arbitrary Host aliases, query-style or
  noncanonical URLs, author/date/paginated archives, shared `WORDPRESS` cache
  roots or Nginx Helper's recursive purge.
- QA is scoped to the environments and request paths actually exercised;
  Production deployment and destructive host changes require **separate**
  environment-specific approval.

## Installation, use and recovery

1. On an **authorized** aaPanel target, download the published native ZIP and
   `SHA256SUMS.txt` from [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases).
   Verify the downloaded checksum; do not treat an arbitrary branch build as
   a public release.
2. In aaPanel use **App Store → Third-party Plugins → Import Plug-ins**
   to import the **native** ZIP. The separately versioned WordPress ZIP, if
   needed, is installed through WordPress **Plugins → Add New → Upload Plugin**.
3. Open Customizer, refresh Overview and website inventory, inspect the exact
   selected site/version/source, then use **Preview/Check readiness → explicit
   approval → Apply → fresh Recheck** for a supported operation. For shared
   PHP-FPM, review **every affected site**. For Recovery, use the original
   module and saved Recovery ID; never blindly retry an uncertain write.
4. On a compatible, **authorized non-production** aaPanel 8.0.7/Nginx host
   running the *new source only*, navigate to **Routing & Nginx → Native WordPress
   failed-install witness**. Click **Inspect witness policy**, review the
   observation-only scope, check its consent box and choose
   **Enable failed-install witness**. The plugin-owned systemd
   `.path`/`.timer`/`.service` units watch *future* single-site WP Toolkit
   installations. They **never edit Hosts**, even when they identify an exact
   orphan alias. Inspect **Activity & Logs** for the affected domain and have an
   OS operator review `/etc/hosts` and the now-terminal installation before a
   manual correction. **Emergency disable** stops future observation.
   Use **Recheck historical recovery** when an older, already-applied recovery
   is uncertain; any separate reviewed legacy Restore requires verifying the
   Recovery ID and unchanged current file. A missed pre-terminal event is
   never retroactively inferred as safe. If the progress record was replaced,
   first disable, run Recheck, and use **Discard stale witness** only with a
   distinct approval and no live native
   task or prepared recovery. This action does not edit Hosts.
5. After upgrade/reinstall, verify installed source **and** resident panel
   helper behavior. aaPanel may keep older Python imports alive despite
   matching installed ZIP bytes and even a matched entrypoint version.
   A resident-helper mismatch disables non-emergency WP witness controls
   while preserving Emergency disable; Activity shows a diagnostic.
   A panel-only reload is a separately approved recovery action, not part
   of automatic installation.

The [native integration guide](docs/aapanel-integration.md) details the actual
workflows and adapter boundaries. Follow the [upgrade and recovery runbook](docs/aapanel-upgrade-recovery.md)
before any authorized lifecycle or rollback operation.

## Development

Build local deterministic **unpublished** ZIPs from this repository:

```bash
python3 -B scripts/build_plugin.py --output /tmp/ach-customizer.zip
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

Run the same core source gates as
[`.github/workflows/ci.yml`](.github/workflows/ci.yml):

```bash
python3 -B -m compileall -q plugin/ach_customizer scripts tests
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_inventory_ui.cjs
sh -n plugin/ach_customizer/install.sh
```

PHP lint, embedded JavaScript parsing and ZIP builds also run in CI.
A green source suite or locally built ZIP **does not** replace native
installed-package/browser/recovery testing, independent review, or
Owner-authorized integration and publication.

## Where project truth lives

| Question | Canonical owner |
| --- | --- |
| What is the product, scope and lasting contract? | [Project specification](docs/PROJECT-SPEC.md) |
| How do actual aaPanel adapters work and what are their limits? | [Native integration guide](docs/aapanel-integration.md) |
| How is an uncertain upgrade/reload/recovery handled? | [Upgrade/recovery runbook](docs/aapanel-upgrade-recovery.md) |
| How does the optional WordPress plugin work? | [Bridge package `readme.txt`](wordpress/ach-aapanel-bridge/readme.txt) for the installed plugin; [repository-only advanced guide](wordpress/ach-aapanel-bridge/README.md) for operators/developers |
| What is published now? | [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) and the source version manifests |
| What is unfinished? | [#2 customization / PHP / Cache](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10 Status Pages](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [#21 native QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) |
| Which exact code, review and tests passed? | [Pull requests](https://github.com/AChWorks/ach-aapanel-customizer/pulls), [CI](https://github.com/AChWorks/ach-aapanel-customizer/actions), [QA receipts in #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) and retained [`docs/evidence/`](docs/evidence/) |

**Current bounded QA example:** the exact public native 0.1.51 ZIP was
installed on an isolated aaPanel 8.0.7 guest (**57/57** member hashes matched),
then safely Restored after two genuine WooCommerce customers showed separate
sessions and private cart/account/checkout BYPASS on HTTP/80 and HTTPS/443.
See the [exact acceptance and cleanup receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6938476216).
That result is not a claim about live payments, every extension or Production.

Contribute through coherent, reviewable pull requests. Do not rewrite vendor
aaPanel/Nginx Helper core files, invent platform compatibility, or merge,
release or deploy through an unfulfilled project approval gate.
