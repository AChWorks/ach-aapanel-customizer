'use strict';

// Reproducible, isolated actual-DOM verification of the shipped inline UI.
// Not an authenticated aaPanel session, live Nginx Apply, or native lifecycle QA.
//
// Required external test-only tools: Playwright + Chromium and the original
// aaPanel 8.0.7 jQuery 2.2.4 (the checksum below pins the observed QA bytes).
//
// Example in an authorized Dev browser environment:
//   ACH_NATIVE_JQUERY=/path/to/aaPanel-jquery-2.2.4.min.js \
//   NODE_PATH=/path/to/playwright/node_modules \
//   CHROMIUM_EXECUTABLE=/path/to/chromium node tests/manual/status_50x_browser.cjs
//
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

const pluginHtml = fs.readFileSync(
  path.join(__dirname, '../../plugin/ach_customizer/index.html'), 'utf8');
const jqueryPath = process.env.ACH_NATIVE_JQUERY;
if (!jqueryPath) throw Error('Set ACH_NATIVE_JQUERY to the verified aaPanel 8.0.7 jQuery 2.2.4 file');
const jquery = fs.readFileSync(jqueryPath, 'utf8');
const checksum = crypto.createHash('sha256').update(jquery).digest('hex');
assert.equal(checksum,
  '05b85d96f41fff14d8f608dad03ab71e2c1017c2da0914d7c59291bad7a54f8e',
  'Use the same 85578-byte jQuery 2.2.4 observed in the isolated native aaPanel QA');

const brand = {
  brand_name:'ACh', tagline:'WEB SYSTEMS', brand_url:'https://ach.li',
  brand_label:'ach.li', accent:'#008b92', background:'#f4f2eb',
  foreground:'#0b1718', footer_enabled:true
};
const prefs = {
  status:true, schema:1, revision:2, apply_supported:false, mode:'Preview only',
  global:brand, effective:brand, source:'Global default', site_id:null,
  templates:['403','404','429','500','502','503','504','50x','new-site','stopped','unbound'],
  locales:['en','fa']
};
const site = {
  id:7, name:'demo.test', document_root:'/www/demo.test', panel_status:'1',
  classification:'Needs Review', canonical_domain_bound:true,
  bound_domains:[{name:'demo.test',port:80}]
};
const snapshot = JSON.stringify([7,'demo.test','/www/demo.test','1',[['demo.test',80]]]);
const sourceHash = 'b'.repeat(64);
const renderedHash = 'a'.repeat(64);
const vhostHash = 'c'.repeat(64);

function sourceReady() {
  return {
    status:true,schema:1,site_id:7,site_key:'demo.test',
    verified_site_snapshot:snapshot,template:'50x',locale:'en',
    scope:'native_vhost_source_only',state:'Source Ready',
    reason:'Native 50x source available', read_only:true,apply_supported:false,
    nginx_runtime_verified:false,revision:2,http_status:null,http_404_observed:false,
    body_sha256:null,body_bytes:null,page_file_sha256:sourceHash,
    rendered_sha256:renderedHash,body_matches_file:false,body_matches_render:false,
    note:'Source only; no simulated Nginx error',
    adoption_preview:{
      schema:1,state:'Source Ready',route_source_state:'Native VHost',
      current_sha256:sourceHash,proposed_sha256:renderedHash,
      vhost_sha256:vhostHash,requires_adoption:false,requires_backup:false,
      ownership_verified:false,recovery_verified:false,apply_supported:false,
      reason:'Exact 50x extension and reload approval required'
    }
  };
}

const ajaxStub = `
window.__qaRequests = [];
window.jQuery.ajax = window.$.ajax = function(options) {
  const entry = {
    options,
    done(handler){ this.doneHandler=handler; return this; },
    fail(handler){ this.failHandler=handler; return this; },
    resolve(response){
      if (!this.doneHandler) throw Error('AJAX .done callback not installed');
      this.doneHandler(response);
    }
  };
  window.__qaRequests.push(entry);
  return entry;
};
`;
const origin = 'http://ach-customizer-qa.invalid';
const fixture = `<!doctype html><html lang="en"><head><meta charset="utf-8">
  <script src="${origin}/jquery.js"></script>
  <script src="${origin}/transport.js"></script>
  </head><body><div class="layui-layer">
  <div class="layui-layer-title" style="height:42px">Customizer QA</div>
  <div class="layui-layer-content">${pluginHtml}</div>
  </div></body></html>`;

async function realPage(browser, width) {
  const page = await browser.newPage({viewport:{width,height:720}});
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message));
  await page.route(origin+'/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/fixture') {
      await route.fulfill({status:200,contentType:'text/html',body:fixture});
    } else if (url.pathname === '/jquery.js') {
      await route.fulfill({status:200,contentType:'application/javascript',body:jquery});
    } else if (url.pathname === '/transport.js') {
      await route.fulfill({status:200,contentType:'application/javascript',body:ajaxStub});
    } else {
      await route.abort('blockedbyclient');
    }
  });
  await page.goto(origin+'/fixture',{waitUntil:'domcontentloaded'});
  assert.equal(await page.locator('#ach-customizer').count(),1);
  assert.equal(await page.evaluate(() => window.jQuery.fn.jquery),'2.2.4');
  assert.ok(await page.evaluate(() => Array.isArray(window.__qaRequests)));
  return {page,pageErrors};
}

async function resolveLatest(page, method, body) {
  return page.evaluate(({method,body}) => {
    const matching = window.__qaRequests.filter(r =>
      new URL(r.options.url,location.href).searchParams.get('s')===method);
    const request = matching[matching.length-1];
    if (!request) throw Error('Missing AJAX request '+method);
    request.resolve(body);
    return {method,data:request.options.data,type:request.options.type,
      count:matching.length};
  },{method,body});
}
async function lastRequest(page, method) {
  return page.evaluate(method => {
    const matching = window.__qaRequests.filter(r =>
      new URL(r.options.url,location.href).searchParams.get('s')===method);
    const request=matching[matching.length-1];
    return request ? {data:request.options.data,type:request.options.type,
      count:matching.length,timeout:request.options.timeout} : null;
  },method);
}
async function completeSiteSelection(page) {
  await page.locator('[data-tab="status"]').click();
  await resolveLatest(page,'status_preferences',prefs);
  await page.locator('#ach-status-scope').selectOption('site');
  await resolveLatest(page,'status_sites',{
    status:true,purpose:'status_site_selection',inventory_schema:2,
    page:1,page_size:25,has_more:false,sites:[site]
  });
  await page.locator('#ach-status-site-id').selectOption('7');
  await resolveLatest(page,'status_preferences',prefs);
  await page.locator('#ach-status-template').selectOption('50x');
  assert.equal(await page.locator('#ach-status-delivery').inputValue(),'extension');
}
async function assertSourceControls(page, expected) {
  assert.equal(await page.locator('#ach-status-site-preflight').isVisible(),expected);
  assert.equal(await page.locator('#ach-status-probe-button').isVisible(),expected);
  assert.equal(await page.locator('#ach-status-probe-result').isVisible(),expected);
  assert.equal(await page.locator('#ach-status-adoption-result').isVisible(),expected);
}

async function fullApplyJourney(browser, width) {
  const {page,pageErrors}=await realPage(browser,width);
  try {
    await completeSiteSelection(page);
    assert.equal(await page.locator('#ach-status-site-audit').isVisible(),false);
    assert.equal(await page.locator('#ach-status-manage-section').isVisible(),true);
    await assertSourceControls(page,true);
    assert.equal(await page.locator('#ach-status-probe-button').isEnabled(),true);
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    await page.locator('#ach-status-probe-button').focus();
    assert.equal(await page.locator('#ach-status-probe-button').evaluate(
      el => document.activeElement === el),true,'Preflight must accept real keyboard focus');
    await page.keyboard.press('Enter');
    const probeRequest=await lastRequest(page,'status_probe');
    assert.equal(probeRequest.type,'POST');
    assert.equal(probeRequest.data.site_id,'7');
    assert.equal(probeRequest.data.template,'50x');
    assert.equal(probeRequest.data.site_delivery,'extension');
    assert.equal(probeRequest.data.expected_site_snapshot,snapshot);
    assert.equal(await page.locator('#ach-status-probe-button').isEnabled(),false,
      'Preflight is not double-clickable while busy');
    await resolveLatest(page,'status_probe',sourceReady());
    assert.match(await page.locator('#ach-status-probe-result').innerText(),
      /HTTP status: Unavailable/,'50x must remain source-only');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false,
      'Valid preflight alone must not authorize a write');
    await page.locator('#ach-status-manage-apply-approve').check();
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),true);
    await page.locator('#ach-status-manage-apply').click();
    const applyRequest=await lastRequest(page,'status_manage');
    assert.equal(applyRequest.type,'POST');
    assert.equal(applyRequest.data.site_action,'apply');
    assert.equal(applyRequest.data.site_delivery,'extension');
    assert.equal(applyRequest.data.template,'50x');
    assert.equal(applyRequest.data.expected_site_snapshot,snapshot);
    assert.equal(applyRequest.data.expected_revision,'2');
    assert.equal(applyRequest.data.expected_page_sha256,sourceHash);
    assert.equal(applyRequest.data.expected_render_sha256,renderedHash);
    assert.equal(applyRequest.data.expected_vhost_sha256,vhostHash);
    assert.equal(applyRequest.data.site_approval,'apply_exact_site_50x_reload');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    assert.deepEqual(pageErrors,[],'No browser exceptions');
    console.log('BROWSER_50X_PREPARE_APPROVE_APPLY_PASS', JSON.stringify({width,
      applyContract:applyRequest.data.site_approval,requestCount:applyRequest.count}));
  } finally {
    await page.close();
  }
}

async function negativeAndAdjacentFlows(browser) {
  const {page,pageErrors}=await realPage(browser,1280);
  try {
    await completeSiteSelection(page);
    await assertSourceControls(page,true);
    await page.locator('#ach-status-delivery').selectOption('file');
    assert.equal(await page.locator('#ach-status-probe-button').isEnabled(),false,
      'Unsupported 50x native site-file preflight must stay disabled');
    assert.equal(await page.locator('#ach-status-manage-recheck').isEnabled(),false);
    await page.locator('#ach-status-manage-apply-approve').check();
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    assert.equal(await lastRequest(page,'status_probe'),null,
      'An unsupported delivery mode must not issue a probe');
    await page.locator('#ach-status-delivery').selectOption('extension');
    assert.equal(await page.locator('#ach-status-probe-button').isEnabled(),true);

    await page.locator('#ach-status-probe-button').click();
    await resolveLatest(page,'status_probe',sourceReady());
    await page.locator('#ach-status-manage-apply-approve').check();
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),true);

    await page.locator('#ach-status-locale').selectOption('fa');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    assert.equal(await page.locator('#ach-status-manage-apply-approve').isChecked(),false);
    await page.locator('#ach-status-locale').selectOption('en');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false,
      'Round-tripping locale must not resurrect stale proof');

    await page.locator('#ach-status-template').selectOption('404');
    assert.equal(await page.locator('#ach-status-site-audit').isVisible(),true);
    assert.equal(await page.locator('#ach-status-inspect-button').isVisible(),true);
    assert.equal(await page.locator('#ach-status-inspect-button').isEnabled(),true);
    assert.equal(await page.locator('#ach-status-comparison-summary').isVisible(),true);
    await assertSourceControls(page,true);
    await page.locator('#ach-status-template').selectOption('502');
    assert.equal(await page.locator('#ach-status-site-audit').isVisible(),true);
    await assertSourceControls(page,true);

    await page.locator('#ach-status-template').selectOption('50x');
    assert.equal(await page.locator('#ach-status-site-audit').isVisible(),false);
    await assertSourceControls(page,true);
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    await page.locator('#ach-status-probe-button').click();
    await resolveLatest(page,'status_probe',sourceReady());
    await page.locator('#ach-status-manage-apply-approve').check();
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),true);
    await page.locator('#ach-status-name').fill('Changed brand');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);
    assert.equal(await page.locator('#ach-status-manage-apply-approve').isChecked(),false);
    // Restore the original brand; even an exact same string cannot revive proof.
    await page.locator('#ach-status-name').fill('ACh');
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);

    // Refreshing native inventory invalidates the current selection while the
    // async read is pending, instead of allowing a stale source-guarded write.
    await page.locator('#ach-status-sites-retry').click();
    assert.equal(await page.locator('#ach-status-probe-button').isEnabled(),false);
    assert.equal(await page.locator('#ach-status-manage-apply').isEnabled(),false);

    assert.deepEqual(pageErrors,[]);
    console.log('BROWSER_50X_NEGATIVE_ADJACENT_PASS',
      JSON.stringify({noFileMode:true,staleLocale:true,staleTemplate:true,
        staleBrand:true,pendingInventory:true,site404502Audit:true}));
  } finally {await page.close();}
}

(async () => {
  const browser=await chromium.launch({
    headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args:['--no-sandbox','--disable-dev-shm-usage']
  });
  try {
    for(const width of [1280,375]) await fullApplyJourney(browser,width);
    await negativeAndAdjacentFlows(browser);
    console.log('BROWSER_50X_REAL_DOM_TOTAL_PASS');
  } finally {
    await browser.close();
  }
})().catch(err => {
  console.error('BROWSER_50X_REAL_DOM_FAIL',err.stack||String(err));
  process.exitCode=1;
});
