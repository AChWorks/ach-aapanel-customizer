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
      const bb=b.getBoundingClientRect(),rr=r.getBoundingClientRect(),
        control=el.querySelector('button')||el, cr=control.getBoundingClientRect(),
        pane=el.closest('.ach-main').getBoundingClientRect(),style=getComputedStyle(b);
      const visibleTop=Math.max(cr.top,pane.top),visibleBottom=Math.min(cr.bottom,pane.bottom);
      const gap=b.dataset.placement==='below'?bb.top-visibleBottom:visibleTop-bb.bottom;
      return {description:desc?.textContent,tooltip:b.textContent,
        fits:bb.left>=pane.left+8&&bb.right<=pane.right-8&&bb.top>=rr.top+8&&bb.bottom<=rr.bottom-8,
        gap,arrow:bb.left+parseFloat(b.style.getPropertyValue('--ach-help-arrow')),
        targetLeft:Math.max(cr.left,pane.left),targetRight:Math.min(cr.right,pane.right),
        background:style.backgroundColor,weight:style.fontWeight,placement:b.dataset.placement};
    });
    assert.equal(state.description,state.tooltip);
    assert.ok(state.fits,JSON.stringify(state));
    assert.ok(Math.abs(state.gap-8)<=1,JSON.stringify(state));
    assert.ok(state.arrow>=state.targetLeft-1&&state.arrow<=state.targetRight+1,JSON.stringify(state));
    assert.equal(state.background,'rgb(255, 255, 255)');
    assert.equal(state.weight,'400');
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
    assert.equal(await bubble.isVisible(),false,'clicking enabled Recheck must not show help');
    assert.equal(await button(read).getAttribute('aria-busy'),'true');
    assert.equal(await button(read).getAttribute('data-ach-action-pending'),'');
    assert.equal(await button(apply).getAttribute('aria-busy'),null,'only initiating action is busy');
    await anchor(read).focus();
    assert.equal(await bubble.isVisible(),false,'busy control cannot show eligibility help even on explicit focus');
    await explain(apply,/in progress/,method);
    await resolveLatest(page,'wp_settings_manage',reply('Already Configured',{
      reason:'WordPress URLs already use HTTPS',
      urls_before:{home:'https://demo.test',siteurl:'https://demo.test'}
    }));
    assert.match(await bubble.innerText(),/already has the requested value/);
    assert.equal(await button(read).getAttribute('aria-busy'),null);
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
    assert.equal(await bubble.isVisible(),false,'click-induced Apply disable must not open help');
    assert.equal(await button(apply).getAttribute('aria-busy'),'true');
    assert.equal(await count(),original+1);
    const req=await lastRequest(page,'wp_settings_manage');
    assert.equal(req.data.settings_action,'apply');
    assert.equal(req.data.expected_source_sha256,'a'.repeat(64));
    assert.equal(req.data.approved,'true');
    // The intercepted mock reports a failed write; never retry without Recheck.
    await resolveLatest(page,'wp_settings_manage',{status:false,stage:'wp_settings_manage',msg:'fixture refusal',operation_id:'e'.repeat(32)});
    assert.equal(await bubble.isVisible(),false,'failed Apply settling under stationary pointer stays quiet');
    assert.equal(await button(apply).getAttribute('aria-busy'),null);
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
      assert.equal(await button(save).getAttribute('aria-busy'),'true');
      await anchor(save).focus();
      assert.equal(await bubble.isVisible(),false,'pending Save uses progress, not disabled help');
      assert.match(await anchor(save).evaluate(el=>document.getElementById(el.getAttribute('aria-describedby')).textContent),/Operation in progress/);
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
      assert.equal(await button(save).getAttribute('aria-busy'),null);
      assert.equal(await bubble.isVisible(),false,'settlement does not open disabled help');
      // A subsequent deliberate keyboard action reveals the current reason.
      await anchor(save).press('Enter');
      assert.ok(await bubble.isVisible());
      assert.match(await bubble.innerText(),expected);
      assert.equal(await bubble.innerText(),await anchor(save).evaluate(el=>
        document.getElementById(el.getAttribute('aria-describedby')).textContent));
      if(outcome!=='refusal') {
        assert.equal(await preview.getAttribute('aria-busy'),'true','independent Preview still running after Save settles');
        await resolveLatest(page,'preview_php_fpm',phpPreview(v));
        assert.equal(await preview.getAttribute('aria-busy'),null);
      }
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
// Exercise the actual shared request bindings beyond the detailed semantic
// cases above. All responses here are intercepted; no backend writer runs.
async function progressWalk(browser,width,height,touch){
  const {page,pageErrors}=await realPage(browser,width,height,touch?{hasTouch:true,isMobile:true}:{});
  const q=id=>page.locator('#'+id), bubble=page.locator('.ach-disabled-bubble');
  const route=selector=>page.locator(selector).click();
  const emptyActivity={status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]};
  const aliases={status:true,schema:1,read_only:true,state:'Aliases Found',hosts_sha256:'a'.repeat(64),
    entries:[{domain:'demo.test',address:'127.0.0.1',line:7}]};
  const checks=[];
  async function run(id,method,response,options={}){
    const control=q(id);
    await control.scrollIntoViewIfNeeded();
    assert.ok(await control.isEnabled(),id+' precondition');
    const label=await control.innerText();
    const before=await page.evaluate(()=>window.__qaRequests.length);
    if(options.keyboard)await control.press('Enter');
    else if(touch)await control.tap();
    else await control.click();
    assert.equal(await page.evaluate(()=>window.__qaRequests.length),before+1,id+' exact dispatch');
    assert.equal(await control.getAttribute('aria-busy'),'true',id);
    assert.equal(await control.innerText(),label,id+' stable label');
    assert.equal(await bubble.isVisible(),false,id+' no unsolicited help');
    assert.equal(await page.locator('button[data-ach-action-pending],input[data-ach-action-pending]').count(),1,id);
    const pending=await control.evaluate(el=>{
      const style=getComputedStyle(el,'::before'),rect=el.getBoundingClientRect(),
        pane=el.closest('.ach-main').getBoundingClientRect();
      return {spinner:style.content==='""'&&style.animationName==='ach-action-spin',
        fits:rect.left>=pane.left-1&&rect.right<=pane.right+1};
    });
    assert.ok(pending.spinner&&pending.fits,id+' '+JSON.stringify(pending));
    if(response===undefined)await rejectLatest(page,method,'timeout');
    else await resolveLatest(page,method,response);
    assert.equal(await control.getAttribute('aria-busy'),null,id+' settled');
    assert.equal(await bubble.isVisible(),false,id+' no settlement popup');
    checks.push(id);
  }
  try{
    await resolveLatest(page,'get_overview',monitor);
    await run('ach-overview-refresh','get_overview',monitor,{keyboard:!touch});
    await page.locator('.ach-home-advanced summary').click();
    const checkbox=q('ach-fpm-enabled');
    await checkbox.click();
    assert.equal(await checkbox.getAttribute('aria-busy'),'true');
    assert.equal(await q('ach-monitor-enabled').getAttribute('aria-busy'),null);
    assert.equal(await bubble.isVisible(),false);
    assert.equal(await checkbox.locator('..').evaluate(el=>getComputedStyle(el,'::after').animationName),'ach-action-spin');
    const off={...monitor,state_revision:1,changed:true,modules_enabled:{...monitor.modules_enabled,php_fpm_file_preview:false}};
    await resolveLatest(page,'set_control',off);
    assert.equal(await checkbox.getAttribute('aria-busy'),null);
    await checkbox.click();
    await resolveLatest(page,'set_control',{...monitor,state_revision:2,changed:true});
    assert.equal(await bubble.isVisible(),false);
    checks.push('ach-fpm-enabled');
    await openDestination(page,'websites');
    assert.equal(await page.locator('[data-ach-action-pending]').count(),0,'automatic route loading is not a clicked action');
    await resolveLatest(page,'get_sites',inventory);
    await q('ach-hosts-site-id').selectOption('7');
    // Reproduce the Owner's exact screenshot context, including hover transfer
    // across the gap, above/below choice, and keyboard dismissal.
    const disabled=q('ach-site-changes-save-selected'),anchor=disabled.locator('..');
    await anchor.scrollIntoViewIfNeeded();
    if(touch)await anchor.tap();else{
      await page.mouse.move(2,2);
      await anchor.hover();
    }
    assert.equal(await bubble.isVisible(),true);
    if(!touch){
      const r=await bubble.boundingBox();
      await page.mouse.move(r.x+r.width/2,r.y+r.height/2,{steps:12});
      assert.equal(await bubble.isVisible(),true,'hover bridge is traversable');
    }
    await page.keyboard.press('Escape');
    assert.equal(await bubble.isVisible(),false);
    await run('ach-site-changes-compare','compare_site_changes',undefined,{keyboard:!touch});
    await run('ach-sites-refresh','get_sites',inventory);
    await q('ach-hosts-site-id').selectOption('7');
    await route('[data-task=protection]');
    await run('ach-guard-preview','manage_nginx_protection',protection('guard','Unmanaged'));
    await route('[data-task=cache]');
    await route('[data-cache-task=inspect]');
    await run('ach-cache-inspect-button','inspect_fastcgi_cache');
    await page.getByText('Advanced: privacy probes and policy reference',{exact:true}).click();
    await run('ach-cache-private-probe-button','probe_private_cache');
    await run('ach-cache-woo-probe-button','probe_private_cache');
    await run('ach-cache-plan-button','preview_cache_safety');
    await route('[data-cache-task=connect]');
    await run('ach-wp-cache-inspect','manage_wordpress_cache');
    await route('[data-cache-task=configure]');
    await run('ach-cache-activation-preview','preview_cache_activation');
    await run('ach-cache-activation-recheck','manage_cache_policy');
    await route('[data-cache-task=bridge]');
    await run('ach-bridge-inspect','manage_cache_policy');
    await route('[data-task=wordpress]');
    await route('[data-wp-task=https]');
    await run('ach-wp-settings-recheck','wp_settings_manage',reply('Already Configured'));
    await route('[data-task=routing]');
    await route('[data-routing-detail=diagnostics]');
    await run('ach-vhost-inspect-button','inspect_native_vhost');
    await run('ach-nginx-candidate-button','inspect_nginx_candidate');
    await route('[data-routing-detail=hosts]');
    await run('ach-hosts-inspect-button','inspect_local_hosts');
    await route('[data-routing-detail=reconcile]');
    await run('ach-reconcile-button','inspect_site_reconciliation');
    await openDestination(page,'server');
    await resolveLatest(page,'get_php_versions',phpInventory);
    await run('ach-php-discover','get_php_versions',phpInventory);
    await q('ach-php-version').selectOption('85');
    await run('ach-php-runtime-check','inspect_php_runtime');
    await route('[data-php-task=policy]');
    await run('ach-fpm-policy-load','fpm_policy_get');
    await run('ach-fpm-policy-recheck','fpm_policy_recheck');
    for(const [id,value] of [['ach-max-children','50'],['ach-start-servers','5'],
      ['ach-min-spare','5'],['ach-max-spare','20'],['ach-max-requests','0']])await q(id).fill(value);
    const preview=page.locator('#ach-php-form button[type=submit]');
    // Two intentionally repeatable read-only Previews, settled out of order.
    await preview.click();await preview.click();
    assert.ok(await preview.isEnabled());
    assert.equal(await preview.getAttribute('aria-busy'),'true');
    assert.equal(await bubble.isVisible(),false);
    await resolveLatest(page,'preview_php_fpm',phpPreview('85'));
    assert.equal(await preview.getAttribute('aria-busy'),'true','first outstanding read still pending');
    await page.evaluate(body=>{
      const reqs=window.__qaRequests.filter(r=>new URL(r.options.url,location.href).searchParams.get('s')==='preview_php_fpm');
      reqs.at(-2).resolve(body);
    },phpPreview('85'));
    assert.equal(await preview.getAttribute('aria-busy'),null);
    checks.push('PHP repeatable Preview');
    await route('[data-server-task=hosts]');
    await resolveLatest(page,'inspect_hosts_aliases',aliases);
    await run('ach-hosts-alias-refresh','inspect_hosts_aliases',aliases);
    await route('[data-server-task=attack]');
    await q('ach-hosts-site-id').selectOption('7');
    await run('ach-scan-preview','manage_abusive_scan',protection('scan','Unmanaged'));
    await run('ach-scan-orphan-list','manage_abusive_scan');
    await route('[data-server-task=http]');
    await resolveLatest(page,'status_preferences',prefs);
    await q('ach-status-template').selectOption('unbound');
    await run('ach-status-unbound-recheck','status_unbound',unbound('Restored'));
    await run('ach-status-tls-recheck','status_tls');
    await openDestination(page,'status');
    await route('[data-status-mode=design]');
    await run('ach-status-load','status_preferences',prefs);
    await run('ach-status-preview-button','status_preview');
    await openDestination(page,'activity');
    await resolveLatest(page,'get_activity',emptyActivity);
    await run('ach-activity-refresh','get_activity',emptyActivity);
    assert.deepEqual(pageErrors,[]);
    assert.equal(await page.locator('[data-ach-action-pending]').count(),0);
    console.log('OF34_PROGRESS_PASS',width,height,checks.length,checks.join(','));
  }finally{await page.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath(),args:['--no-sandbox','--disable-dev-shm-usage']});
  try{
    if (!process.env.ACH_PROGRESS_ONLY) {
      await walk(browser,1280,720,false);
      await walk(browser,320,480,false);
      await walk(browser,390,844,true);
    }
    await progressWalk(browser,1280,720,false);
    await progressWalk(browser,390,844,true);
  }finally{await browser.close();}
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
