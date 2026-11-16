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
    /** URLs captured while a published post still exists; release only after deletion succeeds. */
    private static array $pendingDeleteUrls = [];

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
            // WordPress has no wp_after_insert_post event for a permanent
            // deletion. Capture the old permalink before database removal,
            // then invalidate only after the deletion actually completes.
            \add_action('before_delete_post', [__CLASS__, 'capturePostDeletion'], 10, 2);
            \add_action('after_delete_post', [__CLASS__, 'afterPostDeleted'], 10, 2);
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
     * Reconcile a bounded list of public URLs, never the vendor's Purge All.
     * The live vendor callback independently revalidates the current manifest
     * and Helper configuration for every URL.
     */
    private static function purgePublicUrls(array $urls): void
    {
        global $nginx_purger;
        if (!class_exists('FastCGI_Purger', false)
            || !($nginx_purger instanceof \FastCGI_Purger)
            || self::inspect()['url_filter_ready'] !== true) {
            return;
        }
        $manifest = self::manifest();
        if ($manifest === null) {
            return;
        }
        self::dispatchPublicUrls(
            $urls, $manifest, $nginx_purger,
            static fn(string $url): string => self::selectFile('', $url)
        );
    }

    /**
     * Shared save/delete dispatch: only the registered primary Host,
     * query-free public GET objects already present in the saved generation.
     * The selector always owns the filesystem identity checks; this private
     * seam also permits deterministic tests of the real vendor dispatch.
     */
    private static function dispatchPublicUrls(
        array $urls, array $manifest, \FastCGI_Purger $purger, callable $selectFile
    ): void {
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
            // redirects. Never cross the saved site's physical boundary.
            foreach (['http', 'https'] as $scheme) {
                $candidateUrl = $scheme . '://' . $manifest['site_key'] . $path;
                if (isset($seen[$candidateUrl])) {
                    continue;
                }
                $seen[$candidateUrl] = true;
                $file = $selectFile($candidateUrl);
                if (is_string($file)
                    && str_starts_with($file, $manifest['cache_directory'] . '/')
                    && is_file($file)) {
                    $purger->purge_url($candidateUrl, false);
                }
            }
        }
    }

    /**
     * WordPress wp_after_insert_post provides ID, WP_Post, update, old post.
     * A transition out of publish still invalidates the old public permalink.
     */
    public static function afterPostSaved($postId, $post, $update, $postBefore): void
    {
        if (!is_int($postId) || !is_object($post)
            || !isset($post->ID, $post->post_type, $post->post_status)
            || (int)$post->ID !== $postId
            || !is_string($post->post_type)
            || !\is_post_type_viewable($post->post_type)
            || !in_array('publish', [
                $post->post_status,
                is_object($postBefore) ? ($postBefore->post_status ?? null) : null,
            ], true)) {
            return;
        }

        $urls = [\home_url('/'), \get_permalink($post)];
        if (is_object($postBefore)
            && ($postBefore->post_status ?? null) === 'publish') {
            $urls[] = \get_permalink($postBefore);
        }
        self::purgePublicUrls($urls);
    }

    /** Capture while WordPress still has the original published permalink. */
    public static function capturePostDeletion($postId, $post): void
    {
        if (!is_int($postId) || !is_object($post)
            || !isset($post->ID, $post->post_type, $post->post_status)
            || (int)$post->ID !== $postId
            || !is_string($post->post_type)
            || $post->post_status !== 'publish'
            || !\is_post_type_viewable($post->post_type)) {
            return;
        }
        self::$pendingDeleteUrls[$postId] = [
            \home_url('/'), \get_permalink($post),
        ];
    }

    /** Aborted deletions never purge; finished deletes reuse the saved URL. */
    public static function afterPostDeleted($postId, $post): void
    {
        if (!is_int($postId)) {
            return;
        }
        $urls = self::$pendingDeleteUrls[$postId] ?? null;
        unset(self::$pendingDeleteUrls[$postId]);
        if ($urls === null || !is_object($post)
            || !isset($post->ID) || (int)$post->ID !== $postId) {
            return;
        }
        self::purgePublicUrls($urls);
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
