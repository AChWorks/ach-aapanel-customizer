<?php
/**
 * Plugin Name: ACh aaPanel Bridge
 * Plugin URI: https://github.com/AChWorks/ach-aapanel-customizer/tree/main/wordpress/ach-aapanel-bridge
 * Description: Optional WordPress companion and diagnostics for ACh aaPanel Customizer.
 * Version: 0.1.0
 * Author: AChWorks
 * Author URI: https://ach.li/
 * Text Domain: ach-aapanel-bridge
 * Update URI: https://github.com/AChWorks/ach-aapanel-customizer/tree/main/wordpress/ach-aapanel-bridge
 */

defined('ABSPATH') || exit;

require_once __DIR__ . '/includes/class-nginx-helper-status.php';
require_once __DIR__ . '/includes/class-plugin.php';

\AChWorks\AaPanelBridge\Plugin::boot();
