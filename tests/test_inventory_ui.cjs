'use strict';

// Execute the shipped inline script against a narrow jQuery-like DOM harness.
// No copied validator logic, browser installation, network or npm dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(
  path.join(__dirname, '../plugin/ach_customizer/index.html'), 'utf8'
);
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
assert.equal(scripts.length, 1, 'Test must execute the single deployed inline script');
const script = scripts[0][1];

function fakeNode(tag, attributes = {}) {
  return {
    tag, attributes: { ...attributes }, props: {}, children: [],
    textContent: '', classes: new Set(), handlers: {}
  };
}

function loadUi() {
  const root = fakeNode('div');
  const elements = new Map();
  const tabs = ['overview', 'websites', 'php'].map(name => fakeNode('button', {
    'data-tab': name, 'aria-selected': name === 'overview' ? 'true' : 'false'
  }));
  const views = ['overview', 'websites', 'php'].map(name => fakeNode('section', {
    'data-view': name
  }));
  for (const name of [
    '#ach-message', '#ach-overview-status', '#ach-sites-rows',
    '#ach-page', '#ach-prev', '#ach-next', '#ach-php-form',
    '#ach-fpm-result', '#ach-diff-rows'
  ]) elements.set(name, fakeNode('div'));
  const requests = [];

  function selection(nodes) {
    return {
      _nodes: nodes,
      length: nodes.length,
      find(query) {
        assert.equal(nodes[0], root, 'Only plugin-scoped selectors are allowed');
        if (query === '[data-tab]') return selection(tabs);
        if (query === '[data-view]') return selection(views);
        if (query === '#ach-prev, #ach-next') {
          return selection([elements.get('#ach-prev'), elements.get('#ach-next')]);
        }
        const view = /^\[data-view="([^"]+)"\]$/.exec(query);
        if (view) return selection(views.filter(node => node.attributes['data-view'] === view[1]));
        assert.ok(elements.has(query), 'Unexpected plugin selector: ' + query);
        return selection([elements.get(query)]);
      },
      on(event, callback) {
        for (const node of nodes) node.handlers[event] = callback;
        return this;
      },
      text(value) {
        if (arguments.length === 0) return nodes[0]?.textContent;
        for (const node of nodes) node.textContent = String(value);
        return this;
      },
      empty() {
        for (const node of nodes) node.children = [];
        return this;
      },
      append(value) {
        assert.ok(value && value._nodes, 'append expects a jQuery collection');
        for (const node of nodes) node.children.push(...value._nodes);
        return this;
      },
      appendTo(destination) {
        destination.append(this);
        return this;
      },
      toggleClass(name, enabled) {
        for (const node of nodes) {
          if (enabled) node.classes.add(name);
          else node.classes.delete(name);
        }
        return this;
      },
      attr(name, value) {
        if (arguments.length === 1) return nodes[0]?.attributes[name];
        for (const node of nodes) node.attributes[name] = value;
        return this;
      },
      prop(name, value) {
        if (arguments.length === 1) return nodes[0]?.props[name];
        for (const node of nodes) node.props[name] = value;
        return this;
      },
      serializeArray() {
        return [];
      }
    };
  }

  function $(value) {
    if (value === '#ach-customizer') return selection([root]);
    if (value && typeof value === 'object' && value.handlers) return selection([value]);
    if (typeof value === 'string' && /^<(tr|td)\b/.test(value)) {
      return selection([fakeNode(value.startsWith('<tr') ? 'tr' : 'td')]);
    }
    throw new Error('Unexpected unscoped jQuery target: ' + String(value));
  }

  $.ajax = function (options) {
    const request = {
      options,
      done(callback) { this.respond = callback; return this; },
      fail(callback) { this.reject = callback; return this; }
    };
    requests.push(request);
    return request;
  };

  vm.runInNewContext(script, { $, encodeURIComponent }, { timeout: 1000 });

  function trigger(node, event) {
    assert.equal(typeof node.handlers[event], 'function', event + ' handler missing');
    node.handlers[event].call(node, { preventDefault() {} });
  }
  function openSites() {
    trigger(tabs.find(node => node.attributes['data-tab'] === 'websites'), 'click');
    return requests.at(-1);
  }
  function respond(response) {
    const request = requests.at(-1);
    assert.match(request.options.url, /s=get_sites$/);
    request.respond(response);
    return request;
  }
  function rows() {
    return elements.get('#ach-sites-rows').children.map(tr =>
      tr.children.map(td => td.textContent)
    );
  }
  function state() {
    return {
      rows: rows(),
      error: elements.get('#ach-message').textContent,
      errorClass: elements.get('#ach-message').classes.has('ach-error'),
      prevDisabled: elements.get('#ach-prev').props.disabled,
      nextDisabled: elements.get('#ach-next').props.disabled,
      page: elements.get('#ach-page').textContent
    };
  }
  return { openSites, respond, state, requests,
    clickNext: () => trigger(elements.get('#ach-next'), 'click'),
    clickPrevious: () => trigger(elements.get('#ach-prev'), 'click') };
}

const site = () => ({
  id: 3,
  name: 'site.example.test',
  document_root: '/www/site.example.test',
  classification: 'Needs Review',
  bound_domains: [
    { name: 'site.example.test', port: 80 },
    { name: '*.مثال.ایران', port: 443 },
    { name: 'shop.example.test', port: 8443 }
  ],
  canonical_domain_bound: true
});
const page = (sites = [site()]) => ({
  status: true,
  inventory_schema: 2,
  page: 1,
  page_size: 25,
  has_more: false,
  sites
});

function invalidCase(title, mutate, expectedError = /Invalid inventory response/) {
  test(title, () => {
    const ui = loadUi();
    ui.openSites();
    const data = page();
    mutate(data);
    assert.doesNotThrow(() => ui.respond(data));
    const output = ui.state();
    assert.deepEqual(output.rows, [], 'No misleading or partially rendered rows');
    assert.match(output.error, expectedError, 'Visible error must explain failure');
    assert.equal(output.errorClass, true);
    assert.equal(output.prevDisabled, true);
    assert.equal(output.nextDisabled, true);
    assert.equal(output.page, 'Unavailable');
    assert.doesNotMatch(output.error, /No sites in this page|None \(review required\)/);
  });
}

invalidCase('Old backend without inventory_schema fails closed',
  r => { delete r.inventory_schema; }, /Inventory API mismatch/);
invalidCase('Incorrect schema version fails closed',
  r => { r.inventory_schema = 1; }, /Inventory API mismatch/);
invalidCase('Missing sites array is rejected',
  r => { delete r.sites; });
invalidCase('Null sites array is rejected',
  r => { r.sites = null; });
invalidCase('Missing bound_domains is rejected',
  r => { delete r.sites[0].bound_domains; });
invalidCase('Null binding is rejected without a TypeError',
  r => { r.sites[0].bound_domains = [null]; });
invalidCase('Empty binding object is rejected without fabricated text',
  r => { r.sites[0].bound_domains = [{}]; });
invalidCase('Binding without name is rejected',
  r => { r.sites[0].bound_domains = [{ port: 80 }]; });
invalidCase('Binding without port is rejected',
  r => { r.sites[0].bound_domains = [{ name: 'x.example.test' }]; });
for (const invalidPort of ['80', 0, 65536, 80.1, null, {}, true]) {
  invalidCase('Invalid port ' + JSON.stringify(invalidPort) + ' is rejected',
    r => { r.sites[0].bound_domains = [{ name: 'x.example.test', port: invalidPort }]; });
}
invalidCase('Missing required numeric site ID is rejected',
  r => { delete r.sites[0].id; });
invalidCase('String site ID is rejected',
  r => { r.sites[0].id = '3'; });
invalidCase('Duplicate site IDs are rejected',
  r => { r.sites.push({ ...site() }); });
invalidCase('Missing site name is rejected',
  r => { delete r.sites[0].name; });
invalidCase('Whitespace site name is rejected',
  r => { r.sites[0].name = '   '; });
invalidCase('Missing site document root is rejected',
  r => { delete r.sites[0].document_root; });
invalidCase('Missing classification is rejected',
  r => { delete r.sites[0].classification; });
invalidCase('Missing canonical binding indicator is rejected',
  r => { delete r.sites[0].canonical_domain_bound; });
invalidCase('Contradictory canonical binding indicator is rejected',
  r => { r.sites[0].canonical_domain_bound = false; });
invalidCase('has_more string false is rejected without phantom next page',
  r => { r.has_more = 'false'; });
invalidCase('Missing has_more is rejected',
  r => { delete r.has_more; });
invalidCase('Missing pagination page is rejected',
  r => { delete r.page; });
invalidCase('Incorrect page metadata is rejected',
  r => { r.page = 2; });
invalidCase('Incorrect page_size type is rejected',
  r => { r.page_size = '25'; });
invalidCase('Incorrect page_size value is rejected',
  r => { r.page_size = 100; });
invalidCase('Inconsistent has_more metadata is rejected',
  r => { r.has_more = true; });
invalidCase('Domain result count above contract bound is rejected',
  r => { r.sites[0].bound_domains = Array.from({length:1001}, (_,i) => ({name:'x'+i+'.test',port:80})); });

test('Valid empty inventory renders an empty page without error or pagination', () => {
  const ui = loadUi();
  ui.openSites();
  ui.respond(page([]));
  const output = ui.state();
  assert.deepEqual(output.rows, [['No sites in this page']]);
  assert.equal(output.error, '');
  assert.equal(output.errorClass, false);
  assert.equal(output.page, '1');
  assert.equal(output.prevDisabled, true);
  assert.equal(output.nextDisabled, true);
});

test('Valid multi-domain Unicode/wildcard/port inventory renders safely and accurately', () => {
  const ui = loadUi();
  ui.openSites();
  const detached = { ...site(), id: 9, name: 'historical.test',
    bound_domains: [{ name: '<img src=x onerror=alert(1)>', port: 8443 }],
    canonical_domain_bound: false };
  ui.respond(page([site(), detached]));
  const output = ui.state();
  assert.deepEqual(output.rows, [
    ['3', 'site.example.test',
      'site.example.test, *.مثال.ایران:443, shop.example.test:8443',
      '/www/site.example.test', 'Needs Review'],
    ['9', 'historical.test (not bound)',
      '<img src=x onerror=alert(1)>:8443',
      '/www/site.example.test', 'Needs Review']
  ]);
  assert.equal(output.error, '');
  assert.equal(output.errorClass, false);
  assert.equal(output.prevDisabled, true);
  assert.equal(output.nextDisabled, true);
  // The fake DOM only implements jQuery .text(), not unsafe .html().
  // Executing the shipped renderer therefore also verifies text-safe writes.
});

test('Valid pagination, then invalid page clears prior rows and disables controls', () => {
  const ui = loadUi();
  ui.openSites();
  const firstPage = page(Array.from({length:25}, (_,index) => ({
    ...site(), id:index+1, name:'site'+(index+1)+'.test',
    bound_domains:[], canonical_domain_bound:false
  })));
  firstPage.has_more = true;
  ui.respond(firstPage);
  assert.equal(ui.state().rows.length, 25);
  assert.equal(ui.state().nextDisabled, false);
  ui.clickNext();
  assert.equal(ui.requests.at(-1).options.data.page, 2);
  assert.equal(ui.requests.at(-1).options.data.page_size, 25);
  const secondPage = page([{ ...site(), id:26, name:'new.example.test',
    bound_domains:[], canonical_domain_bound:false }]);
  secondPage.page = 2;
  ui.respond(secondPage);
  assert.equal(ui.state().rows.length, 1);
  assert.equal(ui.state().page, '2');
  assert.equal(ui.state().prevDisabled, false);
  assert.equal(ui.state().nextDisabled, true);
  ui.clickPrevious();
  assert.equal(ui.requests.at(-1).options.data.page, 1);
  const bad = page();
  bad.sites[0].bound_domains = [null];
  ui.respond(bad);
  assert.deepEqual(ui.state().rows, []);
  assert.equal(ui.state().page, 'Unavailable');
  assert.equal(ui.state().prevDisabled, true);
  assert.equal(ui.state().nextDisabled, true);
  assert.match(ui.state().error, /Invalid inventory response/);
});

test('Panel endpoint error clears inventory and preserves explicit diagnostics', () => {
  const ui = loadUi();
  ui.openSites();
  ui.respond(page());
  ui.clickNext(); // With has_more=false this must not dispatch another request.
  assert.equal(ui.requests.length, 2); // overview plus one inventory request
  ui.openSites();
  ui.respond({status:false, stage:'website_discovery',msg:'backend unavailable',operation_id:'abc'});
  assert.deepEqual(ui.state().rows, []);
  assert.equal(ui.state().page, 'Unavailable');
  assert.match(ui.state().error, /website_discovery: backend unavailable/);
  assert.equal(ui.state().nextDisabled, true);
});
