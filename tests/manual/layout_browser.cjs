'use strict';

// Real shipped task navigation in isolated Chromium, with mocked native reads.
// No aaPanel credentials, remote requests, real writes or installed-VM claims.
// See native_browser_fixture.cjs for the pinned aaPanel jQuery requirement.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const version=require('../../plugin/ach_customizer/info.json').versions;
const {chromium,brand,prefs,site,realPage,resolveLatest,openDestination} =
  require('./native_browser_fixture.cjs');

const monitor=(worker_source_version)=>({status:true,mode:'Monitor',worker_source_version,
  notice:'Read-only Monitor controls',enforcement:false,state_schema:1,state_revision:0,
  overall_enabled:true,modules_enabled:{site_inventory:true,php_fpm_file_preview:true}});
const inventory={status:true,inventory_schema:2,page:1,page_size:25,has_more:false,sites:[site]};
const viewports=[[320,480],[375,650],[480,720],[720,650],[800,720],[1024,768],[1280,720]];
const widths=process.env.ACH_QA_WIDTHS ?
  viewports.filter(([w])=>process.env.ACH_QA_WIDTHS.split(',').includes(String(w))) : viewports;
assert.ok(widths.length,'At least one supported QA viewport is required');

async function geometry(page, label) {
  const result=await page.evaluate(()=>{
    const root=document.getElementById('ach-customizer');
    const main=document.getElementById('ach-content');
    const layer=root.closest('.layui-layer');
    const rect=layer.getBoundingClientRect(), edge=main.getBoundingClientRect();
    const visible=el=>el.getClientRects().length>0 && el.getBoundingClientRect().width>0 &&
      el.getBoundingClientRect().height>0;
    const overflows=[...main.querySelectorAll('*')].filter(el=>visible(el) &&
      !el.closest('.ach-scroll, .ach-preview-viewport') && el.getBoundingClientRect().right>edge.right+1)
      .map(el=>({id:el.id,tag:el.tagName,cls:el.className.toString().slice(0,70)})).slice(0,10);
    const rows=[];
    for(const row of main.querySelectorAll('.ach-controls')){
      if(!visible(row)) continue;
      const fields=[...row.querySelectorAll(':scope > .ach-inline-field')].filter(visible)
        .map(outer=>({outer,control:outer.querySelector('select,input:not([type="checkbox"])')}))
        .filter(x=>x.control && visible(x.control));
      const children=[...fields.map(x=>({...x,type:'field'})),
        ...[...row.querySelectorAll(':scope > button')].filter(visible)
          .map(control=>({outer:control,control,type:'button'}))];
      for(let i=0;i<children.length;i++)for(let j=i+1;j<children.length;j++){
        const a=children[i],b=children[j];
        if(a.type==='button'&&b.type==='button')continue;
        const aa=a.outer.getBoundingClientRect(),bb=b.outer.getBoundingClientRect();
        if(Math.min(aa.bottom,bb.bottom)<=Math.max(aa.top,bb.top)+1)continue;
        rows.push({a:a.control.id,b:b.control.id,
          delta:Math.abs(a.control.getBoundingClientRect().bottom-b.control.getBoundingClientRect().bottom)});
      }
    }
    return {
      docOverflow:document.documentElement.scrollWidth>innerWidth+1,
      overflow:main.scrollWidth>main.clientWidth+1,
      rootOverflow:root.scrollWidth>root.clientWidth+1,
      overflows, rows,
      layerFits:rect.left>=0&&rect.top>=0&&rect.right<=innerWidth+1&&rect.bottom<=innerHeight+1,
      rootHeight:root.getBoundingClientRect().height,mainHeight:edge.height,
      scrollMode:getComputedStyle(main).overflowY,
      active:[...root.querySelectorAll('[data-destination][aria-current="page"]')].map(x=>x.dataset.destination),
      visibleViews:[...root.querySelectorAll('[data-view]')].filter(visible).map(x=>x.dataset.view),
      clippedControls:[...main.querySelectorAll('button,input:not([type="checkbox"]),select')]
        .filter(el=>visible(el)&&!el.closest('.ach-scroll') &&
          (el.getBoundingClientRect().left<edge.left-1||el.getBoundingClientRect().right>edge.right+1))
        .map(el=>el.id||el.textContent.trim()).slice(0,10)
    };
  });
  assert.ok(result.layerFits && result.rootHeight>170 && result.mainHeight>100 &&
    result.scrollMode==='auto' && result.active.length===1 && result.visibleViews.length<=1 &&
    !result.docOverflow && !result.rootOverflow && !result.overflow &&
    !result.clippedControls.length, label+' '+JSON.stringify(result));
  assert.deepEqual(result.rows.filter(x=>x.delta>1.5),[],label+' mixed control bottoms');
  return result.rows;
}

async function clickStage(page, attr, value) {
  const button=page.locator('['+attr+'="'+value+'"]');
  await button.click();
  assert.equal(await button.getAttribute('aria-current'),'page',attr+' '+value);
}
async function selectStatusSite(page) {
  await page.locator('#ach-status-scope').selectOption('site');
  await resolveLatest(page,'status_sites',{...inventory,purpose:'status_site_selection'});
  await page.locator('#ach-status-site-id').selectOption('7');
  await resolveLatest(page,'status_preferences',prefs);
}
async function walk(page, width, record) {
  const sample=async(name)=>record(name,await geometry(page,width+' / '+name));
  await sample('home pending');
  await resolveLatest(page,'get_overview',monitor(version));
  assert.equal(await page.locator('#ach-worker-version-status').getAttribute('data-state'),'matched');
  await sample('home matched');
  if(width<=720){
    await page.locator('#ach-menu-toggle').click();
    await page.locator('[data-destination="server"]').focus();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#ach-menu-toggle').getAttribute('aria-expanded'),'false');
    assert.equal(await page.locator('#ach-menu-toggle').evaluate(el=>document.activeElement===el),true);
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  await openDestination(page,'websites');
  assert.equal(await page.locator('#ach-worker-version-status').isVisible(),false);
  assert.equal(await page.locator('#ach-sites-loading').isVisible(),true);
  assert.equal(await page.locator('#ach-sites-rows').isVisible(),false);
  assert.equal(await page.locator('#ach-sites-loading .ach-skeleton-row span').first()
    .evaluate(el=>getComputedStyle(el).animationName),'none');
  await resolveLatest(page,'get_sites',inventory);
  await page.emulateMedia({reducedMotion:'no-preference'});
  await sample('website summary');
  await clickStage(page,'data-task','protection');
  assert.equal(await page.locator('#ach-site-required').isVisible(),true);
  assert.equal(await page.locator('#ach-guard-apply').isVisible(),false);
  const browse = page.getByRole('button',{name:'Browse websites',exact:true});
  const website = page.locator('#ach-hosts-site-id');
  async function checkWebsiteContext(expected, missing){
    assert.equal(await browse.count(),1,'Exactly one visible Browse websites action');
    assert.equal(await page.locator('#ach-website-error-pages').isVisible(),true);
    assert.equal(await website.inputValue(),expected,'No automatic website selection');
    assert.equal(await page.locator('#ach-site-required').isVisible(),missing);
  }
  await checkWebsiteContext('',true);
  await sample('choose website');
  await browse.click();
  assert.equal(await page.locator('[data-task="summary"]').getAttribute('aria-current'),'page');
  await clickStage(page,'data-task','protection');
  await checkWebsiteContext('',true);
  await website.selectOption('7');
  await checkWebsiteContext('7',false);
  assert.equal(await page.locator('#ach-guard-preview').isEnabled(),true);
  assert.equal(await page.locator('#ach-guard-apply').isEnabled(),false);
  await sample('protection');
  const checkboxGeometry=await page.locator('.ach-guard-option').evaluate(label=>{
    const input=label.querySelector('input'),copy=label.querySelector('.ach-option-copy');
    const a=input.getBoundingClientRect(),b=copy.getBoundingClientRect();
    return {columns:getComputedStyle(label).display, gap:b.left-a.right,
      yDelta:a.top-b.top,labelHeight:label.getBoundingClientRect().height};
  });
  assert.equal(checkboxGeometry.columns,'grid');
  assert.ok(checkboxGeometry.gap>=6&&checkboxGeometry.gap<=12&&
    Math.abs(checkboxGeometry.yDelta)<=5&&checkboxGeometry.labelHeight>=28,
    JSON.stringify(checkboxGeometry));
  await page.locator('#ach-guard-preview').click();
  const refusal={status:false,stage:'nginx_guard_manage',reason_code:'unsupported_guard_ruleset',
    msg:'Unsupported native security recovery ruleset. Saved journal ach_customizer.nginx_security.7.json preserved. This version cannot verify or restore it; a server administrator must investigate the original rule and journal separately before further changes.',
    operation_id:'d'.repeat(32)};
  await resolveLatest(page,'manage_nginx_protection',refusal);
  const guardSummary=page.locator('#ach-guard-summary');
  assert.match(await guardSummary.innerText(),/Unsupported saved protection ruleset.*cannot verify or restore.*server administrator/);
  assert.equal(await guardSummary.getAttribute('data-tone'),'review');
  assert.equal(await page.locator('#ach-guard-apply').isEnabled(),false);
  assert.equal(await page.locator('#ach-guard-restore').isEnabled(),false);
  assert.match(await page.locator('#ach-guard-apply-why').innerText(),/cannot be verified/);
  assert.match(await page.locator('#ach-guard-restore-why').innerText(),/cannot restore/);
  await page.locator('#ach-guard-block-xmlrpc').check();
  const evidence=page.locator('#ach-guard-result');
  await evidence.locator('..').locator('summary').click();
  assert.match(await evidence.innerText(),/nginx_security\.7\.json/);
  assert.match(await evidence.innerText(),/Operation ID: d{32}/);
  assert.doesNotMatch(await evidence.innerText(),/Recovery ID:/i);
  await sample('protection unsupported ruleset');
  await clickStage(page,'data-task','cache');
  await clickStage(page,'data-task','protection');
  assert.match(await guardSummary.innerText(),/Unsupported saved protection ruleset/);
  await clickStage(page,'data-task','cache');
  for(const key of ['inspect','connect','configure','clear','bridge']){
    await clickStage(page,'data-cache-task',key);
    await sample('cache '+key);
  }
  await page.locator('#ach-bridge-recheck-route').click();
  assert.equal(await page.locator('[data-cache-task="configure"]').evaluate(el=>document.activeElement===el),true);
  await clickStage(page,'data-cache-task','clear');
  await page.locator('#ach-cache-clear-recheck-route').click();
  assert.equal(await page.locator('[data-cache-task="configure"]').evaluate(el=>document.activeElement===el),true);
  await clickStage(page,'data-task','wordpress');
  for(const key of ['debug','cron','xmlrpc','https']){
    await clickStage(page,'data-wp-task',key);
    assert.equal(await page.locator('#ach-wp-settings-apply').isEnabled(),false);
    assert.equal(await page.locator('p[data-wp-field="https"]').isVisible(),key==='https');
    await sample('wordpress '+key);
    if(key==='cron'){
      const composition=await page.locator('#ach-content').evaluate(main=>{
        main.scrollTop=0;
        const c=main.getBoundingClientRect(), context=main.querySelector('#ach-website-context');
        const b=main.querySelector('#ach-wp-settings-recheck').getBoundingClientRect();
        const bg=getComputedStyle(main.querySelector('#ach-wp-settings-recheck')).backgroundColor;
        const border=getComputedStyle(main.querySelector('#ach-wp-settings-interval')).borderTopColor;
        return {contextHeight:context.getBoundingClientRect().height,actionTop:b.top-c.top,
          actionBottom:b.bottom-c.top,visibleHeight:main.clientHeight,
          contentHeight:main.scrollHeight,primaryBackground:bg,inputBorder:border};
      });
      assert.equal(composition.primaryBackground,'rgb(22, 122, 47)');
      const luminance=(color)=>color.match(/\d+/g).slice(0,3).map(Number).reduce((sum,v,i)=>{
        v/=255;return sum+[.2126,.7152,.0722][i]*(v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
      },0);
      assert.ok(1.05/(luminance(composition.inputBorder)+.05)>=3,
        'Enabled input boundary contrast: '+composition.inputBorder);
      if(width>=1024) {
        assert.ok(composition.contextHeight<=100,JSON.stringify(composition));
        assert.ok(composition.actionBottom<=composition.visibleHeight,JSON.stringify(composition));
      }
      console.log('TASK_COMPOSITION',width,JSON.stringify(composition));
    }
  }
  await clickStage(page,'data-task','routing');
  for(const key of ['diagnostics','hosts','reconcile']){
    await clickStage(page,'data-routing-detail',key);
    await sample('routing '+key);
  }
  await openDestination(page,'server');
  for(const key of ['inspect','policy','apply','restore']){
    await clickStage(page,'data-php-task',key);
    await sample('php '+key);
  }
  await clickStage(page,'data-php-task','apply');
  await page.locator('#ach-php-preview-route').click();
  assert.equal(await page.locator('[data-php-task="policy"]').evaluate(el=>document.activeElement===el),true);
  await clickStage(page,'data-server-task','hosts');
  await resolveLatest(page,'inspect_hosts_aliases',{status:true,schema:1,read_only:true,state:'Aliases Found',
    hosts_sha256:'a'.repeat(64),entries:[{domain:'demo.test',address:'127.0.0.1',line:7}]});
  await sample('local hostnames');
  await clickStage(page,'data-server-task','attack');
  await checkWebsiteContext('7',false);
  await website.selectOption('');
  await checkWebsiteContext('',true);
  assert.equal(await page.locator('[data-routing-group="attack"]').isVisible(),false);
  assert.equal(await page.locator('#ach-scan-orphan-list').isVisible(),true);
  assert.equal(await page.locator('#ach-scan-orphan-list').isEnabled(),true);
  await sample('attack without website');
  await browse.click();
  assert.equal(await page.locator('[data-task="summary"]').getAttribute('aria-current'),'page');
  await openDestination(page,'server');
  await clickStage(page,'data-server-task','attack');
  await checkWebsiteContext('',true);
  assert.equal(await page.locator('#ach-scan-orphan-list').isEnabled(),true);
  await website.selectOption('7');
  await checkWebsiteContext('7',false);
  assert.equal(await page.locator('#ach-scan-orphan-list').isEnabled(),true);
  await sample('attack protection');
  if(width===1024){
    const field=page.locator('label[for="ach-scan-maxretry"]');
    const original=await field.innerText();
    await field.evaluate(el=>el.textContent='Attempts per selected native website (additional explanatory words)');
    const rows=await geometry(page,'wrapped scanner label');
    assert.ok(rows.some(x=>x.a==='ach-scan-maxretry'&&x.b==='ach-scan-findtime'));
    await field.evaluate((el,text)=>el.textContent=text,original);
  }
  await clickStage(page,'data-server-task','monitor');
  await sample('monitoring');
  await clickStage(page,'data-server-task','http');
  await resolveLatest(page,'status_preferences',prefs);
  await page.locator('#ach-status-template').selectOption('unbound');
  await sample('server HTTP/TLS');
  await openDestination(page,'status');
  await clickStage(page,'data-status-mode','design');
  await sample('error design');
  assert.equal(await page.locator('#ach-status-site-id').isVisible(),false,
    'Global branding does not need an irrelevant disabled site field');
  const local=page.locator('#ach-status-design-result');
  await page.locator('#ach-status-save').click();
  assert.match(await local.innerText(),/Saving global branding/);
  await resolveLatest(page,'status_save',{status:true,schema:1,revision:2,changed:false,scope:'global',
    site_id:null,source:'Global default',effective:brand});
  assert.match(await local.innerText(),/No changes needed/);
  assert.equal(await local.getAttribute('data-state'),'saved');
  assert.equal(await local.getAttribute('aria-live'),null,'Only shared notice is live');
  assert.equal(await local.innerText(),await page.locator('#ach-status-result').innerText());
  const nearby=await local.evaluate(el=>({
    gap:el.getBoundingClientRect().top-el.previousElementSibling.getBoundingClientRect().bottom,
    order:[...el.previousElementSibling.querySelectorAll('button')].map(x=>x.id)
  }));
  assert.ok(nearby.gap>=0 && nearby.gap<=25,JSON.stringify(nearby));
  assert.ok(nearby.order.includes('ach-status-save') && nearby.order.includes('ach-status-reset'));
  await sample('error design save result');
  if(width===320||width===1280){
    const template='404',locale='en';
    await page.locator('#ach-status-template').selectOption(template);
    await page.locator('#ach-status-locale').selectOption(locale);
    const html=fs.readFileSync(path.join(__dirname,'../../plugin/ach_customizer/status_pages',locale,template+'.html'),'utf8');
    const digest=crypto.createHash('sha256').update(html).digest('hex');
    await page.locator('#ach-status-preview-button').click();
    await resolveLatest(page,'status_preview',{status:true,schema:1,apply_supported:false,html,
      rendered_sha256:digest,source_sha256:digest,locale,template,source:'Global default'});
    const preview=page.getByRole('region',{name:'Offline preview, scroll horizontally if needed'});
    assert.equal(await preview.isVisible(),true);
    assert.equal(await preview.getAttribute('tabindex'),'0');
    const iframe=preview.locator('iframe');
    assert.equal(await iframe.getAttribute('sandbox'),'');
    assert.equal(await iframe.getAttribute('title'),'Sandboxed offline Status Page preview');
    await preview.focus();
    assert.equal(await preview.evaluate(el=>document.activeElement===el),true);
    const size=await preview.evaluate(el=>({visible:el.clientWidth,content:el.scrollWidth}));
    if(width===320){
      assert.ok(size.content>size.visible,JSON.stringify(size));
      await page.keyboard.press('ArrowRight');
      await page.waitForFunction(()=>document.querySelector('.ach-preview-viewport').scrollLeft>0);
    }
    await sample('named offline preview');
  }
  if(width===1280){
    const primary=page.locator('#ach-status-save');
    const colors=()=>primary.evaluate(el=>({background:getComputedStyle(el).backgroundColor,
      foreground:getComputedStyle(el).color}));
    function luminance(value){
      const rgb=value.match(/[0-9]+/g).slice(0,3).map(Number);
      return rgb.reduce((sum,v,i)=>{
        v/=255;
        return sum+[.2126,.7152,.0722][i]*(v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
      },0);
    }
    function contrast(c){
      const a=luminance(c.background),b=luminance(c.foreground);
      return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    }
    const normal=contrast(await colors());
    await primary.hover();
    await page.waitForTimeout(220);
    const hover=contrast(await colors());
    assert.ok(normal>=4.5&&hover>=4.5,JSON.stringify({normal,hover}));
  }
  await clickStage(page,'data-status-mode','defaults');
  await page.locator('#ach-status-template').selectOption('new-site');
  assert.equal(await page.locator('#ach-status-result').isVisible(),true);
  await sample('error defaults');
  await clickStage(page,'data-status-mode','fallback');
  await page.locator('#ach-status-template').selectOption('unbound');
  await sample('error fallback');
  await selectStatusSite(page);
  assert.equal(await page.locator('#ach-status-site-id').isVisible(),true,
    'Website branding keeps exact explicit scope selection visible');
  await clickStage(page,'data-status-mode','site');
  await page.locator('#ach-status-template').selectOption('404');
  assert.equal(await local.isVisible(),false,'New scope clears local editor result');
  await sample('error site 404');
  await clickStage(page,'data-status-mode','stopped');
  await page.locator('#ach-status-template').selectOption('stopped');
  await sample('error stopped');
  // The existing source comparison is a text-only scroll surface, not HTML.
  if(width===320||width===1280){
    await clickStage(page,'data-status-mode','site');
    await page.locator('#ach-status-template').selectOption('404');
    const result=await page.locator('#ach-status-comparison-excerpt').evaluate(el=>{
      const hostile='<img src=x onerror=alert(1)>';
      el.textContent=Array.from({length:90},(_,i)=>'-'+i+' '+hostile).join('\n');
      const r=el.getBoundingClientRect();
      return {visible:r.height>0,bounded:r.height<=261,scroll:el.scrollHeight>el.clientHeight,
        text:el.textContent.includes(hostile),images:el.querySelectorAll('img').length};
    });
    assert.deepEqual(result,{visible:true,bounded:true,scroll:true,text:true,images:0});
  }
  // Explicit links must reopen their promised stages, even if another
  // stage was previously selected. Never switch an independent target or
  // dispatch a source/privileged action just to follow a shortcut.
  const scope=await page.locator('#ach-status-scope').inputValue();
  const statusSite=await page.locator('#ach-status-site-id').inputValue();
  const template=await page.locator('#ach-status-template').inputValue();
  await openDestination(page,'overview');
  await page.locator('#ach-home-php').click();
  assert.equal(await page.locator('[data-php-stage="inspect"]').isVisible(),true);
  assert.equal(await page.locator('#ach-task-title').evaluate(el=>document.activeElement===el),true);
  await clickStage(page,'data-php-task','restore');
  await openDestination(page,'overview');
  await page.locator('#ach-home-status').click();
  assert.equal(await page.locator('[data-status-stage="design"]').isVisible(),true);
  assert.equal(await page.locator('#ach-status-scope').inputValue(),scope);
  assert.equal(await page.locator('#ach-status-site-id').inputValue(),statusSite);
  assert.equal(await page.locator('#ach-status-template').inputValue(),template);
  await clickStage(page,'data-status-mode','fallback');
  await openDestination(page,'websites');
  await clickStage(page,'data-task','cache');
  await clickStage(page,'data-cache-task','bridge');
  await clickStage(page,'data-task','routing');
  await clickStage(page,'data-routing-detail','reconcile');
  await page.locator('#ach-reconcile-to-cache').click();
  assert.equal(await page.locator('[data-cache-stage="configure"]').isVisible(),true);
  assert.equal(await page.locator('#ach-hosts-site-id').inputValue(),'7');
  assert.equal(await page.locator('#ach-cache-activation-apply').isEnabled(),false);
  await sample('reconcile to cache');
  await clickStage(page,'data-task','routing');
  await page.locator('#ach-reconcile-to-php').click();
  assert.equal(await page.locator('[data-php-stage="policy"]').isVisible(),true);
  await sample('reconcile to php');
  await openDestination(page,'websites');
  await clickStage(page,'data-task','routing');
  await page.locator('#ach-reconcile-to-status').click();
  assert.equal(await page.locator('[data-status-stage="site"]').isVisible(),true);
  assert.equal(await page.locator('#ach-status-scope').inputValue(),scope);
  assert.equal(await page.locator('#ach-status-site-id').inputValue(),statusSite);
  assert.equal(await page.locator('#ach-status-template').inputValue(),template);
  assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
  await sample('reconcile to status');
  await openDestination(page,'activity');
  await resolveLatest(page,'get_activity',{status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  await sample('activity');
  await page.locator('#ach-activity-refresh').click();
  const diagnostic='<img src=x onerror=alert(1)>';
  await resolveLatest(page,'get_activity',{status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[{schema:1,time_utc:'2026-11-24T08:51:33+00:00',level:'ERROR',module:'websites',
      action:'nginx_guard_manage',stage:'recheck',outcome:'Needs Review',target:'site:7',
      detail:diagnostic,error_class:'GuardError',operation_id:'a'.repeat(32),recovery_id:'b'.repeat(32)}]});
  const details=page.locator('#ach-activity-rows .ach-event-detail').first();
  assert.equal(await details.getAttribute('open'),null);
  assert.equal(await details.locator('p').first().isVisible(),false);
  await details.locator('summary').click();
  assert.match(await details.innerText(),/Operation ID: a{32}/);
  assert.match(await details.innerText(),/Recovery ID: b{32}/);
  assert.ok((await page.locator('#ach-activity-rows .ach-event-reason').innerText()).includes(diagnostic));
  assert.equal(await page.locator('#ach-activity-rows img').count(),0);
  await sample('activity evidence expanded');
  await details.locator('summary').click();
  await sample('activity compact');
  const requests=await page.evaluate(()=>window.__qaRequests.map(x=>
    new URL(x.options.url,location.href).searchParams.get('s')));
  // The deliberate mock branding save is the only write permitted in the walk.
  assert.ok(requests.every(x=>['get_overview','get_sites','get_php_versions','inspect_hosts_aliases',
    'status_preferences','status_sites','status_save','status_preview','manage_nginx_protection','get_activity'].includes(x)),JSON.stringify(requests));
  const guardActions=await page.evaluate(()=>window.__qaRequests.filter(x=>
    new URL(x.options.url,location.href).searchParams.get('s')==='manage_nginx_protection').map(x=>x.options.data.guard_action));
  assert.deepEqual(guardActions,['preview'],'Only the explicit read-only protection check is sent');
  assert.equal(requests.filter(x=>x==='status_save').length,1);
}

async function run(){
  const browser=await chromium.launch({headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath(),
    args:['--no-sandbox','--disable-dev-shm-usage']});
  let samples=0,pairs=0;
  const observed=new Set();
  try{
    for(const [width,height] of widths){
      const {page,pageErrors}=await realPage(browser,width,height);
      try{
        await walk(page,width,(_name,rows)=>{
          samples++;pairs+=rows.length;
          for(const row of rows) observed.add([row.a,row.b].sort().join('|'));
        });
        assert.deepEqual(pageErrors,[]);
        console.log('TASK_LAYOUT_VIEWPORT_PASS',width,height);
      }finally{await page.close();}
    }
    assert.ok(samples>=30*widths.length && pairs>0,'Route/geometry coverage missing');
    if(widths.some(([w])=>w===1024)){
      for(const [a,b] of [['ach-hosts-alias-select','ach-hosts-alias-refresh'],
        ['ach-scan-orphan-choice','ach-scan-orphan-list'],['ach-scan-maxretry','ach-scan-findtime']])
        assert.ok(observed.has([a,b].sort().join('|')),'Missing actual form row '+a+' / '+b);
    }
    console.log('TASK_LAYOUT_PASS',JSON.stringify({viewports:widths.length,samples,mixedControlPairs:pairs}));
  }finally{await browser.close();}
}
module.exports={run,geometry};
if(require.main===module)run().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
