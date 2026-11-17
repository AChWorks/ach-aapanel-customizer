# Installed native aaPanel QA — selected-site onboarding, drift and guided recovery

**Date:** 2026-11-17 UTC
**Repository:** AChWorks/ach-aapanel-customizer
**Acceptance:** Issue #1, comment 6934852538 (implementation); Issue #2 (P0); Issue #21 (native installed QA)
**Integration base:** main@1b724495d854e87412174e174b8567f041cfe66d
**Functional candidate:** 7357c54ff8ce298c3747d81ef04c66ca5349aa73, tree 64b9d7213e6f07ee28eb57acf2e0ef3f353a0bc6
**Native package:** 0.1.51, unreleased; companion Bridge 0.1.8 unchanged; public development release v0.1.49 unchanged
**Built ZIP SHA256:** 3d6c4359487ca2ff7c9856e4ff7c9cb93380691ebda4864448e02012878cf6c3
**Exact package integrity:** Dev and Test builders independently produced the same ZIP hash; native aaPanel vendor update/import succeeded; 57/57 installed payloads matched the ZIP
**Required source regression at functional HEAD:** Python unittest discover 820/820 PASS; Node DOM/UI 328/328 PASS; embedded JS syntax passed; package test passed.

## Guest, ownership, preflight

- Reused the authorized isolated Incus QA guest: project ach-aapanel-qa, instance aac-native-qa, native UUID df2e8224-480e-464b-b0b5-e2d33cb02040; aaPanel 8.0.7, Nginx, PHP-FPM 8.1 and 8.5.
- Preserved protected Incus snapshots qa21-pre-exactzip-20261109 and qa21-cold-restore-20261109. No Production host, alternate Incus guest, or other project modified.
- Browser accessed a real authenticated primary-admin aaPanel session; no credential values are stored in this evidence.
- Before mutation, recorded selected native site/database records, file digest sentinels, Nginx syntax and resident plugin state. Private QA-only backups and execution artifacts remain under /root/achqa/qa-native-reconcile-20261117, not a released ZIP.
- Existing native site IDs: 2,3,4,5,6,7,8,9,10,16,17. Test-owned site ID #18: qa-reconcile-20261117.test. Its local PHP 8.5 index.php returned HTTP 200.

## Installed native operator flow: two closely related candidates

**Candidate 0.1.50: source + native Cache operation exercise (only isolated guest, not publicly released).**
1. Added test site #18 through aaPanel Website Add. Plugin native inventory exposed the real ID, canonical domain, root and PHP include; Website baseline Compare reported it as Added.
2. Initial Cache preflight correctly refused Apply because the new aaPanel-generated VHost lacked a site-specific extension include. Used aaPanel's native VHost editor to add a site-owned extension include, and added the task-only extension directory/PHP index fixture. This is an explicit fixture preparation step; the plugin did not silently alter an arbitrary VHost.
3. Fresh Cache preflight became Ready. Operator approved via the native checkbox. Cache Apply succeeded, and Recheck verified Applied with its recorded recovery identity and runtime marker. Local public GET yielded MISS then HIT; synthetic Authorization-bearing GET bypassed the cache.
4. Added an alias to the same site using aaPanel's native domain binding UI. This regenerated the VHost (file SHA256 changed). The selected-site report showed Needs Review, Cache Recheck showed Needs Review, the runtime marker was unverified and the Restore control remained locked.
5. Removed only that task-owned alias using aaPanel. VHost bytes matched the saved pre-regeneration file exactly. A fresh Cache Recheck returned Applied, followed by explicit independent Restore approval. Restore and final Recheck succeeded with state Restored and verified runtime marker. No synthetic force-Restore or blind config overwrite occurred.
6. Checked that all three original WordPress sites still served local HTTP 200, Nginx syntax passed, PHP-FPM services were active, and original VHosts were preserved.

**Final functional candidate 0.1.51: reviewed single-site baseline + combined read-only report (same exact installed ZIP hash above).**
1. Vendor update from 0.1.50 to 0.1.51 succeeded; all 57 installed files exactly matched ZIP. Persistent native baseline and site #18 Cache journal retained their identical pre-upgrade SHA256 values.
2. First real browser request to save a selected-site baseline failed closed: updated on-disk entrypoint reported version 0.1.51, but the resident panel Python process had retained an old import of the site-baseline helper. Error stage website_selected_baseline_save included a Request ID. The native baseline SHA256 stayed unchanged; no blind retry.
3. Reloaded only the aaPanel panel process on this authorized QA guest using its supported init command. No Nginx/PHP-FPM restart was part of this recovery. New page session and verification showed the current module loaded; the same operation was freshly reviewed and succeeded from the actual aaPanel UI.
4. Before selected-only acceptance: saved baseline revision 1, nine stored historical site records, 12 pending site changes including test site #18. After accepting only selected site #18: revision 2; the original nine stored site records remained exactly equal, 11 other site deltas remained visible and unaccepted, and #18 was no longer pending. The separate all-site acceptance button was NOT used.
5. Installed final 0.1.51 combined report for #18: Baseline Unchanged (revision 2), generated VHost File Match, Cache recovery Restored, PHP policy No Policy, Status Pages recovery explicitly Not Inspected. Read-only, no Apply/Restore token, no claim about live worker/config or external HTTPS.
6. Via native UI, temporarily disabled then reenabled Website Monitor (state revision 2->3->4). Final module configuration returned to its initial enabled values. Site baseline and Cache recovery journal SHA256 were unchanged throughout this Monitor cycle.
7. Final guest verification: Nginx syntax OK; PHP 8.1 and 8.5 services active; the task PHP site HTTP 200; WordPress peers wp1.digikalashop.top, wp2.digikalashop.top and wp3.digikalashop.top each HTTP 200. All eleven pre-existing native aaPanel website ID/name/root/status records unchanged.
8. Original pre-QA digest list contained 107 existing files: 103 remained byte-identical. The four expected changes were plugin info.json (installed version), plugin Activity log, plugin Website baseline file and plugin Monitor settings file. No original VHost, global Nginx configuration, peer PHP configuration or peer recovery journal changed; snapshots remained untouched.

## Important scope and evidence boundaries

- The complete Cache Apply -> regeneration -> blocked Recheck -> restored source -> approved Restore cycle above was executed on intermediate 0.1.50, not repeated in full after the 0.1.51 package update. No Cache adapter logic changed between these functional revisions; the final package passed all source regressions and the actual 0.1.51 browser baseline/combined-report/Monitor acceptance. Do not mislabel the earlier Cache exercise as exact-final-package end-to-end Cache Apply.
- The selected-site report is a point-in-time *composition of independent readers*, not a transaction, policy-engine writer, live-Nginx proof, loaded-PHP worker verification, DNS/TLS verification or evidence of real WooCommerce customer privacy. Each module has its own fresh Apply/Restore authorization and current-source preflight.
- Selected-site acceptance records the one verified native database identity; it does not autoaccept deleted/renamed peer sites or write aaPanel configuration. Historical baseline peers remain until the separately reviewed all-site action.
- No fresh Status Pages Apply/Restore or shared PHP-FPM Apply/Restore was performed in this task; those existing guarded adapters have their own previous QA evidence.
- A full plugin Disable/Uninstall/Reinstall was **not** executed at final candidate 0.1.51 because destroying/reinstalling shared QA plugin state is an additional lifecycle test with potential recovery effects. The existing upgrade and Monitor disable/enable were exercised and persistent state preserved. Native full uninstall lifecycle is *unverified for this candidate*, not claimed as PASS.
- No secondary-admin/Operator account was created; Owner explicitly excluded second-user testing. Endpoint guard tests for primary-admin POST, stale site selection, Monitor revision/source races and uncertain returns passed deterministically; real browser used the authorized primary admin.
- Test site #18, its restored Cache journal and bounded private task fixture remain in the isolated QA guest for reproduction; the protected snapshots and unrelated sites stay intact. Cleanup of fixture must be an explicitly gated, identity-verified future QA disposal, not a blind automatic deletion.
- Not authorized: merge, new public Release, Production deployment, auto-enforce, vendor Purge All, shared-root cleanup, unknown Host HTTPS/443 handling, general site repair or unsupported PHP/Nginx topology.

This evidence is tied to the *functional source candidate* and tested installed ZIP, not a claim that future documentation-only commits changed runtime bytes. Reconfirm the final PR HEAD and required CI independently before review/integration.
