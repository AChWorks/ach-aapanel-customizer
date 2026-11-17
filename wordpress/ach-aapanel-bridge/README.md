# ACh aaPanel Bridge

An **optional, independently versioned WordPress plugin** for
[ACh aaPanel Customizer](../../README.md). It is **not** included in the
native aaPanel ZIP and is not necessary for native website, PHP-FPM, Nginx
or Status Pages features.

The independent source version is declared in
[`ach-aapanel-bridge.php`](ach-aapanel-bridge.php). Published artifacts,
checksums and the paired native pre-release are listed in
[GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases)
(the published development package at this checkpoint is **Bridge 0.1.8**
alongside native **0.1.51**). A downloadable pre-release is **not**
a stable compatibility or Production-deployment certification.

## Normal behavior

Activating Bridge adds **Tools → ACh aaPanel Bridge** for WordPress
administrators with `manage_options`. It reports Nginx Helper activation,
purge mode, cache-path evidence and the current mapping/access state,
with `Not connected` or `Unverified` instead of invented success.

**Disconnected is the default.** Without an explicitly provisioned,
verified, root-owned **current-generation** manifest, Bridge makes no
Nginx Helper Cache-hook changes. Installing Bridge does **not** install,
activate or configure Nginx Helper, alter WordPress options or enable
automatic purging.

When separately enabled under a supported site, it verifies the native
manifest's site identity, primary Host, Cache-directory physical identity,
generation and saved Recovery ID before helping Nginx Helper's ordinary
`unlink_files` / `purge_url` per-URL operation. It selects only existing,
verified **GET and HEAD** keys across HTTP/HTTPS for eligible canonical
URLs. It never directly unlinks arbitrary Cache files, scans recursively,
edits vendor code or adds a public purge endpoint.

Current public-content invalidation covers:

- The post's public canonical URL and homepage after supported published-post
  updates, including the **old and new** public URLs where categories change.
- The original permalink after a **successful permanent delete**; an
  aborted delete cannot trigger that deletion-only invalidation.
- Canonical **first-page public taxonomy archives**, including affected
  old/new terms and applicable hierarchical ancestor archives.
- Real term-only changes outside `wp_after_insert_post`: balanced
  request-local before/after snapshots handle standalone add/remove,
  append/replacement, nested/reentrant callbacks and partially committed
  WordPress `WP_Error` paths without losing the original change.

Each operation retains the vendor's per-URL verification and no-op behavior
when a URL/object is absent, unchanged or ineligible. Internal GET/HEAD
selection context is exception-safe and does not change unrelated ordinary
vendor calls.

**Not supported or certified:** alternative Host aliases, query-style
permalinks, encoded/noncanonical original URIs, author/date/paginated
archives, shared/ambiguous physical Cache roots, automatic website-wide
purge, Nginx Helper's recursive `purge_all()` or universal WooCommerce
payment/session behavior. Native full-tree `clear_files` is an independent,
more strictly scoped Customizer operation and does **not** make vendor
`Purge All` safe.

## Install and inspect

Build a local **unpublished** artifact from the repository root:

```bash
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

For normal use, prefer the [published ZIP and checksum](https://github.com/AChWorks/ach-aapanel-customizer/releases)
on a specifically authorized target. In WordPress use **Plugins → Add New →
Upload Plugin**, activate, then open **Tools → ACh aaPanel Bridge** to
inspect diagnostics. The plugin's `Update URI` avoids WordPress.org slug
collisions; it is **not** an automatic updater. ZIP updates are manual.

No Nginx Helper, manifest or Cache Apply is required **just to view**
diagnostics. For actual URL invalidation:

1. Complete native **FastCGI Cache → Apply → fresh Recheck Applied** for an
   eligible **individually owned** WordPress site and confirm real physical
   separation from every peer. Approve **Provision URL mapping** as a
   distinct operation. This creates the root-owned site-specific
   `wp-content/ach-customizer-bridge/cache.php` manifest.
2. The **operator**, not Bridge, activates/configures compatible Nginx
   Helper for automatic `unlink_files` per-URL invalidation and sets
   `RT_WP_NGINX_HELPER_CACHE_PATH` to **that exact site-owned Cache tree**.
   Never point it at a shared `WORDPRESS` root or enable vendor Purge All.
3. The website's **PHP-FPM process** must have read/write access to the
   same owned directory. If an aaPanel `.user.ini` `open_basedir`
   restricts it, change only that website's allowed paths through an
   independently approved site configuration step, retaining its existing
   site/temp paths. Recheck under real PHP-FPM using Bridge's
   **Site Cache filesystem access / URL-file mapping** diagnostics.
   A root `php` CLI check is not equivalent.
4. Exercise one approved canonical public URL and verify actual HTTP
   Cache response, method-specific disk-key behavior and non-target
   preservation. Do not infer all-worker or private-session safety from
   a healthy manifest alone.

Native **Cache Restore revokes the manifest before retiring its generation**.
**Disable URL mapping** removes only the exact native-owned manifest.
Another Cache generation needs fresh operator opt-in. Restore any operator
changes to Nginx Helper settings and website PHP filesystem access
separately; Bridge does not do this for you.

## Source, QA and open work

The authoritative [native integration guide](../../docs/aapanel-integration.md#optional-wordpress-bridge-operator-prerequisites)
documents its separate native Cache/manifest boundary.
[Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2)
owns unsupported URL/Cache features; [Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
owns real installed WordPress/Nginx Helper/browser/rollback evidence.
The [v0.1.8 code review](https://github.com/AChWorks/ach-aapanel-customizer/pull/91)
and its preceding WordPress QA receipts are preserved on GitHub. Neither
those checks nor a released ZIP provide general production authorization.
