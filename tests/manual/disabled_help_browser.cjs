'use strict';
// Real bundled DOM, pinned native jQuery, intercepted AJAX. No live writes.
const assert=require('node:assert/strict');
const {chromium,site,prefs,realPage,resolveLatest,lastRequest,openDestination}=require('./native_browser_fixture.cjs');
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
const protection=(family,state,extra={})=>({
  status:true,schema:1,site_id:7,site_key:site.name,state,reason:'Verified existing native source',
  read_only:true,changed:false,runtime_verified:['Applied','Restored'].includes(state),
  recovery_id:['Applied','Recovery Required','Restored'].includes(state)?'a'.repeat(32):null,
  journal_phase:({Applied:'applied','Recovery Required':'prepared',Restored:'restored'})[state]||null,
  vhost_sha256:'b'.repeat(64),
  ...(family==='guard'?{
    mode:'native_site_sensitive_paths',site_root:site.document_root,
    ruleset:'site-sensitive-files-v1',block_xmlrpc:false,automatic_enforcement:false,
    proposal_sha256:'c'.repeat(64)
  }:{
    mode:'native_site_abusive_scan_fail2ban',ruleset:'sensitive-scan-combined-v1',
    firewall_scope:'origin_wide_web_ports',log_scope:'selected_native_site',
    plan_sha256:'c'.repeat(64),log_path:'/www/wwwlogs/demo.test.log'
  }),...extra
});
const phpInventory={status:true,schema:1,state:'Observed',read_only:true,runtime_verified:false,
  versions:['81','85'].map(v=>({code:v,label:'PHP '+v[0]+'.'+v[1],state:'File Preview Candidate',
    binary_present:true,config_present:true,preview_candidate:true,manual_apply_adapter:'guarded_php'+v,
    apply_eligible:false,reason:'Prepare required'})),reason:'',note:'File-only inventory'};
const phpPreview=(v,revision=0)=>({
  status:true,state:'File Drift',scope:'shared_service',version:v,note:'Read-only file preview',
  source:'/www/server/php/'+v+'/etc/php-fpm.conf',
  changes:[{setting:'pm.max_children',desired:50,actual:80}],
  shared_impact:{schema:1,scope:'shared_service',state:'File Mapping',version:v,
    matched_sites:[{id:7,site_key:site.name}],unresolved_sites:[],site_count:1,
    other_php_sites_count:0,dependency_sha256:'e'.repeat(64),manual_apply_eligible:true,
    reason:'',note:'File mapping only'},
  fpm_observation_sha256:revision?'d'.repeat(64):'c'.repeat(64),
  fpm_saved_policy:{schema:1,version:v,policy_revision:revision,monitor_revision:revision,
    saved:false,desired:null,read_only:true,runtime_verified:false,auto_enforce:false,
    scope:'shared_service',pool:'www'}
});
const unbound=(state)=>({
  status:true,schema:1,mode:'native_http_unbound',unbound_action:'recheck',
  scope:'global',site_id:null,template:'unbound',locale:'en',revision:2,
  request_id:'a'.repeat(32),operation_id:'a'.repeat(32),
  state,source_sha256:'b'.repeat(64),rendered_sha256:'c'.repeat(64),
  recovery_id:['Applied','Recovery Required','Needs Review','Restored','Drift'].includes(state)?'d'.repeat(32):null,
  before_ipv4_status:state==='Conflict'?null:200,before_ipv6_status:state==='Conflict'?null:200,
  changed:false,read_only:true,runtime_verified:state==='Applied',
  impact:'Unknown HTTP Host on native HTTP/80 listeners only; no HTTPS or stopped-site change'
});
async function rejectLatest(page,method,status){
  await page.evaluate(({method,status})=>{
    const req=window.__qaRequests.filter(r=>new URL(r.options.url,location.href).searchParams.get('s')===method).at(-1);
    if(!req) throw Error('Missing request '+method);
    req.reject(status);
  },{method,status});
}
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
    // R135-03: reasons must distinguish validated native state, not just
    // provide a nonempty label. Exercise both preview-only and recovery paths.
    const semanticMethod=touch?'touch':'hover';
    for(const state of ['Applied','Recovery Required','Unmanaged']){
      await button('ach-guard-preview').click();
      await resolveLatest(page,'manage_nginx_protection',protection('guard',state));
      if(state==='Unmanaged') await explain('ach-guard-restore',/no active saved Guard protection operation/,semanticMethod);
      else{
        await explain('ach-guard-apply',state==='Applied'?/already Applied.*No Enable/:/Recovery Required.*Resolve the saved recovery/,semanticMethod);
        await explain('ach-guard-restore',/Recheck current protection.*Recovery ID/,'focus');
        await button('ach-guard-recheck').click();
        await resolveLatest(page,'manage_nginx_protection',protection('guard',state));
        assert.ok(await button('ach-guard-restore').isEnabled());
        assert.ok(await button('ach-guard-apply').isDisabled());
      }
    }
    await openDestination(page,'server');
    await resolveLatest(page,'get_php_versions',phpInventory);
    await page.locator('[data-server-task=attack]').click();
    await button('ach-hosts-site-id').selectOption('7');
    for(const state of ['Applied','Recovery Required','Unmanaged','Needs Review','Dependency Missing']){
      const reason=state==='Needs Review'?'Untrusted native access log':state==='Dependency Missing'?'Fail2ban dependency missing':'Verified source';
      await button('ach-scan-preview').click();
      await resolveLatest(page,'manage_abusive_scan',protection('scan',state,{reason}));
      if(state==='Unmanaged')await explain('ach-scan-restore',/no active saved Fail2ban scanner operation/,semanticMethod);
      else{
        await explain('ach-scan-apply',state==='Applied'?/already Applied.*No Enable/:
          state==='Recovery Required'?/Recovery Required.*Resolve the saved recovery/:
          new RegExp(reason),semanticMethod);
        await explain('ach-scan-restore',['Applied','Recovery Required'].includes(state)?/Recheck jail \/ recovery.*Recovery ID/:/No eligible matching recovery/,'focus');
        if(['Applied','Recovery Required'].includes(state)){
          await button('ach-scan-recheck').click();
          await resolveLatest(page,'manage_abusive_scan',protection('scan',state,{reason}));
          assert.ok(await button('ach-scan-restore').isEnabled());
        }
      }
    }
    await page.locator('[data-server-task=http]').click();
    await resolveLatest(page,'status_preferences',prefs);
    await button('ach-status-template').selectOption('unbound');
    for(const state of ['Conflict','Drift','Source Ready','Applied']){
      await button('ach-status-unbound-recheck').click();
      await resolveLatest(page,'status_unbound',unbound(state));
      await explain('ach-status-unbound-apply',({Conflict:/Conflict:.*ownership.*do not overwrite/,
        Drift:/Drift:.*assets remain/, 'Source Ready':/Current HTTP\/80 source ready.*tick/,Applied:/already Applied.*no Apply/})[state],semanticMethod);
      await explain('ach-status-unbound-restore',state==='Applied'?/Saved HTTP\/80 recovery confirmed/:
        state==='Source Ready'?/no active saved HTTP\/80 operation/:
        /No eligible saved HTTP\/80 recovery/,'focus');
      if(state==='Conflict'||state==='Drift'){
        const n=await count();
        await anchor('ach-status-unbound-apply').click();
        assert.equal(await count(),n);
      }
    }
    // R135-01/02: actual DOM keeps the open help synchronized with every
    // outcome; a late pre-settlement Preview must not grant fresh approval.
    await page.locator('[data-server-task=php]').click();
    await page.locator('[data-php-task=policy]').click();
    const selectVersion=async v=>button('ach-php-version').selectOption(v);
    await selectVersion('85');
    for(const [id,value] of [['ach-max-children','50'],['ach-start-servers','5'],
      ['ach-min-spare','5'],['ach-max-spare','20'],['ach-max-requests','0']]) await button(id).fill(value);
    const preview=page.locator('#ach-php-form button[type=submit]');
    const save='ach-fpm-policy-save';
    // Exercise all outcomes in the desktop; representative success on narrow
    // and touch viewports. The contract matrix covers all 36 order permutations.
    const cases=width===1280?['success','refusal','malformed','timeout','selection']:['success'];
    for(const outcome of cases){
      await selectVersion('85');
      await preview.click();
      await resolveLatest(page,'preview_php_fpm',phpPreview('85'));
      assert.ok(await button(save).isEnabled());
      await button(save).click();
      assert.ok(await button(save).isDisabled());
      const saveReq=await lastRequest(page,'fpm_policy_save');
      assert.equal(saveReq.data.expected_policy_revision,0);
      assert.equal(saveReq.data.expected_monitor_revision,0);
      assert.equal(saveReq.data.expected_observation_sha256,'c'.repeat(64));
      const v=outcome==='selection'?'81':'85';
      if(v!=='85')await selectVersion(v);
      await preview.click();
      if(outcome==='refusal')await resolveLatest(page,'preview_php_fpm',phpPreview(v));
      await explain(save,/Saving desired Monitor settings|in progress/,'focus');
      const expected=outcome==='success'||outcome==='selection'?/Save completed.*fresh Preview/:
        outcome==='refusal'?/Save rejected.*reload saved desired values.*fresh Preview/:
        /Save outcome unconfirmed.*Reconcile saved desired values.*fresh Preview/;
      if(outcome==='timeout')await rejectLatest(page,'fpm_policy_save','timeout');
      else await resolveLatest(page,'fpm_policy_save',outcome==='refusal'?{
        status:false,stage:'fpm_policy_save',msg:'Saved PHP policy changed',operation_id:'f'.repeat(32)
      }:outcome==='malformed'?{status:true,schema:999}:{
        status:true,schema:1,state:'Policy Saved',version:'85',scope:'shared_service',
        auto_enforce:false,runtime_verified:false,policy_revision:1,changed:true
      });
      assert.ok(await button(save).isDisabled());
      assert.ok(await bubble.isVisible(),'settlement updates already-open help');
      assert.match(await bubble.innerText(),expected);
      assert.equal(await bubble.innerText(),await anchor(save).evaluate(el=>
        document.getElementById(el.getAttribute('aria-describedby')).textContent));
      if(outcome!=='refusal')await resolveLatest(page,'preview_php_fpm',phpPreview(v));
      assert.ok(await button(save).isDisabled());
      assert.match(await bubble.innerText(),expected);
      assert.ok(await button('ach-fpm-prepare').isDisabled());
      if(outcome==='refusal')assert.match(await button('ach-fpm-policy-status').innerText(),/Operation ID: f{32}/);
      await preview.click();
      await resolveLatest(page,'preview_php_fpm',phpPreview(v,3));
      assert.ok(await button(save).isEnabled());
      assert.equal(await anchor(save).evaluate(el=>el.classList.contains('ach-disabled-anchor')),false);
      // Fresh source must carry its own observed policy/Monitor revision.
      await button(save).click();
      const next=await lastRequest(page,'fpm_policy_save');
      assert.equal(next.data.php_version,v);
      assert.equal(next.data.expected_policy_revision,3);
      assert.equal(next.data.expected_monitor_revision,3);
      assert.equal(next.data.expected_observation_sha256,'d'.repeat(64));
      await resolveLatest(page,'fpm_policy_save',{status:false,stage:'fpm_policy_save',msg:'Fixture only',operation_id:'f'.repeat(32)});
    }
    assert.deepEqual(pageErrors,[]);
    console.log('DISABLED_HELP_PASS',width,height,touch?'touch':'pointer + keyboard');
    console.log('R135_SEMANTIC_HELP_PASS',width,height,cases.join(','));
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
