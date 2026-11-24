# ACh aaPanel Customizer

A native aaPanel plugin for **inspect → preview → explicit apply → recheck → restore** of administrator-selected site and service customizations. It runs **inside aaPanel**, not as another web console, a WordPress-only tool, or an unattended server optimizer.

## Install

**Use the assets and checksums from [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases)**. GitHub source archives and locally built ZIPs are not substitutes for a published, checksum-verified package.

1. Download the matching `ach-aapanel-customizer-vX.Y.Z.zip` and `SHA256SUMS.txt` from the **same Release**. Verify the native ZIP against the supplied SHA-256 manifest.
2. In aaPanel open **App Store → Third-party Plug-ins → Import plugins** and import the native ZIP. Open **ACh aaPanel Customizer → Home → Refresh observations**.
3. Choose **Manage a website** or **Websites → Summary & changes**, select the exact native website, and start with a read-only inspection of its task. Use explicit **Apply**, **Recheck** and **Restore** only for the chosen operation.
4. **Optional:** install the separately versioned `ach-aapanel-bridge-vX.Y.Z.zip` through **WordPress → Plugins → Add New → Upload Plugin** only for supported WordPress Cache integration. The Bridge is not embedded in or required by the native ZIP.

The WordPress Bridge 0.1.11 includes Persian (`fa_IR`) and uses
WordPress's current administration locale, with English fallback. Its
product name and technical identifiers remain unchanged; the native
aaPanel interface is independent. Obtain the actual published Bridge
version from Releases.

Native and Bridge versions advance independently. Until the Owner explicitly accepts a final named baseline, published development versions (including Stable labels) do not require backward-compatibility adapters or migrations. See [the compatibility policy](docs/PROJECT-SPEC.md#8-installation-enablement-update-and-uninstall-semantics). Existing operator data and applied settings are not silently deleted. Always obtain the **latest published** assets and SHA256 checksums from Releases rather than assuming the source tree is a Release.

A successful import does **not** prove that aaPanel's resident Python helpers were refreshed. If the installed files and observed behavior disagree, consult the [native ZIP upgrade and resident-worker recovery runbook](docs/aapanel-upgrade-recovery.md); preserve the saved Recovery ID and recheck before retrying. Neither ZIP performs a Production deployment or enables optional enforcement on its own.

## What you can do

The task-first destinations below describe the redesigned interface
introduced in Native 0.1.101 and subsequently refined, including the shared
wrapped-approval spacing correction in PR #139. The authoritative
published package and its actual availability are recorded in GitHub
Releases, not implied by this source guide.

| Start here | Tasks and boundaries |
| --- | --- |
| **Home / Server → Monitoring controls** | Inspect availability and packaged/resident entrypoint versions. Manage Monitor switches; a matching entrypoint is not proof that imported helpers are current. |
| **Websites → Summary & changes** | Browse native sites, bound domains and file-based WordPress/WooCommerce classifications; compare and explicitly save selected-site or all-sites observation baselines (not host configuration). |
| **Websites → Protection** | Inspect and apply a selected-site recoverable sensitive-file Guard and optional pre-PHP XML-RPC protection. Shared Nginx reload is disclosed. |
| **Websites → WordPress** | Debug, system WP-Cron, application XML-RPC and HTTPS URLs. Separate source checks and recovery; certificates are not installed. |
| **Websites → Routing & diagnostics** | Nginx/VHost observations, selected-site local Hosts and drift/Recovery evidence; no public DNS change. |
| **Websites → Cache & performance** | Inspect, Connect WordPress, Apply/restore, Clear Cache, and Advanced URL mapping. Exact site-owned cache operations and HTTP/HTTPS origin verification; vendor Purge All remains separate. |
| **Server → PHP services** | Inspect service/sites, desired policy, explicit shared Apply, independently available saved-service Recovery and separately opted-in automatic repair of witnessed regeneration. |
| **Server → Local hostnames / Attack protection / Default HTTP/TLS** | Remove an exact chosen origin-local loopback alias without touching the system hostname; site-log Fail2ban bans are origin-wide; orphan Recovery is site-selection-independent. Unknown HTTP/80 and eligible TLS/443 fallback are separate. |
| **Error pages** | Design/preview 11 EN/LTR + 11 FA/RTL templates; explicitly choose website delivery, future-site defaults, stopped-site 503 or server fallback. TLS handshake rejection does not create certificates/listeners. |
| **Activity & recovery** | Read exact operation stage, result, time and Operation/Recovery IDs in Operation details; open the owning task then Recheck without inferring a site or authorizing Restore. |

The optional [ACh aaPanel Bridge](wordpress/ach-aapanel-bridge/README.md) is a separate WordPress plugin. It supports verified, generation-bound, eligible per-URL invalidation; it does **not** automatically install Nginx Helper, replace vendor Purge All or make a shared Cache directory safe.

## Operating model

- A **primary aaPanel administrator** explicitly chooses each write. Preview and Recheck are observational; saved observation baselines do not modify sites. Source identity, authorization, owned files and recovery are checked again when changing host settings.
- A site-specific Guard requires a compatible server-level `extension/<site>/*.conf` include and root-owned directory. A missing or foreign include is reported with remediation; the plugin does not silently rewrite the site's native VHost.
- **External aaPanel changes can invalidate an earlier approval.** After domain, VHost, PHP or WordPress regeneration, inspect and Recheck; Restore the exact saved recovery if needed, then perform one fresh approved Apply. There is no catch-all automatic site-repair watcher.
- A site-scoped Fail2ban scanner can ban access to the **entire origin**, not merely its selected website. On an untrusted writable log or unclear proxy real-client IP, it refuses or needs operator review; never assume a check proves CDN attribution.
- WordPress/WooCommerce *files detected* does not prove application activation. Source and local probes do not prove private-customer Cache safety or external HTTPS. Do not run vendor **Purge All** on shared/ambiguous physical Cache roots.
- Server-scoped Guard and Status Pages extensions recognize canonical native public/run subdirectories. Extension 404 uses the observed HTTP baseline; identical content needs no Apply and does not establish Recovery. Unmanaged 502/50x Recheck and preflight use the same actual served-file source, not an unrelated HTTP response. Existing-file replacement remains separately ownership-checked.
- The Nginx TLS default policy leaves existing named HTTPS sites and certificates alone, and refuses unsupported listener/default-server conflicts. Status Pages HTTP/80, HTTPS/443, and application-layer pages have different delivery and recovery scopes.

**Verified reference, not a universal support promise:** non-production **aaPanel 8.0.7**, Nginx, PHP-FPM **8.1/8.5** on representative sites. Other aaPanel/Nginx/PHP writer layouts are inspected by capability, not arbitrarily rejected by version, but a write requires a supported real source/ownership contract. See [installed-native QA evidence, exact candidate and remaining coverage](https://github.com/AChWorks/ach-aapanel-customizer/issues/21), [feature/compatibility backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2) and [TLS/Status Pages scope](https://github.com/AChWorks/ach-aapanel-customizer/issues/10). **Publishing a Stable Release is not a claim of comprehensive Production certification or permission to deploy to Production.**

## Task-first interface redesign

The [accepted screen and task contract](docs/UX-REDESIGN.md) defines the
five-destination native shell and task-stage navigation. S1–S5 were merged
through PRs #129–#133 and refined through #136. The UI groups the original
module-owned controls without another privileged writer, permission route or
recovery store. Task navigation alone never authorizes a write. Direct task
shortcuts open their named stage without silently selecting a website or
changing a scope.

Disabled actions explain their actual missing prerequisites through
inline guidance and an anchored help popover, available via pointer,
keyboard or touch. A request-producing action shows progress while
its operation runs; it does not automatically open disabled help on
click or settlement. Explicit approval and native recovery guards remain
authoritative.

See [Issue #128](https://github.com/AChWorks/ach-aapanel-customizer/issues/128)
for current acceptance and delivery status, and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
for exact installed QA receipts. Automated task/geometry tests and bounded
live Apply/Restore are distinct from unassisted human task completion.
Public Release and Production require separate Owner approval. Use the
published assets and checksums from GitHub Releases for normal installation.

## License

**Mozilla Public License 2.0 (MPL-2.0)** governs the original project source,
including the native aaPanel plugin and the separately distributed WordPress
Bridge, unless an individual file explicitly carries different terms. Read the
[complete MPL-2.0 license](LICENSE). Both independently built installer ZIPs
include that same license text. The MPL requires modified covered source files
to remain available under its terms when distributed; it permits combination
with other software through its file-level copyleft and its unmodified
Secondary Licenses provision. Existing releases and their original contents
remain unchanged; check the exact Release assets for the terms shipped in
that version.

## Development and verification

The native and WordPress packages are independent deterministic ZIPs:

```bash
python3 -B scripts/build_plugin.py --output /tmp/ach-customizer.zip
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

The checked-in [CI workflow](.github/workflows/ci.yml) compiles Python, runs source/unit/API/UI tests, validates the embedded JavaScript, lints companion PHP and builds both ZIPs. Locally:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_inventory_ui.cjs
sh -n plugin/ach_customizer/install.sh
```

The isolated real-DOM task/geometry and Status 50x checks use Playwright,
Chromium and the pinned aaPanel jQuery 2.2.4 test fixture documented in
[the native guide](docs/aapanel-integration.md#isolated-browser-regression).
They intercept network requests and never use a live panel or credentials.

These checks do **not** replace authenticated, installed aaPanel/browser/HTTP/HTTPS/site-recovery testing. The [native integration guide](docs/aapanel-integration.md) contains exact operator/runtime prerequisites and the protected QA Browser procedure. Use the **one retained QA VM** and existing credential workflow recorded in Issue #21; do not create more QA guests or reset its credentials.

## Where the authoritative information lives

| Question | Owner |
| --- | --- |
| Durable product scope and design decisions | [Project specification](docs/PROJECT-SPEC.md) |
| Technical adapters, supported source shapes, native operator procedures | [Native integration guide](docs/aapanel-integration.md) |
| Upgrade mismatch, stale resident workers and safe recovery | [Upgrade runbook](docs/aapanel-upgrade-recovery.md) |
| Current version, installable packages, checksums and release notes | [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) |
| Code, exact review, CI and change provenance | [Pull requests](https://github.com/AChWorks/ach-aapanel-customizer/pulls) and [Actions](https://github.com/AChWorks/ach-aapanel-customizer/actions) |
| Outstanding capabilities, compatibility and retained installed QA | [#2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [#10](https://github.com/AChWorks/ach-aapanel-customizer/issues/10), [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) |
| Historical, version-bound native evidence | [Existing evidence files](docs/evidence/) and Issue/PR history |

Keep actual operator choices simple, errors specific and recovery honest; preserve unrelated sites, third-party state and functional diagnostic logs.
