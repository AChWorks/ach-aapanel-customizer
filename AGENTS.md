# ACh aaPanel Customizer — Development Guidance

Read [the canonical product specification](docs/PROJECT-SPEC.md) before changing product behavior. The Owner-wide operating principle **simplicity and informed choice** applies to every module, old and new.

- Build the smallest maintainable solution that completes a real administrator task; avoid speculative scenarios, duplicate persistence layers, repetitive approval checkboxes, and hardcoded feature restrictions that do not follow from actual system capabilities.
- Do not impose arbitrary version, provider, platform, path, domain, site-count, payload-size or timeout allowlists. Discover the installed environment, paginate native collections, and expose genuinely variable settings rather than encoding a convenient QA value as a product limitation.
- Distinguish necessary protocol, resource and data-integrity bounds from artificial restrictions. Correct authorization, intended target ownership, and prevention of destructive changes to unrelated data are not optional.
- For acceptable residual uncertainty, show a short **nonmandatory** pre-action note explaining impact and useful checks. An authorized administrator's explicit action is consent: perform the supported operation without requiring all suggestions to be completed or adding a second checkbox.
- Keep errors, results, recovery information and the actual supported scope truthful. A warning cannot make an incorrect or loss-causing write safe; do not pretend an unfamiliar writer is supported when its target format is unknown.
- When touching an older flow, reconcile it with the latest Owner decision, simplify documented obsolete gates, add focused regression tests, and keep the nearest relevant README/technical guide and owning Issue consistent. Historical source-bound evidence remains historical, not an absolute future-version ban.
- Preserve repository approval gates: stable candidate, relevant automated validation, independent review where required, and separate explicit Owner authorization for Merge, public Release and Production deployment.
