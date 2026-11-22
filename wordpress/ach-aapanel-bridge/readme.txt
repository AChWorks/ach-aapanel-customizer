=== ACh aaPanel Bridge ===
Tags: aapanel, nginx, cache, wordpress, diagnostics
Tested up to: 7.1
Stable tag: 0.1.10
License: MPL-2.0
License URI: https://www.mozilla.org/en-US/MPL/2.0/

Optional WordPress diagnostics and opt-in, site-owned Nginx Helper cache URL invalidation for ACh aaPanel Customizer.

== Description ==

ACh aaPanel Bridge is a separately packaged, optional WordPress companion for
[ACh aaPanel Customizer](https://github.com/AChWorks/ach-aapanel-customizer).
It is intended for operators who manage a compatible site-owned FastCGI cache
through the native aaPanel plugin.

After activation, visit **Tools > ACh aaPanel Bridge** to inspect the observed
Nginx Helper activation, purge settings, cache path and integration readiness.
The page is available to WordPress administrators with manage_options.

**Disconnected by default.** Installing this plugin does not install or
configure Nginx Helper, create a cache, enable purging, alter WordPress
configuration or make any changes to aaPanel, Nginx or PHP-FPM.

With an independently authorized, verified native Cache generation and a
root-owned site manifest, Bridge can participate in Nginx Helper's normal
per-URL unlink_files workflow for supported public URLs. It validates the
current site, canonical Host, Cache directory and generation, then selects
existing GET/HEAD cache objects for HTTP and HTTPS without a recursive purge.

Supported invalidation includes published public post URLs, the homepage,
eligible first-page public taxonomy archives, successful permanent deletion,
and real term-only changes. Nested term callbacks and partially committed
term changes are handled without dropping an outer committed operation.
Missing, changed or unsupported URL/cache objects are left alone.

**Not supported:** arbitrary Host aliases, query-string permalinks,
noncanonical or encoded paths, author/date/paginated archives, physically
shared Cache roots, automatic site-wide purging, or Nginx Helper's vendor
Purge All. The separately guarded native site-owned full-tree Clear is a
different operation and does not make vendor Purge All safe.

This GitHub-distributed package is a development pre-release, not a
Production deployment or general compatibility certification. Actual
nonproduction acceptance includes WordPress 7.1.4 and Nginx Helper 2.4.1
in an isolated aaPanel 8.0.7 environment; untested combinations require
separate verification. For evidence and scope, see the
[project QA issue](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).

== Installation ==

1. On a specifically authorized site, download the standalone ACh aaPanel
   Bridge WordPress ZIP and its checksum from
   [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases).
   Do not import the native aaPanel ZIP into WordPress.
2. In WordPress open **Plugins > Add New > Upload Plugin**. Upload, install
   and activate Bridge. Open **Tools > ACh aaPanel Bridge**. Diagnostics work
   even without Nginx Helper or a native Cache mapping.
3. To enable actual URL-file invalidation, first complete the native
   Customizer **FastCGI Cache > Apply > fresh Recheck Applied** on one
   physically independent WordPress Cache tree. Separately approve
   **Provision URL mapping** for the selected site; this creates a
   native-owned manifest in wp-content/ach-customizer-bridge/cache.php.
4. The operator must separately activate and configure compatible Nginx
   Helper with automatic unlink_files per-URL purging and
   RT_WP_NGINX_HELPER_CACHE_PATH pointing to the **same exact site-owned
   directory**. Never point it to a shared WORDPRESS Cache root.
5. The website's PHP-FPM worker needs filesystem access to that directory.
   If the site uses .user.ini open_basedir restrictions, separately approve
   adding only the site's owned Cache path without removing existing
   site/temp paths. Recheck access from WordPress Tools diagnostics under
   the site's PHP-FPM worker; a root CLI check is not equivalent.
6. Test a canonical, public URL and confirm HTTP Cache behavior and peer
   preservation. A positive manifest check is not proof of loaded Nginx
   worker state, checkout/session privacy or safe recursive purge.

Native **Cache Restore** revokes its manifest before retiring the generation.
**Disable URL mapping** removes the exact native-owned mapping. Manually
reverse any operator changes to Nginx Helper options or site PHP filesystem
access; Bridge does not change these settings for you.

The detailed
[operator and recovery guide](https://github.com/AChWorks/ach-aapanel-customizer/blob/main/docs/aapanel-integration.md)
covers the native adapter's readiness, ownership and Restore procedures.

== Frequently Asked Questions ==

= Does activation immediately purge cache? =

No. The plugin is disconnected until a current, independently approved
site-owned manifest and Nginx Helper prerequisites are verified.

= Can I use Nginx Helper's Purge All? =

Not as part of this integration. Its recursive vendor operation bypasses
the per-URL filter and can affect unrelated cache data on a shared root.

= Why is the diagnostics page reporting Not connected or Unverified? =

The manifest, Helper mode/path, filesystem permissions, current generation
or verified URL mapping may be missing or stale. Review the exact diagnostics,
then use the original native Cache module's fresh Recheck and authorized
provision/Restore flow. Do not bypass a refusal by editing the manifest.

= Does this plugin auto-update? =

No. The external Update URI prevents accidental WordPress.org slug-based
replacement, but it does not provide an update server. Use explicitly
verified, manually installed ZIPs from the project Releases page.

= Is this a WordPress.org Plugin Directory release? =

No. This is a GitHub-distributed development pre-release. Plugin Directory
submission, licensing and other Directory requirements are separate
decisions and are not implied by the presence of this standard readme.txt.

== Changelog ==

= 0.1.10 =

* Declare MPL-2.0 in WordPress plugin metadata and ship the complete license
  with the standalone ZIP. Functional WordPress Cache behavior is unchanged.

= 0.1.9 =

* Reconcile the official, authorized frontend Purge Current Page action
  against the selected site's generation-bound HTTP/HTTPS GET/HEAD cache objects
  through the existing verified Nginx Helper per-URL file filter.
* Keep invalid/unauthorized purge requests and the independent vendor
  recursive Purge Entire Cache outside that per-URL integration.

= 0.1.8 =

* Handle published post/homepage invalidation after term-only changes.
* Preserve nested and reentrant term-change context, including committed
  partial WordPress errors, without a broad or recursive purge.
* Retain current-generation GET/HEAD invalidation for eligible public
  permalinks and first-page taxonomy archives through Nginx Helper.

Older reviewed changes and their exact tests remain in the
[project pull requests](https://github.com/AChWorks/ach-aapanel-customizer/pulls)
and [native QA history](https://github.com/AChWorks/ach-aapanel-customizer/issues/21).
