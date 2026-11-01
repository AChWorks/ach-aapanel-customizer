# ACh aaPanel Customizer

A native, modular **aaPanel customization plugin** for keeping operator-approved changes to aaPanel, its modules/plugins, websites, and managed services visible, durable, and recoverable.

**Status: Project specification and feasibility planning.** No working plugin package, installer, or production deployment is available yet.

## Why

aaPanel and its plugins can regenerate configuration when sites are created, modules are changed, or the panel is upgraded. This project aims to manage those intentional customizations *inside aaPanel* instead of relying on repeated manual edits or a second management interface.

The intended experience includes normal aaPanel plugin install/update/uninstall; a built-in management screen; plugin/module enable/disable; site and service discovery; monitored configuration drift; previewed, authorized changes; verification and reliable recovery.

It is **not WordPress-only** and does not imply every aaPanel subsystem will be supported immediately.

## Project map

- [Canonical product specification](docs/PROJECT-SPEC.md) — mission, accepted requirements, scope, constraints, lifecycle and first acceptance criteria.
- [AChWorks descriptor](achworks.yaml) — concise project discovery metadata.
- GitHub [Issues](https://github.com/AChWorks/ach-aapanel-customizer/issues) — active research and implementation work after issue creation.
- GitHub [PRs](https://github.com/AChWorks/ach-aapanel-customizer/pulls) — proposed code/documentation changes and review evidence.

## Development and installation

There is no supported install command or artifact yet. The first task is to validate actual aaPanel third-party plugin interfaces, lifecycle behavior, compatibility boundaries and a reversible customization flow on a **non-production** installation. Do not deploy this repository to production as a plugin.

Current specification intentionally leaves the implementation language and detailed configuration adapter contracts open until tested against aaPanel behavior.

## Security and scope

This repository must never contain host passwords, tokens, session material, production configuration snapshots, or restricted logs. Creating this source repository does **not** authorize changes on production aaPanel hosts.

AChWorks owns the project; relevant cross-project engineering principles and lifecycle contracts are maintained in [Koinon](https://github.com/AChWorks/koinon).
