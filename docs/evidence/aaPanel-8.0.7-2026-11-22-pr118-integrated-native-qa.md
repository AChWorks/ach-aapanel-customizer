# PR #118 — bounded installed-native QA on the retained aaPanel guest

**Status:** completed bounded native integration evidence for installed Native
**0.1.83** and source commit **`42c51c898c3b966a522c9d4a4c9ef9258d1e39d4`**.
This is not an independent code review, public Release, production
qualification or blanket certification of pending Issue #2 capabilities.
The canonical source proposal is [PR #118](https://github.com/AChWorks/ach-aapanel-customizer/pull/118);
the continuing source/QA contract is [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

## Environment and source identity

- **Exactly one retained VM:** Incus `ach-aapanel-qa/aac-native-qa-20261118`,
  UUID `deb34917-cdaf-4c04-8428-b6d32a0bcd67`, 10.131.48.20,
  **Running**. No new VM, snapshot, replacement, VM shutdown or production target.
- Native aaPanel **8.0.7**; Nginx **1.30.6**; PHP-FPM **8.1/8.5**;
  system Fail2ban **1.1.0**, Cron and MariaDB. Optional Bridge **0.1.9**
  unchanged by the proposal.
- Both 0.1.82 and final **0.1.83** were installed through the actual
  authenticated aaPanel **App Store / Third-party Plug-ins / Import plugins** UI,
  not substituted by directly copying test files into the installed plugin.
- Final 0.1.83 deterministic QA ZIP SHA-256:
  `4c3dc2e1c49d460d3823f83dc4f8c76dc6ef4047421264658342b199afbb63ed`.
  All **67/67** ZIP member hashes matched the native installed files; no missing,
  differing or unrelated files in that plugin directory.
- A controlled **panel-only** `/etc/init.d/bt reload` was performed after
  verifying that VM's actual script. This was necessary because aaPanel retained
  an older imported helper in memory even when the new native files and
  resident entrypoint version were present. Nginx, PHP-FPM, Fail2ban and Cron
  remained active; protected native login succeeded again. It does not imply
  that ordinary ZIP import always requires or authorizes such a reload.
- Exact 0.1.83 candidate GitHub CI:
  [run #44960571607](https://github.com/AChWorks/ach-aapanel-customizer/actions/runs/44960571607)
  **completed / SUCCESS**. The 0.1.82 source full Python run directly in the
  Dev worktree was **1,177 OK / one optional skip**, and the 0.1.82 UI
  harness **376 PASS**. A later 0.1.83 TLS regression test and packaging suite
  passed locally and are included in exact 0.1.83 successful CI.

## Actual native operator/UI and website results

1. **Read-only site profiles:** native Website list showed site `#5`
   `wp.aitest.gotohell.top` as `WordPress files detected (runtime unverified)`;
   site `#6` `woo.aitest.gotohell.top` as
   `WordPress + WooCommerce files (activation unverified)`; site `#1`
   static as `Needs Review`. No inference of WooCommerce activation from
   filesystem presence; no mutation by inventory.
2. **Manual WordPress Debug**, installed 0.1.82 (feature source unchanged in
   installed 0.1.83): selected native WordPress site `#5`, then genuine plugin
   UI `Recheck → Apply → Recheck → Restore`. The site's own PHP CLI executed
   as `www` loaded WordPress and observed `WP_DEBUG=true`. The site,
   WooCommerce peer and static peer returned HTTP 200.
3. **Manual system WP-Cron**, same site and version: genuine plugin UI
   `Recheck → Apply → Recheck → Restore`. A root-owned mode 0644
   `/etc/cron.d/ach-customizer-wp-cron-5` task ran the site's PHP 8.5 as
   `www`, schedule `*/5`. WordPress loaded as `www` observed
   `DISABLE_WP_CRON=true`; manually running the exact `wp-cron.php`
   invocation as `www` succeeded. The task was removed on Restore;
   `wp-config.php` returned to original SHA-256
   `094503f86b383ea4fd058a9063dccb668c5c23654598b65da838273fa7519c40`.
   This proves invocation and source/runtime constant, not that every
   WordPress scheduled hook would execute on its future minute boundary.
4. **Unknown/no-SNI HTTPS/443 Option A**, native **0.1.83**:
   before testing no Nginx port 443 existed, and native TLS Recheck returned
   **Not Applicable** with disabled Apply. A temporary **task-owned**
   dual-stack wildcard HTTPS/443 native Nginx VHost plus a short-lived,
   nonproduction certificate was introduced with syntax-checked reload.
   Its configured hostname `ach-pr118.aitest.gotohell.top` returned HTTPS
   200 over IPv4 and IPv6. Native plugin UI
   `Recheck → Apply → Recheck → Restore` passed:
   - During Apply, native probe on **both IPv4 and IPv6** observed the known
     SNI accepted, unknown SNI **rejected**, and no SNI **rejected**.
     The known-host certificate fingerprint stayed identical to the
     pre-Apply certificate. Nginx `-t` and all three HTTP peers passed.
   - The saved recovery `e2b67573b8f04acaa653d88c1fd9454d`
     advanced from `applied` to `restored` on the real Nginx operation,
     with confirmed no-SNI/unknown-SNI behavior after Restore.
   - The task-owned HTTPS VHost and certificate/private key were cleaned
     after Restore; no port 443 listener remained; native Recheck again
     returned **Not Applicable**, with Apply disabled.
   - Initial installed 0.1.82 trial had an honest **Uncertain** result despite
     correct eventually-settled handshake behavior. The actual causes
     investigated were asynchronous Nginx-worker reload settling and a
     stale imported aaPanel helper. Commit `42c51c8` uses bounded waiting
     for three consecutive matching live handshake rounds and improves
     typed failure evidence. Older recovery journals were restored normally
     before the final successful 0.1.83 cycle.
5. **Offline orphan Fail2ban recovery**, actual installed 0.1.83 module code
   with a **separate real Fail2ban daemon and nftables inside an ephemeral
   Linux network namespace on this same VM** (not a new VM):
   - A synthetic journal-owned jail `ach-customizer-scan-2000000123` used a
     task-owned native-format log within `/www/wwwlogs`. Native aaPanel
     SQLite `sites` confirmed that site ID was absent. The private daemon
     started with that jail; the host's real Fail2ban daemon and sole
     `sshd` jail were never stopped or reconfigured.
   - Stopping **only the isolated** daemon and deleting its own task log
     made the isolated Fail2ban configuration test reject the missing log.
     Calling the installed plugin's `manage_orphans` logic with the original
     Recovery ID retired precisely the owned orphan jail source offline,
     retained a durable `restore_pending` journal, and returned
     `runtime_verified=False`. There was no false claim that bans had
     been removed.
   - The isolated daemon then restarted with its other task-owned sentinel
     jail; online Restore through the installed module checked runtime
     jail absence and actual isolated `nft -j list sets`. The journal
     reached `restored`, `runtime_verified=True`, and the orphan list
     became empty. The isolated daemon was stopped and all task-owned files
     were cleaned. Real host Fail2ban remained **active with exactly
     `sshd` jail**. This is real daemon/source/firewall recovery against a
     synthetic, DB-confirmed-absent site identity, **not** a claim that
     the official aaPanel site-delete UI itself was executed.

## Final restoration and boundaries

- Native site `#5` `wp-config.php` exact original SHA as above, and task
  WP-Cron entry absent. Temporary TLS listener/certificate and isolated
  Fail2ban namespace/files absent. Plugin TLS recovery journal retains
  `restored`, as intended. The one persistent QA VM remains **Running**.
- Nginx `-t` **PASS**; `btpanel`, `nginx`, `php-fpm-81`,
  `php-fpm-85`, `fail2ban`, `cron` **active**;
  `wp.aitest.gotohell.top`, `woo.aitest.gotohell.top`,
  `static.aitest.gotohell.top` each HTTP **200**. Original
  Fail2ban `sshd` jail remains the sole live host jail.
- **Not proven here:** actual deletion through aaPanel's native Website UI,
  future scheduled WP hook execution at a real cron tick, WooCommerce
  authenticated cart/payment/webhook/REST on exact 0.1.83 (earlier scoped
  evidence remains version-bound), all Nginx/IPv6/QUIC topologies, all PHP
  versions, native XML-RPC/canonical-HTTPS controls not implemented by
  this PR, vendor Nginx Helper recursive Purge All on ambiguous cache roots,
  public Release, Production or independent exact-HEAD code review.

**Gate:** Source PR stays **DRAFT / not merged** pending exact-head
independent reviewer verdict and the Owner's separate Merge permission.
Releases and Production require their own authorization. Issue #2 stays
open for genuinely unfinished optional/compatibility product outcomes.
