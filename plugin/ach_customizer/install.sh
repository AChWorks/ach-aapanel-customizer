#!/bin/sh
set -eu
# aaPanel owns removable plugin source. Uninstall does not revert earlier
# manually applied host configuration. Persistent recovery records are retained.

cleanup=/www/server/panel/plugin/ach_customizer/ach_customizer_cleanup.py
lifecycle=/www/server/panel/plugin/ach_customizer/ach_customizer_lifecycle.py
wp_watcher=/www/server/panel/plugin/ach_customizer/ach_customizer_wp_watcher.py
fpm_watcher=/www/server/panel/plugin/ach_customizer/ach_customizer_fpm_watcher.py
panel_python=/www/server/panel/pyenv/bin/python3

trusted_helper_path() {
    # Do not execute a helper through a redirected plugin source directory.
    # The Python helper then validates owner, mode and descriptor identity for
    # *both* complete paths before it considers removing the copied icon.
    for directory in /www /www/server /www/server/panel \
        /www/server/panel/plugin /www/server/panel/plugin/ach_customizer
    do
        [ -d "$directory" ] && [ ! -L "$directory" ] || return 1
    done
    [ -f "$cleanup" ] && [ ! -L "$cleanup" ]
}

trusted_lifecycle_path() {
    # Fixed native plugin code path; reject redirected plugin directories.
    for directory in /www /www/server /www/server/panel \
        /www/server/panel/plugin /www/server/panel/plugin/ach_customizer
    do
        [ -d "$directory" ] && [ ! -L "$directory" ] || return 1
    done
    [ -f "$lifecycle" ] && [ ! -L "$lifecycle" ]
}

log_lifecycle() {
    # Audit failure never changes install/uninstall outcomes.
    if [ -x "$panel_python" ] && trusted_lifecycle_path; then
        "$panel_python" "$lifecycle" "$1" ||
            echo 'ACh aaPanel Customizer: lifecycle Activity persistence unconfirmed'
    else
        echo 'ACh aaPanel Customizer: lifecycle Activity unavailable; persistence unconfirmed'
    fi
}

case "${1:-}" in
    install)
        echo 'ACh aaPanel Customizer source registered (Monitor default; Manual Apply requires approval)'
        log_lifecycle install_registered
        ;;
    uninstall)
        # Disable opted-in FPM auto repair before aaPanel removes its worker
        # source; preserve existing FPM settings and all recovery journals.
        if [ -f /etc/systemd/system/ach-customizer-fpm-auto.path ] || \
           [ -f /www/server/panel/data/ach_customizer.fpm-auto.json ]; then
            if [ -x "$panel_python" ] && trusted_lifecycle_path && \
               [ -f "$fpm_watcher" ] && [ ! -L "$fpm_watcher" ]; then
                if ! "$panel_python" "$fpm_watcher" uninstall; then
                    echo 'ACh PHP-FPM auto watcher removal blocked: an in-flight safe-stop or ownership review remains' >&2
                    exit 1
                fi
            else
                echo 'ACh PHP-FPM auto watcher helper unavailable; refusing unattended removal of an enabled worker' >&2
                exit 1
            fi
        fi
        # Explicit opt-in watcher is not registered by ordinary installation.
        # On uninstall, disable any previously opted-in watcher before native
        # aaPanel removes plugin files. Preserve unreadable policy evidence.
        if [ -f /etc/systemd/system/ach-customizer-wp-terminal.path ] || \
           [ -f /www/server/panel/data/ach_customizer.wp-terminal.json ]; then
            if [ -x "$panel_python" ] && trusted_lifecycle_path && \
               [ -f "$wp_watcher" ] && [ ! -L "$wp_watcher" ]; then
                "$panel_python" "$wp_watcher" uninstall ||
                    echo 'ACh WP terminal watcher disable/uninstall unconfirmed; inspect systemd units'
            else
                echo 'ACh WP terminal watcher helper unavailable; inspect systemd units'
            fi
        fi
        # The cleanup helper performs descriptor-anchored, no-symlink and
        # ownership validation before removing only our copied icon.
        # If the executable or helper is unavailable, fail safely.
        if [ -x "$panel_python" ] && trusted_helper_path; then
            if "$panel_python" "$cleanup"; then
                lifecycle_event=uninstall_icon_removed
            else
                lifecycle_event=uninstall_icon_preserved
                echo 'ACh aaPanel Customizer: icon copy preserved (helper failed)'
            fi
        else
            lifecycle_event=uninstall_cleanup_unavailable
            echo 'ACh aaPanel Customizer: icon copy preserved (cleanup unavailable)'
        fi
        log_lifecycle "$lifecycle_event"
        echo 'ACh aaPanel Customizer: aaPanel removes plugin files; only verified plugin-owned icon cleanup was attempted'
        echo 'ACh aaPanel Customizer: existing PHP-FPM settings may include previously applied changes; uninstall does not revert them'
        echo 'ACh aaPanel Customizer: applied website Status Pages extensions, Nginx assets and recovery journals are preserved; Restore explicitly before uninstall if needed'
        echo 'ACh aaPanel Customizer: any previously applied global HTTP/80 unbound default-server and recovery journal are preserved; Restore explicitly before uninstall if needed'
        echo 'ACh aaPanel Customizer: any manually Applied unknown-SNI HTTPS/443 policy and saved recovery are preserved; Restore explicitly before uninstall if needed'
        echo 'ACh aaPanel Customizer: any manually Applied WordPress Debug and system WP-Cron setting/cron task are preserved to keep site scheduling; Restore explicitly before uninstall if needed'
        echo 'ACh aaPanel Customizer: persistent operator state and recovery records are preserved'
        echo 'ACh aaPanel Customizer: reinstall the plugin or follow documented supervised recovery to restore earlier PHP-FPM settings'
        ;;
    *)
        echo 'Usage: install.sh install|uninstall' >&2
        exit 2
        ;;
esac
