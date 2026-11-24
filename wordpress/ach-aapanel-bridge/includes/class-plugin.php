<?php
/**
 * WordPress administrator view for the optional ACh aaPanel Bridge.
 *
 * A verified native-owned manifest may opt into Nginx Helper per-URL remapping.
 * The plugin itself never creates manifests or invokes purge operations.
 */
namespace AChWorks\AaPanelBridge;

defined('ABSPATH') || exit;

final class Plugin
{
    public static function boot(): void
    {
        \add_action('admin_menu', [__CLASS__, 'registerAdminPage']);
        CacheInvalidation::boot();
    }

    public static function registerAdminPage(): void
    {
        \add_management_page(
            'ACh aaPanel Bridge',
            'ACh aaPanel Bridge',
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
        echo '<h1><bdi>ACh aaPanel Bridge</bdi></h1>';
        echo '<p>' . \esc_html__(
            'Optional WordPress companion for ACh aaPanel Customizer.',
            'ach-aapanel-bridge'
        ) . '</p>';
        echo '<h2>' . \esc_html__('Connection', 'ach-aapanel-bridge') . '</h2>';
        echo '<p>' . \esc_html__(
            'The Bridge never enables Nginx Helper purging or Purge All. The URL-file filter requires a verified native-managed site manifest and an active unlink_files Helper. Other Nginx workers are not certified.',
            'ach-aapanel-bridge'
        ) . '</p>';
        $connection = CacheInvalidation::inspect();
        echo '<h2>' . \esc_html__('Site cache URL mapping', 'ach-aapanel-bridge') . '</h2>';
        echo '<table class="widefat striped" style="max-width:900px"><tbody>';
        self::tableRow(
            __('Manifest', 'ach-aapanel-bridge'),
            $connection['manifest_verified']
                ? __('Native manifest verified', 'ach-aapanel-bridge')
                : __('Not connected', 'ach-aapanel-bridge')
        );
        self::tableRow(
            __('URL-file mapping', 'ach-aapanel-bridge'),
            $connection['url_filter_ready']
                ? __('Provisioned (worker state unverified)', 'ach-aapanel-bridge')
                : __('Unavailable', 'ach-aapanel-bridge')
        );
        self::tableRow(
            __('Site Cache filesystem access', 'ach-aapanel-bridge'),
            $connection['cache_access_verified']
                ? __('Readable and writable by this PHP process', 'ach-aapanel-bridge')
                : __('Not verified / blocked', 'ach-aapanel-bridge')
        );
        self::tableRow(__('Readiness', 'ach-aapanel-bridge'), $connection['reason']);
        echo '</tbody></table>';
        echo '<h2>' . \esc_html__('Nginx Helper observations', 'ach-aapanel-bridge') . '</h2>';
        echo '<table class="widefat striped" style="max-width:900px"><tbody>';
        self::tableRow(
            __('Plugin status', 'ach-aapanel-bridge'),
            $activation[$status['activation']]
        );
        self::tableRow(
            __('Purge method', 'ach-aapanel-bridge'),
            $value($status['purge_method']),
            $status['purge_method'] !== null
        );
        $automatic = $status['automatic_purge_enabled'] === null
            ? __('Not available', 'ach-aapanel-bridge')
            : ($status['automatic_purge_enabled']
                ? __('Enabled', 'ach-aapanel-bridge')
                : __('Disabled', 'ach-aapanel-bridge'));
        self::tableRow(__('Automatic purge setting', 'ach-aapanel-bridge'), $automatic);
        self::tableRow(
            __('Configured cache path', 'ach-aapanel-bridge'),
            $value($status['effective_cache_path']),
            $status['effective_cache_path'] !== null
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

    private static function tableRow(string $label, string $value, bool $technical = false): void
    {
        echo '<tr><th scope="row">' . \esc_html($label) . '</th><td>';
        // Paths and mode identifiers are data, never translated. Isolate
        // their direction in RTL admin pages; human explanations inherit
        // WordPress's locale and ordinary typography.
        echo $technical
            ? '<code dir="ltr" style="overflow-wrap:anywhere">' . \esc_html($value) . '</code>'
            : \esc_html($value);
        echo '</td></tr>';
    }
}
