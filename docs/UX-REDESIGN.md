# Native UI redesign — accepted task-first experience contract

Status: Owner-approved task-first interface and visual refinement, implemented in PRs #129–#136, with wrapped-approval and Status Pages guidance refinements in PR #139 (Native 0.1.111, 2026-11-24). Exact delivery and residual acceptance evidence belong to Issues #128 and #21. Scope: `AChWorks/ach-aapanel-customizer`. Source of approval and complete audit: [Issue #128](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7090292152). This document owns the intended UI/navigation and testing contract, not backend authorization, actual installed capabilities, or release status.

## Outcome and compatibility

An aaPanel administrator must be able to find a task without knowing an implementation module, identify the exact website/service/server/future-site scope, distinguish read-only inspection from write, see the supported next action, understand failure and recovery, and complete routine work without consulting developer documentation. Skilled operators retain direct access to evidence and Recovery IDs.

No previous Customizer release has a Production installation. **Prior Customizer UI tab structure, old internal version schemas, and historical fallback adapters are not compatibility targets.** Do not keep obsolete control flows solely to preserve their old appearance. Existing real aaPanel, Nginx, PHP, WordPress, WordPress Bridge and data/permission contracts are separate external/live obligations. The single retained QA VM, its native websites, source files, existing owned recovery records and peer services must not be destroyed by development. Current-candidate repair/Restore remains trustworthy. No invented migration or alternate state store.

Retain one native aaPanel plugin, its authentication, primary-admin restrictions and CSRF rules. Avoid a standalone SPA, independent login/service or mandatory build chain. Split UI modules only when the resulting reuse and testability justify it. **Do not implement all new views as one long form under renamed tabs.**

## Final information architecture

Five top-level destinations. The count follows actual task grouping and can be refined against first-click and task tests without changing the invariant that scoped jobs have a clear home:

```text
Home
  Start a task; recent activity; current observation state; open blocked jobs
Websites
  Website inventory → select native website (stable, explicit ID/name)
    Summary & changes       site identity, source observations, reviewed baseline
    Protection             Guard sensitive files, optional XML-RPC and site-local IP blocking
    Cache & performance    inspect, configure, WP connect, purge exact owned scope
    WordPress              Debug, Cron, app XML-RPC, HTTPS URLs, install witness
    Routing & diagnostics  VHost, local HTTP, selected-site Hosts, related Recovery
    Error page             deep-link into canonical Error Pages delivery editor
Server
  PHP services             installed versions/pools, desired Monitor, live Apply,
                           opted-in repair, exact shared-service Recovery
  Local hostnames          list current loopback entries, protected system names,
                           manual/deleted-site aliases, exact eligible removal
  Default HTTP/TLS routing unknown Host HTTP/80 vs unknown SNI HTTPS/443
  Monitoring controls      inspection availability and auto-repair gating
Error pages
  Design & preview         all 11 supported templates, English/Persian, branding
  Show on a website        actual supported 404/502/50x and stopped-site 503
  New website defaults     future native site templates
  Server fallback          cross-link to Server routing, no duplicate writer
Activity & recovery
  Understand event, identify exact target, follow link to owning workflow,
  Recheck before Restore; advanced IDs, and raw logs
```

An operation has **one canonical owner view**. A relevant shortcut may open that same view with an explicit target; it must not duplicate privileged Apply, persistence or Recovery code. A site selection never falsely changes the scope of server-wide work. Advanced source/path/hash evidence is expandable and reachable, not deleted.

### Common novice journeys

| Intent | First-click path | Exact effect to show |
|---|---|---|
| Check website record | Websites → select → Summary & changes → Compare | Observation-only vs plugin-saved baseline; choose one-site accept, bulk only explicitly |
| Protect files | Websites → select → Protection → Sensitive files | Site config plus shared Nginx reload; verify eligible Nginx include |
| Stop malicious IPs | Websites → Protection → optional temporary IP blocking | Selected-site HTTP 429; expires automatically; no firewall change |
| Manage Cache | Websites → select → Cache & performance | Inspect source ≠ worker proof; connect optional WP integration vs site policy; clear exact URL/owned tree |
| Adjust PHP | Server → PHP services → choose discovered pool | Desired Monitor Save ≠ live shared Apply; show peers and recheck |
| Modify WordPress | Websites → select → WordPress → choose task | Independent Debug, Cron, MU XML-RPC, HTTPS URL source and owner |
| Customize 404 | Error pages → design/preview → show on website | Saved branding ≠ live site delivery; unsupported destination is preview-only |
| Recover error | Activity & recovery → event → exact owning workflow | No universal rollback; exact current-generation evidence and ID |
| Fix host override | Server → Local hostnames → inspect | Machine name is immutable here; stale non-system aliases remain manageable |

Use existing capability inventory and **91-button/57-form/36-disclosure original-to-new crosswalk** in [Issue #128 Part 2](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7089964275), revised by the server-side Fail2ban navigation and present hierarchy. Every old capability must be discoverable through its canonical task; controls need not retain historical HTML IDs after a coherent tested refactor.

## Page pattern and visual system

**Standard task layout:**

1. Breadcrumb + plain-language task heading; website/service/server/future/preview target clearly visible.
2. Current observations: what was inspected, when, from which source; native managed status and last operation separately.
3. A short primary action named by outcome. Missing target → prominent `Choose website`, not a forest of disabled actions.
4. Before any consequential write: current → proposed change, exact blast radius (peer service reload, firewall bans, cache deletion), prerequisites and supported current-generation recovery. `Cancel` and `Apply` are distinct; do not require a redundant "I understand" checkbox when an explicit authorized action suffices.
5. Persistent outcome, verified effect or precise partial/uncertain state, useful next action; technical details/Operation and Recovery IDs in a labelled disclosure.

### Canonical action verbs

`Refresh` = refresh observation. `Inspect` = read current source. `Compare` = show before/after. `Preview` = render/plan without write. `Recheck` = reconcile current source, identity and saved Recovery. `Save` = persist plugin preference/desired policy, not live config. `Apply` = write eligible live config with actual verification. `Enable/Disable` = explicit named behavior toggle. `Connect/Disconnect` = optional WordPress integration. `Clear` = delete an identified cache target. `Restore` = guarded current-generation module-owned saved state. Use the exact consequence for high-risk buttons rather than just `Run`.

One dominant action per local decision; neutral read-only links, red destructive actions, substantive warnings amber, success green **only after verified success**, info/next step in blue or neutral, no state determined by color alone. Avoid competing primary actions or styling Restore as proof of success.

### Design tokens and components (targets, not proof of rendering)

- Retain aaPanel-compatible brand green for identity and verified-success emphasis; choose a darker accessible `primary` foreground on white. Distinct semantic `surface`, `text`, `muted`, `border`, `action`, `focus`, `success`, `attention`, `error`, `danger`, and `disabled` roles.
- Suggested body 14–16px, field labels 13–14px, secondary metadata 12–13px, section title 16–18px, page title 20–24px, line-height 1.5–1.6; 4/8/12/16/24/32px spacing scale. Color pairs must be tested in actual rendered states (WCAG 2.2 AA target). Contrast: 4.5:1 ordinary text, 3:1 large text and applicable UI boundaries.
- Forms: associated persistent label, meaningful current value, units/range, required/optional explanation, inline validation and preserved input on failure. Error summary attracts focus for blocking errors; routine status uses polite live announcement, consequential failure uses an appropriate alert and stable visibility.
- Context header; site/service chooser; task link/list row; evidence summary; scoped review; one next-action row; clear blocked/empty/loading/success/partial/error/uncertain/recovery surface; labelled advanced evidence; copyable IDs. No gratuitous nested card hierarchy or mandatory onboarding wizard.
- Responsive at 320/375/800/1024/1280 and browser zoom 200%; narrow top-level navigation becomes a labelled menu, not a horizontally hidden seven-tab strip. Site selection, edits and focus survive safe navigation/resize; source or site change invalidates only affected prepared operations. Technical tables can scroll inside a clearly labelled container.
- Native interface starts English/LTR, but text is localizable and all eleven existing Status templates preserve correct EN/LTR and FA/RTL previews with bidi-safe domains and codes. Full native Persian translation is **not a prerequisite** for the approved redesign; do not block later i18n.

## Visual consistency refinement (Owner accepted 2026-11-24)

[Measured installed 0.1.101 audit and accepted correction plan](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7126797508)
establish the baseline; [Owner acceptance receipt](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7127490129)
records the authorization to implement. Native 0.1.103 candidate uses the
existing five destinations and one canonical operation owner, not a new framework.

- Compact selected-site context: exact native selector, short state feedback,
  browse/independent error-page scope links. Secondary task choices wrap as
  navigation rather than full-size command cards. No duplicate Home/title
  headings; explain the actual chosen operation rather than every sibling.
- Use shared scoped controls: 14px body, 22px/600 desktop task title, 13px
  labels and data table text, adaptive form groups with label above the field,
  36px standard control height, and one 16px checkbox plus a whole-copy text
  column. Effective checkbox label target at least 28px. Stronger enabled
  input boundaries, visible focus and distinct disabled state. A designated
  check is the primary next action until its positive commit is eligible;
  consequential restore and destructive actions retain explicit scope and
  distinct treatment. Do not change authorization based on styling.
- Put WordPress HTTPS warning only in HTTPS task. PHP Preview result and
  affected-site evidence directly follow the editable form; optional auto
  repair has its own visible section. Cache source inspection is first;
  optional privacy probes and reference policy remain discoverable in one
  advanced disclosure. Error design hides irrelevant global-scope website
  selector, keeps branding read/retry and live delivery explicit, and
  contains the sandboxed preview independently; its hashes are accessible on
  demand. Activity shows outcome and warning/error reason first; raw
  Operation/Recovery IDs and detailed machine evidence remain selectable in
  native disclosure. No diagnostic fields removed or mutator cloned.
- The installed-audit legacy Guard journal is not established as tampered.
  A structurally parseable but unsupported ruleset returns an explicit
  unsupported-family error and remains blocked. The Protection summary
  explains that the current version cannot verify/restore it and requires
  separate administrator investigation; the technical report retains the
  read-only journal filename and request Operation ID, never a fabricated
  Recovery ID. Preserve the diagnosis on policy option edits, and clear it
  when selecting a different site or superseding the result with a new check. Keep
  all original journal bytes and native files; this is not a legacy recovery
  migration. First-use Protection and Attack retain exactly one Browse
  websites control, with independently accessible orphan-jail recovery.

For acceptance, run real Chromium route/width regression plus composition
checks (compact site context, first action visible on desktop, checkbox
alignment, enabled input contrast, conditional warning and global-scope
selector, exact text-rendered Activity evidence). Repeat the installed QA
journeys and inspect real pixels. Do not claim human usability, full
screen-reader acceptance, or production writer qualification from geometry.

## Owner follow-up: secondary actions and disabled-action guidance

[Accepted OF-01/OF-02 contract](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7130362918).
Native 0.1.105 established the shared secondary-button primitive for
Browse websites and Error pages. Error pages retains a distinct scope and
does not inherit the Website selector. No second Browse action.

Use `setActionDisabled(selector, disabled, reason)` at the existing
eligibility transition. A reason can reference the canonical adjacent
inline guidance by its element ID. The native disabled property and
existing request/authorization guards are authoritative; the presentation
helper does not grant permission. An associated focusable help anchor
exists only while the action is disabled; hover, keyboard focus and tap
expose its reason. Escape dismisses the bubble. The description is
associated programmatically, and current evidence/input changes update or
remove it. Enabled controls have no redundant tab stop. Preserve complete
technical diagnostics separately; do not infer recovery from an error.

Coverage matrix (existing actual controls, not new feature requirements):

| Task / action family | Disabled help follows |
|---|---|
| Home and Monitor | pending observation/write, missing verified Monitor state, Refresh |
| Website inventory and baseline | pending/invalid inventory, page bounds, selected/whole baseline comparison and reviewed change |
| Protection | exact selected site, check/preview, saved ruleset refusal, source/recovery state |
| Cache inspect/connect/configure/clear/Bridge | native selection, pending check, fresh site-owned plan/recovery/Applied Cache identity, exact URL validity/approval |
| WordPress Debug/Cron/XML-RPC/HTTPS | selection/value, pending and failed check, Source Ready/Restored vs Already Configured/conflict, matching Recovery ID |
| Routing and selected-site Hosts | verified site, source inspection, removable alias and matching recovery/approval |
| PHP inspect/policy/Apply/Restore/auto | discovered compatible service, pending operations, current form/plan/revision, shared scope and recovery |
| Local hostnames / failed-install witness | refreshed alias selection, matching witness/readiness, stale helper refusal |
| Protection / temporary IP blocking | current site, exact policy, native Lua capability and Guard journal ownership |
| Error pages | explicit independent scope/template, loaded branding, current source/preflight, running/stopped site, saved recovery/approval; separate HTTP and TLS capabilities |
| Activity | pending refresh; dynamic owner links navigate only and never select a target or authorize Restore |

Regression: actual disabled and enabled DOM states are checked in the
seven-width route walk. `disabled_help_browser.cjs` additionally exercises
the real DOM with mocked native responses: pointer/focus/touch, Escape,
viewport containment, pending/Already Configured/Needs Review/malformed
evidence, enabling, stale input, unsupported Guard journal and the exact
allowed WP request contract. This is not live mutation or screen-reader
certification. The installed HTTPS no-op observation is version-bound.
R135 remediation: policy Save invalidates Preview/Prepare tickets both
when the write starts and when it settles, including failure and changed
form/service. Read-only file observations can still run during Save but
cannot authorize Save or Prepare; only a new post-settlement Preview can
grant evidence for the current revision. The existing inline Save status
retains the failure stage/Operation ID and distinguishes confirmed,
rejected and unconfirmed outcomes. The associated help updates with it.

The focused contract matrix covers both callback orders plus no parallel
Preview, across success/refusal/malformed/transport failure and unchanged
form/changed values/changed service. It asserts actual outgoing revision
and observation identity after a fresh Preview. The real DOM suite also
checks the already-open help on settlement and late responses; semantic
reason cases for Guard cover Applied, Recovery Required, no
active saved recovery and actual source/dependency refusal, while global
HTTP unbound distinguishes Conflict/Drift from missing inspection and
uses the existing explicit approvals. These are mocked native responses;
they are not live writer certification.

### Owner follow-up OF-03 / OF-04: anchored help versus real request progress

[Owner-approved correction](https://github.com/AChWorks/ach-aapanel-customizer/issues/128#issuecomment-7131966316).
Native 0.1.106 retains one help surface but uses a white, normal-weight
popover with a subtle border/shadow, an 8px gap and a directional arrow
pointing at the visible control. Position within the content column and
dialog; prefer below, flip above when appropriate, and scroll lengthy
copy internally instead of overlapping the action. Pointer movement,
explicit keyboard focus/Enter/Space and tap can disclose reasons; Escape
dismisses them. Automatic focus restoration and synthetic pointer-entry
events never request help. Keep the hover bridge and associated
description; reduced-motion users get a nonanimated progress glyph.

Use `bindAction(selector, event, handler)` for direct request-producing
buttons, Monitor controls and PHP Preview submit. It scopes the
initiating element to the synchronous handler. The existing
`request()` lifecycle adds/removes that element's progress indicator and
aria-busy state, including stale, malformed, refusal and transport
completions. No new busy guard or request restriction is introduced.
Independent or intentionally repeated read-only requests retain their
own indicator until their outstanding callbacks settle. Navigation
and automatic reads continue using existing task statuses, and
dependent disabled controls may explain their current waiting state
on deliberate inspection. The initiating action does not show
disabled-help while busy or auto-open it when the request settles.
Its original label and native disabled/approval checks remain intact.

The previous R135 expectation that help is open on the initiating
pending Save is superseded by OF-04. The canonical settled reason must
still be accurate and available after explicit subsequent interaction;
late Preview replies must not overwrite it. Existing 36-case identity
and lifecycle assertions remain unchanged. The progress walk exercises
31 actual request bindings in desktop and emulated-touch Chromium,
including Compare, Monitor checkbox changes, independent concurrent
Save/Preview and repeated Preview settlement; all transport is mocked.

Retain #128 and #21 for exact candidate and native QA evidence.

### Wrapped content and approval spacing (Issue #138)

Vertical view/workflow stacks preserve the intrinsic height of each child;
the containing main pane scrolls rather than compressing labels. The
full-width availability flex basis belongs only to horizontal control rows.
Do not use per-button margins to compensate for overflowing text. Checkbox
copy remains inside its padded label, including wrapped and disabled
states. Place approval-following actions in the standard controls row,
including the expanded stale-witness discard action. The layout regression
measures actual text containment, vertical sibling gaps and an 8px minimum
copy-to-action gap, not only border-box alignment. Exercise all native
checkbox controls, including populated PHP Prepare/Recovery and approved/
unapproved transitions, without invoking shared-service writes.

## Protect sensitive files — reference interaction states

The image concept previously generated is **not runtime proof** and its compulsory acknowledgement checkbox is **not mandatory** in this contract.

| State | Main user-facing status and action | Invariant |
|---|---|---|
| Inspect | Not checked → `Inspect protection` | no write |
| Ready | Eligible → `Review & enable` | exact source/target and Nginx reload known |
| Blocked | Missing site-specific include → `View setup guidance` / `Recheck` | no fake Apply; exact manual fix; no silent VHost rewrite |
| Apply | Current → proposed + shared reload → `Enable protection` / `Cancel` | fresh identity/source and authorization |
| Success | Applied **and verified** → `Recheck` / `View recovery` | only claim proof actually observed |
| Error/partial | Could not prove completion → `Recheck` + exact outcome | rollback only when verified, no blind repeat |
| Recovery | Exact owned journal and changed-source guard → `Restore` | recheck stale data; no universal undo |

## Semantic feedback and repeat-action audit (#144)

The same state semantics apply to every native task. Use the common inline
feedback helper and existing summary palette: verified, explicitly scoped
success is green; a partial or conflicting result needing review is amber;
failed/unconfirmed execution is red; pending, inactive, unknown-before-check,
and no-op are neutral. Color is supplementary to the written state and
actionable explanation. File or synthetic evidence is not proof of live or
general privacy behavior. Every new request clears the previous result tone.

| Area | Audited decision |
| --- | --- |
| Home and Monitor | Keep explicit Refresh and revision-aware switches; an unavailable observation is not success. |
| Website baseline | Saved/verified success is visible; unchanged baseline needs no Save; Compare remains available. |
| Protection | Unmanaged is neutral; verified Applied/Restored is green; recovery/unsupported is review. Optional temporary IP blocking shares the Guard owner and recovery. |
| Routing and Hosts | Preserve read-only VHost checks and origin-local scope; alias removal success is confirmed by refreshed inventory; preserve witness repair and emergency Disable even when watcher health is uncertain. |
| WordPress settings | Reflect verified per-setting outcome, actual recovery ownership and request failure; retain independent inspection. |
| Cache and WordPress Connect | Connected disables repeated Connect; Not Connected/Restored disables redundant Disconnect. Check remains available; Needs Review permits repair/recovery. Bridge Provision/Disable observes the exact manifest state. Selection changes and related writes or conflicting recovery identities clear stale proof. Cache Clear is repeatable. |
| PHP services | Separate saved policy, source mapping and runtime results; pending/no change is neutral, persistence warnings are amber, confirmed operation is green. Existing automatic repair state gates and independent emergency Disable remain. |
| Error pages | Distinguish content/route evidence, saved-journal-only, stale selected branding and failed operations. Keep explicit scope Save/Reset (an inherited value match alone cannot prove the scope is stored). |
| Activity and recovery | Severity remains distinct from operation success; unavailable data is red, retention/persistence warnings amber. Never infer a write or recovery authorization from a log. |

Related positive evidence is invalidated on unconfirmed Clear or a
conflicting manifest recovery identity, not on a verified Clear (including
zero removed files). Zero-file Clear is neutral. Bridge inspection uses
its own manifest contract even before the first native lock exists; a
completed WordPress Disconnect stays disconnected independently of later
native Cache generations. Explicitly contradictory action/read-only/runtime
fields cannot establish Connected proof. PHP watcher readiness does not
override its last repair outcome, and unresolved shared-site impact is
review feedback. PHP recovery and Error Pages preflight output are marked
historical when their owning evidence is superseded, even on failed or
unconfirmed requests.

This is a feedback and action-availability refinement, not a new required
checklist or persistence layer. The API remains the authority; no action is
authorized by a UI color or stale observation. The installed release,
independent review, actual native acceptance and exact test receipts are
tracked separately in #144 and #21.

## Current source implementation and acceptance boundary

S1–S5 are merged into `main` through PRs #129–#133, with Owner refinements
through #136. Native 0.1.101 established the task-first redesign; 0.1.103
refined layout; 0.1.105 integrated the R135 remediation; 0.1.106 refines
the help surface and separates initiating-action progress. The historical
0.1.100 package uses the seven-tab interface. The 0.1.106 source was
independently approved, verified on retained QA, and accepted by the Owner.
PR #139 preserves the task-first navigation, corrects wrapped approval spacing
and makes already-current HTTP 404 and source-only 502/50x observations
explicit without granting a write or Recovery. Native 0.1.111 was independently
approved and installed on the retained QA guest; exact evidence remains in
[PR #139](https://github.com/AChWorks/ach-aapanel-customizer/pull/139)
and [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
This does not certify every Production writer or unassisted novice task.
A source ZIP is not a published Release asset. Current release availability
belongs to GitHub Releases; exact installed QA and human acceptance belong
to Issues #21 and #128. The browser projection adds only one selected workflow at a time;
privileged actions continue through the original native backend.

- **Selected website:** Protection remains site-owned; WordPress exposes four
  independent setting choices; Routing exposes VHost, local Hosts, and drift;
  Cache separates passive inspection, WordPress Connect, live site Cache
  configuration, exact Cache Clear and Bridge mapping.
- **Shared server:** PHP exposes inspection, desired policy, explicit live
  shared-service change and independently discoverable saved Recovery;
  local aliases remain site-selection-independent.
- **Error pages:** Template/language/scope selectors remain explicit. Design,
  website publication, future-site defaults, stopped-site 503 and default
  HTTP/TLS routes are separate pages within the same canonical state owner.
  Unsupported scope/template combinations display guidance rather than an
  empty or wrongly actionable screen. Activity links to a known owning task
  without inferring a site or silently executing a recovery.
- **Navigation dependency:** Clear and Bridge expose a direct route to the
  single original Cache Recheck; PHP Apply exposes a route to the original
  read-only preview. Stage shortcuts transfer keyboard focus to the destination
  stage. The mobile Sections menu supports Escape from inside the menu.
  Error page branding read/retry feedback stays common to every mode, while
  editor Save/Reset/Preview outcomes appear beside their controls with one
  canonical live announcement. Explicit Home and reconciliation shortcuts
  open the promised stage rather than a previously visited one; they do not
  change site/service/branding scope or submit an operation. There is no
  duplicate backend action or automatic writer.

**Source/interaction structure is not proof of installed acceptance.** Unit tests,
real Chromium with mocked native reads, and automation can demonstrate specific
behaviors, but not primary-admin native sessions, live backend authorization,
active Nginx effects, human novice completion or the health of the retained
13-site QA fixture. S5 is a separate required acceptance boundary. Record exact
HEAD/CI/QA evidence in the PR and Issue #128, not as a mirrored status log here.

## Validation and delivery slices

- **S0** (design baseline): this agreed contract, Issue mapping, source/API review and operator journey benchmark; **accepted in principle**. Improve when real usability evidence changes an assumption.
- **S1** (foundation): backend dynamic system hostname protection (including direct mutator); truthful Baseline saved/unchanged messaging; shared navigation/site context/Home task flow and reusable state/visual primitives. Use a coherent worktree/PR.
- **S2** (website tasks): Protection, Routing/Hosts/VHost, four WordPress task views and advanced witness/recovery.
- **S3** (Cache/Server tasks): independent Cache/WordPress Connect and exact Clear, PHP shared service vs Monitor, local hostname tasks, default HTTP/TLS routing.
- **S4** (Error Pages/Activity): all 11 template types, supported real delivery/ownership and module-derived Activity/Recovery.
- **S5** (integrated acceptance): ensure no original capability orphaned, native import, 13 retained QA peer sites, current-source/worker checks, scoped real Apply/Restore only with reversible task-owned fixtures, keyboard/accessible feedback/viewport/zoom/RTL and representative novice task completion. Automated tests must bind to actual source/HEAD; source tests never imply live aaPanel verification. Independent review before integration.

All implementation is scoped to the repository and QA permission. **GitHub Merge, public Release and Production require separate explicit Owner authorization after the review gates.** No new VM, snapshot or Production deployment.

## Measured success targets, not current claims

100% current capabilities reachable with truthful scope and backend guarantees; normal tasks within three meaningful navigation choices after target selection; no system hostname removable by UI or direct API; no first-use inactive button maze; no false success or generic Restore; no global horizontal overflow for 320px; keyboard/focus semantics and 200% zoom; actual beginner task evidence (suggested five-person formative cycle, target ≥4/5 unassisted ordinary tasks and 5/5 correct cross-site scope identification before sensitive action). Those participant success criteria remain **unverified** until tested.
