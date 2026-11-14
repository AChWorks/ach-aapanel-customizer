# Native aaPanel ZIP upgrade: resident-worker recovery

**Scope:** aaPanel 8.0.7 native plugin update/QA, not an automated restart
procedure, Production authorization, or proof that Nginx/PHP workers reloaded.

## Why this matters

During the independently recorded 0.1.40 native QA upgrade, the official
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

## Controlled recovery only with operator authorization

If the installed files are confirmed, the new functionality is blocked by
plausibly stale imports, and a restart is approved for the **specific
environment** during an acceptable maintenance window:

1. Preserve the known-good ZIP, backup/recovery references and Activity
   evidence; ensure the panel login method remains available.
2. Record current aaPanel, Nginx, PHP-FPM service state and `nginx -t` result.
3. The authorized administrator may run the aaPanel panel-service command
   `/etc/init.d/bt restart` **on that approved host only**. Do not wire this
   command into ZIP installation, a probe endpoint, cron, or automatic
   remediation.
4. Reauthenticate through the normal native panel login. Reopen the plugin
   dialog, **Refresh state** and compare UI/entrypoint versions again.
   Re-run **only the previously blocked read-only probe** and correlate its
   result with its new Activity Operation ID.
5. Recheck native plugin member hashes, Nginx syntax, PHP-FPM service health,
   and representative website HTTP/HTTPS status. Recheck any uncertain
   prior Apply/Restore through their original journal, without blind retry.
6. If still mismatched or failing, retain rollback material, stop further
   changes and investigate exact worker logs/import paths and original
   exception. Do not claim success merely because a panel process restarted.

**Limits:** No automatic restart, new privileged endpoint, logout bypass,
new Apply/Purge permissions, or public Release is part of the 0.1.41
observation. One matching version is not a full module-integrity or live
routing certification. Exact v0.1.41 positive native Browser acceptance
confirmed the matching-version path. Real native stale-worker mismatch and
subsequent authorized reload **did not reproduce** for that ZIP; the synthetic
Browser negative attempt is unverified, while local negative-response tests
passed. A later controlled mismatch/reload reproduction remains a separate
native QA objective, not a retrospective claim of success or an unapproved
mandatory integration gate for the narrow read-only v0.1.41 diagnostic.
