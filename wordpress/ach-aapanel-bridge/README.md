# ACh aaPanel Bridge — repository guide

The optional WordPress companion to [ACh aaPanel Customizer](../../README.md)
is maintained in this repository and distributed as an **independent ZIP**.
It is neither bundled with, nor required by, the native aaPanel plugin.

This document is for **contributors and code reviewers** and is **not
bundled in the WordPress ZIP**. Use the authoritative sources for each
different question:

| Question | Source of truth |
| --- | --- |
| What WordPress users install, how they connect it, FAQs, changes | [WordPress-standard `readme.txt`](readme.txt), **included in the ZIP** |
| Native Cache provisioning, ownership, recovery and operator prerequisites | [Native integration guide](../../docs/aapanel-integration.md#optional-wordpress-bridge-operator-prerequisites) |
| Lasting product scope and safety constraints | [Project specification](../../docs/PROJECT-SPEC.md) |
| Published ZIP version and checksum | [GitHub Releases](https://github.com/AChWorks/ach-aapanel-customizer/releases) |
| Reviewable changes, open gaps and installed acceptance | [PRs](https://github.com/AChWorks/ach-aapanel-customizer/pulls), [Issue #2](https://github.com/AChWorks/ach-aapanel-customizer/issues/2), [QA Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21) |

## Source layout and invariants

| Source | Responsibility |
| --- | --- |
| [`ach-aapanel-bridge.php`](ach-aapanel-bridge.php) | Native WordPress plugin header, independent version/slug/Update URI, code entrypoint |
| [`includes/class-plugin.php`](includes/class-plugin.php) | WordPress Tools diagnostics, `manage_options` authorization and escaped status presentation |
| [`includes/class-nginx-helper-status.php`](includes/class-nginx-helper-status.php) | Observe (never configure) Nginx Helper presence/mode/path |
| [`includes/class-cache-invalidation.php`](includes/class-cache-invalidation.php) | Current-generation manifest checks, narrow GET/HEAD per-URL hooks and balanced post/taxonomy mutation handling |
| [`readme.txt`](readme.txt) | Standard WordPress-facing package readme; `Stable tag` must equal PHP header version |
| [`scripts/build_wordpress_bridge.py`](../../scripts/build_wordpress_bridge.py) | Deterministic separate WordPress ZIP; ships `readme.txt` but not this Markdown file |
| [`tests/test_wordpress_bridge.py`](../../tests/test_wordpress_bridge.py) | PHP behavior stubs, access/control negatives, readme/version guards and exact ZIP contract |

The entrypoint is **disconnected by default**: without a separately
approved, current, site-owned native Cache manifest it does not attach
vendor Cache hooks. A valid manifest alone does not prove effective Nginx
workers, private-session isolation or safe site-wide purge. The source
checks both actual GET/HEAD objects and vendor per-URL selection; it does
not directly unlink arbitrary files, modify Nginx Helper code, install
dependencies or make vendor `purge_all()` site-scoped. In particular, its
term mutation hooks balance old/new state across nested changes and
partially committed WordPress errors, without inventing a persistent URL
registry. Consult the code/tests for precise callback contracts.

## Local build and verification

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_wordpress_bridge.py' -v
python3 -B scripts/build_wordpress_bridge.py --output /tmp/ach-aapanel-bridge.zip
```

The archive must contain one `ach-aapanel-bridge/` directory, the main
PHP file, three PHP helpers and **`readme.txt`**; it must not ship
`README.md`, build fixtures, cache artifacts or an updater. The builder
refuses a missing/redirected readme, mismatched `Stable tag` and any
output path that would overwrite a source package member. Package members
are read once before validation and archival, keeping the checked
metadata identical to the shipped bytes.
Check the independent header version and its release artifact checksum
when reviewing an update. The external `Update URI` avoids accidental
WordPress.org slug replacement; it does not implement automatic updates.

The [repository CI](../../.github/workflows/ci.yml) additionally runs
source-wide tests, PHP lint and the package build. Real WordPress,
Nginx Helper, PHP-FPM and native host acceptance belongs to
[QA Issue #21](https://github.com/AChWorks/ach-aapanel-customizer/issues/21)
and must not be claimed from isolated PHP stubs or a ZIP hash alone.
An internal development ZIP is not a published release or Production
installation. WordPress.org Plugin Directory listing and software
licensing remain separate decisions, not implied by this readme format.
