#!/bin/sh
set -eu
# aaPanel owns distribution/removal of this plugin's code. This candidate
# creates no jobs, services, or host configuration. Persistent operator data
# (if added in a later version) is never purged by ordinary uninstall.

plugin_icon=/www/server/panel/plugin/ach_customizer/icon.png
copied_icon=/www/server/panel/BTPanel/static/img/soft_ico/ico-ach_customizer.png

cleanup_owned_icon() {
    # aaPanel copies the icon outside the replaceable plugin directory, but
    # its native uninstall may leave that copy behind. Remove only the exact
    # product-named, regular, byte-identical copy; preserve other ownership.
    if [ -f "$plugin_icon" ] && [ ! -L "$plugin_icon" ] && \
       [ -f "$copied_icon" ] && [ ! -L "$copied_icon" ] && \
       cmp -s "$plugin_icon" "$copied_icon"; then
        rm -f -- "$copied_icon"
        echo 'ACh aaPanel Customizer: removed verified product-owned icon copy'
    else
        echo 'ACh aaPanel Customizer: unknown or absent icon copy preserved'
    fi
}

case "${1:-}" in
    install)
        echo 'ACh aaPanel Customizer source registered (monitor-only)'
        ;;
    uninstall)
        cleanup_owned_icon
        echo 'ACh aaPanel Customizer: no services, jobs or host configurations to revert'
        ;;
    *)
        echo 'Usage: install.sh install|uninstall' >&2
        exit 2
        ;;
esac
