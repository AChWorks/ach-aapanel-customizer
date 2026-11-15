<?php
/**
 * WordPress administrator view for the optional ACh aaPanel Bridge.
 *
 * Version 0.1.0 does not mutate cache, Nginx, WordPress options, or cron.
 * A later native-to-WordPress integration must be independently approved and
 * verified before any invalidation hook can become effective.
 */
namespace AChWorks\AaPanelBridge;

defined('ABSPATH') || exit;

final class Plugin
{
    public static function boot(): void
    {
        \add_action('admin_menu', [__CLASS__, 'registerAdminPage']);
    }

    public static function registerAdminPage(): void
    {
        \add_management_page(
            __('ACh aaPanel Bridge', 'ach-aapanel-bridge'),
            __('ACh aaPanel Bridge', 'ach-aapanel-bridge'),
            'manage_options',
            'ach-aapanel-bridge',
            [__CLASS__, 'renderAdminPage']
        );
    }

    public static function renderAdminPage(): void
    {
        if (!\current_user_can('manage_options')) {
            \wp_die(
                \esc_html__('You are not allowed to view this page.', 'ach-aapanel-bridge'),
                '',
                ['response' => 403]
            );
            return;
        }

        $status = NginxHelperStatus::inspect();
        $activation = [
            'active' => __('Active', 'ach-aapanel-bridge'),
            'inactive' => __('Installed but inactive', 'ach-aapanel-bridge'),
            'not_installed' => __('Not installed', 'ach-aapanel-bridge'),
            'unknown' => __('Not verified', 'ach-aapanel-bridge'),
        ];
        $value = static function ($item): string {
            return is_string($item) && $item !== '' ? $item :
                __('Not available', 'ach-aapanel-bridge');
        };

        echo '<div class="wrap">';
        echo '<h1>' . \esc_html__('ACh aaPanel Bridge', 'ach-aapanel-bridge') . '</h1>';
        echo '<p>' . \esc_html__(
            'Optional WordPress companion for ACh aaPanel Customizer.',
            'ach-aapanel-bridge'
        ) . '</p>';
        echo '<h2>' . \esc_html__('Connection', 'ach-aapanel-bridge') . '</h2>';
        echo '<p>' . \esc_html__(
            'Not connected. This version provides diagnostics only; it does not enable automatic invalidation, Purge All, or remote management.',
            'ach-aapanel-bridge'
        ) . '</p>';
        echo '<h2>' . \esc_html__('Nginx Helper observations', 'ach-aapanel-bridge') . '</h2>';
        echo '<table class="widefat striped" style="max-width:900px"><tbody>';
        self::tableRow(
            __('Plugin status', 'ach-aapanel-bridge'),
            $activation[$status['activation']]
        );
        self::tableRow(
            __('Purge method', 'ach-aapanel-bridge'),
            $value($status['purge_method'])
        );
        $automatic = $status['automatic_purge_enabled'] === null
            ? __('Not available', 'ach-aapanel-bridge')
            : ($status['automatic_purge_enabled']
                ? __('Enabled', 'ach-aapanel-bridge')
                : __('Disabled', 'ach-aapanel-bridge'));
        self::tableRow(__('Automatic purge setting', 'ach-aapanel-bridge'), $automatic);
        self::tableRow(
            __('Configured cache path', 'ach-aapanel-bridge'),
            $value($status['effective_cache_path'])
        );
        echo '</tbody></table>';
        if ($status['purge_method'] === 'get_request') {
            echo '<p>' . \esc_html__(
                'The Nginx Helper get_request route is not verified against any Customizer-owned cache zone or generation.',
                'ach-aapanel-bridge'
            ) . '</p>';
        } elseif ($status['purge_method'] === 'unlink_files') {
            echo '<p>' . \esc_html__(
                'Nginx Helper unlink_files requires generation-aware site ownership checks before it can invalidate Customizer-managed entries.',
                'ach-aapanel-bridge'
            ) . '</p>';
        }
        echo '<p><strong>' . \esc_html__('Important:', 'ach-aapanel-bridge') . '</strong> ';
        echo \esc_html__(
            'These are WordPress-side observations, not proof of the effective Nginx cache configuration or site ownership. Nginx Helper Purge All can affect shared cache directories. Do not enable it based on this page.',
            'ach-aapanel-bridge'
        ) . '</p>';
        echo '</div>';
    }

    private static function tableRow(string $label, string $value): void
    {
        echo '<tr><th scope="row">' . \esc_html($label)
            . '</th><td><code>' . \esc_html($value) . '</code></td></tr>';
    }
}
