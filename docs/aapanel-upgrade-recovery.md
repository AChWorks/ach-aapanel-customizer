# Native aaPanel ZIP upgrade: resident-worker recovery

**Scope:** aaPanel 8.0.7 native plugin update/QA, not an automated restart
procedure, Production authorization, or proof that Nginx/PHP workers reloaded.

## Why this matters

During a documented nonproduction native ZIP upgrade, the official
**App Store → Third-party Plug-ins → Import plugins** operation reported
**Installation succeeded!** and all 55 installed source member hashes matched
the exact ZIP. However, a subsequently invoked new Cache probe returned
`cache_runtime_probe` / `TypeError` in Activity. The installed files were new,
but a resident aaPanel Python worker continued to serve previously imported
code. In the **authorized QA-only** incident, a controlled aaPanel restart
reloaded the new Python implementation and the new probe returned its expected
schema-2 nine-request result.

Original evidence:
- https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6866096928
- https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6866631461

This is a confirmed **one-environment observation**, not a guarantee about
all aaPanel versions or a blanket reason to restart after every install.

## Observe before intervening

1. Verify the native plugin inventory shows the intended installed version.
   When investigating an update failure, compare ZIP file hashes to installed
   plugin members if authorized; the inventory label alone does not prove
   that Python workers adopted the same code.
2. Open **Overview → Refresh state**. The UI displays its packaged version
   and the version compiled into the currently resident Python *entrypoint*.
   An older or missing `worker_source_version` in an otherwise valid Overview
   response is **Upgrade needs review**. This can be observed without
   restarting services, changing cache, or writing site files.
3. If Overview is unavailable or invalid, treat the worker version as
   **unverified**, not as a confirmed stale import. Investigate native session,
   request failure, authorization, and plugin Activity first.
4. For a new feature failing despite exact installed source, open
   **Activity & Logs**. Capture its UTC timestamp, action/stage, error class,
   Operation ID, installed version, and the exact action attempted.
   A `TypeError` alone is not conclusive: check source and call-contract
   compatibility instead of assuming a restart fixes every error.
5. Check Nginx syntax, site health and saved recovery Operation IDs. A
   package upgrade does not authorize touching or discarding recovery
   journals, restarting Nginx/PHP, clearing cache or repeating uncertain
   writes. A matching entrypoint version **does not prove** its imported
   Python helpers are fresh or running Nginx worker configuration.

   **Observed again during isolated QA v0.1.55 -> v0.1.56:** the official
   native ZIP importer installed 61/61 exact candidate file bytes, App
   Store reported v0.1.56, and the resident Python entrypoint matched the
   UI v0.1.56, but the resident `ach_customizer_wp_terminal` helper still
   returned the old response without the mandatory manual-review fields.
   The UI correctly refused that incompatible response. Candidate v0.1.57
   adds a **loaded-helper contract check** to the authenticated WP observer
   endpoint. The unpublished v0.1.60 candidate increments that contract
   to v3: long-domain, incomplete-evidence and single-link crash-safe
   atomic rename semantics must be present before
   the installed entrypoint may trust the resident helper. When the helper
   is stale, Enable/Inspect/Recheck/Restore/
   Discard are refused with a specific reason; Emergency disable remains
   available. Generic Activity stays readable with a warning that private
   manual-review outbox projection cannot be verified. This does not reload
   aaPanel, imply automatically refreshed imports, or certify a running
   watcher. Follow the controlled recovery procedure below **only after
   explicit target-specific authorization**.

## Controlled recovery only with operator authorization

If the installed files are confirmed, the new functionality is blocked by
plausibly stale imports, and a panel-service reload or restart is approved for
the **specific environment** during an acceptable maintenance window:

1. Preserve the known-good ZIP, backup/recovery references and Activity
   evidence; ensure the panel login method remains available.
2. Record current aaPanel, Nginx, PHP-FPM service state and `nginx -t` result.
3. First inspect that aaPanel installation's **actual** `/etc/init.d/bt`
   `reload` implementation. On the authorized aaPanel 8.0.7 QA guest for
   candidate 0.1.51, a **panel-only** `/etc/init.d/bt reload` replaced the
   resident `BT-Panel` process and refreshed its imported helper modules;
   `BT-Task`, Nginx and PHP-FPM did not need to restart. Prefer this bounded
   command **only when that host's script has been verified to provide the
   same semantics** and a brief control-panel interruption is approved.
   If `reload` is unavailable/does not actually reload imports, fall back
   to an explicitly approved `/etc/init.d/bt restart` after assessing its
   larger task/process impact. Neither command is a universal aaPanel
   compatibility guarantee. Do not wire either into ZIP installation,
   a probe endpoint, cron or automatic remediation.
4. Reauthenticate through the normal native panel login. Reopen the plugin
   dialog, **Refresh state** and compare UI/entrypoint versions again.
   First repeat a safe **read-only** inspection to verify the fresh helper
   import and current source. If the prior blocked action was a write,
   establish its earlier outcome from the saved state/journal before attempting
   anything else; obtain a **new** source comparison and explicit approval
   through the original module. Do not blindly resubmit the old request.
   Preserve the Activity Request/Operation IDs before and after recovery.
5. Recheck native plugin member hashes, Nginx syntax, PHP-FPM service health,
   and representative website HTTP/HTTPS status. Recheck any uncertain
   prior Apply/Restore through their original journal, without blind retry.
6. If still mismatched or failing, retain rollback material, stop further
   changes and investigate exact worker logs/import paths and original
   exception. Do not claim success merely because a panel process restarted.

**Observed root cause — stale imported Python helpers:** One later
aaPanel 8.0.7 QA upgrade had byte-identical installed source files **and**
a matching Overview entrypoint version, but the resident worker still used
an older site-baseline helper. A selected-site baseline save failed closed,
leaving its persistent baseline unchanged. After an **explicitly approved
panel-only reload**, a fresh browser comparison and consented save updated
only the selected site's record while preserving its peers. This is an
import-lifecycle observation, **not** a requirement to restart after every
upgrade or evidence that restarting fixes arbitrary exceptions.

The original detailed evidence and recovery proof remain in
[#21 native QA](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6935859654)
and [the exact installed site-reconciliation record](evidence/aaPanel-8.0.7-2026-11-17-site-reconciliation-qa.md).
Neither a matching metadata version nor a successful reload alone certifies
a current helper, worker runtime or safe new host mutation.

## Selected-site reconciliation after native lifecycle events

Site baseline records, saved shared PHP policies, current Cache/Status Pages
recovery journals, and actual host Nginx/PHP configuration are **distinct
authorities**. They survive or change independently during an aaPanel install,
plugin import/restart, site addition, native VHost regeneration, Monitor
disable, uninstall and reinstall. The selected-site report does not
modify or migrate any of those stores and is not an automatic repair process.

For a new or modified website, accept only its reviewed native identity with
**Website list → Compare website records → Save only selected website baseline**.
This preserves other sites' previous saved baseline records and pending
changes. The older **Save baseline for ALL websites** deliberately replaces
the complete snapshot; never use it merely to accept one new website. An
uncertain scoped write must be reconciled with fresh Compare, not retried
blindly. A removed site requires separate explicit all-site review.

On an authorized test host, record the existing plugin ZIP SHA256, installed
member hashes, primary administrator role, current native site key/ID and
bindings, saved baseline revision, relevant shared PHP service, journal
Recovery ID, Nginx syntax, and healthy peer sites **before** lifecycle testing.
After a replacement, reopen/refresh the panel and confirm the resident
Python entrypoint version. Use Website list Compare, Routing & Nginx Review
selected site & recovery, and the relevant module's **fresh independent**
Recheck. Never use an old combined report as a write precondition.

When the selected native site identity, baseline revision, PHP source or
generated VHost changes while a review is running, its report is invalid;
refresh native inventory and rerun. If a guarded Cache/Status operation has
a retained recovery journal but source ownership is unknown, **do not**
replace the journal, remove the generated file manually, or blindly retry.
Preserve an Operation ID and investigate exact current source/peer impact
with a separately approved module Restore only after its original adapter
proves eligibility. Site deletion or a native ID reused for a different
site also requires manual orphan/identity recovery; the combined report
does not perform that destructive step.

An update/disable/uninstall/reinstall acceptance is complete only when
operator configuration and recovery records remain readable, native files
and peer site behavior are accounted for, and uncertain steps are explicitly
reported rather than counted as successful. A successful ZIP import, green
CI or matching entrypoint version alone does not establish those outcomes.
