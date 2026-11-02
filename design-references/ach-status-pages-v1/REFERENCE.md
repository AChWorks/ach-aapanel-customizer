# ACh Status Pages v1.0 — design reference

**Reference only:** the templates below are not integrated into the native aaPanel Customizer, not reviewed for production use, and not a deployment instruction.

- Tracking Issue: https://github.com/AChWorks/ach-aapanel-customizer/issues/10
- 22 approved HTML files: `en/` and `fa/` (11 variants each). Git blob contents were compared to the original v1.0 ZIP source during transfer.
- Reference documentation: `README.md`, `README-FA.md`, `preview.html`.
- Original complete source archive: `ACh-Status-Pages-v1.0.zip`
- Original ZIP SHA-256: `a15d895607e7870588bd3da5f836e517a350209899e38c13c11e72dcbafdf5fc`
- The original ZIP also contains `source/build_pages.py`, `source/fa-copy.json`, `source/verify_pages.py`, `examples/site-error-alias.conf`, screenshots, and `MANIFEST.sha256`. Those extra files are **not mirrored in this reference branch**. An operator can attach the entire original ZIP to the Issue using GitHub's file attachment UI, verifying the SHA-256 first.

Do not treat these HTML references as already applied, and do not merge this design-only branch into `main` without a coherent implementation PR, independent review and the project's integration gates. When the actual feature is implemented, integrate/version the templates as plugin-owned package data and later remove the superseded reference branch only after source continuity is secured.
