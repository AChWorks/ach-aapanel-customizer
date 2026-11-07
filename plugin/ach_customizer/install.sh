#!/bin/sh
set -eu
# aaPanel owns removable plugin source. Uninstall does not revert earlier
# manually applied host configuration. Persistent recovery records are retained.

cleanup=/www/server/panel/plugin/ach_customizer/ach_customizer_cleanup.py
lifecycle=/www/server/panel/plugin/ach_customizer/ach_customizer_lifecycle.py
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
        echo 'ACh aaPanel Customizer: persistent operator state and recovery records are preserved'
        echo 'ACh aaPanel Customizer: reinstall the plugin or follow documented supervised recovery to restore earlier PHP-FPM settings'
        ;;
    *)
        echo 'Usage: install.sh install|uninstall' >&2
        exit 2
        ;;
esac
