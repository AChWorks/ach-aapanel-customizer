<?php
/**
 * Isolated smoke test of real WordPress translation APIs; no WordPress DB
 * bootstrap, existing site options, credentials or plugin activation.
 *
 * Usage:
 * php bridge_locale_wordpress.php WP_INCLUDES EXTRACTED_PLUGIN SITE_LOCALE [USER_LOCALE]
 *
 * EXTRACTED_PLUGIN is the standalone ZIP's ach-aapanel-bridge directory
 * within a disposable fixture. Only environment/menu/escaping APIs are
 * stubbed; hook dispatch, locale determination, textdomain registration,
 * MO loading, and gettext are the installed WordPress core implementation.
 */
error_reporting(E_ALL);
if (PHP_SAPI !== 'cli' || count($argv) < 4) {
    fwrite(STDERR, "Expected WP_INCLUDES EXTRACTED_PLUGIN SITE_LOCALE [USER_LOCALE]\n");
    exit(2);
}
$core=realpath($argv[1]);
$plugin=realpath($argv[2]);
if (!$core || !$plugin || basename($plugin)!=='ach-aapanel-bridge') {
    throw new RuntimeException('Invalid core or extracted plugin directory');
}
$d=dirname(dirname($plugin));
define('ABSPATH',$d.'/');
define('WP_PLUGIN_DIR',dirname($plugin));
define('WPMU_PLUGIN_DIR',$d.'/mu-plugins');
define('WP_CONTENT_DIR',$d.'/isolated-content');
define('WP_LANG_DIR',$d.'/languages');
define('HOUR_IN_SECONDS',3600);
define('RT_WP_NGINX_HELPER_CACHE_PATH','/www/cache/example');
$locale=$argv[3];
$profile=$argv[4] ?? '';
function is_admin(){return true;}
function wp_get_current_user(){return (object)['locale'=>$GLOBALS['profile']];}
function wp_installing(){return false;}
function get_template_directory(){return __DIR__.'/theme';}
function get_stylesheet_directory(){return __DIR__.'/theme';}
function trailingslashit($s){return rtrim($s,"/\\").'/';}
function wp_normalize_path($s){return str_replace('\\','/',$s);}
function wp_cache_get(...$args){return false;}
function wp_cache_set(...$args){return true;}
function wp_cache_delete(...$args){return true;}
function _doing_it_wrong($fn,$msg,$ver){throw new Exception($fn.': '.$msg);}
function current_user_can($cap){return $cap==='manage_options';}
function esc_html($s){return htmlspecialchars($s,ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');}
function add_management_page($title,$menu,$cap,$slug,$cb){$GLOBALS['menu']=[$title,$menu,$cap,$slug];}
require $core.'/plugin.php';
require $core.'/pomo/translations.php';
foreach(['file','file-mo','file-php','controller'] as $file)require $core.'/l10n/class-wp-translation-'.$file.'.php';
require $core.'/l10n/class-wp-translations.php';
require $core.'/class-wp-textdomain-registry.php';
require $core.'/l10n.php';
$wp_plugin_paths=[];
$wp_textdomain_registry=new WP_Textdomain_Registry();
$GLOBALS['nginx_helper_admin']=(object)['options'=>['purge_method'=>'unlink_files','enable_purge'=>1]];
require WP_PLUGIN_DIR.'/ach-aapanel-bridge/ach-aapanel-bridge.php';
if(isset($l10n['ach-aapanel-bridge']))throw new Exception('Early domain evaluation');
do_action('after_setup_theme');
do_action('init');
do_action('admin_menu');
ob_start();
\AChWorks\AaPanelBridge\Plugin::renderAdminPage();
$html=ob_get_clean();
$actual=determine_locale();
$fa=$actual==='fa_IR';
$label=$fa?'متصل نیست':'Not connected';
$reason=$fa?'مانیفست تأییدشدهٔ این سایت تحت مدیریت افزونهٔ aaPanel وجود ندارد.':'No verified native-managed site manifest';
if (!str_contains($html,$label)||!str_contains($html,$reason)||!str_contains($html,'<h1><bdi>ACh aaPanel Bridge</bdi></h1>')||!str_contains($html,'/www/cache/example</code>')||!str_contains($html,'unlink_files</code>')||$GLOBALS['menu'][0]!=='ACh aaPanel Bridge')throw new Exception('Unexpected localized rendering');
if ($fa && str_contains($html,'>Not connected<'))throw new Exception('Untranslated label');
echo json_encode(['site_locale'=>$locale,'profile_locale'=>$profile,'effective_locale'=>$actual,'translated'=>$fa,'connection'=>__('Connection','ach-aapanel-bridge'),'readiness'=>__('Readiness','ach-aapanel-bridge'),'brand'=>$GLOBALS['menu'][0],'native_loader'=>get_class(get_translations_for_domain('ach-aapanel-bridge')),'html_tables'=>substr_count($html,'<table ')],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR),PHP_EOL;
