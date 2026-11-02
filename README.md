# ACh aaPanel Customizer

A native, modular **aaPanel customization plugin** for keeping operator-approved changes to aaPanel, its modules/plugins, websites, and managed services visible, durable, and recoverable.

**Status: Native monitor-only development candidate under validation.** Source and a local ZIP builder exist, but no supported installable release or production deployment is available.

## Why

aaPanel and its plugins can regenerate configuration when sites are created, modules are changed, or the panel is upgraded. This project aims to manage those intentional customizations *inside aaPanel* instead of relying on repeated manual edits or a second management interface.

The intended experience includes normal aaPanel plugin install/update/uninstall; a built-in management screen; plugin/module enable/disable; site and service discovery; monitored configuration drift; previewed, authorized changes; verification and reliable recovery.

It is **not WordPress-only** and does not imply every aaPanel subsystem will be supported immediately.

## Project map

- [Canonical product specification](docs/PROJECT-SPEC.md) — mission, accepted requirements, scope, constraints, lifecycle and first acceptance criteria.
- [Native aaPanel integration and test gates](docs/aapanel-integration.md) — official source references, safety boundaries, and open runtime compatibility checks.
- [AChWorks descriptor](achworks.yaml) — concise project discovery metadata.
- GitHub [Issues](https://github.com/AChWorks/ach-aapanel-customizer/issues) — active research and implementation work after issue creation.
- GitHub [PRs](https://github.com/AChWorks/ach-aapanel-customizer/pulls) — proposed code/documentation changes and review evidence.

## Development and installation

A provisional native plugin source lives at `plugin/ach_customizer/`. Run `python3 -B -m unittest discover -s tests -p "test_*.py" -v` for source-only tests and `python3 -B scripts/build_plugin.py` to construct a **local development ZIP**. On an **isolated Debian 12 + aaPanel 8.0.7 lab**, the exact merged 0.1.0 ZIP passed real browser file-picker upload, installation, Settings, website inventory, Uninstall and Reinstall. The unmerged 0.1.1 candidate also passed browser update and reinstall with preserved Monitor flags. Its later optimistic-revision correction was independently re-executed through a real authenticated guest session: a stale action was rejected without changing the latest state. See the [source-bound browser evidence](docs/evidence/aaPanel-8.0.7-2026-11-02-native-browser-lifecycle-state.json) and [integration details](docs/aapanel-integration.md). A real static website was subsequently created, served via Nginx 1.28.3 and discovered dynamically in the isolated aaPanel 8.0.7 guest; site deletion and VHost regeneration/extension interactions were also examined. See the [runtime integration evidence](docs/aapanel-integration.md#actual-native-website-and-nginx-lifecycle-isolated-guest-2026-11-02). A real native shared PHP-FPM 8.5 pool and two-site HTTP mapping were then tested in the same isolated guest, exposing and correcting the omitted `pm.max_requests=0` default in the read-only monitor (see the [PHP-FPM integration evidence](docs/aapanel-integration.md#actual-php-85-native-pool-verification-and-bounded-monitor-correction-isolated-guest-2026-11-02)). Restricted-role browser authorization, real PHP-FPM reset/recovery, canonical website/VHost rename, Nginx extension durability, policy migrations, other panel versions and Apply operations remain unverified. This is not an authorized production installation path or supported public release. **Do not deploy this repository to production as a plugin.**

Native `AddDomain`/`DelDomain` tests on aaPanel 8.0.7 established that bound domains can change while the site key and VHost filename remain stable; the development website inventory now shows recorded bound domains separately from the site key. The latest read-only PHP-FPM parser was also rechecked against a real guest pool by exact source SHA. See the [bounded native domain lifecycle evidence](docs/aapanel-integration.md#native-domain-binding-lifecycle-and-exact-current-helper-runtime-test-isolated-guest-2026-11-02). No production installation or Apply is implied.

The candidate uses Python for aaPanel compatibility and an English-only UI consistent with native aaPanel plugin patterns. Monitor-only overall/module switches persist in the owner-checked data directory outside the replaceable plugin. An administrator-only POST must supply the last-seen state revision; conflicting stale actions fail visibly rather than silently replacing new preferences. Disable does not stop websites or services, grant Apply permissions, or enable background enforcement. Specific adapter contracts, support matrix and host-writing operations are still evidence-gated.

## Security and scope

This repository must never contain host passwords, tokens, session material, production configuration snapshots, or restricted logs. Creating this source repository does **not** authorize changes on production aaPanel hosts.

AChWorks owns the project; relevant cross-project engineering principles and lifecycle contracts are maintained in [Koinon](https://github.com/AChWorks/koinon).
