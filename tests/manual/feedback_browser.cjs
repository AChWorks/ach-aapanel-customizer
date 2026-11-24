'use strict';
// Real Chromium + the shipped plugin DOM and pinned native jQuery.
// Backend replies are mocked, so this verifies UX, not live server changes.
const assert = require('node:assert/strict');
const {chromium,site,prefs,realPage,resolveLatest,lastRequest,openDestination} = require('./native_browser_fixture.cjs');
const version = require('../../plugin/ach_customizer/info.json').versions;
const monitor = {status:true,mode:'Monitor',worker_source_version:version,
  notice:'Read-only Monitor controls',enforcement:false,state_schema:1,state_revision:0,
  overall_enabled:true,modules_enabled:{site_inventory:true,php_fpm_file_preview:true}};
const inventory = {status:true,inventory_schema:2,page:1,page_size:25,has_more:false,
  sites:[site,{...site,id:8,name:'other.test',document_root:'/www/other.test',
    bound_domains:[{name:'other.test',port:80}]}]};
const state = (name,extra={})=>({status:true,schema:1,state:name,site_id:7,site_key:site.name,
  read_only:true,recovery_id:name==='Not Connected'?null:'f'.repeat(32),...extra});

(async()=>{
  const browser=await chromium.launch({headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath(),
    args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    for(const width of [375,720,1280]){
      const {page,pageErrors}=await realPage(browser,width,768);
      try {
        await resolveLatest(page,'get_overview',monitor);
        await openDestination(page,'websites');
        await resolveLatest(page,'get_sites',inventory);
        await page.locator('[data-task="cache"]').click();
        await page.locator('#ach-hosts-site-id').selectOption('7');
        await page.locator('[data-cache-task="connect"]').click();
        const result=page.locator('#ach-wp-cache-result');
        const check=page.locator('#ach-wp-cache-inspect');
        const connect=page.locator('#ach-wp-cache-setup');
        const disconnect=page.locator('#ach-wp-cache-restore');
        async function tone(expected,color){
          assert.equal(await result.getAttribute('data-tone'),expected);
          if(color)assert.equal(await result.evaluate(el=>getComputedStyle(el).color),color);
          assert.equal(await result.getAttribute('role'),'status');
          assert.equal(await result.getAttribute('aria-live'),'polite');
        }
        await check.click();
        assert.equal(await connect.isDisabled(),true);
        await tone('neutral');
        await resolveLatest(page,'manage_wordpress_cache',state('Not Connected'));
        await tone('neutral');
        assert.equal(await disconnect.isDisabled(),true);
        await connect.click();
        await tone('neutral');
        await resolveLatest(page,'manage_wordpress_cache',state('Connected',
          {read_only:false,changed:true,runtime_verified:true,note:'Verified WordPress connection.'}));
        await tone('observed','rgb(32, 93, 49)');
        assert.match(await result.innerText(),/Connected/);
        assert.equal(await connect.isDisabled(),true);
        assert.equal(await check.isEnabled(),true);
        assert.equal(await disconnect.isEnabled(),true);
        assert.match(await connect.getAttribute('data-ach-disabled-help'),/already Connected/);
        const count=(await lastRequest(page,'manage_wordpress_cache')).count;
        await connect.evaluate(el=>el.click());
        assert.equal((await lastRequest(page,'manage_wordpress_cache')).count,count);
        await check.click();
        await resolveLatest(page,'manage_wordpress_cache',state('Needs Review',
          {note:'Native source changed; inspect recovery.'}));
        await tone('review','rgb(121, 80, 14)');
        assert.equal(await connect.isEnabled(),true);
        await check.click();
        await resolveLatest(page,'manage_wordpress_cache',
          {status:false,stage:'wordpress_cache_inspect',msg:'Inspection failed',operation_id:'a'.repeat(32)});
        await tone('error','rgb(155, 52, 46)');
        await check.click();
        await resolveLatest(page,'manage_wordpress_cache',state('Connected'));
        await tone('observed','rgb(32, 93, 49)');
        // R145-01/03/04: real bundled DOM; only verified Cache Clear
        // preserves the current Connected proof. Zero removals are neutral.
        const native={status:true,schema:1,state:'Applied',site_id:7,site_key:site.name,
          recovery_id:'f'.repeat(32),journal_phase:'applied',read_only:true,
          runtime_verified:true,purge_supported:false};
        const cacheResult=page.locator('#ach-cache-activation-result');
        for(const [reply,expected,retained] of [
          [{...native,read_only:false,cache_files_removed:0,changed:false},'neutral',true],
          [{...native,read_only:false,cache_files_removed:2,changed:true},'observed',true],
          [{status:false,stage:'cache_manage',msg:'Site Cache is not verified Applied'},'error',false]
        ]){
          await page.locator('[data-cache-task="configure"]').click();
          await page.locator('#ach-cache-activation-recheck').click();
          await resolveLatest(page,'manage_cache_policy',native);
          await page.locator('[data-cache-task="clear"]').click();
          await page.locator('#ach-cache-clear-reviewed').check();
          await page.locator('#ach-cache-clear-files').click();
          await resolveLatest(page,'manage_cache_policy',reply);
          assert.equal(await cacheResult.getAttribute('data-tone'),expected);
          assert.equal(await page.locator('#ach-cache-clear-files').isDisabled(),true);
          await page.locator('[data-cache-task="connect"]').click();
          await tone(retained?'observed':'neutral',retained?'rgb(32, 93, 49)':undefined);
          assert.equal(await connect.isDisabled(),retained);
        }
        await check.click();
        await resolveLatest(page,'manage_wordpress_cache',state('Connected',{changed:true}));
        await tone('error','rgb(155, 52, 46)');
        assert.equal(await connect.isEnabled(),true);
        await check.click();
        await resolveLatest(page,'manage_wordpress_cache',state('Connected'));
        await tone('observed','rgb(32, 93, 49)');
        await page.locator('#ach-hosts-site-id').selectOption('8');
        await tone('neutral');
        assert.doesNotMatch(await result.innerText(),/WordPress Cache: Connected/);
        assert.equal(await connect.isEnabled(),true);
        // R145-02: clean, independent manifest absence disables only
        // redundant Disable, not the inspection or native Cache task.
        await page.locator('[data-cache-task="bridge"]').click();
        await page.locator('#ach-bridge-inspect').click();
        await resolveLatest(page,'manage_cache_policy',{status:true,schema:1,
          site_id:8,site_key:'other.test',state:'Not Provisioned',read_only:true,
          recovery_id:null,runtime_verified:false,purge_supported:false});
        assert.equal(await page.locator('#ach-bridge-result').getAttribute('data-tone'),'neutral');
        assert.equal(await page.locator('#ach-bridge-disable').isDisabled(),true);
        assert.equal(await page.locator('#ach-bridge-inspect').isEnabled(),true);
        await openDestination(page,'server');
        await resolveLatest(page,'get_php_versions',{status:true,schema:1,state:'Observed',
          read_only:true,runtime_verified:false,reason:'',note:'File-only inventory',
          versions:['85'].map(v=>({code:v,label:'PHP 8.5',state:'File Preview Candidate',
            binary_present:true,config_present:true,preview_candidate:true,
            manual_apply_adapter:'guarded_php'+v,apply_eligible:false,reason:'Prepare required'}))});
        await page.locator('#ach-php-version').selectOption('85');
        await page.locator('[data-php-task="policy"]').click();
        const automatic={status:true,schema:1,version:'85',state_revision:1,enabled:true,
          pending_disable:false,watcher_ready:true};
        for(const [last_state,expected,color] of [
          ['Armed','observed','rgb(32, 93, 49)'],
          ['Needs Review: nonvendor PHP-FPM drift','review','rgb(121, 80, 14)'],
          ['Repair refused at reload','review','rgb(121, 80, 14)']
        ]){
          await page.locator('#ach-fpm-auto-refresh').click();
          await resolveLatest(page,'fpm_auto_manage',{...automatic,last_state});
          const feedback=page.locator('#ach-fpm-auto-status');
          assert.equal(await feedback.getAttribute('data-tone'),expected);
          assert.equal(await feedback.evaluate(el=>getComputedStyle(el).color),color);
          assert.equal(await page.locator('#ach-fpm-auto-disable').isEnabled(),true);
        }
        await page.locator('[data-php-task="restore"]').click();
        await page.locator('#ach-fpm-recovery-version').selectOption('85');
        const values={'pm.max_children':50,'pm.start_servers':5,'pm.min_spare_servers':5,
          'pm.max_spare_servers':20,'pm.max_requests':0};
        await page.locator('#ach-fpm-check-recovery').click();
        await resolveLatest(page,'fpm_recovery',{status:true,version:'85',state:'Applied',
          phase:'applied',operation_id:'d'.repeat(32),safe_rollback_file_match:true,
          baseline_sha256:'a'.repeat(64),applied_sha256:'b'.repeat(64),observed_sha256:'b'.repeat(64),
          impact_sha256:'c'.repeat(64),recovery_decision_sha256:'f'.repeat(64),
          shared_impact:{schema:1,scope:'shared_service',state:'File Mapping',version:'85',
            matched_sites:[{id:7,site_key:site.name}],unresolved_sites:[],site_count:1,
            other_php_sites_count:0,dependency_sha256:'e'.repeat(64),manual_apply_eligible:true,
            reason:'',note:'File mapping only'},warning:'Shared service impact',
          baseline_values:values,observed_values:{...values,'pm.max_children':80}});
        await page.locator('#ach-fpm-rollback-approval').check();
        await page.locator('#ach-fpm-rollback').click();
        const recovery=page.locator('#ach-fpm-recovery-status');
        assert.equal(await recovery.getAttribute('data-tone'),'neutral');
        await resolveLatest(page,'fpm_rollback',{status:true,state:'Rolled Back',
          operation_id:'d'.repeat(32),restored_sha256:'a'.repeat(64),
          audit_logged:true,activity_logged:true});
        assert.equal(await recovery.getAttribute('data-tone'),'observed');
        await page.locator('#ach-fpm-check-recovery').click();
        assert.equal(await recovery.getAttribute('data-tone'),'neutral');
        assert.doesNotMatch(await recovery.innerText(),/Rolled Back/);
        await resolveLatest(page,'fpm_recovery',{status:true});
        assert.equal(await recovery.getAttribute('data-tone'),'error');
        await openDestination(page,'status');
        await resolveLatest(page,'status_preferences',prefs);
        await page.locator('#ach-status-scope').selectOption('site');
        await resolveLatest(page,'status_sites',{...inventory,purpose:'status_site_selection'});
        await page.locator('#ach-status-site-id').selectOption('7');
        await resolveLatest(page,'status_preferences',prefs);
        await page.locator('#ach-status-template').selectOption('404');
        await page.locator('[data-status-mode="site"]').click();
        await page.locator('#ach-status-delivery').selectOption('file');
        await page.locator('#ach-status-probe-button').click();
        await resolveLatest(page,'status_probe',{status:true,schema:1,site_id:7,
          site_key:site.name,verified_site_snapshot:JSON.stringify([7,site.name,site.document_root,
            '1',[[site.name,80]]]),template:'404',locale:'en',scope:'loopback_http_80',
          state:'HTTP Match',reason:'Exact selected render',read_only:true,
          apply_supported:false,nginx_runtime_verified:false,revision:2,http_status:404,
          http_404_observed:true,body_sha256:'a'.repeat(64),body_bytes:50,
          page_file_sha256:'a'.repeat(64),rendered_sha256:'a'.repeat(64),
          body_matches_file:true,body_matches_render:true,note:'HTTP observation only'});
        const probe=page.locator('#ach-status-probe-result');
        assert.equal(await probe.getAttribute('data-tone'),'observed');
        await page.locator('#ach-status-manage-recheck').click();
        assert.equal(await probe.getAttribute('data-tone'),'neutral');
        assert.match(await probe.innerText(),/historical/);
        await resolveLatest(page,'status_manage',{status:false,stage:'status_manage',msg:'Unconfirmed source'});
        assert.equal(await probe.getAttribute('data-tone'),'neutral');
        assert.equal(await page.locator('#ach-status-manage-result').getAttribute('data-tone'),'error');
        assert.deepEqual(pageErrors,[]);
        console.log('FEEDBACK_BROWSER_PASS',width);
      } finally { await page.close(); }
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
