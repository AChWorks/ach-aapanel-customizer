<?php
/**
 * Isolated non-production behavior check for the *installed* Nginx Helper 2.4.1.
 *
 * Usage: php -n scripts/qa_nginx_helper_241.php /path/to/wp-content/plugins/nginx-helper
 *
 * Only the two real vendor purger classes are loaded, without WordPress
 * bootstrap, external HTTP, website/config writes or a real cache directory.
 * Two physically separate site fixtures are created under one new private
 * temp directory, never a caller argument. The documented WordPress cache
 * filename filter is simulated through apply_filters; this does NOT install
 * a bridge in WordPress. Purge All runs ONLY against the site A fixture.
 */
declare(strict_types=1);

function require_true(bool $condition, string $reason): void {
    if (!$condition) {
        throw new RuntimeException($reason);
    }
}

function fixture_file(string $directory, string $key): string {
    $hash = md5($key);
    $path = $directory . '/' . substr($hash, -1) . '/' . substr($hash, -3, 2);
    require_true(is_dir($path) || mkdir($path, 0700, true), 'Cannot create cache fixture path');
    $file = $path . '/' . $hash;
    require_true(file_put_contents($file, 'ONLY TEST DATA') !== false, 'Cannot create cache fixture');
    return $file;
}

function remove_fixture(string $path): void {
    if (!is_dir($path) || is_link($path)) {
        throw new RuntimeException('Unsafe fixture cleanup root');
    }
    $walk = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($path, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST
    );
    foreach ($walk as $entry) {
        if ($entry->isDir() && !$entry->isLink()) {
            require_true(rmdir($entry->getPathname()), 'Cannot clean fixture subdir');
        } else {
            require_true(unlink($entry->getPathname()), 'Cannot clean fixture file');
        }
    }
    require_true(rmdir($path), 'Cannot clean fixture directory');
}

if (PHP_SAPI !== 'cli' || count($argv) !== 2 || defined('WPINC')) {
    fwrite(STDERR, "Usage: php -n qa_nginx_helper_241.php /path/to/nginx-helper\n");
    exit(2);
}
$plugin = realpath($argv[1]);
if (!$plugin || !is_dir($plugin)) {
    fwrite(STDERR, "An installed Nginx Helper directory is required.\n");
    exit(2);
}
$main = $plugin . '/nginx-helper.php';
$purgerFile = $plugin . '/admin/class-purger.php';
$fastcgiFile = $plugin . '/admin/class-fastcgi-purger.php';
// Exact upstream rtCamp/nginx-helper@a89a17f03f808cbabc572a6f25d99b1decf50406.
// These digests also match the actual QA guest's installed 2.4.1 source.
// Deliberately check the two executable classes before the main file: a
// spoofed 2.4.1 header alone must never authorize arbitrary class execution.
$auditedSources = [
    $purgerFile => '5e8a5f6cbf2e16342f5acb99a3cadc774f798e43a51d7cdfe6c6fc8b38abd1a5',
    $fastcgiFile => '3561fbc01a26e28225d5368ce958a92cfb0a27898ded6fec3a699594d6877d9f',
    $main => '4783c975c2942d0917e6fb4236a79b1939bcbb0026fd6003f99bd188d134838a',
];
foreach (array_keys($auditedSources) as $file) {
    if (!is_file($file) || is_link($file)) {
        fwrite(STDERR, "The installed Nginx Helper source is incomplete.\n");
        exit(2);
    }
}
$header = file_get_contents($main, false, null, 0, 4096);
if ($header === false || !preg_match('/^[ \t]*\*[ \t]*Plugin Name:[ \t]*Nginx Helper[ \t]*$/m', $header)
    || !preg_match('/^[ \t]*\*[ \t]*Version:[ \t]*2\.4\.1[ \t]*$/m', $header)) {
    fwrite(STDERR, "This behavior fixture is pinned to Nginx Helper v2.4.1.\n");
    exit(2);
}
// Capture the exact bytes, not just hash_file() on a path that could change
// before require_once. Never execute vendor PHP from the caller's directory.
$verifiedSource = [];
foreach ($auditedSources as $file => $expected) {
    $bytes = file_get_contents($file);
    if ($bytes === false || !hash_equals($expected, hash('sha256', $bytes))) {
        fwrite(STDERR, 'Audited Nginx Helper 2.4.1 source SHA-256 mismatch: '
            . basename($file) . "\n");
        exit(2);
    }
    $verifiedSource[$file] = $bytes;
}

// Minimal WordPress function surface, with no WordPress/plugin bootstrap.
$remoteCalls = [];
function wp_parse_url(string $url): array|false { return parse_url($url); }
$cacheFilenameFilter = null;
function apply_filters(string $name, mixed $value, mixed ...$args): mixed {
    global $cacheFilenameFilter;
    if ($name === 'rt_nginx_helper_purge_cached_file' && $cacheFilenameFilter !== null) {
        return $cacheFilenameFilter($value, ...$args);
    }
    return $value;
}
function do_action(string $name, mixed ...$args): void {}
function home_url(): string { return 'http://qa-helper-a.invalid'; }
function untrailingslashit(string $path): string { return rtrim($path, '/'); }
function is_page(): bool { return false; }
function is_single(): bool { return false; }
function is_wp_error(mixed $value): bool { return false; }
function wp_remote_get(string $url): array {
    global $remoteCalls;
    $remoteCalls[] = $url;
    // A 200 is deliberately simulated to show that this alone proves NO purge.
    return ['response' => ['code' => 200]];
}

$scratch = sys_get_temp_dir() . '/ach-nginx-helper-241-' . bin2hex(random_bytes(10));
require_true(mkdir($scratch, 0700), 'Cannot allocate isolated QA fixture');
$cacheRoot = $scratch . '/cache';
// Mirror Customizer's physical per-site partition, not a shared directory.
$cache = $cacheRoot . '/site-a';
$peerCache = $cacheRoot . '/site-b';
$failure = null;
$report = null;
try {
    require_true(mkdir($cacheRoot, 0700), 'Cannot create isolated cache parent');
    require_true(mkdir($cache, 0700), 'Cannot create site A cache');
    require_true(mkdir($peerCache, 0700), 'Cannot create site B cache');
    // Copy only the already verified bytes into our own private directory.
    // Rehash the copies before including them, so changes in installed source
    // after verification cannot change what PHP actually executes.
    $snapshotDir = $scratch . '/verified-vendor';
    require_true(mkdir($snapshotDir, 0700), 'Cannot create verified vendor snapshot');
    $snapshots = [];
    foreach ([$purgerFile, $fastcgiFile] as $file) {
        $copy = $snapshotDir . '/' . basename($file);
        $bytes = $verifiedSource[$file];
        require_true(file_put_contents($copy, $bytes, LOCK_EX) === strlen($bytes),
            'Cannot stage the verified vendor source');
        require_true(chmod($copy, 0600), 'Cannot protect the verified vendor source');
        require_true(hash_equals($auditedSources[$file], hash_file('sha256', $copy)),
            'Verified vendor snapshot changed before execution');
        $snapshots[] = $copy;
    }
    define('RT_WP_NGINX_HELPER_CACHE_PATH', $cache);
    require_once $snapshots[0];
    require_once $snapshots[1];
    if (getenv('ACH_NGINX_HELPER_QA_TEST_FAILURE') === 'after_verified_load') {
        throw new RuntimeException('Injected QA failure after verified vendor loading');
    }
    $nginx_helper_admin = new class {
        public array $options = [
            'purge_method' => 'unlink_files',
            'purge_feeds' => 0,
            'purge_amp_urls' => 0,
            'log_level' => 'NONE',
        ];
        public function is_nginx_log_enabled(): bool { return false; }
    };
    $purger = new FastCGI_Purger();
    $url = 'http://qa-helper-a.invalid/post';
    $urlQuery = 'http://qa-helper-a.invalid/post?draft=1';
    $key = 'httpGETqa-helper-a.invalid/post';
    $generation = str_repeat('a', 32);
    $legacy = fixture_file($cache, $key);
    $current = fixture_file($cache, $key . '|' . $generation);
    $legacyQuery = fixture_file($cache, $key . '?draft=1');
    $currentQuery = fixture_file($cache, $key . '?draft=1|' . $generation);
    // Site B has its own physical cache tree, with a separate generation.
    $isolatedPeer = fixture_file($peerCache, $key . '|' . str_repeat('b', 32));
    require_true($legacy !== $current && $legacyQuery !== $currentQuery,
        'Fixture keys unexpectedly overlap');

    $purger->purge_url($url, false);
    $purger->purge_url($urlQuery, false);
    // Unmodified v2.4.1 intentionally ignores query strings when hashing
    // URL-based unlink_files. Its query-specific cache key is untouched.
    require_true(!file_exists($legacy) && file_exists($legacyQuery),
        'Expected vendor unlink_files to ignore query components');
    require_true(file_exists($current) && file_exists($currentQuery),
        'unlink_files unexpectedly targeted generation-keyed cache');
    require_true(file_exists($isolatedPeer), 'URL purge changed a separate site cache');

    $nginx_helper_admin->options['purge_method'] = 'get_request';
    $purger->purge_url($url, false);
    $purger->purge_url($urlQuery, false);
    require_true(count($remoteCalls) === 2, 'get_request did not call both remote purge URLs');
    require_true($remoteCalls[0] === 'http://qa-helper-a.invalid/purge/post'
        && $remoteCalls[1] === 'http://qa-helper-a.invalid/purge/post?draft=1',
        'Unexpected remote URL or query handling');
    require_true(file_exists($current) && file_exists($currentQuery),
        'Fake 200 unexpectedly changed a cache fixture');
    require_true(file_exists($isolatedPeer), 'get_request changed the separate site');

    // Nginx Helper 2.4.1 exposes the documented WordPress filter below.
    // A site-owned adapter can map a URL to Customizer's generation-suffixed
    // exact Nginx key *without patching the vendor class*. The fixture filter
    // is intentionally active only for these owned, isolated test URLs.
    $cacheFilenameFilter = static function(string $vendorPath, string $targetUrl) use ($cache, $generation): string {
        $parts = wp_parse_url($targetUrl);
        require_true(is_array($parts) && ($parts['scheme'] ?? '') === 'http'
            && ($parts['host'] ?? '') === 'qa-helper-a.invalid'
            && !isset($parts['port']) && !isset($parts['user'])
            && !isset($parts['pass']),
            'Unexpected URL reached generation-aware purge filter');
        $uri = ($parts['path'] ?? '/')
            . (isset($parts['query']) ? '?' . $parts['query'] : '');
        $hash = md5($parts['scheme'] . 'GET' . $parts['host'] . $uri . '|' . $generation);
        return $cache . '/' . substr($hash, -1) . '/' . substr($hash, -3, 2) . '/' . $hash;
    };
    $nginx_helper_admin->options['purge_method'] = 'unlink_files';
    $purger->purge_url($url, false);
    $purger->purge_url($urlQuery, false);
    require_true(!file_exists($current) && !file_exists($currentQuery),
        'Verified Nginx Helper cache-file filter did not remove generation-keyed entries');
    require_true(file_exists($legacyQuery) && file_exists($isolatedPeer),
        'Generation remap unexpectedly removed legacy query or a peer site');
    $cacheFilenameFilter = null;

    // The actual vendor Purge All ignores the per-URL filter. Keep another
    // live generated site A object to test that path separately.
    $retainedSiteA = fixture_file($cache, $key . '|' . str_repeat('c', 32));

    // Exercise the real vendor Purge All with both a mis-scoped peer file
    // INSIDE its configured root and an independent sibling site cache.
    // A shared-directory setting deletes everything under it; a verified
    // site-specific setting cannot touch an independently owned sibling.
    $misScopedPeer = $cache . '/shared-peer-private-file';
    $siteA = $cache . '/site-a-private-file';
    require_true(file_put_contents($misScopedPeer, 'SHARED PEER ONLY') !== false,
        'Cannot seed mis-scoped peer');
    require_true(file_put_contents($siteA, 'SITE A ONLY') !== false, 'Cannot seed site A');
    require_true(file_exists($isolatedPeer), 'Cannot find isolated site B cache entry');
    $purger->purge_all();
    require_true(!file_exists($misScopedPeer) && !file_exists($siteA)
        && !file_exists($retainedSiteA) && !file_exists($current) && !file_exists($currentQuery),
        'Expected Nginx Helper Purge All to clear every object under its path');
    require_true(file_exists($isolatedPeer),
        'Purge All changed physically isolated site B cache outside its configured path');

    $report = [
        'schema' => 2,
        'source_version' => '2.4.1',
        'source_sha256' => hash('sha256', $verifiedSource[$main]),
        'class_purger_sha256' => hash('sha256', $verifiedSource[$purgerFile]),
        'fastcgi_purger_sha256' => hash('sha256', $verifiedSource[$fastcgiFile]),
        'vendor_code_executed_from_verified_private_snapshot' => true,
        'unlink_files_legacy_key_deleted' => true,
        'unlink_files_query_legacy_key_ignored' => true,
        'unlink_files_query_generation_key_preserved' => true,
        'unlink_files_peer_site_preserved' => true,
        'unlink_files_verified_filter_deleted_generation_key' => true,
        'unlink_files_verified_filter_deleted_query_generation_key' => true,
        'unlink_files_generation_key_preserved' => true,
        'get_request_remote_urls' => $remoteCalls,
        'get_request_http_200_simulated_not_proof' => true,
        'get_request_generation_key_preserved' => true,
        'get_request_query_generation_key_preserved' => true,
        'get_request_peer_site_preserved' => true,
        'get_request_purge_all_site_a_deleted' => true,
        'get_request_purge_all_retained_generation_deleted' => true,
        'get_request_purge_all_mis_scoped_peer_deleted' => true,
        'get_request_purge_all_physically_separate_peer_preserved' => true,
        'wp_remote_get_calls_stubbed' => count($remoteCalls),
        'remote_http_response_simulated' => true,
        'tested_cache_root' => 'private_temporary_fixture',
        'process_network_monitoring_performed' => false,
        'safe_customizer_purge_inferred' => false,
    ];
} catch (Throwable $error) {
    $failure = $error;
} finally {
    try {
        remove_fixture($scratch);
    } catch (Throwable $cleanupError) {
        $failure = $cleanupError;
    }
}
if ($failure !== null) {
    fwrite(STDERR, 'Nginx Helper isolated QA failed: ' . $failure->getMessage() . "\n");
    exit(1);
}
$report['fixture_cleaned'] = true;
echo json_encode($report, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES) . "\n";
