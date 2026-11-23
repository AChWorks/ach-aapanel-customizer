# ACh aaPanel Customizer

A native aaPanel plugin for **inspect → preview → explicit apply → recheck → restore** of administrator-selected site and service customizations. It runs **inside aaPanel**, not as another web console, a WordPress-only tool, or an unattended server optimizer.

## Install

**Use the assets and checksums from [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases)**. GitHub source archives and locally built ZIPs are not substitutes for a published, checksum-verified package.

1. Download the matching `ach-aapanel-customizer-vX.Y.Z.zip` and `SHA256SUMS.txt` from the **same Release**. Verify the native ZIP against the supplied SHA-256 manifest.
2. In aaPanel open **App Store → Third-party Plug-ins → Import plugins** and import the native ZIP. Open **ACh aaPanel Customizer → Overview → Refresh state**.
3. Open **Website list**, refresh the inventory and choose a site using the **Selected website → Website** dropdown. Start with a read-only inspection; use explicit **Apply**, **Recheck** and **Restore** only for the chosen operation.
4. **Optional:** install the separately versioned `ach-aapanel-bridge-vX.Y.Z.zip` through **WordPress → Plugins → Add New → Upload Plugin** only for supported WordPress Cache integration. The Bridge is not embedded in or required by the native ZIP.

The first Stable release was **Native 0.1.98** with optional **WordPress Bridge 0.1.9**. Later native and Bridge package versions advance independently. Earlier development previews are historical, not mandatory compatibility/migration targets. Always obtain the **latest published** assets and SHA256 checksums from Releases rather than assuming the source tree is a Release.

A successful import does **not** prove that aaPanel's resident Python helpers were refreshed. If the installed files and observed behavior disagree, consult the [native ZIP upgrade and resident-worker recovery runbook](docs/aapanel-upgrade-recovery.md); preserve the saved Recovery ID and recheck before retrying. Neither ZIP performs a Production deployment or enables optional enforcement on its own.

## What you can do

| aaPanel section | Capabilities and boundaries |
| --- | --- |
| **Overview** | Inspect module availability, Monitor switches and packaged/resident entrypoint versions. A matching entrypoint is not proof that every imported helper is current. |
| **Website list** | Page through real aaPanel sites, bound domains and file-based WordPress/WooCommerce classifications. Compare native-record changes and explicitly save a selected-site or all-sites *observation* baseline; this does not Apply host settings. |
| **Routing & Nginx** | Inspect native VHost/source; find and remove a chosen **origin-local Hosts loopback alias** with one administrator click; apply a selected-site, recoverable sensitive-file Guard (optional pre-PHP XML-RPC block). Optional Fail2ban scanner bans require trusted native access logs and have **origin-wide firewall impact**, even when watching one site. Manage selected WordPress HTTPS URLs, Debug, system Cron and application-level XML-RPC by separate guarded actions. |
| **FastCGI Cache** | Inspect a selected site's source and real local Cache observations; opt in to site-scoped Cache Apply/Recheck/Restore and precisely verified Cache clears. A separate WordPress/Nginx Helper connection is available when private physical Cache ownership and prerequisites are satisfied. |
| **PHP-FPM** | Discover installed PHP/services and shared pool consumers; inspect, save, apply and restore supported shared `[www]` policies. A separately enabled systemd worker can repair *witnessed* native PHP regeneration against saved intent; normal plugin import does not enable it. |
| **Status Pages** | Preview 11 English/LTR + 11 Persian/RTL offline designs, set scoped branding and explicitly manage supported site/global Nginx error-page modes. Opt-in **unknown-SNI HTTPS/443 handshake rejection** requires an already configured, eligible HTTPS listener; it does not create certificates or a listener. |
| **Activity & Logs** | Read real stage, result, timestamp and Operation/Recovery IDs; retain these when an action is uncertain. |

The optional [ACh aaPanel Bridge](wordpress/ach-aapanel-bridge/README.md) is a separate WordPress plugin. It supports verified, generation-bound, eligible per-URL invalidation; it does **not** automatically install Nginx Helper, replace vendor Purge All or make a shared Cache directory safe.

## Operating model

- A **primary aaPanel administrator** explicitly chooses each write. Preview and Recheck are observational; saved observation baselines do not modify sites. Source identity, authorization, owned files and recovery are checked again when changing host settings.
- A site-specific Guard requires a compatible server-level `extension/<site>/*.conf` include and root-owned directory. A missing or foreign include is reported with remediation; the plugin does not silently rewrite the site's native VHost.
- **External aaPanel changes can invalidate an earlier approval.** After domain, VHost, PHP or WordPress regeneration, inspect and Recheck; Restore the exact saved recovery if needed, then perform one fresh approved Apply. There is no catch-all automatic site-repair watcher.
- A site-scoped Fail2ban scanner can ban access to the **entire origin**, not merely its selected website. On an untrusted writable log or unclear proxy real-client IP, it refuses or needs operator review; never assume a check proves CDN attribution.
- WordPress/WooCommerce *files detected* does not prove application activation. Source and local probes do not prove private-customer Cache safety or external HTTPS. Do not run vendor **Purge All** on shared/ambiguous physical Cache roots.
- The Nginx TLS default policy leaves existing named HTTPS sites and certificates alone, and refuses unsupported listener/default-server conflicts. Status Pages HTTP/80, HTTPS/443, and application-layer pages have different delivery and recovery scopes.

**Verified reference, not a universal support promise:** non-production **aaPanel 8.0.7**, Nginx, PHP-FPM **8.1/8.5** on representative sites. Other aaPanel/Nginx/PHP writer layouts are inspected by capability, not arbitrarily rejected by version, but a write requires a supported real source/ownership contract. See [installed-native QA evidence, exact candidate and remaining coverage](https://github.com/AChWorks/ach-aapanel-customizer/issues/21), [feature/compatibility backlog](https://github.com/AChWorks/ach-aapanel-customizer/issues/2) and [TLS/Status Pages scope](https://github.com/AChWorks/ach-aapanel-customizer/issues/10). **Publishing a Stable Release is not a claim of comprehensive Production certification or permission to deploy to Production.**

## Task-first interface redesign (source in progress, not released)

The Owner-approved redesign is being implemented in stages under
[Issue #128](https://github.com/AChWorks/ach-aapanel-customizer/issues/128)
and the [screen and task contract](docs/UX-REDESIGN.md). The **merged S1**
source (PRs [#129](https://github.com/AChWorks/ach-aapanel-customizer/pull/129)
and [#130](https://github.com/AChWorks/ach-aapanel-customizer/pull/130))
has a task-first native shell with **Home**, **Websites**, **Server**,
**Error pages** and **Activity & recovery**. It is not part of the
published v0.1.100 package.

The **S2–S4 candidate is under development/review, not merged or installed**.
Its task-level navigation groups the original module-owned controls instead of
introducing another writer, store, permission route or Recovery mechanism:

| Start here in redesigned source | Next task choices | What stays separate |
| --- | --- | --- |
| **Websites → choose a verified website → Protection** | Inspect / enable sensitive-file Guard, optional Nginx XML-RPC rule | Other websites, shared Nginx reload and unrelated settings |
| **Websites → WordPress** | Debug, WP-Cron, XML-RPC, HTTPS URLs | Independent WordPress source and Recovery for each task; HTTPS certificates not installed |
| **Websites → Routing & diagnostics** | Nginx/VHost observations, selected-site Hosts, drift and saved Recovery | Inspect never Apply; local Hosts are not public DNS |
| **Websites → Cache & performance** | Inspect, Connect WordPress, Apply/Restore, exact Clear, advanced Bridge URL mapping | Vendor Purge All, other sites' physical Cache, and separate Recheck/approval |
| **Server → PHP services** | Inspect, desired Monitor Policy, guarded shared Apply, saved-service Restore | Saving a policy never reloads PHP; Restore remains available when discovery is incomplete |
| **Server → Attack protection / Local hostnames / Default HTTP/TLS** | Site-log scanner and independent orphan-jail recovery; local aliases; unknown HTTP/80 and TLS/443 | Origin-wide firewall or Nginx effects are never presented as site-only |
| **Error pages** | Design/preview, selected-site delivery, future-site defaults, stopped-site 503, server fallback | The eleven EN/FA templates, explicit scope and independent backend source/recovery authority |
| **Activity & recovery** | Inspect event and IDs, open the original owning task, then Recheck | An Activity row does not select a site or authorize a Restore |

The original native UI behavior, source and safety checks remain the authority
for all live actions; task navigation alone never authorizes a write. A disabled
operation explains its missing evidence and guides the operator back to Recheck
or the relevant source check. The new screen layout and novice flows require
**S5 installed-native acceptance**, independent source review, and separate
Owner Merge and Release approvals before they may be considered delivered.

The **Install** and **What you can do** sections above describe the currently
**published native ZIP** (seven-tab interface), not an unreviewed source build.
Use published assets and matching checksums from GitHub Releases. Historical
Customizer UI compatibility is not required because no previous Customizer
Production installation exists; aaPanel and active vendor integrations, primary
administrator authorization, current Recovery data and peer safety remain binding.

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
