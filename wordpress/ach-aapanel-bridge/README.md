# ACh aaPanel Bridge

The optional **WordPress companion** for [ACh aaPanel Customizer](https://github.com/AChWorks/ach-aapanel-customizer).

- WordPress plugin slug: `ach-aapanel-bridge`
- Independent companion version: **0.1.0** (development candidate, not published)
- Source of truth: `wordpress/ach-aapanel-bridge/` in the **same repository** as the native aaPanel plugin
- Distribution: independent WordPress ZIP; it is **not** included inside the aaPanel plugin ZIP

## Current functionality (0.1.0)

When activated, the plugin adds **Tools → ACh aaPanel Bridge** for WordPress administrators with `manage_options`. It reports the standard Nginx Helper source/activation observation, in-memory purge method and automatic purge setting when available, and the declared cache path. Missing data is reported as unverified rather than guessed.

**No active bridge or cache operations in this version.** The diagnostics do **not** prove that Nginx Helper's `get_request`, `unlink_files`, or `Purge All` safely target an aaPanel Customizer cache generation. The plugin does not install or change Nginx Helper, does not write WordPress options, does not modify Nginx, and has no network listener, schedule, remote endpoint, background updater, or automatic cache hook.

The separate, generation-aware invalidation contract between the native plugin and WordPress remains work under [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), requiring independent code review and real nonproduction acceptance before enablement. Other future WordPress integrations can be added as focused modules without renaming the plugin.

## Development and manual installation

Build the deterministic companion artifact from the repository root:

```bash
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

The archive contains one `ach-aapanel-bridge/` WordPress plugin directory. In a separately **authorized** target WordPress site, use **Plugins → Add New → Upload Plugin**, choose the ZIP, install/activate, then open **Tools → ACh aaPanel Bridge**. No special setup, Nginx Helper installation, or Customizer Cache Apply is required merely to view the diagnostics. Do not confuse installation with an operational cache integration.

The independent version in `ach-aapanel-bridge.php` is the canonical WordPress plugin version. The native aaPanel plugin has its own `info.json` version and separate ZIP. Future coordinated GitHub Releases may attach both artifacts only after their respective review, release and licensing decisions. The WordPress `Update URI` prevents accidental WordPress.org slug-based replacement; **it is not an automatic update service**. Until an authenticated updater is intentionally implemented, WordPress ZIP updates are manual.

No Production install, public Release, licensing grant, or third-party-plugin ownership change is implied by this development candidate.
