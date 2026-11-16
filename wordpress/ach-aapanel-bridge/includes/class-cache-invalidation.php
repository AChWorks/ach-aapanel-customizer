<?php
/**
 * Optional site-owned, generation-bound Nginx Helper URL-file remapping.
 *
 * A verified site manifest permits scoped URL-file mapping and an explicit
 * WordPress post-save fallback through Nginx Helper's own per-URL purger.
 * The vendor's recursive Purge All never passes through this mapping.
 */
namespace AChWorks\AaPanelBridge;

defined('ABSPATH') || exit;

final class CacheInvalidation
{
    private const DIR = 'ach-customizer-bridge';
    private const MANIFEST = 'cache.php';
    private const PREFIX = "<?php defined('ABSPATH') || exit; __halt_compiler(); ?>\n";

    /** Call once during WordPress plugin boot. An absent manifest changes nothing. */
    public static function boot(): void
    {
        if (self::manifest() !== null) {
            \add_filter('rt_nginx_helper_purge_cached_file', [__CLASS__, 'selectFile'], 10, 2);
            // Gutenberg updates through REST can leave the vendor's canonical
            // homepage response stale. Reconcile only currently cached public
            // post and homepage keys after WordPress finishes persistence.
            \add_action('wp_after_insert_post', [__CLASS__, 'afterPostSaved'], 50, 4);
        }
    }

    private static function contentRoot(): ?string
    {
        if (!defined('WP_CONTENT_DIR') || !is_string(WP_CONTENT_DIR)) {
            return null;
        }
        $root = realpath(WP_CONTENT_DIR);
        if ($root === false || $root !== rtrim(WP_CONTENT_DIR, '/') || !is_dir($root)) {
            return null;
        }
        return $root;
    }

    /** An untrusted WordPress process cannot install/edit the root-owned manifest. */
    private static function verifiedManifestPath(?int $owner = null): ?string
    {
        $root = self::contentRoot();
        if ($root === null) {
            return null;
        }
        $owner = $owner ?? 0;
        $dir = $root . '/' . self::DIR;
        $file = $dir . '/' . self::MANIFEST;
        clearstatcache(true, $dir);
        clearstatcache(true, $file);
        $d = @lstat($dir);
        $f = @lstat($file);
        if ($d === false || $f === false
            || ($d['mode'] & 0170000) !== 0040000
            || ($f['mode'] & 0170000) !== 0100000
            || ($d['mode'] & 07777) !== 0755
            || ($f['mode'] & 07777) !== 0644
            || $d['uid'] !== $owner || $f['uid'] !== $owner
            || $d['nlink'] < 2 || $f['nlink'] !== 1) {
            return null;
        }
        return $file;
    }

    /**
     * @return array<string,mixed>|null
     * Internal owner override exists only for isolated unprivileged test fixtures.
     */
    public static function manifest(?int $testOwner = null): ?array
    {
        $file = self::verifiedManifestPath($testOwner);
        if ($file === null) {
            return null;
        }
        $bytes = @file_get_contents($file, false, null, 0, 4097);
        if (!is_string($bytes) || strlen($bytes) > 4096 ||
            !str_starts_with($bytes, self::PREFIX)) {
            return null;
        }
        $data = json_decode(substr($bytes, strlen(self::PREFIX)), true);
        if (!is_array($data) || array_keys($data) !== [
                'cache_directory', 'cache_generation', 'cache_identity',
                'recovery_id', 'schema', 'site_id', 'site_key', 'wp_root',
            ] || $data['schema'] !== 1 || !is_int($data['site_id'])
            || $data['site_id'] < 1 || $data['site_id'] > 2147483647
            || !is_string($data['site_key']) ||
            preg_match('/\A[a-z0-9][a-z0-9.-]{0,253}\z/D', $data['site_key']) !== 1
            || !is_string($data['cache_generation']) ||
            preg_match('/\A[0-9a-f]{32}\z/D', $data['cache_generation']) !== 1
            || !is_string($data['recovery_id']) ||
            preg_match('/\A[0-9a-f]{32}\z/D', $data['recovery_id']) !== 1
            || !is_array($data['cache_identity']) ||
            count($data['cache_identity']) !== 2 ||
            !array_is_list($data['cache_identity']) ||
            !is_int($data['cache_identity'][0]) || $data['cache_identity'][0] <= 0 ||
            !is_int($data['cache_identity'][1]) || $data['cache_identity'][1] <= 0 ||
            $data['cache_directory'] !==
                '/www/server/ach-customizer-fastcgi/site-' . $data['site_id']
            || !is_string($data['wp_root']) ||
            realpath($data['wp_root']) !== $data['wp_root'] ||
            realpath(ABSPATH) !== $data['wp_root'] ||
            realpath($data['wp_root'] . '/wp-content') !== self::contentRoot()) {
            return null;
        }
        return $data;
    }

    /** Only report the manifest scope, never certify Nginx workers or Purge All. */
    public static function inspect(): array
    {
        $manifest = self::manifest();
        $helper = NginxHelperStatus::inspect();
        // aaPanel commonly restricts the site PHP-FPM worker with .user.ini
        // open_basedir. A valid manifest/Helper path is not enough: the
        // worker must actually be able to reach and unlink its own cache.
        $cacheAccess = $manifest !== null
            && @is_dir($manifest['cache_directory'])
            && @is_readable($manifest['cache_directory'])
            && @is_writable($manifest['cache_directory']);
        $ready = $manifest !== null && $helper['activation'] === 'active'
            && $helper['purge_method'] === 'unlink_files'
            && $helper['effective_cache_path'] === $manifest['cache_directory']
            && $helper['automatic_purge_enabled'] === true && $cacheAccess;
        return [
            'manifest_verified' => $manifest !== null,
            'cache_access_verified' => $cacheAccess,
            'site_id' => $manifest['site_id'] ?? null,
            'site_key' => $manifest['site_key'] ?? null,
            'generation' => $manifest['cache_generation'] ?? null,
            'url_filter_ready' => $ready,
            'reason' => !$manifest ? 'No verified native-managed site manifest' :
                ($helper['activation'] !== 'active' ? 'Nginx Helper is not active' :
                ($helper['purge_method'] !== 'unlink_files' ?
                'Nginx Helper is not in unlink_files mode' :
                ($helper['effective_cache_path'] !== $manifest['cache_directory'] ?
                'Nginx Helper cache path is not the verified site-owned directory' :
                ($helper['automatic_purge_enabled'] !== true ?
                'Nginx Helper automatic purge is disabled' :
                (!$cacheAccess ?
                'Site PHP-FPM cannot access its own Cache directory. Check the per-site open_basedir and filesystem permissions; never include a shared cache directory.' :
                'URL remapping is provisioned; effective Nginx workers not independently certified'))))),
            'safe_purge_all_verified' => false,
        ];
    }

    /**
     * A bounded post-save reconciliation for block/classic/REST updates.
     * Uses the vendor's per-URL unlink_files method; never calls Purge All.
     * The on-disk manifest and configured physical cache ownership are
     * revalidated before dispatching EACH eligible URL.
     */
    public static function afterPostSaved($postId, $post, $update, $postBefore): void
    {
        global $nginx_purger;
        // WordPress wp_after_insert_post first passes the numeric post ID,
        // then the WP_Post object (WP 5.6+). Never confuse the two.
        if (!is_int($postId) || !is_object($post) ||
            !isset($post->ID) || (int)$post->ID !== $postId ||
            !isset($post->post_type, $post->post_status)
            || !is_string($post->post_type)
            || !\is_post_type_viewable($post->post_type)
            || !in_array('publish', [
                $post->post_status,
                is_object($postBefore) ? ($postBefore->post_status ?? null) : null,
            ], true)
            || !class_exists('FastCGI_Purger', false)
            || !($nginx_purger instanceof \FastCGI_Purger)
            || self::inspect()['url_filter_ready'] !== true) {
            return;
        }

        $manifest = self::manifest();
        if ($manifest === null) {
            return;
        }
        $urls = [\home_url('/'), \get_permalink($post)];
        if (is_object($postBefore) &&
            ($postBefore->post_status ?? null) === 'publish') {
            // Preserve invalidation of the former URL after slug/status edits.
            $urls[] = \get_permalink($postBefore);
        }
        $seen = [];
        foreach ($urls as $url) {
            if (!is_string($url)) {
                continue;
            }
            $parts = \wp_parse_url($url);
            if (!is_array($parts) || !isset($parts['host'], $parts['scheme'])
                || !in_array($parts['scheme'], ['http', 'https'], true)
                || strtolower($parts['host']) !== $manifest['site_key']
                || isset($parts['port']) || isset($parts['user']) || isset($parts['pass'])
                || array_key_exists('query', $parts)
                || array_key_exists('fragment', $parts)) {
                continue;
            }
            $path = $parts['path'] ?? '/';
            if (!is_string($path)) {
                continue;
            }
            // The native policy serves both HTTP and HTTPS without forcing
            // redirects. Invalidate both scheme variants, never foreign Hosts.
            foreach (['http', 'https'] as $scheme) {
                $candidateUrl = $scheme . '://' . $manifest['site_key'] . $path;
                if (isset($seen[$candidateUrl])) {
                    continue;
                }
                $seen[$candidateUrl] = true;
                $file = self::selectFile('', $candidateUrl);
                if (str_starts_with($file, $manifest['cache_directory'] . '/')
                    && is_file($file)) {
                    $nginx_purger->purge_url($candidateUrl, false);
                }
            }
        }
    }

    /** The vendor callback must never see a guessed path for an invalid URL. */
    public static function selectFile($vendorPath, $url): string
    {
        $manifest = self::manifest();
        $dir = self::contentRoot();
        // A root-owned directory is not writable by the WordPress PHP worker.
        // This is a deliberately nonexistent path, never the vendor shared path.
        $denied = ($dir ?? '/nonexistent') . '/' . self::DIR .
            '/.denied-' . hash('sha256', is_string($url) ? $url : '');

        $status = NginxHelperStatus::inspect();
        if (!$manifest || !is_string($url) ||
            $status['activation'] !== 'active' ||
            $status['purge_method'] !== 'unlink_files' ||
            $status['effective_cache_path'] !== $manifest['cache_directory']) {
            return $denied;
        }
        return self::selectVerifiedFile($manifest, $url, $denied);
    }

    /**
     * Pure scope boundary, also exercised with disposable non-root fixtures.
     * Validating a pathname is NOT a security proof against privileged races.
     */
    public static function selectVerifiedFile(array $manifest, string $url, string $denied): string
    {
        $parts = \wp_parse_url($url);
        if (!is_array($parts) ||
            !isset($parts['scheme'], $parts['host']) ||
            !in_array($parts['scheme'], ['http', 'https'], true) ||
            strtolower($parts['host']) !== $manifest['site_key'] ||
            isset($parts['port']) || isset($parts['user']) ||
            isset($parts['pass']) || array_key_exists('query', $parts) ||
            array_key_exists('fragment', $parts)) {
            return $denied;
        }
        $path = $parts['path'] ?? '/';
        if (!is_string($path) || strlen($path) > 1024 ||
            preg_match("#\A/[A-Za-z0-9._~!$&'()*+,;=:@/\-]{0,1023}\z#D", $path) !== 1 ||
            str_contains($path, '//') ||
            preg_match('#(?:\A|/)\.{1,2}(?:/|\z)#D', $path)) {
            return $denied;
        }
        $base = $manifest['cache_directory'];
        clearstatcache(true, $base);
        $root = @lstat($base);
        if (!is_array($root) || ($root['mode'] & 0170000) !== 0040000
            || [$root['dev'], $root['ino']] !== $manifest['cache_identity']) {
            return $denied;
        }
        $key = $parts['scheme'] . 'GET' . $manifest['site_key'] . $path .
            '|' . $manifest['cache_generation'];
        $hash = md5($key); // Nginx disk-format key, NOT a security primitive.
        $first = $base . '/' . substr($hash, -1);
        $second = $first . '/' . substr($hash, -3, 2);
        $candidate = $second . '/' . $hash;
        foreach ([$first, $second] as $folder) {
            clearstatcache(true, $folder);
            $st = @lstat($folder);
            if (!$st || ($st['mode'] & 0170000) !== 0040000
                || ($st['mode'] & 07777) !== 0700
                || $st['dev'] !== $root['dev'] || $st['uid'] !== $root['uid']) {
                return $denied;
            }
        }
        clearstatcache(true, $candidate);
        $st = @lstat($candidate);
        if (!$st || ($st['mode'] & 0170000) !== 0100000 ||
            ($st['mode'] & 07777) !== 0600 || $st['nlink'] !== 1 ||
            $st['dev'] !== $root['dev'] || $st['uid'] !== $root['uid']) {
            return $denied;
        }
        $head = @file_get_contents($candidate, false, null, 0, 4096);
        $position = is_string($head) ? strpos($head, 'KEY: ' . $key . "\n") : false;
        return ($position !== false && $position <= 1536) ? $candidate : $denied;
    }
}
