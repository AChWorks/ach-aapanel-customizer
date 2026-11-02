# ACh Status Pages - deployment guide (preview build v1)

22 standalone HTML documents (11 scenarios x English/Persian) with inline CSS, system fonts, no JavaScript or remote dependencies.

## Index

- `en/404.html`, `fa/404.html`: missing route (404).
- `403.html`: restricted resource (403).
- `429.html`: request throttling (429).
- `500.html`: server failure (500).
- `502.html`: upstream/gateway failure (502).
- `503.html`: temporarily unavailable (503).
- `504.html`: timeout (504).
- `50x.html`: generic emergency fallback (serve with actual failure status).
- `new-site.html`: default page for newly created site (normally HTTP 200).
- `unbound.html`: unknown domain / missing VHost (should NOT be HTTP 200).
- `stopped.html`: intentionally stopped/temporarily unavailable site (use HTTP 503 when temporary).

The pages set `noindex,nofollow`. They link to https://ach.li; site error pages also link to their own root or retry the current URL. All are independent: you can open a file without hosting its CSS anywhere else. Each language has a native `lang`/`dir` and localized text.

**Production status:** HTML files created and browser-tested locally. No server files, VHosts, reloads, databases, or WordPress data have been changed. Nginx example below is tested in an isolated local Nginx environment, not deployed on aaPanel servers.

## Option A: immediate, per-site repair of deleted `404.html` / `502.html`

The inspected aaPanel-created Nginx VHosts already contain:

```nginx
error_page 404 /404.html;
error_page 502 /502.html;
```

For a regular website, these resolve to the site's DOCUMENT ROOT (not necessarily `/www/acdomains/<site>`; verify the VHost `root`). The source files are `en/404.html` or `fa/404.html` and `en/502.html` or `fa/502.html`.

Example for a selected WordPress site whose DOCUMENT ROOT is `/www/acdomains/example.com`:

```sh
SITE_ROOT=/www/acdomains/example.com
# Inspect before replacing any pre-existing custom page.
ls -l "$SITE_ROOT/404.html" "$SITE_ROOT/502.html" 2>/dev/null || true
# From the unzipped package directory, after target-specific authorization:
install -o www -g www -m 0644 en/404.html "$SITE_ROOT/404.html"
install -o www -g www -m 0644 en/502.html "$SITE_ROOT/502.html"
```

Choose `fa/` for Persian. For a public-root framework website, the root may be `/www/acdomains/example.com/public` instead. Check the exact `root` in `Website > Config` or `/www/server/panel/vhost/nginx/<site>.conf`.

Only replacing HTML files needs no Nginx reload. Verify by requesting a new nonexistent static path (at origin, not only through a CDN) and confirm the HTTP status remains `404` and the branded HTML is served. Real `502` testing must use a safe isolated test; DO NOT stop a production PHP/backend service just to test it.

## Option B: a single shared file set for many websites (recommended long-term)

Keep the templates OUTSIDE site document roots, for example:

```
/www/ach-status-pages/en/404.html
/www/ach-status-pages/en/502.html
/www/ach-status-pages/fa/404.html
/www/ach-status-pages/fa/502.html
```

Copy each complete `en/` and `fa/` directory there (permissions: directories 0755, files 0644, readable by Nginx). In the verified aaPanel per-VHost extension directory, add a site-specific server-context include based on `examples/site-error-alias.conf`:

```
/www/server/panel/vhost/nginx/extension/<site>/ach-status-pages.conf
```

The `location = /404.html` and `/502.html` exact matches alias to the shared files. Existing aaPanel `error_page` references remain in the VHost. The example also adds optional mappings for 403, 429, 500, 503, 504; do not activate any mappings that conflict with an existing application-managed behavior. Change `/en/` to `/fa/` when appropriate.

**Before any production VHost change:** make a backup, inspect *effective* Nginx config and overlaps, review existing `location` blocks, run `/www/server/nginx/sbin/nginx -t`, reload only after success and authorization, check status and body, and verify rollback. aaPanel-generated files may be regenerated. Test extension durability on your actual panel version. For WordPress, keep its genuine application-level 404 pages; do not globally enable `fastcgi_intercept_errors` or `proxy_intercept_errors`.

## Future websites: aaPanel source templates (verified on observed installation)

Read-only inspection of the installed `panelSite.py` confirmed that the panel copies these templates **only if the destination does not already exist** during site creation:

| Default source file | Destination in the newly created website |
| --- | --- |
| `/www/server/panel/data/404.html` | `<site-root>/404.html` |
| `/www/server/panel/data/502.html` | `<site-root>/502.html` |
| `/www/server/panel/data/defaultDoc.html` | `<site-root>/index.html` |

After backup and explicit production approval, place the corresponding language's `404.html`, `502.html`, `new-site.html` (renamed `defaultDoc.html`) in these source-template paths to affect FUTURE site creation. It will **not** automatically change existing websites. aaPanel updates may replace its managed templates; monitor drift.

## Special fallback pages

- Stopped website: aaPanel has `/www/server/stop/index.html`. The package's `stopped.html` is a visual replacement candidate. Copying it does not itself set HTTP 503; verify stop-site VHost response and enforce 503 only with a reviewed, supported rule.
- Unbound domain: `/www/server/nginx/html/index.html` is one stock Nginx page, but it might not be the active catch-all. On the inspected NL host, `ach.li` itself is configured with `default_server`; unknown domains reached a 200 response in prior tests. Review the actual port-80/443 default-VHost and SNI before changing it. An unbound domain should return a proper 404/421 as applicable, NOT a successful 200 page.
- Generic Nginx fallback: `/www/server/nginx/html/50x.html` exists as a stock file but Nginx only uses it when a configured `error_page` points to it. Use `50x.html` accordingly; preserve the actual HTTP failure code.
- Cloudflare error pages: errors generated at the Cloudflare edge do not necessarily use your origin Nginx templates.

## Verification checklist

1. Identify the `server_name`, `root`, active default VHost, error-page mapping and target language.
2. Backup files and configuration; do not overwrite application-specific `404.html` without review.
3. Stage/copy files. Test a known-nonexistent static URL; check response body and status.
4. For Nginx config changes: syntax test, authorized reload, origin + CDN check, non-regression tests (`/.well-known/`, WordPress 404, static files, private paths).
5. Verify no `200` for unknown/maintenance/error states unless explicitly intended (new-site landing is a legitimate `200`).
6. Keep templates versioned outside aaPanel vendor core where possible; record the affected sites and a restore command.

## Source and quality checks

- `python3 source/build_pages.py` regenerates all HTML files using `source/fa-copy.json` and built-in English strings.
- `python3 source/verify_pages.py` checks all pages and uses locally available `playwright`, `bs4`, and Chromium for 320/390/768/1440px viewport smoke tests.
- The HTML templates have no external requests/JS; the source and smoke test are included for editable handoff.

## Important security separation

Nginx does not interpret `.htaccess`. On an inspected production host, nested `.htaccess` contents were retrievable as HTTP 200; a separate issue records the validated gap and requires an effective Nginx policy for nested dotfiles and private directories. **Do not mass-delete `.htaccess` until actual protections are translated and verified.** These visual page files are NOT a security remediation.
