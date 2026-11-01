#!/bin/sh
set -eu
# aaPanel owns the removable plugin source. This candidate creates no jobs,
# services or host configuration. Persistent operator data is never purged.

cleanup=/www/server/panel/plugin/ach_customizer/ach_customizer_cleanup.py
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

case "${1:-}" in
    install)
        echo 'ACh aaPanel Customizer source registered (monitor-only)'
        ;;
    uninstall)
        # The cleanup helper performs descriptor-anchored, no-symlink and
        # ownership validation before removing only our copied icon.
        # If the executable or helper is unavailable, fail safely.
        if [ -x "$panel_python" ] && trusted_helper_path; then
            "$panel_python" "$cleanup" || echo 'ACh aaPanel Customizer: icon copy preserved (helper failed)'
        else
            echo 'ACh aaPanel Customizer: icon copy preserved (cleanup unavailable)'
        fi
        echo 'ACh aaPanel Customizer: no services, jobs or host configurations to revert'
        ;;
    *)
        echo 'Usage: install.sh install|uninstall' >&2
        exit 2
        ;;
esac
