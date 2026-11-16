# ACh aaPanel Bridge

The optional **WordPress companion** for [ACh aaPanel Customizer](https://github.com/AChWorks/ach-aapanel-customizer).

- WordPress plugin slug: `ach-aapanel-bridge`
- Independent companion source version: **0.1.6 candidate** (unmerged/unreviewed, not released or Production-certified; [v0.1.5](https://github.com/AChWorks/ach-aapanel-customizer/pull/85) is merged, while the latest published companion ZIP remains **0.1.4**)
- Source of truth: `wordpress/ach-aapanel-bridge/` in the **same repository** as the native aaPanel plugin
- Distribution: independent WordPress ZIP; it is **not** included inside the aaPanel plugin ZIP

## Current functionality (0.1.6 source candidate)

When activated, the plugin adds **Tools → ACh aaPanel Bridge** for WordPress administrators with `manage_options`. It reports the standard Nginx Helper source/activation observation, in-memory purge method and automatic purge setting when available, and the declared cache path. Missing data is reported as unverified rather than guessed.

**Default remains disconnected.** Without a native-managed, root-owned manifest, the plugin does not add Cache hooks or modify Nginx Helper behavior. **Provision URL mapping** is a separate approved native action after a fresh Cache Apply → Recheck Applied and physical peer-isolation verification.

The vendor's unlink_files per-URL file filter maps canonical, query-free primary-Host URLs only to existing, verified Nginx GET objects in the current native generation. **The v0.1.6 candidate additionally handles separately stored HEAD objects:** during Bridge's own wp_after_insert_post or successful after_delete_post dispatch, it selects the exact GET **and** HEAD keys for the affected public permalink/homepage, across HTTP and HTTPS, and calls Nginx Helper's ordinary per-URL purge_url for each present object. Each vendor callback rechecks the current manifest, Helper mode/path, Nginx KEY header, physical directory identity and regular-file ownership. The method-selection context is bound to the exact URL and reset even if the vendor throws; ordinary Nginx Helper invocations keep their original GET behavior. There is **no Bridge direct filesystem unlink**, recursive sweep or vendor-core edit. The vendor's purge_url($url, false) argument disables extra feed-URL purges, not recursion.

Nginx Helper must be activated and separately configured for unlink_files, automatic purge and the same site-owned cache directory; WordPress PHP-FPM must have directory access. Bridge does not modify Helper options, wp-config.php, .user.ini or PHP services. A published, viewable post's original public permalink is captured at before_delete_post and reconciled only after the permanent deletion succeeds; aborted deletions do not trigger Bridge's new purge. Trash/status transitions remain on the post-save path. **Aliases, query-string permalinks, taxonomies/authors/paginated archives, shared WORDPRESS roots and vendor purge_all() remain unsupported.**

The previous installed v0.1.5 successful-delete and abort-negative QA passed in isolated aaPanel 8.0.7 / WordPress 7.1.4 ([Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21#issuecomment-6914874554)). This **v0.1.6 HEAD candidate has no release or Production certification**; independent review and real method-specific installed QA must be evaluated separately.

Native Cache **Restore revokes the manifest before retiring that generation**. Manual Bridge Disable removes only the exact native-owned site manifest. A new generation requires fresh opt-in. Root-owned metadata and a positive PHP-FPM access observation prove limited site-file preconditions, **not effective Nginx worker state, all-site ownership, session/privacy, or safe vendor Purge All**; the standard Nginx Helper `purge_all()` bypasses this URL filter, so do not enable/advertise Purge All without separately verified physical site scope. This integration has no new public endpoint, socket, cron, remote service or privilege escalation. It does not automatically install/activate WordPress Bridge or switch Nginx Helper's `get_request` mode or legacy shared cache path.

Further all-route/HEAD/archive/WooCommerce invalidation certification remains work under [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), requiring independent code review and real nonproduction acceptance before enablement. Other future WordPress integrations can be added as focused modules without renaming the plugin.

## Development and manual installation

Build the deterministic companion artifact from the repository root:

```bash
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

The archive contains one `ach-aapanel-bridge/` WordPress plugin directory. In a separately **authorized** target WordPress site, use **Plugins → Add New → Upload Plugin**, choose the ZIP, install/activate, then open **Tools → ACh aaPanel Bridge**. No special setup, Nginx Helper installation, or Customizer Cache Apply is required merely to view the diagnostics. Do not confuse installation with an operational cache integration.

The independent version in `ach-aapanel-bridge.php` is the canonical WordPress plugin version. The native aaPanel plugin has its own `info.json` version and separate ZIP. Coordinated GitHub pre-releases can attach both separately versioned artifacts after review and release authorization. The WordPress `Update URI` prevents accidental WordPress.org slug-based replacement; **it is not an automatic update service**. Until an authenticated updater is intentionally implemented, WordPress ZIP updates are manual.

A downloadable pre-release does not imply a Production installation, compatibility certification for all Nginx Helper releases, a licensing grant, or ownership of third-party plugins.

### PHP-FPM filesystem prerequisite (site-scoped, operator configured)

The WordPress PHP-FPM worker must have **read/write directory access to the exact site-owned cache directory** (not the shared cache). On aaPanel sites with per-website `.user.ini` `open_basedir`, add **only** the currently Applied site's owned directory (shown in native Cache Recheck) to that site's allowed paths; preserve existing document root and temporary-file paths. Confirm PHP-FPM has refreshed its `.user.ini` cache, then open **Tools → ACh aaPanel Bridge** to verify **Site Cache filesystem access** and `URL-file mapping`. Do not disable `open_basedir` globally or grant access to the shared `WORDPRESS` directory. This companion does not edit `.user.ini`, PHP-FPM services or WordPress configuration. Record and reverse this site-specific prerequisite when retiring the connection. A root PHP CLI test is insufficient because CLI does not have the website's effective PHP-FPM `open_basedir`.
