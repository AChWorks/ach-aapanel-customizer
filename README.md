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

A provisional native plugin source lives at `plugin/ach_customizer/`. Run `python3 -B -m unittest discover -s tests -p "test_*.py" -v` for source-only tests and `python3 -B scripts/build_plugin.py` to construct a **local development ZIP**. The native backend import, in-panel read-only UI, session/CSRF, uninstall and reinstall have been tested on an **isolated Debian 12 + aaPanel 8.0.7 lab** (see [integration evidence](docs/aapanel-integration.md)). The UI file-picker upload path, state-preserving updates, real managed websites, other panel versions, and any Apply/rollback operations remain unverified. This is not an authorized production installation path or supported public release. **Do not deploy this repository to production as a plugin.**

The first prototype uses Python for aaPanel compatibility and an English-only UI consistent with aaPanel’s standard plugin patterns. Specific adapter contracts, support matrix and host-writing operations are still evidence-gated.

## Security and scope

This repository must never contain host passwords, tokens, session material, production configuration snapshots, or restricted logs. Creating this source repository does **not** authorize changes on production aaPanel hosts.

AChWorks owns the project; relevant cross-project engineering principles and lifecycle contracts are maintained in [Koinon](https://github.com/AChWorks/koinon).
