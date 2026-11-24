'use strict';
// Real bundled DOM, pinned native jQuery, intercepted AJAX. No live writes.
const assert=require('node:assert/strict');
const {chromium,site,realPage,resolveLatest,lastRequest,openDestination}=require('./native_browser_fixture.cjs');
const version=require('../../plugin/ach_customizer/info.json').versions;
const monitor={status:true,mode:'Monitor',worker_source_version:version,notice:'Read-only Monitor controls',enforcement:false,state_schema:1,state_revision:0,overall_enabled:true,modules_enabled:{site_inventory:true,php_fpm_file_preview:true}};
const inventory={status:true,inventory_schema:2,page:1,page_size:25,has_more:false,sites:[site]};
const reply=(state='Source Ready',extra={})=>({
  status:true,schema:1,site_id:7,site_key:site.name,settings_action:'recheck',kind:'https',state,
  source_sha256:'a'.repeat(64),recovery_id:state==='Applied'?'c'.repeat(32):null,
  changed:false,read_only:true,runtime_verified:false,interval:null,reason:'',
  impact:'Selected WordPress home/siteurl database options only; converts HTTP to HTTPS, no DNS/Nginx/certificate changes',
  urls_before:{home:'http://demo.test',siteurl:'http://demo.test'},
  urls_target:{home:'https://demo.test',siteurl:'https://demo.test'},request_id:'d'.repeat(32),...extra
});
async function walk(browser,width,height,touch){
  const {page,pageErrors}=await realPage(browser,width,height,touch?{hasTouch:true,isMobile:true}:{});
  const bubble=page.locator('.ach-disabled-bubble');
  const button=id=>page.locator('#'+id);
  const anchor=id=>button(id).locator('..');
  async function explain(id,pattern,method){
    const control=button(id),holder=anchor(id);
    assert.equal(await control.isDisabled(),true);
    await holder.scrollIntoViewIfNeeded();
    if(method==='touch')await holder.tap();
    else if(method==='hover'){await page.mouse.move(2,2);await holder.hover();}
    else await holder.focus();
    assert.equal(await bubble.isVisible(),true,id+' bubble');
    assert.match(await bubble.innerText(),pattern);
    const state=await holder.evaluate(el=>{
      const desc=document.getElementById(el.getAttribute('aria-describedby'));
      const b=document.querySelector('.ach-disabled-bubble'),r=document.getElementById('ach-customizer');
      const bb=b.getBoundingClientRect(),rr=r.getBoundingClientRect();
      return {description:desc?.textContent,tooltip:b.textContent,
        fits:bb.left>=rr.left&&bb.right<=rr.right+1&&bb.top>=rr.top&&bb.bottom<=rr.bottom+1};
    });
    assert.equal(state.description,state.tooltip);
    assert.ok(state.fits,JSON.stringify(state));
  }
  const method=touch?'touch':'hover';
  const count=()=>page.evaluate(()=>window.__qaRequests.length);
  const apply='ach-wp-settings-apply',restore='ach-wp-settings-restore',read='ach-wp-settings-recheck';
  try{
    await resolveLatest(page,'get_overview',monitor);
    await openDestination(page,'websites');
    await resolveLatest(page,'get_sites',inventory);
    await explain('ach-prev',/first website page/,method);
    await page.keyboard.press('Escape');
    assert.equal(await bubble.isVisible(),false);
    await button('ach-hosts-site-id').selectOption('7');
    await page.locator('[data-task=wordpress]').click();
    await page.locator('[data-wp-task=https]').click();
    await explain(apply,/fresh Source Ready or Restored/,method);
    const before=await count();
    if(touch) await anchor(apply).tap(); else await anchor(apply).click();
    await page.keyboard.press('Enter');
    assert.equal(await count(),before,'disabled help must not dispatch any request');
    await page.keyboard.press('Escape');
    assert.equal(await bubble.isVisible(),false);
    // Leaving the native dialog and returning to the very same coordinates
    // is physical pointer movement, not a synthetic layout re-entry.
    if(!touch){
      await button(read).focus();
      await page.mouse.move(2,2);
      await anchor(apply).hover();
      assert.equal(await bubble.isVisible(),true,'hover re-entry after Escape outside dialog');
      await page.keyboard.press('Escape');
      assert.equal(await bubble.isVisible(),false);
    }
    await explain(restore,/matching saved Applied or Recovery Required/,'focus');
    await page.keyboard.press('Escape');
    assert.equal(await bubble.isVisible(),false);
    await button(read).click();
    await explain(apply,/in progress/,method);
    await resolveLatest(page,'wp_settings_manage',reply('Already Configured',{
      reason:'WordPress URLs already use HTTPS',
      urls_before:{home:'https://demo.test',siteurl:'https://demo.test'}
    }));
    assert.match(await bubble.innerText(),/already has the requested value/);
    await explain(restore,/No matching recoverable saved change/,method);
    await button(read).click();
    await resolveLatest(page,'wp_settings_manage',reply('Needs Review',{reason:'Native source is not verifiable'}));
    await explain(apply,/Needs Review: Native source is not verifiable/,method);
    await button(read).click();
    await resolveLatest(page,'wp_settings_manage',{status:true,schema:999});
    await explain(apply,/previous operation was not confirmed/,method);
    await button(read).click();
    await explain(apply,/in progress/,'focus');
    await resolveLatest(page,'wp_settings_manage',reply());
    assert.equal(await button(apply).isEnabled(),true);
    assert.equal(await button(apply).evaluate(el=>el.closest('.ach-disabled-anchor')===null && document.activeElement===el),true);
    assert.equal(await bubble.isVisible(),false);
    const original=await count();
    await button(apply).click();
    assert.equal(await count(),original+1);
    const req=await lastRequest(page,'wp_settings_manage');
    assert.equal(req.data.settings_action,'apply');
    assert.equal(req.data.expected_source_sha256,'a'.repeat(64));
    assert.equal(req.data.approved,'true');
    // The intercepted mock reports a failed write; never retry without Recheck.
    await resolveLatest(page,'wp_settings_manage',{status:false,stage:'wp_settings_manage',msg:'fixture refusal',operation_id:'e'.repeat(32)});
    await explain(apply,/previous operation was not confirmed/,method);
    await button(read).click();
    await resolveLatest(page,'wp_settings_manage',reply('Applied'));
    assert.equal(await button(restore).isEnabled(),true);
    await explain(apply,/saved change exists/,method);
    await page.locator('[data-wp-task=cron]').click();
    assert.equal(await bubble.isVisible(),false);
    assert.equal(await button(restore).isDisabled(),true);
    await button('ach-wp-settings-interval').fill('0');
    await explain(apply,/valid WordPress setting/,method);
    await page.locator('[data-task=protection]').click();
    assert.equal(await bubble.isVisible(),false);
    await explain('ach-guard-apply',/fresh Unmanaged\/Restored/,method);
    await button('ach-guard-preview').click();
    await resolveLatest(page,'manage_nginx_protection',{status:false,stage:'nginx_guard_manage',reason_code:'unsupported_guard_ruleset',msg:'Unsupported native security recovery ruleset; journal preserved.',operation_id:'f'.repeat(32)});
    await explain('ach-guard-restore',/cannot restore the retained journal/,method);
    await page.keyboard.press('Escape');
    assert.equal(await bubble.isVisible(),false);
    assert.deepEqual(pageErrors,[]);
    console.log('DISABLED_HELP_PASS',width,height,touch?'touch':'pointer + keyboard');
  }finally{await page.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath(),args:['--no-sandbox','--disable-dev-shm-usage']});
  try{
    await walk(browser,1280,720,false);
    await walk(browser,320,480,false);
    await walk(browser,390,844,true);
  }finally{await browser.close();}
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
