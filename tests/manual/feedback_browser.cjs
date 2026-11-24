'use strict';
// Real Chromium + the shipped plugin DOM and pinned native jQuery.
// Backend replies are mocked, so this verifies UX, not live server changes.
const assert = require('node:assert/strict');
const {chromium,site,realPage,resolveLatest,lastRequest,openDestination} = require('./native_browser_fixture.cjs');
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
        await page.locator('#ach-hosts-site-id').selectOption('8');
        await tone('neutral');
        assert.doesNotMatch(await result.innerText(),/WordPress Cache: Connected/);
        assert.equal(await connect.isEnabled(),true);
        assert.deepEqual(pageErrors,[]);
        console.log('FEEDBACK_BROWSER_PASS',width);
      } finally { await page.close(); }
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
