'use strict';

// Real bundled UI + pinned native jQuery; every HTTP request is intercepted.
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
const fixture = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="${origin}/jquery.js"></script>
  <script src="${origin}/transport.js"></script>
  </head><body><div class="layui-layer" style="position:fixed;left:90px;top:20%;width:1100px;height:672px">
  <div class="layui-layer-title" style="height:42px">Customizer QA</div>
  <div class="layui-layer-content">${pluginHtml}</div>
  </div></body></html>`;

async function realPage(browser, width, height=720, options={}) {
  const page = await browser.newPage({viewport:{width,height},...options});
  page.setDefaultTimeout(5000);
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(e.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === origin && url.pathname === '/fixture') {
      await route.fulfill({status:200,contentType:'text/html',body:fixture});
    } else if (url.origin === origin && url.pathname === '/jquery.js') {
      await route.fulfill({status:200,contentType:'application/javascript',body:jquery});
    } else if (url.origin === origin && url.pathname === '/transport.js') {
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
async function openDestination(page, name) {
  const target=page.locator('[data-destination="'+name+'"]');
  if (!await target.isVisible()) await page.locator('#ach-menu-toggle').click();
  await target.click();
}
module.exports={chromium,brand,prefs,site,realPage,resolveLatest,lastRequest,openDestination};
