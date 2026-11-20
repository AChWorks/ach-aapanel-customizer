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
| **Website list** | Refresh paginated native website inventory, compare site/domain changes without an arbitrary site or alias count cap, and save selected-site or all-sites observation baselines. Baseline changes never modify website configuration. |
| **Routing & Nginx** | Inspect current origin-local loopback entries and remove a chosen hostname with one administrator click, whether WordPress installation succeeded or failed and even without a native website record (merged, unpublished source v0.1.65). Existing site-specific recovery and source-scoped Nginx tools remain available; no unattended Hosts cleanup. Published v0.1.51 does not include these additions. |
| **PHP-FPM** | Discover and inspect PHP installations based on actual native files (including older versions), view file/socket relationships, and use guarded Apply/Restore only for currently implemented 8.1/8.5 adapters. Native post-terminal PHP-FPM repair is merged in unpublished v0.1.62, with successful isolated ordinary-systemd QA for both successful and failed native WordPress setup. Complete authenticated PHP-FPM policy/automatic-repair UI and Production qualification remain outstanding (the separate primary-admin Login/Local Hosts UI has passed). |
| **Status Pages** | Offline EN/FA branding and templates, with nonblocking readability advice for low-contrast operator color choices in unreleased source; source-scoped Nginx status-page delivery and recovery are available for their verified native configurations. Merged, unpublished v0.1.64 validates complete native Nginx source graphs and peer inventories instead of fixed site/file counts before those writes. |
| **FastCGI Cache** | Site-specific source audit, guarded manual Cache Apply/Recheck/Restore, exact URL Clear and **site-owned** full-tree file Clear after verified physical peer isolation. Public HIT/MISS and private BYPASS depend on the actual eligible site/handler. The merged v0.1.66 native probe recognizes exact applied site-owned Cache headers on stock or wpfastcgi PHP. Real two-customer WooCommerce private-session HTTP/80 isolation and one-site WordPress/Nginx Helper post-update HTTP/80 invalidation have also passed on isolated native QA. These do not certify HTTPS, other sites, Purge All or Production. |
| **Activity & Logs** | Operation/stage/error details, correlation IDs, scope and recovery guidance. |

**Owner-approved product direction:** Keep tasks usable and straightforward.
Do not invent hard-coded site/domain count or version limits when native
capabilities or paginated data can be discovered. For acceptable residual
risk, show a brief, nonmandatory pre-action note; an authorized administrator
can continue without completing every recommendation. Real authorization,
target correctness, and avoidance of unintended unrelated data loss remain
essential. See the [project-wide operating principle](docs/PROJECT-SPEC.md#owner-wide-operating-principle-simplicity-and-informed-choice-2026-11-20).
Native **0.1.69** is merged in `main` but **not publicly released**. Its
ZIP was installed through the real aaPanel importer on isolated QA (63/63
installed package bytes matched CI); the real site-owned Cache
**wpfastcgi → stock** handler recovery completed Preview/Apply/Recheck/Restore
with preserved original configuration. The genuine protected **administrator
Browser login, Local Hosts one-click Remove, Activity correlation, and
no-session/CSRF refusal** also passed on installed 0.1.69. These specific
Browser tests are no longer pending; full PHP-FPM/Status Pages/Nginx UI
acceptance and Production qualification remain separate. Follow the
[exact QA Browser login runbook](docs/aapanel-integration.md#native-authenticated-browser-qa-runbook-aapanel-807)
before repeating earlier login-tool diagnostics. No release or Production
deployment is implied; verify current GitHub/CI/releases before installation.

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
- **Origin-local Hosts removal (merged, unpublished 0.1.65):** open **Routing & Nginx**
  to see current local loopback hostnames, regardless of WordPress installation
  result or whether aaPanel still has a matching site. Select the hostname and
  press **Remove selected hostname**: no watcher or second approval checkbox is
  required, and only matching loopback aliases are removed. The server's
  own `/etc/hosts` is the evidence. This is an explicit primary-admin action,
  not unattended cleanup, a DNS change or a universal transaction with foreign
  writers. Legacy failed-WP witness records and historical recovery actions
  remain accessible when previously created; they are not prerequisites.
  Original v0.1.60 native-WP watcher remains optional and read-only for
  diagnostic event evidence, while PHP-FPM has its separate automation.
- **Unpublished 0.1.62 automatic FPM repair:** following explicit one-time
  primary-admin approval of saved PHP 8.1/8.5 shared `[www]` values, a separate
  owned `ach-customizer-fpm-auto.path`/`.timer`/`.service` tracks the
  source-verified aaPanel native WP Toolkit start and terminal. It captures
  FPM file identity before the native task and repairs only a changed source
  after the exact terminal event, revalidating the **administrator-reviewed**
  shared-site impact SHA and Monitor/policy revisions. The native writer's
  RAM-derived numeric output and unchanged max_requests are verified
  before each guarded write, preventing unrelated administrator edits.
  Current site mapping is checked before syntax-validated reload and runtime
  verification. Failed native WP initialization that removed the temporary
  site additionally requires confirmed absence of its site/domain/binding
  records. Prior automatic recovery is archived
  by operation identity before repeat repair. Journal event-token
  reconciliation preserves truthful Operation IDs after worker crashes.
  Emergency Disable is durably queued and auto-completed if a guarded
  reload holds the shared lock; no repeated click is necessary.
  No ordinary installation activates this watcher; skipped starts and unrelated PHP changes do not
  authorize writes. The exact 0.1.62 source passed isolated real aaPanel
  8.0.7 systemd-only WordPress PHP 8.1 success and post-optimizer
  PHP 8.5 failure automatic repair. See the
  [native QA evidence](docs/evidence/aaPanel-8.0.7-2026-11-19-fpm-auto-v062-native-systemd-qa.json).
  It is not a universal FPM hook or a Hosts fix. Independent exact-source
  review and PR #102 integration passed. The **PHP-FPM-specific** authenticated Browser Apply/automatic-repair
  acceptance and Production qualification remain separate gates. Do not deploy to Production based on isolated QA alone.
- Per-site website roots are discovered from current native aaPanel records,
  not assumed under `/www/wwwroot`. Confirmed QA roots include `/www/acdomains`
  and `/www/other-sites`; unrelated aaPanel service-install prefixes and
  custom/unsupported Nginx layouts are separately gated.
- Source version 0.1.67 fixes the optional **global unbound HTTP/80** route:
  native IPv4-only, IPv6-only and dual-stack wildcard listener families are
  checked separately. Missing families are neither probed nor enabled;
  Apply/Restore retain exact recovery and source ownership. Narrow address-only
  listeners and IPv6 dual-mode sockets are not silently widened. No HTTPS/443 change.
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
| How do I log into isolated native QA without false credential failures? | [Verified protected Browser login runbook](docs/aapanel-integration.md#native-authenticated-browser-qa-runbook-aapanel-807) and [Issue #21 test receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-7045862216) |
| How is an uncertain upgrade/reload/recovery handled? | [Upgrade/recovery runbook](docs/aapanel-upgrade-recovery.md) |
| How does the optional WordPress plugin work? | [Bridge package `readme.txt`](wordpress/ach-aapanel-bridge/readme.txt) for the installed plugin; [repository-only advanced guide](wordpress/ach-aapanel-bridge/README.md) for operators/developers |
| What is published now? | [Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) and the source version manifests |
| What is unfinished? | [#2 customization / PHP / Cache](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10 Status Pages](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [#21 native QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) |
| Which exact code, review and tests passed? | [Pull requests](https://github.com/AChWorks/ach-aapanel-customizer/pulls), [CI](https://github.com/AChWorks/ach-aapanel-customizer/actions), [QA receipts in #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) and retained [`docs/evidence/`](docs/evidence/) |

**Historical published-package QA example (v0.1.51):** the exact public native 0.1.51 ZIP was
installed on an isolated aaPanel 8.0.7 guest (**57/57** member hashes matched),
then safely Restored after two genuine WooCommerce customers showed separate
sessions and private cart/account/checkout BYPASS on HTTP/80 and HTTPS/443.
See the [exact acceptance and cleanup receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6938476216).
That result is not a claim about live payments, every extension or Production.

Contribute through coherent, reviewable pull requests. Do not rewrite vendor
aaPanel/Nginx Helper core files, invent platform compatibility, or merge,
release or deploy through an unfulfilled project approval gate.
