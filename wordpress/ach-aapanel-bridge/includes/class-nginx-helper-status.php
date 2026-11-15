<?php
/**
 * Read-only, WordPress-owned Nginx Helper runtime observations.
 *
 * Deliberately never trusts a plugin header, mode, or path as proof that an
 * aaPanel Customizer cache generation is active or that Purge All is safe.
 */
namespace AChWorks\AaPanelBridge;

defined('ABSPATH') || exit;

final class NginxHelperStatus
{
    /**
     * No WordPress settings, network requests, cache reads, or file writes.
     *
     * @return array<string, mixed>
     */
    public static function inspect(): array
    {
        $installed = defined('WP_PLUGIN_DIR')
            && is_file(WP_PLUGIN_DIR . '/nginx-helper/nginx-helper.php');
        $active = 'unknown';

        if (!$installed) {
            $active = 'not_installed';
        } elseif (function_exists('is_plugin_active')
            && function_exists('is_plugin_active_for_network')) {
            $active = (
                \is_plugin_active('nginx-helper/nginx-helper.php')
                || \is_plugin_active_for_network('nginx-helper/nginx-helper.php')
            ) ? 'active' : 'inactive';
        } elseif (function_exists('is_plugin_active')) {
            $active = \is_plugin_active('nginx-helper/nginx-helper.php')
                ? 'active' : 'unknown';
        }

        $mode = null;
        $autoPurge = null;
        $runtime = $GLOBALS['nginx_helper_admin'] ?? null;
        if (is_object($runtime)) {
            $public = get_object_vars($runtime);
            $options = $public['options'] ?? null;
            if (is_array($options)) {
                $value = $options['purge_method'] ?? null;
                if (is_string($value) && $value !== '') {
                    $mode = $value;
                }
                if (isset($options['enable_purge'])) {
                    $autoPurge = (bool) $options['enable_purge'];
                }
            }
        }

        $cachePath = null;
        if (defined('RT_WP_NGINX_HELPER_CACHE_PATH')) {
            $value = constant('RT_WP_NGINX_HELPER_CACHE_PATH');
            if (is_string($value) && $value !== '') {
                $cachePath = $value;
            }
        }

        return [
            'installed' => $installed,
            'activation' => $active,
            'purge_method' => $mode,
            'automatic_purge_enabled' => $autoPurge,
            'effective_cache_path' => $cachePath,
            'customizer_invalidation_connected' => false,
            'safe_purge_all_verified' => false,
        ];
    }
}
