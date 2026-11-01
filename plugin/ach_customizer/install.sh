#!/bin/sh
set -eu
# aaPanel imports the plugin files. This candidate owns no services, jobs, or
# generated host configurations; durable operator data is never purged here.
case "${1:-}" in
  install) echo "ACh aaPanel Customizer source registered (monitor-only)" ;;
  uninstall) echo "ACh aaPanel Customizer has no jobs or host changes to undo; panel owns plugin code removal" ;;
  *) echo "Usage: install.sh install|uninstall" >&2; exit 2 ;;
esac
