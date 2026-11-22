# ACh aaPanel Customizer — Project Specification

- **Status:** Canonical product intent — staged development with reviewed pre-release packages; Production deployment remains separately gated
- **Repository:** `AChWorks/ach-aapanel-customizer`
- **Owner:** AChWorks
- **Product:** ACh aaPanel Customizer
- **Primary distribution:** Native, installable aaPanel plugin

> **QA environment policy (Owner, 2026-11-21):** Continue all non-production
> native development/testing on the **same retained Running VM** recorded in
> [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
> Never create, replace, stop or delete that VM, or create disposable VM
> snapshots during development. Existing credentials and sites persist.
> This operating rule does not widen source compatibility or permit
> Production rollout. Older multi-VM QA experiments are historical evidence.

## 1. Mission

Create a native aaPanel plugin through which an administrator can **customize aaPanel itself, its built-in modules, installed plugins, websites, and the services they manage**, without repeatedly reapplying fragile manual edits after new-site creation, plugin changes, or aaPanel upgrades.

The product manages *operator-approved desired behavior* rather than blindly overriding whatever aaPanel currently generates. It makes customizations visible, understandable, maintainable, and recoverable.

**Identity:** This is an aaPanel **customization system**, not merely a WordPress optimization tool, generic hosting control panel, separate administration service, or automatic server optimizer.


### Owner-wide operating principle: simplicity and informed choice (2026-11-20)

**Applies to every existing and future module**, including UI, configuration,
website operations, security controls, repair, automation and diagnostics.
Prefer the smallest understandable implementation that performs the intended
operation. Do not add compatibility allowlists, exhaustive scenario checks,
persistent recovery machinery or strict blocking preconditions merely for
hypothetical risks.

Avoid **arbitrary hard-coded limits** on supported versions, paths, ports,
providers, domains, counts, payload sizes, timeouts or feature combinations.
When a property varies by deployment, discover the actual environment or use
existing operator configuration instead of freezing a convenient test value
into a product restriction. Lack of prior test coverage alone is not a reason
to block an otherwise supported action; explain uncertainty and let the
operator proceed when technically feasible. Retain fixed values only when
required by an actual protocol, resource capacity, correctness or evidenced
safety boundary, and make legitimately operator-variable settings adjustable.

If the operation could have side effects or some checks are unverified, show
the administrator a **brief, plain-language pre-action note** identifying the
affected scope, meaningful risks and a few suggested checks (such as verifying
a backup or current configuration). These are **recommendations, not a
mandatory checklist**. Provide **Cancel / Continue anyway**. When an
authorized administrator chooses Continue, **execute the intended operation
even when suggested checks remain undone**, and report its real result;
do not require a new mechanism to force every precaution to be satisfied.
Do not silently upgrade uncertainty into a claim of success.

Keep only boundaries justified by an actual correctness requirement, a
demonstrated destructive failure, genuine access/authorization constraints,
or the inability to identify the intended target. Operator confirmation does
not authorize unrelated data deletion or make an inherently destructive
concurrent write safe; solve such concrete problems with the simplest correct
operation or a clearly scoped manual route, not layered hypothetical defenses.
Protect the intended operation from errors while preserving the administrator's
choice over acceptable *disclosed* residual risk.

This owner decision governs subsequent design and the simplification of
overly defensive existing workflows. An explicit Save/Reset button suffices
as an operator decision for plugin-owned website observation baselines and
branding preferences; do not require a second approval checkbox for these
low-risk state updates. Low-contrast branding is a nonblocking accessibility
note, not a schema rejection. Paginate native inventories rather than
rejecting an otherwise valid 101st site, domain alias or branding scope.
A read-only inspection must not reject actual PHP installations, additional
native Nginx source files, or large but valid local inventories merely
because they exceed a convenient test quantity. Prefer actual stable
enumeration and parser evidence, with byte/resource bounds proportionate
to the operation. For saved Monitor-only PHP desired values, a fresh valid
Preview plus explicit Save is sufficient; do not add a redundant checkbox.
Actual PHP-FPM/Cache mutation adapters remain separate and must understand
the target service/configuration before writing.
Earlier checklists and proposed complexity must be re-evaluated against this
principle. Recording it does not imply other runtime controls have changed.


### Owner decision: manual-first site reconciliation (2026-11-22)

For complicated or infrequent changes made outside Customizer (native aaPanel
website regeneration, domain/SSL/PHP assignment, WordPress URLs, Nginx source
or unsupported site layouts), the authorized administrator can **manually
refresh/Recheck the affected site and Apply/Restore the specific policy once**.
If the change does not affect an enabled Customizer policy, no Customizer
action is necessary. Accurate source/runtime/drift status and actionable
Recovery remain mandatory; an external edit never licenses overwriting foreign
settings, certificates, sites or data.

**Do not create new persistent watchers, generic self-healing, automatic
reconfiguration, unsupported source adapters, or recurring scans** merely to
avoid this manual workflow. Existing explicitly accepted PHP-FPM automatic
repair and the WordPress Cache/Bridge normal event behavior continue unchanged.
A new automatic mechanism requires separately evidenced benefit and Owner
acceptance. Success for an uncommon supported configuration can be
**Recheck -> one-time guarded Apply/Restore -> verify** rather than a
forever-running synchronization service. See Issue #2 for the active backlog.

### Owner decision: direct local Hosts removal (2026-11-20)

Unattended /etc/hosts cleanup after WordPress setup is **no longer a product
requirement**. The administrator's explicit **Remove** click authorizes removal
of the chosen hostname's current loopback mappings on the aaPanel origin. On
opening Routing, the plugin must inspect the *actual local Hosts file*, not
infer aliases from a WordPress failure record. The action must work whether
WordPress installation succeeded, failed or left no native site record; it
requires neither a pre-terminal watcher nor a selected website, automatic
cleanup, a second review checkbox or a version-pinned WP writer. It does not
edit DNS, unrelated names or network/peer hosts. Retain primary-admin access,
exact hostname targeting and basic file integrity, but do not invent extra
prerequisite/recovery layers or prevent an informed Remove because no native
site exists. Preserve current-generation manual Hosts Recovery and its owned records.
Retired pre-Stable automatic WordPress Hosts cleanup Restore is not a
supported operator action. Retained old QA records are forensic evidence,
not a mandate to keep obsolete compatibility code. An OS-level edit is not
the required workflow.

### Optional WordPress companion

The native aaPanel plugin remains a standalone aaPanel product. An operator may also install **ACh aaPanel Bridge**, a separate, optional ordinary WordPress plugin (slug `ach-aapanel-bridge`) maintained **in this repository** under `wordpress/ach-aapanel-bridge/`. The companion has its **own independent version** and installable ZIP; do not embed it in the native aaPanel ZIP or make WordPress mandatory for ordinary aaPanel features. Coordinated pre-releases can attach both artifacts after their respective review and release authorization; installation and Production deployment remain separate actions.
The WordPress installable ZIP must include a platform-standard
`readme.txt` (with its `Stable tag` matching the main PHP entrypoint
version). The longer repository-only Markdown guide must not replace
`readme.txt` inside the distributed ZIP. These packaging conventions
do not authorize a WordPress.org Plugin Directory listing or decide
the project's software license.

The companion is **opt-in**, disconnected by default and never required
for native aaPanel functions. After the native and both WordPress plugins are installed, an administrator may run **Connect WordPress Cache (once)** for a selected native WordPress site. This one authorized action configures its private physical Nginx Cache, WordPress Nginx Helper constant, selected PHP open_basedir, Helper unlink_files options and generation-aware Bridge mapping. Ordinary WordPress content changes and repeated use of the vendor's page/site purge buttons need no per-site manual path edits or continuous watcher; site sources that materially change must be reported and rechecked. The corresponding **Disconnect and restore** action recovers the managed site configuration and disables vendor purge before returning to a potentially shared aaPanel path. This one-click path does not install third-party WordPress plugins, support unverified PHP/Nginx layouts, or authorize an arbitrary shared Cache root. The normal native manual Cache Apply remains independently available. Its currently implemented capability is
native-generation-bound, owner-verified per-URL invalidation via the
WordPress Nginx Helper `unlink_files` integration for supported public
post/homepage/taxonomy changes; it does not activate Nginx Helper, create
shared Cache ownership, authorize vendor `Purge All` or prove the effective
Nginx worker state. Keep the companion small and add only evidenced,
reviewed WordPress-side integrations, without turning it into a replacement
for the native plugin. The [companion guide](../wordpress/ach-aapanel-bridge/README.md)
owns operating details, [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2)
owns unmet functionality and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
owns QA evidence. Exact shipping versions belong to GitHub Releases and
the independent source manifests, not this product specification.

## 2. Problem and desired outcomes

aaPanel may regenerate shared and per-site configuration during normal operations. Manually edited files can change unexpectedly when a site is created, a module runs an optimization, or an upgrade replaces generated content. Repeating the same modification across websites is brittle, especially as additional sites or non-WordPress applications are added.

The product should produce these lasting outcomes:

1. Operators can define and inspect intentional, targeted aaPanel customizations in one native interface.
2. Suitable customizations remain effective—or are reliably identified as requiring review—after relevant aaPanel, module, and website lifecycle events.
3. New supported sites and services are discovered without hard-coded domain inventories or manual copying of configuration.
4. Shared controls are correctly distinguished from per-site controls; one site's customization cannot silently corrupt another site's state.
5. Changes are explainable, validated, safely applied, verified, logged, and recoverable.
6. New kinds of aaPanel customization can be implemented as focused modules without rebuilding the product's core.
7. The product remains simple to install, operate, update, disable, and uninstall.

Correctness, continuity, usability, and recoverability matter more than the quantity of settings exposed.

### Native document-root compatibility and per-site security ownership

No website operation may assume all native aaPanel sites live under
`/www/wwwroot`. The currently registered aaPanel site ID/path, domain
bindings and generated VHost root provide the baseline for any selected-site
action. Coexisting native-supported roots (including `/www/acdomains` and
`/www/other-sites`) must work without a separately configured base path.
Re-read and recheck whenever native roots or included source files change.
Unsupported, aliasing or symlinked source/ownership cannot authorize writes.
The static installation prefixes for aaPanel, Nginx and PHP-FPM are **separate**
adapter concerns and need independent compatibility proof if relocated.

The same site-owned identity rule applies to Website inventory, VHost drift,
Status Pages, site-owned cache and WordPress Bridge. A root move invalidates
stale previews, cache manifests and recoveries; never silently replace it
with a default path. Certify each module with representative real custom-root
behavior rather than inferring compatibility from inventory alone.

**Pre-stable internal compatibility policy:** No official production
installation of ACh aaPanel Customizer exists. **Apply this decision across
all Customizer subsystems** (Status Pages, Nginx Guard, PHP-FPM, Cache,
WordPress operations, website management, UI and recovery): remove previous
Customizer version/schema/ruleset recovery shims, historic automatic Hosts
Restore paths, and old role/profiles baseline guesses. Only preserve current
capabilities and the durability/Restore guarantees for operations created
by the current candidate. Names such as aaPanel's `class_v2` and native
Nginx Helper's older cache paths are **external vendor/source contracts**,
not old Customizer adapters; assess them by real active use.
Real aaPanel vendor sources, supported PHP/WordPress versions,
third-party plugin contracts and user-created site files are
external compatibility requirements and must not be removed under this
policy. The persistent QA VM is for testing, not a compatibility customer.

An opt-in site-specific Nginx sensitive-path policy should deny known
sensitive dotfile, backup-directory and upload-PHP requests *before* PHP-FPM
work. Prefer source-verified server-rewrite `if` + `return 403` rather than
a regex-only `location` policy which `^~` Nginx prefixes could bypass.
Do not break legitimate `.well-known` ACME/OAuth, public assets, peer sites
or ordinary downloads. When native Nginx already disables directory listing,
do **not** duplicate that policy. A small fixed pre-PHP rule may block common
website-local `debug.log`/`error_log`, WordPress config backups, raw SQL
dumps and `.bak` artifacts. Do not globally block ZIP files or add a site
crawler, watcher, ownership rewrite or another plugin. Before the first
Stable release, prefer one current source/journal contract; the retained QA
VM must explicitly retire its old test-only state before exercising a
new incompatible policy.
Every active security policy needs fresh
source ownership, guarded apply/reload, live response proof, durable recovery,
separate approval for Restore and drift awareness. Exact URL probes are
not universal proof of full HTTP/2/3, CDN/HTTPS or all custom site aliases.
Security policy starts disabled until primary-admin opt-in. A site
freshly created by aaPanel can lack its Nginx `extension/<site>/*.conf`
include; do not silently edit such a VHost during ordinary inspection.
Show the exact missing-include prerequisite for a one-time operator-owned
correction. The optional Fail2ban scanner consumes native access logs to
make **origin-wide** root firewall decisions: the log file AND its parent
directory must be protected against non-root writing, replacement and
forgery. A `root`-owned file alone inside a `www`-writable directory is
insufficient. Refuse new Scanner Apply with an actionable diagnostic when
the source is untrusted; do not change aaPanel's shared log directory
ownership automatically or remove existing recoverable jails. This boundary
does not pretend that aaPanel's ordinary `www`-writable access logs are
tamper-proof or that a trusted CDN client-IP ban can be enforced at the
origin. After native
aaPanel regenerates a selected-site source, **manual Recheck followed by
one-time guarded Apply/Restore** is the accepted reconciliation route;
a separate automatic Nginx-regeneration watcher is not required. Existing
approved PHP-FPM auto-repair remains a distinct, unchanged capability.

### Owner-confirmed operational acceptance priority (2026-11-18)

The existing Monitor/manual-preview foundation is **not** the operational
completion criterion. Priority outcome is to make recurrent aaPanel/WordPress
provisioning/configuration failures stop requiring repeated manual repair, and
to enforce explicitly opted-in, site/service-scoped protections against
known sensitive-file exposure and abusive traffic. In particular, preserve
approved shared PHP-FPM settings automatically after compatible lifecycle
changes (with verified, recoverable native event/reconciliation ownership),
provide a straightforward administrator-click removal of unwanted local
Hosts loopback aliases even after successful WP installation or a deleted
site record, implement verified Nginx-sensitive-path and
pre-PHP anti-scan rules, and address actual HTTP/2/HTTP/3-aware site-log
Fail2ban compatibility. Site-level `.well-known`/OAuth/hotlink exceptions
and authorized WordPress HTTPS URL, debugging, Cron and XML-RPC corrections
are also required operational outcomes, not simply a list of diagnostics.

Keep native plugin installation observation-only. **Unpublished 0.1.60**
implements an opt-in, source-pinned **observation-only witness** of actual
failed, single-site WP Toolkit installs: it captures a previously alias-free
Hosts baseline during native setup, verifies the terminal failure and exact
vendor-appended loopback alias, then reports **Manual Review Required** with
its operation/domain through Activity. This expected outcome is not a failed
systemd execution. The verified domain/Operation ID and immutable Activity
event must be persisted in a bounded, private per-operation outbox *before*
the terminal token. Preserve the entire canonical native domain (up to
253 ASCII characters) in manual-review Activity; unrelated descriptive
targets keep their existing bound. Atomically publish the initial Outbox
record by fsyncing a private staging inode, atomic no-clobber rename, and directory
fsync. Incomplete stages are non-authoritative. If older canonical evidence
is malformed, retain it intact, identify the affected Operation ID in
Routing/Activity while retaining other valid reports, and require explicit
OS-operator review before private quarantine. Activity delivery must recover
from restart, fsync-to-
receipt crash, verbosity suppression and log rotation without duplicate
operator-visible records. The native Routing panel must display the latest
durable report even if last_worker is overwritten or Activity is unavailable.
No new unattended Hosts mutation is permitted. A matching installed
manifest or resident entrypoint version cannot prove Python helper freshness:
non-emergency watcher controls must verify the **loaded helper** contract
and fail closed if stale, while keeping Emergency disable accessible.
A panel reload is separately authorized, never triggered by import.

**Current Hosts/FPM behavior:** Failed WordPress provisioning is
observation-only; the user explicitly selects any unwanted alias for
one-click Hosts removal. The legacy automatic Hosts-cleanup path and its
journals have no runtime adapter. An independent opt-in PHP 8.1/8.5
automatic-repair worker watches verified native PHP-FPM regeneration. It records a trusted
pre-terminal native WP progress identity and FPM file fingerprint, requires a
matching later successful/failed terminal and changed FPM source, then
rechecks saved admin intent and shared-site mapping before guarded
syntax/reload/runtime verification and per-cycle recovery. Prior verified
automatic recovery is archived rather than erased for repeated repairs;
manual or uncertain recovery blocks automation. Independent-review
remediation additionally requires Enable to match the exact user-reviewed
shared-site fingerprint plus policy/Monitor revisions; the verified native
`setFpmConfig` RAM-derived output must still own all four modified pool
values immediately before replacement while pre-task `pm.max_requests`
remains unchanged. Automatic recovery must bind the native event token so
a SIGKILL after a committed Apply can be acknowledged idempotently without
another reload. Emergency Disable durably queues a version-specific
revocation even when a guarded operation holds the shared lock longer than
the request timeout, then completes autonomously at the next safe worker
boundary; it never silently leaves future authority active after a
successfully acknowledged final Disable.
Exact previous FPM runtime acceptance is recorded in [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
The current witness and Hosts action do not attempt automatic Hosts cleanup;
no old kernel-lease append-Restore code or compatibility tests remain. Native
auto PHP-FPM repair retains its own scoped source/recovery verification.

The current WordPress witness is observation-only, with no automatic
Hosts edit and no historical append-only Restore. A matching terminal
progress record may close a current active witness, while an unproven task
remains Needs Review until explicitly discarded. Distinguish Enabled
observation policy, actual watcher readiness and typed last worker result
in UI and Activity.
The Hosts witness alone does **not** authorize generic alias cleanup,
batch WP install mutation, or shared PHP-FPM auto-enforcement. The separate
0.1.62 FPM worker is opt-in and has its own narrower native-writer boundary.
An aaPanel source update, active native
operation, missed start or concurrent editor must produce actionable refusal
evidence; sources are not patched in place.
Unknown vendor layouts, IP trust assumptions, external
WordPress integrations and Production deployments require their respective
review/approval and working rollback. Issue #2 holds the exact current
acceptance matrix; #21 holds installed/negative/recovery verification.


## 3. Users and product experience

**Primary user:** the full primary aaPanel administrator operating one or multiple websites and server modules on a managed Linux host. The accepted initial usage model is **one primary administrator**; secondary Admin/Operator accounts and paid multi-user provisioning are not requirements or release blockers, without weakening existing session/CSRF authorization.

The plugin must behave as an ordinary **aaPanel-installed plugin**:

- Be installable/importable from aaPanel's plugin-management experience, with a verified package and reproducible installation path.
- Appear in the aaPanel plugin inventory and open a management interface **inside aaPanel**, consistent with the native visual and interaction conventions of the supported version.
- Offer a simple overview, managed targets, customization modules, policies/settings, activity/diagnostics, and change/recovery controls.
- Offer overall enable/disable behavior and per-module enable/disable controls. If aaPanel does not provide a suitable built-in third-party-plugin toggle, implement the control inside the plugin rather than claim native support.
- Support versioned updates, uninstall, and reinstall with explicit treatment of persistent user configuration, already-applied host changes, and recovery records.
- Native ZIP updates must distinguish installed source bytes from previously imported aaPanel Python worker code. Expose a read-only resident-entrypoint version observation, describe stale/unverified responses without implying that a version match certifies all helper modules, and reserve a controlled panel reload for explicit operator authorization. Never restart the panel automatically during import, inspection, or ordinary plugin use.
- Not require a second public administrative interface, separate login, or extra network listener.

The primary workflows must be understandable without editing Nginx, PHP, or WordPress files directly. Advanced diagnostics remain available, with actionable failure stage, cause, impacted targets, and operation/correlation ID. Use aaPanel's established native visual, navigation, and interaction conventions. English-only UI is acceptable and sufficient for the initial supported release; Persian translation and RTL are optional future enhancements, not acceptance gates. Keep application-specific content and target identifiers Unicode-safe without introducing a speculative localization framework.

### Typical operator journey

1. Install the plugin; see existing compatible websites, aaPanel modules, and managed services.
2. Select a target and a suitable customization profile or explicit policy.
3. Inspect its current state, proposed changes, ownership boundary, and impacted resources.
4. Start with monitoring/dry-run and explicitly opt in to manual or automatic enforcement where appropriate.
5. See changes detected after a site is added or aaPanel modifies an existing setting.
6. Apply or approve a safe change, inspect validation results, and recover the prior state if needed.
7. Disable, upgrade, or uninstall without unintentionally disabling websites or erasing operator state.

### Current interface and operational acceptance (Owner update, 2026-11-03)

The native UI must follow the installed aaPanel visual and interaction conventions, particularly the Nginx plugin's left navigation and independently scrollable content. Operators must not need browser zoom-out to reach controls. The supported acceptance viewports include 1280x720, 1366x768 and 1920x1080 at 100% browser zoom, plus narrow and reduced-height cases. Preserve keyboard/focus semantics, explicit loading/empty/error/recovery states, scope awareness and clear separation of Monitor, Preview, guarded Manual Apply and unsupported capabilities.

Provide site selectors from validated, paginated aaPanel inventory rather than requiring operators to type raw IDs in routine workflows. Website selection for Status Pages must remain available to a full primary aaPanel administrator even if the optional Website Monitor is disabled: its dedicated, bounded native listing is read-only, independently authorized, and the selected site identity is revalidated by every relevant backend action. The Monitor website inventory keeps its separate enabled/disabled policy. Stale or incompatible inventory replies must never authorize an action. The Status Pages module retains safe offline branding/preview and read-only inspection; each implemented manual delivery/Restore adapter remains separately source-checked, authorized and proven within its supported scope, not assumed available for every target.

### Owner-approved unknown-SNI HTTPS policy (2026-11-22)

The Owner selected **Option A** for global unknown-domain HTTPS/443: reject
TLS handshakes with an unknown or absent SNI name, not a branded HTTP
error page or an arbitrary borrowed certificate. This is separately opt-in
and applies only to already-configured Nginx HTTPS TCP wildcard listener
families; the plugin never opens port 443, changes certificates or silently
takes a foreign/default server. Existing named HTTPS hosts, ACME/proxy paths
and the separate HTTP/80 unknown-Host page must remain intact. If the
Nginx listener or default ownership cannot be proved, report the concrete
conflict instead of widening the listener or weakening HTTPS identity.
Apply/Restore need a fresh source comparison, explicit native administrator
action, exact recovery record, guarded Nginx test/reload and real known
versus unknown/no-SNI handshake checks. Code integration and nonproduction
QA do not authorize public Release or Production rollout. Current
acceptance and Owner decision are tracked in Issue #10.

The plugin must expose a built-in Activity/Diagnostics view backed by bounded persistent structured log records. Include UTC timestamp, severity, module/action, stage/outcome/error class, target/service identity, correlation ID and relevant recovery reference. Keep useful bounded troubleshooting context without recording session tokens, credentials, request payloads or arbitrary exception messages. Preserve successful operation outcomes if audit persistence fails; surface that failure separately. Diagnose real authorizations, failures and recoveries. Use aaPanel-compatible ownership/permissions, bounded retention and configurable verbosity.

**PHP compatibility:** Discover installed PHP versions and real service
capabilities, not a fixed whitelist. Distinguish detected, preview-capable,
native Apply-capable and tested-in-QA. The current 8.1/8.5 shared-pool
adapters are the implemented write paths, not a permanent version limit.
For other layouts, prefer a capability-derived adapter with targeted
syntax/reload/impact checks rather than a blanket compatibility matrix.
Never guess an unfamiliar destructive file rewrite; offer inspection,
an actionable explanation and a usable manual route until a correct writer
exists. Real authorization, target identity and unrelated-site integrity
remain mandatory.

These are durable product requirements; verified implementation and release readiness must be recorded against the exact candidate and non-production environment, independently reviewed and separately approved by the Owner. Production changes and automatic enforcement remain separately gated; an approved pre-release publication is not an installation or rollout.

## 4. Product boundary and modular evolution

The **product boundary is aaPanel customization**. WordPress support is one integration, not a platform-wide requirement.

Potential customization surfaces include:

- aaPanel's supported settings, plugin UI/integration points, and website-management behavior;
- websites based on WordPress, other CMS/frameworks, and static sites;
- web servers, shared PHP runtimes, per-site PHP controls, caching, scheduled jobs, and relevant database/service modules;
- installed aaPanel plugins and their configuration or safe extension points.

These are eligible product domains, **not commitments to ship all adapters in the initial release**.

Use the smallest modular architecture that meets current needs: a core for target discovery, policy handling, operation/recovery safety, lifecycle, and diagnostics; modules for domain-specific discovery, comparison, validation, application, and verification. Keep the extension boundary clear and useful for a real second module. Do not pre-build a marketplace, universal SDK, unrelated service, or speculative module framework.

The project owns its aaPanel-specific behavior and lifecycle. Its status as an AChWorks project does not require consumption of an unrelated Foundation. Reconsider sharing only when actual additional consumers and stable common behavior justify it under Koinon's reuse rules.

## 5. Target and configuration semantics

A customization must identify what it governs. At minimum the domain model must distinguish, where relevant:

| Scope | Example | Responsibility |
| --- | --- | --- |
| Panel/global | aaPanel-level behavior | All affected operations or modules |
| Shared service | PHP-FPM pool serving multiple sites | One service-level policy, not conflicting per-site writes |
| aaPanel module/plugin | A module's owned settings | Only targets where that module is present and compatible |
| Website | A site's virtual host or application settings | The exact discovered website and its managed resources |
| Integration-specific | WordPress or commerce sessions | Only when that integration and behavior are verified |

The engine distinguishes desired configuration, generated files, current runtime values, and observed behavior. A change may need to reconcile more than one of these layers. Ownership, scope, and policy precedence must be explicit, deterministic, and inspectable. Existing manual settings are not silently adopted or replaced.

A policy must not assume that changing shared PHP-FPM settings is the same as changing one website. Ambiguous ownership, conflicting policies, and unknown versions require review rather than destructive guesses.

For shared PHP-FPM, the operator's **desired** `[www]` settings are a service/version-scoped policy, independently durable from the aaPanel-managed configuration file. A Monitor save only records intent after reviewing a current file/default comparison; it does not mean the effective worker state matches, nor constitute authorization for Manual Apply or Auto-enforce. Reconciliation should compare the saved desired values against refreshed generated/source evidence and separately verified runtime/service/affected-site behavior when available; the operator must retain control of approval and recovery.

## 6. Discovery, persistence, and reconciliation

- Discover supported sites, modules, service instances, and relationships from authoritative aaPanel/host/application sources; never rely on a fixed list of domains or WordPress-only markers.
- Detect new websites, removed or renamed targets, and material changes caused by aaPanel/module upgrades and operator actions.
- Prefer proven supported aaPanel extension/event mechanisms when available; a bounded periodic reconciliation mechanism is acceptable when native hooks are missing or unreliable.
- Do not modify aaPanel core merely to add a hook, and do not claim protection against an unknown update before compatibility has been tested.
- Preserve policies, operator preferences, and necessary recovery evidence independently from replaceable plugin code so an update/reinstall does not silently destroy them.
- Keep the website **observation baseline** separate from runtime settings and native host files. A newly added/changed **selected-site-only** baseline acceptance must preserve all other pending site records; the **all-sites** baseline acceptance is a separate, explicitly reviewed operation that can also accept removals. Neither baseline action implies host Apply, or silently erases orphan/recovery state.
- Distinguish a *new/unclassified target* from an existing target. Unknown targets begin in a non-destructive review state; unsupported platforms or configurations are reported accurately.
- Reconciliation must remain bounded and resource-efficient; unexpected or high-volume target sets cannot cause uncontrolled scans or repeated reloads.

### Enforcement modes

- **Monitor:** read, compare, and report without mutating the target.
- **Manual Apply:** provide a precise preview; execute only after the authorized operator approves the particular change.
- **Auto-enforce:** only for a policy and supported target type explicitly opted in, with compatibility, ownership, validation, and rollback requirements satisfied.

The default after initial installation is **Monitor**. A global Enable switch does not by itself authorize enforcement of every policy.

## 7. Change safety and recoverability

For consequential target changes, the implementation must:

1. Confirm target identity, policy scope, applicable authorization, current state, and change ownership.
2. Present or record a readable preview of the actual change and its shared/per-site impact.
3. Validate input, compatibility, preconditions, and the existence and quality of recovery evidence **before** destructive or privileged activation.
4. Serialize conflicting operations and detect intervening user/aaPanel changes.
5. Modify only the narrowest proven supported extension surface or controlled fragment; preserve unrelated content and ownership.
6. Validate the actual resulting configuration (for example, with the target service's syntax test) and activate/reload only the necessary service when permitted.
7. Confirm the effective runtime outcome and affected-site health, not merely a successful file write.
8. Record success, failure, degraded state, or **uncertain outcome** accurately; do not repeat ambiguous changes blindly.
9. Offer a verifiable restore/rollback where the previous state can be faithfully restored. Otherwise, retain precise evidence and explain the recovery action instead of claiming rollback.

Policy application should be convergent/idempotent when meaningful. Unsupported configuration structures and edits that conflict with unrelated ownership must fail safely.

Prefer supported extension points over patches to aaPanel core or generated vendor files. If a narrow compatibility override is ever required, it must be separately justified, strictly version-gated, tested, and recoverable; it must not become the assumed default.

**Native operator UX (Issues #17/#21):** Group administration by real
operator tasks rather than backend-module names; allow distinct website
inventory, Routing/Nginx and FastCGI Cache destinations with one validated
selected-site context. Make each check's purpose, limits and usage clear.
Show a human-readable result and recommended next step by default, with
expandable exact diagnostic details (including hashes, operation/recovery
IDs and real failure stages). Wherever an Apply/Restore/Save confirmation
or action is currently disabled, expose its actual evidence prerequisite
and next supported step beside the control, independent of hover. A checked
consent box must never be confused with successful preflight or backend
authorization; keep readiness and saved-recovery requirements distinct. Use semantic colors plus words, keep shared
service and dangerous Apply/Restore consequences clear, preserve navigation
scroll, drafts, keyboard/focus, mobile reflow and stale-evidence invalidation.
No UI status may imply effective runtime, private-data safety or site-scoped
Purge All without actual acceptance evidence.

**FastCGI cache operational acceptance (Issue #2):** Keep HTTP-scope cache zones and per-site filesystem trees independently owned; a host-partitioned key does **not** make a shared physical directory safe to Purge All. Activation requires a version-appropriate native Nginx include surface, owned and fingerprinted config fragments, exact native site ID/root/bindings, a verified PHP handler, conservative private request/write exclusion, syntax preflight, narrowly authorized reload, runtime route observation, and an explicit saved recovery path. A single loopback marker establishes one effective PHP handler only; **real WordPress/WooCommerce session and cart/checkout/admin/webhook behavior**, multiple registered sites, cross-site isolation, and Nginx Helper `get_request` / `unlink_files` must be verified before advertising operational cache safety or exposing **Purge All**. A source-only preview and isolated Nginx fixture never substitute for authenticated native aaPanel installed-package acceptance, nor do they authorize production changes.

**Targeted site-owned invalidation (Issue #2):** For already-approved and freshly Rechecked site-owned FastCGI Cache generations, support an explicitly approved exact URL-file clear without broadening the general Purge All or Nginx Helper contracts. Derive candidate Nginx `levels=1:2` files from the saved generation and registered primary Host; verify stored `KEY` and physical file identity, full current Nginx source, native site identity and peer physical isolation before unlinking. Only the current policy's cacheable, canonical, query-free URL paths are eligible. Report the exact removal count, retain journal/recovery material and handle uncertain partial cleanup by Recheck; never treat a file clear as cache/session privacy or full site-purge certification. WordPress Nginx Helper automatic invalidation, aliases and native `-wpfastcgi.conf` Apply remain separate requirements.

**Production boundary:** building or maintaining this repository does not authorize installing the plugin, changing aaPanel, reloading production services, modifying production databases, or enabling production auto-enforcement. Such effects require explicit environment-specific authorization.

## 8. Installation, enablement, update, and uninstall semantics

### Install

The distribution target is one aaPanel-compatible, versioned plugin package, including dependencies required for a usable offline/local import where feasible. A successful download is not proof of package integrity. Verify identity, compatibility, package structure, file ownership, and lifecycle prerequisites before privileged installation. Keep host footprint minimal.

### Enable / disable

- **Enable** starts only those plugin-owned monitoring/enforcement mechanisms separately configured and authorized.
- **Disable** stops plugin-owned enforcement, monitoring, and scheduled work; it must not implicitly reverse applied service/site configurations or stop the underlying websites.
- Module-level enable/disable behavior must be independently understandable, with clear handling of existing applied state.

### Update

- Preserve operator configuration, managed-target identities, policy state, logs/recovery records as appropriate, and required backups.
- Treat schema migrations and code activation as verifiable lifecycle steps; failures must be diagnosable and recoverable or safely stopped.
- Detect changes in aaPanel's plugin APIs or target configuration syntax; prevent incompatible enforcement after upgrading either side.

### Uninstall and reset

- Ordinary uninstall removes **positively identified product-owned** code, scheduled activities, and disposable resources, while preserving operator data and already-applied host configuration by default unless a separately confirmed safe restoration is available.
- Removing the plugin must not remove sites, modules, or third-party data merely because the product previously managed them.
- **Restore managed changes** and **purge persistent state/backups** are explicit, separately confirmed operations, not hidden consequences of Disable or Uninstall.
- Reinstallation must recognize preserved state without duplicating jobs, directives, or modules.

A lifecycle state shown in the UI must reflect the actual outcome, not merely that an API call was attempted.

## 9. Security, privacy, reliability, and operations

- Use aaPanel's authenticated plugin integration and authoritative platform permissions; enforce privileged operation authorization server-side, including for background jobs.
- Minimize privileges and exposed surfaces; do not introduce a public administration port or unrelated resident service without evidence it is necessary.
- Do not store credentials, database passwords, private keys, session tokens, or unrestricted diagnostic dumps in Git, general logs, or accessible UI output.
- Retain meaningful structured logs for changes and failures: time, operator/actor when available, target, stage, operation/correlation ID, effective result, and recovery reference.
- Prevent duplicate or concurrent edits and preserve enough evidence to reconcile crashes, timeouts, and partial application.
- Avoid high CPU, memory, disk, or network cost for idle monitoring; ensure bounded scanning, retention, and recovery operations.
- Show compatibility and unsupported states without claiming success; do not hide errors or silently disable diagnostic logging.
- Product UI should support usable responsive layouts and applicable accessibility conventions.

## 10. Delivery and continuing acceptance criteria

**Initial milestone (already delivered as a bounded public development preview):** a validated native aaPanel plugin foundation with a working operator experience and a useful, recoverable vertical slice. Its continuing acceptance dimensions are:

1. Plugin install/open, enable/disable, update/uninstall/reinstall contract and durable state ownership.
2. Discovery and display of actual aaPanel websites and relevant shared resources (not a fixed domain list).
3. Monitor/dry-run of configuration drift with a comprehensible change preview.
4. A bounded, testable customization path covering native aaPanel/Nginx extension surfaces and PHP-FPM shared settings where compatibility is proven.
5. Verified Apply → syntax/runtime checks → outcome reporting → recovery for approved changes.
6. Safe handling of a newly created site and an aaPanel-induced rewrite of previously customized configuration.

Acceptance requires practical test evidence, not just source files or a mock UI. In an isolated or explicitly authorized non-production aaPanel environment, demonstrate:

- install, native management screen, correct enable/disable, update, uninstall, and reinstall behavior;
- correct discovery of several sites with different application types and a newly created site;
- differentiation of a shared PHP pool setting from a per-site virtual-host setting;
- no unauthorized mutation in Monitor mode;
- compatibility rejection/Needs Review for an unsupported aaPanel version or unknown config shape;
- preflight/backup, idempotence, duplicate/conflict resistance, real validation, recoverable failure and rollback on representative supported operations;
- preservation of unrelated host configuration and functioning websites across all lifecycle tests;
- clear diagnostic evidence and low bounded monitoring overhead.

### Development sequence (durable guidance, not live work status)

**Evidence first:** verify current native aaPanel plugin import/UI, lifecycle callbacks, generated-vhost extension mechanisms, website discovery APIs, update behavior, and supported test environment. Resolve compatibility and permission boundaries before accepting adapter implementation promises.

**First vertical slice:** implement the smallest native UI + discovery + drift preview + one verified reversible customization; validate site creation and panel regeneration.

**Broaden carefully:** add the other accepted initial adapter and robust lifecycle/testing. Additional WordPress, database, cron, security, or service modules are later work and require real needs.

Publication of a development pre-release does not authorize installation on Production, general production auto-enforcement or unverified platform compatibility. Release and rollout approvals are separate.

## 11. Supported environment and unresolved compatibility

The verified nonproduction **reference configuration** includes native
aaPanel 8.0.7 with Nginx and tested PHP-FPM 8.1/8.5 adapters, as recorded
in [#21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
This is not a universal support matrix. Actual installed site/PHP topology,
versioned service controls, VHost includes, filesystem ownership and reload
behavior determine whether a target-specific operation is eligible.

For future aaPanel versions, web servers, PHP pool layouts, and alternate
installation paths, probe actual capabilities instead of rejecting version
strings by default. Correct writer support still requires understanding the
target format, reload semantics and ownership. Operator notes can cover
reasonable residual uncertainty, not make destructive writes on unrelated
state safe. Live worker status, DNS/TLS, cache isolation and vendor Purge All
must be determined from their actual runtime behavior, not version labels.

Exact integration/operation details are maintained in
[the native technical guide](aapanel-integration.md); accepted gaps and
compatibility work belong to the owning GitHub Issues, not a fixed version
allowlist or rolling checkpoint here.

## 12. Non-goals

The project must not become:

- a WordPress-only product, full hosting-panel replacement, general-purpose remote shell, or universal server optimization daemon;
- an independent public web console or mandatory external control plane;
- a permanent patch set against arbitrary aaPanel core internals;
- a speculative marketplace, cross-product Foundation, universal automation runtime, or monorepo for unrelated projects;
- an installer that overwrites third-party/operator state, silently changes production settings, or claims rollback without evidence;
- a second source of truth for GitHub work, releases, installed software inventory, or real runtime state.

## 13. Project ownership and authoritative sources

This file owns the project's durable mission, accepted behavior, target users, scope, constraints, and success/delivery criteria. Edit it **only when these durable product decisions change**.

- `README.md` is the human-facing product/developer entrypoint and documentation map.
- `achworks.yaml` is the AChWorks discovery descriptor, not an implementation, release, or production-state registry.
- Technical architecture, package/CLI/API details, compatibility matrices, and operational procedures belong in focused references **only after verified decisions make them useful**.
- Active execution, unresolved tasks, exact code review, CI, release, and deployment evidence belong in GitHub Issues, PRs, commits, checks, and Releases.
- Production state, configs, secrets, logs, and backups belong to their authorized host/runtime owners, not this repository.

Applicable AChWorks cross-project contracts (consult current versions when implementing the related failure surfaces):

- [Koinon New Project Intake](https://github.com/AChWorks/koinon/blob/main/docs/workflows/new-project-intake.md)
- [Component Lifecycle and Release](https://github.com/AChWorks/koinon/blob/main/docs/contracts/lifecycle-release.md)
- [Linux Tool Distribution](https://github.com/AChWorks/koinon/blob/main/docs/contracts/linux-tool-distribution.md)
- [Validation and Evidence](https://github.com/AChWorks/koinon/blob/main/docs/contracts/validation-evidence.md)
- [External Effect Safety](https://github.com/AChWorks/koinon/blob/main/docs/contracts/external-effect-safety.md)
- [Build vs Buy / Reuse](https://github.com/AChWorks/koinon/blob/main/docs/principles/build-vs-buy.md)
