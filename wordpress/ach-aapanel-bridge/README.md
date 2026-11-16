# ACh aaPanel Bridge

The optional **WordPress companion** for [ACh aaPanel Customizer](https://github.com/AChWorks/ach-aapanel-customizer).

- WordPress plugin slug: `ach-aapanel-bridge`
- Independent companion version: **0.1.4** (reviewed development pre-release; not production-certified)
- Source of truth: `wordpress/ach-aapanel-bridge/` in the **same repository** as the native aaPanel plugin
- Distribution: independent WordPress ZIP; it is **not** included inside the aaPanel plugin ZIP

## Current functionality (0.1.4)

When activated, the plugin adds **Tools → ACh aaPanel Bridge** for WordPress administrators with `manage_options`. It reports the standard Nginx Helper source/activation observation, in-memory purge method and automatic purge setting when available, and the declared cache path. Missing data is reported as unverified rather than guessed.

**Default remains disconnected.** With no native-managed root-owned manifest, the plugin does not add cache hooks or change Nginx Helper behavior. A separate, explicit **Provision URL mapping** action in native Customizer can supply an immutable site/generation-bound manifest **only after fresh Applied Cache Recheck** and current physical peer-isolation verification. A WordPress Helper `unlink_files` *per-URL file filter* then maps a canonical, query-free URL to its exact **GET** key only when the installed Helper is active, its configured physical cache root matches the native-owned site directory and the cached object has an exact Nginx `KEY` header with expected file identity. An invalid or drifted mapping is refused; **HEAD entries, aliases, query strings, Purge All, and shared `WORDPRESS` zone are not mapped or cleared**. Nginx Helper itself must be separately activated/configured; automatic purging must be enabled in its settings for per-URL post-save reconciliation. For WordPress post-save (including REST/Gutenberg), Bridge also uses the vendor's existing per-URL `purge_url` to reconcile the exact public post and homepage GET entries for both HTTP/HTTPS schemes, guarded by the current native manifest and Nginx Helper settings. It never calls recursive Purge All or edits Nginx Helper settings or files.

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
