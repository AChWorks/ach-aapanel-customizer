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

    /** Previous public permalink captured before a term relationship changes, per request. */
    private static array $pendingTermPermalinks = [];

    /** Per-dispatch vendor file-filter target; absent for ordinary Nginx Helper calls. */
    private static ?array $activeUrlPurge = null;

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
            // WordPress sets terms before notifying set_object_terms. Capture
            // the actual old public permalink at the earliest pre-mutation
            // relationship hook (addition happens before deletion on replace).
            \add_action('add_term_relationship', [__CLASS__, 'captureTermPermalink'], 10, 3);
            \add_action('delete_term_relationships', [__CLASS__, 'captureTermPermalink'], 10, 3);
            // Reconcile old/new post URLs and taxonomy archives only when the
            // completed relationship sets genuinely differ.
            \add_action('set_object_terms', [__CLASS__, 'afterPostTermsSet'], 20, 6);
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
            static fn(string $url, string $method): string =>
                self::selectVerifiedFile($manifest, $url, '', $method)
        );
    }

    /**
     * Shared save/delete dispatch: only the registered primary Host,
     * query-free public GET/HEAD objects already present in the saved generation.
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
            // A real Nginx cache can store independent GET and HEAD keys.
            // Use the existing vendor per-URL unlink path for each verified
            // object; never direct-unlink it or allow a different vendor URL
            // to inherit the temporary HEAD selector.
            foreach (['http', 'https'] as $scheme) {
                $candidateUrl = $scheme . '://' . $manifest['site_key'] . $path;
                foreach (['GET', 'HEAD'] as $method) {
                    $identity = $method . ' ' . $candidateUrl;
                    if (isset($seen[$identity])) {
                        continue;
                    }
                    $seen[$identity] = true;
                    $file = $selectFile($candidateUrl, $method);
                    if (!is_string($file)
                        || !str_starts_with($file, $manifest['cache_directory'] . '/')
                        || !is_file($file)) {
                        continue;
                    }
                    $previous = self::$activeUrlPurge;
                    self::$activeUrlPurge = ['url' => $candidateUrl, 'method' => $method];
                    try {
                        // false disables feed-URL purging, not recursive Purge All.
                        $purger->purge_url($candidateUrl, false);
                    } finally {
                        self::$activeUrlPurge = $previous;
                    }
                }
            }
        }
    }

    /**
     * Canonical first-page taxonomy archives only. The native Nginx policy
     * bypasses queries and encoded/noncanonical request URIs; the existing
     * generation-bound selector remains the only authority to purge a file.
     */
    private static function termArchiveUrls(array $terms, string $taxonomy): array
    {
        if (!\is_taxonomy_viewable($taxonomy)) {
            return [];
        }
        $urls = [];
        $seenTerms = [];
        foreach ($terms as $term) {
            if (!is_object($term) || !isset($term->term_id)
                || (int)$term->term_id < 1) {
                continue;
            }
            $ids = [(int)$term->term_id];
            if (\is_taxonomy_hierarchical($taxonomy)) {
                $parents = \get_ancestors((int)$term->term_id, $taxonomy, 'taxonomy');
                if (is_array($parents)) {
                    $ids = array_merge($ids, $parents);
                }
            }
            foreach ($ids as $termId) {
                if (!is_int($termId) && !is_string($termId)) {
                    continue;
                }
                $termId = (int)$termId;
                if ($termId < 1 || isset($seenTerms[$termId])) {
                    continue;
                }
                $seenTerms[$termId] = true;
                $resolved = $termId === (int)$term->term_id
                    ? $term : \get_term($termId, $taxonomy);
                if (!is_object($resolved) || \is_wp_error($resolved)) {
                    continue;
                }
                $url = \get_term_link($resolved, $taxonomy);
                if (is_string($url)) {
                    $urls[] = $url;
                }
            }
        }
        return $urls;
    }

    /** Current public first-page archives of all viewable post taxonomies. */
    private static function postArchiveUrls(object $post): array
    {
        $urls = [];
        $taxonomies = \get_object_taxonomies($post->post_type);
        if (!is_array($taxonomies)) {
            return [];
        }
        foreach ($taxonomies as $taxonomy) {
            if (!is_string($taxonomy) || !\is_taxonomy_viewable($taxonomy)) {
                continue;
            }
            $terms = \get_the_terms($post, $taxonomy);
            if (is_array($terms)) {
                $urls = array_merge($urls, self::termArchiveUrls($terms, $taxonomy));
            }
        }
        return $urls;
    }

    /** Only published, publicly viewable posts and their public taxonomies qualify. */
    private static function publicTaxonomyPost($objectId, $taxonomy): ?object
    {
        if (!is_int($objectId) || $objectId < 1 || !is_string($taxonomy)) {
            return null;
        }
        $post = \get_post($objectId);
        if (!is_object($post) || !isset($post->ID, $post->post_type, $post->post_status)
            || (int)$post->ID !== $objectId || $post->post_status !== 'publish'
            || !is_string($post->post_type)
            || !\is_post_type_viewable($post->post_type)
            || !in_array($taxonomy, \get_object_taxonomies($post->post_type), true)
            || !\is_taxonomy_viewable($taxonomy)) {
            return null;
        }
        return $post;
    }

    /**
     * First pre-add/delete callback observes the canonical permalink while
     * the previous category relationships still exist. No URL reconstruction
     * or persistent storage: the matching set_object_terms consumes the value.
     */
    public static function captureTermPermalink($objectId, $termTaxonomyIds, $taxonomy): void
    {
        $post = self::publicTaxonomyPost($objectId, $taxonomy);
        if ($post === null || isset(self::$pendingTermPermalinks[$objectId][$taxonomy])) {
            return;
        }
        $url = \get_permalink($post);
        if (is_string($url) && $url !== '') {
            self::$pendingTermPermalinks[$objectId][$taxonomy] = $url;
        }
    }

    /** Compose old/current public URLs for the existing exact-file dispatcher. */
    private static function changedTermUrls(
        object $post, string $taxonomy, $affectedTerms, ?string $previousUrl
    ): array {
        $urls = [\home_url('/'), $previousUrl, \get_permalink($post)];
        return is_array($affectedTerms)
            ? array_merge($urls, self::termArchiveUrls($affectedTerms, $taxonomy))
            : $urls;
    }

    /**
     * Term assignments can change without wp_after_insert_post. The hook
     * receives old/new TERM-TAXONOMY IDs, not interchangeable term IDs.
     * WordPress has already written the relationship when this runs. Consume
     * the pre-mutation permalink before checking no-op and public eligibility.
     */
    public static function afterPostTermsSet(
        $objectId, $terms, $termTaxonomyIds, $taxonomy, $append, $oldTermTaxonomyIds
    ): void {
        $previousUrl = null;
        if (is_int($objectId) && $objectId > 0 && is_string($taxonomy)) {
            $previousUrl = self::$pendingTermPermalinks[$objectId][$taxonomy] ?? null;
            unset(self::$pendingTermPermalinks[$objectId][$taxonomy]);
            if (empty(self::$pendingTermPermalinks[$objectId])) {
                unset(self::$pendingTermPermalinks[$objectId]);
            }
        }
        if (!is_array($termTaxonomyIds) || !is_array($oldTermTaxonomyIds)) {
            return;
        }
        $post = self::publicTaxonomyPost($objectId, $taxonomy);
        if ($post === null) {
            return;
        }
        $current = [];
        $previous = [];
        foreach ($termTaxonomyIds as $id) {
            if ((is_int($id) || is_string($id)) && (int)$id > 0) {
                $current[(int)$id] = (int)$id;
            }
        }
        foreach ($oldTermTaxonomyIds as $id) {
            if ((is_int($id) || is_string($id)) && (int)$id > 0) {
                $previous[(int)$id] = (int)$id;
            }
        }
        // WordPress can re-save an unchanged relationship during ordinary
        // post edits. Avoid a duplicate taxonomy purge in that no-op case.
        if (!array_diff_key($current, $previous)
            && !array_diff_key($previous, $current)) {
            return;
        }
        $ttIds = array_values($current + $previous);
        $affectedTerms = \get_terms([
            'taxonomy' => $taxonomy,
            'term_taxonomy_id' => $ttIds,
            'hide_empty' => false,
        ]);
        self::purgePublicUrls(self::changedTermUrls(
            $post, $taxonomy, $affectedTerms, $previousUrl
        ));
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
        self::purgePublicUrls(array_merge($urls, self::postArchiveUrls($post)));
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
        self::$pendingDeleteUrls[$postId] = array_merge(
            [\home_url('/'), \get_permalink($post)],
            self::postArchiveUrls($post)
        );
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
        return self::selectFileForManifest($manifest, $url, $denied);
    }

    /**
     * The Nginx Helper vendor filter supplies only a URL, not a request method.
     * An ordinary vendor call maps GET, exactly as before. Only this class's
     * synchronous, verified dispatch can select HEAD for that same URL.
     */
    private static function selectFileForManifest(
        array $manifest, string $url, string $denied
    ): string {
        $target = self::$activeUrlPurge;
        if ($target !== null && $target['url'] !== $url) {
            return $denied;
        }
        return self::selectVerifiedFile(
            $manifest, $url, $denied, $target['method'] ?? 'GET'
        );
    }

    /**
     * Pure scope boundary, also exercised with disposable non-root fixtures.
     * Validating a pathname is NOT a security proof against privileged races.
     */
    public static function selectVerifiedFile(
        array $manifest, string $url, string $denied, string $method = 'GET'
    ): string {
        if (!in_array($method, ['GET', 'HEAD'], true)) {
            return $denied;
        }
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
        $key = $parts['scheme'] . $method . $manifest['site_key'] . $path .
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
