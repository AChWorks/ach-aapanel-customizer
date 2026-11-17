"""Selected-site onboarding and regeneration review; no implicit host writes.

Compose the existing native site baseline, generated VHost, Cache recovery and
shared PHP policy readers. Their independent Apply/Restore preflights remain
authoritative: this report is a point-in-time guide, never an approval token.
"""
from __future__ import annotations

from ach_customizer_site_changes import compare, read_baseline
from ach_customizer_vhost_drift import inspect_vhost_drift
from ach_customizer_cache_audit import inspect_site_fastcgi_cache
from ach_customizer_cache_manage import CacheManageError, manage_cache
from ach_customizer_fpm_policy import get_policy, observe
from ach_customizer_monitor import inspect_php_fpm_site_impact
from ach_customizer_state import read_state


class ReconciliationError(ValueError):
    """A current, trustworthy combined report cannot be established."""


def _shared_php(panel_public, version, monitor, directory, config_root):
    result = {
        "version": version, "scope": "shared_service",
        "state": "Not Inspected", "policy_revision": None,
        "desired": None, "changes": [], "shared_impact": None,
        "runtime_verified": False, "read_only": True, "reason": "",
    }
    if version is None:
        result["state"] = "Not Applicable"
        return result
    if not monitor["enabled"] or not monitor["modules"]["php_fpm_file_preview"]:
        result["state"] = "Monitor Disabled"
        result["reason"] = "PHP-FPM Monitor is disabled; no policy inference was made."
        return result
    try:
        policy = get_policy(version, directory=directory)
        result["policy_revision"] = policy["policy_revision"]
        result["desired"] = policy["desired"]
        if not policy["saved"]:
            result["state"] = "No Policy"
            return result
        observation, token = observe(config_root, version, policy["desired"])
        if get_policy(version, directory=directory) != policy:
            raise ReconciliationError("Saved shared PHP policy changed during the read")
        if observation["state"] not in ("File Match", "File Drift") or not token:
            result["state"] = "Needs Review"
            result["reason"] = observation.get("reason") or "PHP file evidence is incomplete."
            return result
        result["state"] = observation["state"]
        result["changes"] = observation["changes"]
        result["source_observation_sha256"] = token
        try:
            result["shared_impact"] = inspect_php_fpm_site_impact(
                panel_public, version, observation["source"])
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            result["shared_impact"] = {
                "state": "Needs Review", "reason": str(exc)[:250],
                "matched_sites": [], "unresolved_sites": [],
            }
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        result["state"] = "Needs Review"
        result["reason"] = str(exc)[:250]
    return result


def inspect_selected_site(panel_public, site, *, current_site, directory,
                          php_root="/www/server/php"):
    """Read a selected, previously validated native site without applying policy.

    The caller owns POST/full-admin authorization and native snapshot selection.
    A repeated selected-site read, native baseline revision and VHost identity
    check reject stale combined evidence; later manual writes still revalidate.
    """
    before_monitor = read_state(directory)
    if not before_monitor["enabled"] or not before_monitor["modules"]["site_inventory"]:
        raise ReconciliationError("Website Monitor disabled; enable and compare again")
    baseline_before = read_baseline(directory)
    comparison = compare(panel_public, directory=directory)
    if (comparison["baseline_revision"] != baseline_before["revision"] or
            comparison["baseline_sha256"] != baseline_before["source_sha256"] or
            comparison["monitor_revision"] != before_monitor["revision"]):
        raise ReconciliationError("Site baseline or Monitor changed during comparison")

    change = next((item for item in comparison["changes"]
                   if item["id"] == site["id"]), None)
    if baseline_before["revision"] == 0:
        baseline_state = "Baseline Missing"
    else:
        baseline_state = change["kind"] if change else "Unchanged"
    baseline = {
        "state": baseline_state, "revision": comparison["baseline_revision"],
        "source_sha256": comparison["source_sha256"],
        "fields": change["fields"] if change else [],
        "before": change["before"] if change else None,
        "after": change["after"] if change else None,
    }

    vhost = inspect_vhost_drift(panel_public, site)
    cache_source = inspect_site_fastcgi_cache(
        panel_public, site["id"], site["name"])
    source_php = (cache_source.get("php_version")
                  if cache_source.get("state") == "Source Observed" else None)
    php = _shared_php(panel_public, source_php, before_monitor, directory, php_root)
    if cache_source.get("state") != "Source Observed":
        php["state"] = "Not Inspected"
        php["reason"] = "Native PHP assignment is not verified by the source audit."

    try:
        recovered = manage_cache("recheck", site, panel_public, data_dir=directory)
        cache_recovery = {
            "state": recovered["state"],
            "recovery_id": recovered.get("recovery_id"),
            "journal_phase": recovered.get("journal_phase"),
            "runtime_verified": recovered.get("runtime_verified") is True,
            "note": recovered.get("note", ""),
        }
    except (CacheManageError, OSError, ValueError, RuntimeError) as exc:
        cache_recovery = {
            "state": "Needs Review", "recovery_id": None,
            "journal_phase": None, "runtime_verified": False,
            "note": "Cache recovery inspection failed: " + str(exc)[:250],
        }

    # Current site and saved intent must not have changed between independent
    # readers. Rechecking the generated source also detects a late aaPanel
    # VHost regeneration. This result is still not a host-write preflight.
    if current_site() != site or read_state(directory) != before_monitor:
        raise ReconciliationError("Native selected site or Monitor changed during review")
    if read_baseline(directory) != baseline_before:
        raise ReconciliationError("Saved site baseline changed during review")
    if php["policy_revision"] is not None:
        saved_php = get_policy(source_php, directory=directory)
        if (saved_php["policy_revision"] != php["policy_revision"] or
                saved_php["desired"] != php["desired"]):
            raise ReconciliationError("Saved shared PHP policy changed during review")
    if inspect_vhost_drift(panel_public, site) != vhost:
        raise ReconciliationError("Generated VHost changed during review; inspect again")

    cache_findings = cache_source.get("findings") or []
    needs_review = (
        vhost["state"] != "File Match" or
        cache_source.get("state") != "Source Observed" or
        bool(cache_findings) or
        cache_recovery["state"] in ("Needs Review", "Recovery Required") or
        php["state"] in ("File Drift", "Needs Review") or
        (isinstance(php["shared_impact"], dict) and
         php["shared_impact"].get("state") == "Needs Review")
    )
    state = ("Needs Review" if needs_review else
             "Changes Observed" if baseline_state in
             ("Baseline Missing", "Added", "Changed") else "Observed")
    return {
        "schema": 1, "site_id": site["id"], "site_key": site["name"],
        "state": state, "read_only": True,
        "runtime_verified": False, "auto_reconcile": False,
        "apply_supported": False, "restore_supported": False,
        "monitor_revision": before_monitor["revision"],
        "baseline": baseline,
        "vhost": vhost,
        "cache_source": {
            "state": cache_source.get("state", "Needs Review"),
            "source_sha256": cache_source.get("source_sha256"),
            "php_version": source_php,
            "zone_state": cache_source.get("zone_state"),
            "findings": cache_findings,
            "other_sites_same_zone": cache_source.get("other_sites_same_zone", []),
            "other_sites_same_directory": cache_source.get("other_sites_same_directory", []),
            "reason": cache_source.get("reason") or "",
        },
        "php_policy": php,
        "cache_recovery": cache_recovery,
        "status_recovery_state": "Not Inspected",
        "note": (
            "This point-in-time report combines independent readers, not a "
            "transaction or an Apply/Restore token. Baseline covers native "
            "database records, VHost compares generated files, PHP policy "
            "compares saved intent with source/defaults, and Cache recovery "
            "uses its own guarded Recheck. It does not prove loaded Nginx/PHP "
            "workers, DNS, HTTPS, WordPress privacy or peer traffic. Use the "
            "separate module's fresh Preview/Recheck and explicit manual "
            "approval before any Apply/Restore; inspect Status Pages recovery "
            "for each selected template separately."
        ),
    }
