<?php
/**
 * Isolated non-production behavior check for the *installed* Nginx Helper 2.4.1.
 *
 * Usage: php -n scripts/qa_nginx_helper_241.php /path/to/wp-content/plugins/nginx-helper
 *
 * Only the two real vendor purger classes are loaded, without WordPress
 * bootstrap, external HTTP, website/config writes or a real cache directory.
 * The fixture's cache root is a new private temp directory, never a caller
 * argument. Purge All is intentionally executed ONLY against this fixture.
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
function apply_filters(string $name, mixed $value, mixed ...$args): mixed { return $value; }
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
$cache = $scratch . '/cache';
$failure = null;
$report = null;
try {
    require_true(mkdir($cache, 0700), 'Cannot create isolated cache');
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
    $key = 'httpGETqa-helper-a.invalid/post';
    $generation = str_repeat('a', 32);
    $legacy = fixture_file($cache, $key);
    $current = fixture_file($cache, $key . '|' . $generation);
    require_true($legacy !== $current, 'Fixture keys unexpectedly overlap');

    $purger->purge_url($url, false);
    require_true(!file_exists($legacy), 'unlink_files failed to purge its legacy-key fixture');
    require_true(file_exists($current), 'unlink_files unexpectedly targeted generation-keyed cache');

    $nginx_helper_admin->options['purge_method'] = 'get_request';
    $purger->purge_url($url, false);
    require_true(count($remoteCalls) === 1, 'get_request did not call the remote helper');
    require_true($remoteCalls[0] === 'http://qa-helper-a.invalid/purge/post', 'Unexpected remote URL');
    require_true(file_exists($current), 'Fake 200 unexpectedly changed a cache fixture');

    // This tests the actual vendor Purge All implementation, against a NEW
    // fixture containing two sites. Never supply a production cache path.
    $peer = $cache . '/site-b-private-file';
    $siteA = $cache . '/site-a-private-file';
    require_true(file_put_contents($peer, 'PEER ONLY') !== false, 'Cannot seed peer');
    require_true(file_put_contents($siteA, 'SITE A ONLY') !== false, 'Cannot seed site A');
    $purger->purge_all();
    require_true(!file_exists($peer) && !file_exists($siteA) && !file_exists($current),
        'Expected shared-root Purge All to remove both sites and generated objects');

    $report = [
        'schema' => 1,
        'source_version' => '2.4.1',
        'source_sha256' => hash('sha256', $verifiedSource[$main]),
        'class_purger_sha256' => hash('sha256', $verifiedSource[$purgerFile]),
        'fastcgi_purger_sha256' => hash('sha256', $verifiedSource[$fastcgiFile]),
        'vendor_code_executed_from_verified_private_snapshot' => true,
        'unlink_files_legacy_key_deleted' => true,
        'unlink_files_generation_key_preserved' => true,
        'get_request_remote_url' => $remoteCalls[0],
        'get_request_http_200_simulated_not_proof' => true,
        'get_request_generation_key_preserved' => true,
        'get_request_purge_all_shared_site_a_deleted' => true,
        'get_request_purge_all_shared_peer_deleted' => true,
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
