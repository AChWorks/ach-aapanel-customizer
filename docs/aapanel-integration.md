# aaPanel native integration - evidence and provisional boundaries

This is **technical integration guidance**, not a second product specification.
The canonical requirements remain in [PROJECT-SPEC.md](PROJECT-SPEC.md), and the active research/acceptance owner is [Issue #1](https://github.com/AChWorks/ach-aapanel-customizer/issues/1).

## Primary source evidence

1. Official [aaPanel third-party plugin documentation v1.1](https://www.aapanel.com/pkg/aaPanel_Linux_Panel_Plug-in_development_documentation_v1.1.pdf), pages 1-2: `plugin/<name>/<name>_main.py`, `index.html`, `info.json`, `icon.png`, `install.sh`; class matches `<name>_main`; conventional POST invocation uses `/plugin?action=a&name=<name>&s=<method>`.
2. The official [demo.zip](https://www.aapanel.com/pkg/demo.zip) was inspected **as data, not executed**. Its parent folder is `demo/`; its `index.html` opens inside aaPanel and requests methods through the legacy `/plugin` route. Sample SHA-256 at inspection: `52f2d7f212212a1496b91c0f96070ce83c8ea66ee63c1b755eb6d16863cfadff`. The supplied sample is not a security template.
3. Official [App Store docs](https://www.aapanel.com/docs/Function/AppStore.html) describe Third-party Plug-ins -> Import Plug-ins, but do **not** prove lifecycle/update compatibility on any specific installation.
4. Public aaPanel source [panelPlugin.py](https://github.com/aaPanel/aaPanel/blob/38bf35903b37b50d9654f47c4ad904ca3369715f/class/panelPlugin.py) recognizes `plugin/<name>/info.json` and constructs local-plugin inventory. The inspected implementation invokes uninstall scripts and removes plugin code. This is source evidence for that Git revision, **not** a cross-version contract.
5. The same official PDF documents read-only `public.M('sites')` selectors for site IDs, names, paths and status. Actual panel schemas and revision-specific API behavior still require tests.

## Important security boundary

The aaPanel PDF explicitly warns: **dynamic plugin routes do not inherit aaPanel session authorization** and require an appropriate `_check` implementation. Its sample declares `_check` returning `True`, allowing unauthenticated requests. **Never copy this sample access pattern.**

This first candidate intentionally **does not define `_check`** and only uses the conventional in-panel `/plugin?action=a` route. The exact current session/permission/CSRF enforcement still requires an isolated, version-specific runtime test before privileged operations are added. No Apply/write endpoint is exposed in this candidate.

## First non-production implementation slice

`plugin/ach_customizer/` is a prototype native plugin package with an in-panel read-only UI and two narrowly bounded read operations:

- `get_sites`: paginated source records from the panel's `sites` table. IDs are returned as discovered; no WordPress-specific assumption or hard-coded list. Application and resource relationships remain **Needs Review** until verified.
- `preview_php_fpm`: compares *operator-supplied* concurrency values to explicit `[www]` pool settings in a single, conventional, versioned PHP-FPM configuration file. Rejects missing/ambiguous/duplicate/unreadable configuration. The result's scope is **shared service**. It does not infer sites sharing a pool, include-expanded config, effective runtime, or what aaPanel would write. It NEVER writes, reloads, restarts or schedules anything.

This is **not a supported package or initial release**. `install.sh` owns no resident service or host settings; ordinary uninstall is expected to be handled by aaPanel and must be demonstrated. Overall/per-module enable/disable, persistent policies, authorization checks for future writes, update/uninstall/reinstall semantics, and recovery are still pending. Do not equate a source or ZIP build with those outcomes.

## Compatibility and acceptance status

| Required proof | Status |
| --- | --- |
| Official plugin layout, request syntax, sample ZIP | Source-verified; current version compatibility unverified |
| Real aaPanel version, OS and module matrix | Not selected |
| Real native import, in-panel load and auth/CSRF behavior | Unverified |
| Dynamic discovery and a new/renamed non-WordPress site | Pure unit fixtures only |
| Shared PHP-FPM config file preview and source syntax | Pure fixture tests only; runtime/impact unverified |
| Panel site generation and regeneration effects | Unverified |
| Enable/disable, update, uninstall, reinstall and persistence | Not implemented/verified |
| Nginx include durability and syntax/application/rollback | Unverified |

A non-production aaPanel test is essential before accepting Issue #1. Do **not** install on production. When an isolated environment is available, record exact panel version/build, OS, webserver, PHP module and plugin import UI, capture a new site and PHP-FPM drift, verify auth and session boundaries, then exercise lifecycle operations **without reusing production data**.

## Local source verification (safe to run without aaPanel)

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py' -v
sh -n plugin/ach_customizer/install.sh
python3 -B scripts/build_plugin.py --output /tmp/ach-customizer-dev.zip
```

This ZIP is a **development artifact only**. It must not be marked compatible, released, or deployed until actual panel and lifecycle acceptance is documented.

## Architectural guardrails

- No core patching, public admin listener, background daemon or scheduler in the first slice.
- Never assume a site ID belongs to one PHP-FPM pool or that site-specific policies may write shared pool settings.
- Dynamic routing cannot be used as a privileged shortcut; server-side operator authorization at execution time is mandatory.
- Persistent future policy/recovery state must be outside the replaceable plugin directory; uninstall/purge semantics must preserve non-owned state.
- A source-defined `server` include is not proof that arbitrary Nginx `location` changes can be overridden there.
- Monitor must never perform host changes. Runtime validation, per-policy approval, preflight, locks, recovery and uncertain-effect reconciliation are prerequisites for any Apply mode.
