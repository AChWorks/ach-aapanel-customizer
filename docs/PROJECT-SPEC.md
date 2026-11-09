# ACh aaPanel Customizer — Project Specification

- **Status:** Canonical product intent — staged unreleased native development
- **Repository:** `AChWorks/ach-aapanel-customizer`
- **Owner:** AChWorks
- **Product:** ACh aaPanel Customizer
- **Primary distribution:** Native, installable aaPanel plugin

## 1. Mission

Create a native aaPanel plugin through which an administrator can **customize aaPanel itself, its built-in modules, installed plugins, websites, and the services they manage**, without repeatedly reapplying fragile manual edits after new-site creation, plugin changes, or aaPanel upgrades.

The product manages *operator-approved desired behavior* rather than blindly overriding whatever aaPanel currently generates. It makes customizations visible, understandable, maintainable, and recoverable.

**Identity:** This is an aaPanel **customization system**, not merely a WordPress optimization tool, generic hosting control panel, separate administration service, or automatic server optimizer.

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

## 3. Users and product experience

**Primary user:** aaPanel administrator operating one or multiple websites and server modules on a managed Linux host.

The plugin must behave as an ordinary **aaPanel-installed plugin**:

- Be installable/importable from aaPanel's plugin-management experience, with a verified package and reproducible installation path.
- Appear in the aaPanel plugin inventory and open a management interface **inside aaPanel**, consistent with the native visual and interaction conventions of the supported version.
- Offer a simple overview, managed targets, customization modules, policies/settings, activity/diagnostics, and change/recovery controls.
- Offer overall enable/disable behavior and per-module enable/disable controls. If aaPanel does not provide a suitable built-in third-party-plugin toggle, implement the control inside the plugin rather than claim native support.
- Support versioned updates, uninstall, and reinstall with explicit treatment of persistent user configuration, already-applied host changes, and recovery records.
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

Provide site selectors from validated, paginated aaPanel inventory rather than requiring operators to type raw IDs in routine workflows. Website selection for Status Pages must remain available to a full primary aaPanel administrator even if the optional Website Monitor is disabled: its dedicated, bounded native listing is read-only, independently authorized, and the selected site identity is revalidated by every relevant backend action. The Monitor website inventory keeps its separate enabled/disabled policy. Stale or incompatible inventory replies must never authorize an action. The Status Pages module is initially a safe branding/offline preview and read-only site-file inspection; a production Apply/Restore adapter must be separately implemented and proven.

The plugin must expose a built-in Activity/Diagnostics view backed by bounded persistent structured log records. Include UTC timestamp, severity, module/action, stage/outcome/error class, target/service identity, correlation ID and relevant recovery reference. Keep useful bounded troubleshooting context without recording session tokens, credentials, request payloads or arbitrary exception messages. Preserve successful operation outcomes if audit persistence fails; surface that failure separately. Diagnose real authorizations, failures and recoveries. Use aaPanel-compatible ownership/permissions, bounded retention and configurable verbosity.

**PHP compatibility:** Inspect/manage installed PHP 8.1 and newer versions, but distinguish *detected*, *file-only preview*, *native Apply eligible* and *recoverably tested*. The current guarded 8.5 shared-[www] adapter is not authorization to write another version by string substitution. Each other version and pool shape must pass native aaPanel PHP discovery, mapping, syntax/reload, shared-service attribution, after-state, website and rollback/fault tests before Apply eligibility. Unsupported configurations fail closed. PHP 8.1+ remains an acceptance target, not a claim of tested compatibility.

These are durable product requirements; verified implementation and release readiness must be recorded against the exact candidate and non-production environment, independently reviewed and separately approved by the Owner. Production changes, publication and automatic enforcement remain unapproved.

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

## 10. Initial outcome and acceptance criteria

**First deliverable:** a validated native aaPanel plugin foundation with a working operator experience and a small useful vertical slice. Initial development prioritizes:

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

### Delivery phases (direction, not an implementation backlog)

**Evidence first:** verify current native aaPanel plugin import/UI, lifecycle callbacks, generated-vhost extension mechanisms, website discovery APIs, update behavior, and supported test environment. Resolve compatibility and permission boundaries before accepting adapter implementation promises.

**First vertical slice:** implement the smallest native UI + discovery + drift preview + one verified reversible customization; validate site creation and panel regeneration.

**Broaden carefully:** add the other accepted initial adapter and robust lifecycle/testing. Additional WordPress, database, cron, security, or service modules are later work and require real needs.

No production installation, public release, or general production auto-enforcement is included in repository initialization.

## 11. Supported environment and open technical questions

The initial integration target is a **real supported aaPanel installation on Linux**. Exact aaPanel versions, distribution/system-manager support, Nginx/Apache variants, runtime dependencies, plugin import/update behavior, and extension file durability are not yet declared supported. They must be verified and documented from current authoritative sources and practical tests before releasing the first package.

Decisions intentionally left for validated architecture and implementation:

- exact aaPanel plugin packaging, hooks, service/API compatibility, and module/UI routing;
- whether an external scheduled process is required or platform-native scheduling is sufficient;
- which path/layout can survive aaPanel updates without creating a separate management panel;
- exact format and versioning of policies, persistent state, and backups;
- supported web-stack integrations and the safest first read/write adapter;
- whether update and uninstall behavior requires a compatibility-specific installation adapter.

These are not grounds to weaken the approved native-plugin product experience.

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
