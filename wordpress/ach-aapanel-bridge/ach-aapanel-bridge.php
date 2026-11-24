<?php
/**
 * Plugin Name: ACh aaPanel Bridge
 * Plugin URI: https://github.com/AChWorks/ach-aapanel-customizer/tree/main/wordpress/ach-aapanel-bridge
 * Description: Optional WordPress companion and diagnostics for ACh aaPanel Customizer.
 * Version: 0.1.11
 * License: MPL-2.0
 * License URI: https://www.mozilla.org/en-US/MPL/2.0/
 * Author: AChWorks
 * Author URI: https://ach.li/
 * Text Domain: ach-aapanel-bridge
 * Domain Path: /languages
 * Update URI: https://github.com/AChWorks/ach-aapanel-customizer/tree/main/wordpress/ach-aapanel-bridge
 */

defined('ABSPATH') || exit;

require_once __DIR__ . '/includes/class-nginx-helper-status.php';
require_once __DIR__ . '/includes/class-cache-invalidation.php';
require_once __DIR__ . '/includes/class-plugin.php';

// GitHub-distributed plugin: register the bundled catalog after WordPress
// establishes the current user's locale. Do not translate during plugin boot.
add_action('init', static function (): void {
    load_plugin_textdomain(
        'ach-aapanel-bridge',
        false,
        dirname(plugin_basename(__FILE__)) . '/languages'
    );
});

\AChWorks\AaPanelBridge\Plugin::boot();
