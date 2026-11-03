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
  const tabs = ['overview', 'websites', 'php', 'status', 'activity'].map(name => fakeNode('button', {
    'data-tab': name, 'aria-selected': name === 'overview' ? 'true' : 'false'
  }));
  const views = ['overview', 'websites', 'php', 'status', 'activity'].map(name => fakeNode('section', {
    'data-view': name
  }));
  for (const name of [
    '#ach-message', '#ach-overview-status', '#ach-sites-rows',
    '#ach-page', '#ach-prev', '#ach-next', '#ach-php-form',
    '#ach-fpm-result', '#ach-diff-rows', '#ach-state-revision',
    '#ach-impact-summary', '#ach-impact-rows',
    '#ach-fpm-prepare', '#ach-fpm-plan', '#ach-fpm-review',
    '#ach-fpm-details', '#ach-fpm-approval', '#ach-fpm-commit',
    '#ach-fpm-check-recovery', '#ach-fpm-recovery-status',
    '#ach-fpm-recovery-impact', '#ach-fpm-restore-rows',
    '#ach-fpm-rollback-controls', '#ach-fpm-rollback-approval', '#ach-fpm-rollback',
    '#ach-status-template', '#ach-status-locale', '#ach-status-scope', '#ach-status-site-id',
    '#ach-status-name', '#ach-status-tagline', '#ach-status-url', '#ach-status-label',
    '#ach-status-accent', '#ach-status-background', '#ach-status-foreground',
    '#ach-status-footer', '#ach-status-load', '#ach-status-preview-button',
    '#ach-status-save', '#ach-status-reset', '#ach-status-reset-approve',
    '#ach-status-source', '#ach-status-result', '#ach-status-sha', '#ach-status-iframe',
    '#ach-status-inspect-button', '#ach-status-inspect-result',
    '#ach-status-sites-more', '#ach-status-sites-retry', '#ach-status-sites-state',
    '#ach-activity-level', '#ach-activity-module', '#ach-activity-refresh',
    '#ach-activity-result', '#ach-activity-rows'
  ]) elements.set(name, fakeNode('div'));
  for (const [selector, val] of [
    ['#ach-status-template','404'], ['#ach-status-locale','en'],
    ['#ach-status-scope','global'], ['#ach-status-site-id',''],
    ['#ach-activity-level',''], ['#ach-activity-module','']
  ]) elements.get(selector).props.value = val;
  const controls = [
    ['#ach-monitor-enabled', 'overall'],
    ['#ach-site-enabled', 'site_inventory'],
    ['#ach-fpm-enabled', 'php_fpm_file_preview']
  ].map(([name, control]) => {
    const node = fakeNode('input', {'data-monitor-control': control});
    node.props.disabled = true;
    elements.set(name, node);
    return node;
  });
  const requests = [];

  function selection(nodes) {
    return {
      _nodes: nodes,
      length: nodes.length,
      find(query) {
        assert.equal(nodes[0], root, 'Only plugin-scoped selectors are allowed');
        if (query === '[data-tab]') return selection(tabs);
        if (query === '[data-view]') return selection(views);
        if (query === '[data-monitor-control]') return selection(controls);
        if (query === '#ach-prev, #ach-next') {
          return selection([elements.get('#ach-prev'), elements.get('#ach-next')]);
        }
        if (query.startsWith('#ach-status-') && query.includes(', ')) {
          const selected = query.split(', ').map(key => elements.get(key));
          assert.ok(selected.every(Boolean), 'Unknown Status Pages selector group: ' + query);
          return selection(selected);
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
      addClass(name) {
        for (const node of nodes) node.classes.add(name);
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
      val(value) {
        if (arguments.length === 0) return nodes[0]?.props.value;
        for (const node of nodes) node.props.value = value;
        return this;
      },
      serializeArray() {
        return nodes[0]?.props.fields || [];
      }
    };
  }

  function $(value) {
    if (value === '#ach-customizer') return selection([root]);
    if (value && typeof value === 'object' && value.handlers) return selection([value]);
    if (typeof value === 'string' && /^<(tr|td|option)\b/.test(value)) {
      return selection([fakeNode(value.slice(1).split(/\W/)[0])]);
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
  function openOverview() {
    trigger(tabs.find(node => node.attributes['data-tab'] === 'overview'), 'click');
    return requests.at(-1);
  }
  function respondOverview(value) {
    const request = requests.at(-1);
    assert.match(request.options.url, /s=get_overview$/);
    request.respond(value);
  }
  function toggleMonitor(controlName, enabled) {
    const node = controls.find(item => item.attributes['data-monitor-control'] === controlName);
    assert.ok(node, 'Unknown test control');
    node.props.checked = enabled;
    trigger(node, 'change');
    return requests.at(-1);
  }
  function respondControl(value) {
    const request = requests.at(-1);
    assert.match(request.options.url, /s=set_control$/);
    request.respond(value);
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
      page: elements.get('#ach-page').textContent,
      overview: elements.get('#ach-overview-status').textContent,
      stateRevision: elements.get('#ach-state-revision').textContent,
      statusResult: elements.get('#ach-status-result').textContent,
      statusSource: elements.get('#ach-status-source').textContent,
      statusHtml: elements.get('#ach-status-iframe').props.srcdoc,
      statusHash: elements.get('#ach-status-sha').textContent,
      statusSaveDisabled: elements.get('#ach-status-save').props.disabled,
      statusResetDisabled: elements.get('#ach-status-reset').props.disabled,
      statusInspectDisabled: elements.get('#ach-status-inspect-button').props.disabled,
      statusInspect: elements.get('#ach-status-inspect-result').textContent,
      impactSummary: elements.get('#ach-impact-summary').textContent,
      fpmPlan: elements.get('#ach-fpm-plan').textContent,
      fpmDetails: elements.get('#ach-fpm-details').textContent,
      fpmReviewHidden: elements.get('#ach-fpm-review').props.hidden,
      fpmPrepareDisabled: elements.get('#ach-fpm-prepare').props.disabled,
      fpmCommitDisabled: elements.get('#ach-fpm-commit').props.disabled,
      fpmRecovery: elements.get('#ach-fpm-recovery-status').textContent,
      fpmRecoveryImpact: elements.get('#ach-fpm-recovery-impact').textContent,
      fpmRestoreRows: elements.get('#ach-fpm-restore-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      fpmRollbackHidden: elements.get('#ach-fpm-rollback-controls').props.hidden,
      fpmRollbackDisabled: elements.get('#ach-fpm-rollback').props.disabled,
      impactRows: elements.get('#ach-impact-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      controls: Object.fromEntries(controls.map(node => [
        node.attributes['data-monitor-control'],
        {checked: node.props.checked, disabled: node.props.disabled}
      ]))
    };
  }
  function submitPhp(version = '85') {
    elements.get('#ach-php-form').props.fields = [
      {name: 'php_version', value: version},
      {name: 'max_children', value: '50'},
      {name: 'start_servers', value: '5'},
      {name: 'min_spare_servers', value: '5'},
      {name: 'max_spare_servers', value: '20'},
      {name: 'max_requests', value: '0'}
    ];
    trigger(elements.get('#ach-php-form'), 'submit');
    return requests.at(-1);
  }
  function fpmTrigger(selector, event = 'click') {
    trigger(elements.get(selector), event);
    return requests.at(-1);
  }
  function fpmApproval(selector, checked) {
    elements.get(selector).props.checked = checked;
    fpmTrigger(selector, 'change');
  }
  function changePhp(name, value) {
    const fields = elements.get('#ach-php-form').props.fields;
    const entry = fields.find(item => item.name === name);
    assert.ok(entry); entry.value = value;
    trigger(elements.get('#ach-php-form'), 'input change');
  }
  function statusClick(selector, event = 'click') {
    trigger(elements.get(selector), event);
    return requests.at(-1);
  }
  function openStatus() {
    trigger(tabs.find(node => node.attributes['data-tab'] === 'status'), 'click');
    return requests.at(-1);
  }
  function openActivity() {
    trigger(tabs.find(node => node.attributes['data-tab'] === 'activity'), 'click');
    return requests.at(-1);
  }
  function statusSetValue(selector, value, event = null) {
    assert.ok(elements.has(selector));
    elements.get(selector).props.value = value;
    if (event) trigger(elements.get(selector), event);
  }
  function statusSetChecked(selector, value) {
    elements.get(selector).props.checked = value;
    trigger(elements.get(selector), 'change');
  }
  return { openSites, openOverview, openStatus, statusSetValue, statusSetChecked,
    statusClick, openActivity, respond, respondOverview, toggleMonitor, submitPhp,
    prepareFpm: () => fpmTrigger('#ach-fpm-prepare'),
    approveFpm: checked => fpmApproval('#ach-fpm-approval', checked),
    commitFpm: () => fpmTrigger('#ach-fpm-commit'),
    inspectFpmRecovery: () => fpmTrigger('#ach-fpm-check-recovery'),
    approveFpmRollback: checked => fpmApproval('#ach-fpm-rollback-approval', checked),
    rollbackFpm: () => fpmTrigger('#ach-fpm-rollback'),
    changePhp,
    respondControl, state, requests,
    clickNext: () => trigger(elements.get('#ach-next'), 'click'),
    clickPrevious: () => trigger(elements.get('#ach-prev'), 'click'),
    activityRows: () => elements.get('#ach-activity-rows').children.map(tr => tr.children.map(td => td.textContent)),
    activityMessage: () => elements.get('#ach-activity-result').textContent,
    activityFilter: (selector, value) => {
      elements.get(selector).props.value = value;
      trigger(elements.get(selector), 'change');
      return requests.at(-1);
    },
    statusSiteChoices: () => elements.get('#ach-status-site-id').children.map(option => ({
      id: option.props.value, text: option.textContent
    })),
    statusSiteInfo: () => elements.get('#ach-status-sites-state').textContent,
    statusSiteDisabled: () => elements.get('#ach-status-site-id').props.disabled,
    loadMoreSites: () => {
      trigger(elements.get('#ach-status-sites-more'), 'click');
      return requests.at(-1);
    }
  };
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
  r => { r.sites[0].bound_domains = [{}]; r.sites[0].canonical_domain_bound = false; });
invalidCase('Binding without name is rejected',
  r => { r.sites[0].bound_domains = [{ port: 80 }]; r.sites[0].canonical_domain_bound = false; });
invalidCase('Binding without port is rejected',
  r => { r.sites[0].bound_domains = [{ name: 'site.example.test' }]; });
for (const invalidPort of ['80', 0, 65536, 80.1, null, {}, true]) {
  invalidCase('Invalid port ' + JSON.stringify(invalidPort) + ' is rejected',
    r => { r.sites[0].bound_domains = [{ name: 'site.example.test', port: invalidPort }]; });
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
  r => {
    r.sites[0].bound_domains = Array.from({length:1001}, (_,i) =>
      ({name:i === 0 ? 'site.example.test' : 'x'+i+'.test',port:80}));
  });

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


const monitorOverview = (overrides = {}) => ({
  status: true,
  mode: 'Monitor',
  notice: 'Read-only Monitor controls',
  enforcement: false,
  state_schema: 1,
  state_revision: 0,
  overall_enabled: true,
  modules_enabled: {site_inventory: true, php_fpm_file_preview: true},
  ...overrides
});

test('Native overview shows all three safe Monitor switches and revision', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  const state = ui.state();
  assert.equal(state.overview, 'Monitor — Read-only Monitor controls');
  assert.equal(state.stateRevision, 'State revision: 0');
  for (const flag of Object.values(state.controls)) {
    assert.equal(flag.checked, true);
    assert.equal(flag.disabled, false);
  }
  assert.equal(state.error, '');
});

test('Overall Monitor disable updates only the intended switch and preserves module preferences', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  ui.toggleMonitor('overall', false);
  const pending = ui.requests.at(-1);
  assert.match(pending.options.url, /s=set_control$/);
  assert.equal(pending.options.type, 'POST');
  assert.equal(pending.options.data.control, 'overall');
  assert.equal(pending.options.data.enabled, 'false');
  assert.equal(pending.options.data.expected_revision, 0);
  assert.equal(ui.state().controls.overall.disabled, true);
  ui.respondControl(monitorOverview({
    mode: 'Disabled',
    notice: 'Monitoring is disabled',
    overall_enabled: false,
    state_revision: 1
  }));
  const current = ui.state();
  assert.equal(current.stateRevision, 'State revision: 1');
  assert.equal(current.controls.overall.checked, false);
  assert.equal(current.controls.site_inventory.checked, true);
  assert.equal(current.controls.php_fpm_file_preview.checked, true);
  assert.equal(current.controls.overall.disabled, false);
  assert.equal(current.error, '');
});

test('Module-level disable does not enable enforcement or disable unrelated modules', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  ui.toggleMonitor('site_inventory', false);
  assert.equal(ui.requests.at(-1).options.data.control, 'site_inventory');
  assert.equal(ui.requests.at(-1).options.data.enabled, 'false');
  assert.equal(ui.requests.at(-1).options.data.expected_revision, 0);
  ui.respondControl(monitorOverview({
    state_revision: 1,
    modules_enabled: {site_inventory: false, php_fpm_file_preview: true}
  }));
  const current = ui.state();
  assert.equal(current.controls.overall.checked, true);
  assert.equal(current.controls.site_inventory.checked, false);
  assert.equal(current.controls.php_fpm_file_preview.checked, true);
  assert.equal(current.stateRevision, 'State revision: 1');
});

test('Failed Monitor state update restores previous switches and exposes backend error', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  ui.toggleMonitor('overall', false);
  ui.respondControl({status: false, stage: 'monitor_authorization',
    msg: 'Primary administrator required', operation_id: 'op123'});
  const current = ui.state();
  assert.equal(current.controls.overall.checked, true);
  assert.equal(current.controls.overall.disabled, false);
  assert.equal(current.stateRevision, 'State revision: 0');
  assert.match(current.error, /monitor_authorization: Primary administrator required/);
  assert.match(current.error, /op123/);
  assert.equal(current.errorClass, true);
});

test('Unexpected Monitor state schema disables all state controls without claiming success', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_schema: 2}));
  const current = ui.state();
  assert.match(current.error, /Monitor state API mismatch/);
  assert.equal(current.stateRevision, 'Monitor state unavailable');
  assert.equal(Object.values(current.controls).every(flag => flag.disabled), true);
  const requests = ui.requests.length;
  ui.toggleMonitor('overall', false);
  assert.equal(ui.requests.length, requests);
});

test('Stale control revision fails visibly without repeating the conflicting mutation', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_revision: 4}));
  ui.toggleMonitor('overall', false);
  assert.equal(ui.requests.at(-1).options.data.expected_revision, 4);
  ui.respondControl({
    status: false,
    stage: 'monitor_state_write',
    msg: 'Monitor state revision changed; reopen Overview before retrying',
    operation_id: 'conflict'
  });
  const current = ui.state();
  assert.equal(current.controls.overall.checked, true);
  assert.equal(current.controls.overall.disabled, false);
  assert.match(current.error, /revision changed/);
  assert.equal(ui.requests.length, 2);
  ui.openOverview();
  ui.respondOverview(monitorOverview({state_revision: 5, overall_enabled: false, mode: 'Disabled'}));
  assert.equal(ui.state().controls.overall.checked, false);
  assert.equal(ui.state().stateRevision, 'State revision: 5');
});


const phpImpact = (overrides = {}) => ({
  schema: 1, scope: 'shared_service', state: 'File Mapping', version: '85',
  matched_sites: [
    {id: 3, site_key: 'site-a.test'},
    {id: 6, site_key: '<img src=x onerror=alert(1)>'}
  ],
  unresolved_sites: [], site_count: 3, other_php_sites_count: 1,
  dependency_sha256: 'e'.repeat(64),
  reason: '', note: 'File-only attribution, not effective runtime.',
  ...overrides
});
const phpPreview = (impact = phpImpact()) => ({
  status: true, state: 'File Drift', scope: 'shared_service', version: '85',
  source: '/www/server/php/85/etc/php-fpm.conf', note: 'No Apply',
  changes: [{setting:'pm.max_children', desired:50, actual:80}],
  shared_impact: impact
});

test('Native PHP preview shows two shared file-linked websites safely without implying Apply', () => {
  const ui = loadUi();
  const request = ui.submitPhp();
  assert.match(request.options.url, /s=preview_php_fpm$/);
  assert.equal(request.options.data.php_version, '85');
  request.respond(phpPreview());
  const result = ui.state();
  assert.deepEqual(result.impactRows, [
    ['3', 'site-a.test', 'PHP 85 (file only)'],
    ['6', '<img src=x onerror=alert(1)>', 'PHP 85 (file only)']
  ]);
  assert.match(result.impactSummary, /File mapping: 2 site\(s\)/);
  assert.match(result.impactSummary, /not effective runtime/);
  assert.equal(result.errorClass, false);
});

test('Incomplete shared mapping shows partial evidence and visible Needs Review', () => {
  const ui = loadUi();
  ui.submitPhp().respond(phpPreview(phpImpact({
    state: 'Needs Review',
    unresolved_sites: [{id: 9, site_key: 'site-unknown', reason: 'VHost PHP assignment needs review'}],
    site_count: 4,
    reason: 'Unresolved website'
  })));
  const result = ui.state();
  assert.equal(result.impactRows.length, 3);
  assert.deepEqual(result.impactRows.at(-1),
    ['9', 'site-unknown', 'Needs Review: VHost PHP assignment needs review']);
  assert.match(result.impactSummary, /Needs Review/);
  assert.match(result.impactSummary, /1 unresolved/);
});

test('Invalid or stale shared impact API never invents affected sites', () => {
  for (const invalid of [
    null,
    phpImpact({schema:2}),
    phpImpact({version:'84'}),
    phpImpact({matched_sites:[{id:3,site_key:'A'},{id:3,site_key:'B'}]}),
    phpImpact({unresolved_sites:[{id:9,site_key:'unknown'}]})
  ]) {
    const ui = loadUi();
    ui.submitPhp().respond(phpPreview(invalid));
    const result = ui.state();
    assert.deepEqual(result.impactRows, []);
    assert.match(result.impactSummary, /unavailable/);
    assert.match(result.error, /Shared impact API mismatch/);
    assert.equal(result.errorClass, true);
  }
});

test('Backend PHP preview error clears any previously presented site attribution', () => {
  const ui = loadUi();
  ui.submitPhp().respond(phpPreview());
  assert.equal(ui.state().impactRows.length, 2);
  ui.submitPhp().respond({status:false,stage:'php_fpm_file_preview',
    msg:'Unsupported configuration', operation_id:'err'});
  assert.deepEqual(ui.state().impactRows, []);
  assert.match(ui.state().impactSummary, /unavailable/);
  assert.match(ui.state().error, /Unsupported configuration/);
});

const guardedPlan = (overrides = {}) => ({
  status: true, request_id: 'request-id', monitor_revision: 7,
  approval_scope: 'PHP85-www-shared-service', warning: 'All users may be affected.',
  impact_sha256: 'c'.repeat(64),
  plan: {version:'85', pool:'www', scope:'shared_service',
    source:'/www/server/php/85/etc/php-fpm.conf',
    before_sha256:'a'.repeat(64), after_sha256:'b'.repeat(64)},
  shared_impact: phpImpact(), ...overrides
});

const recoveryPreview = (overrides = {}) => ({
  status: true, version: '85', state: 'Applied', phase: 'applied',
  operation_id: 'd'.repeat(32), safe_rollback_file_match: true,
  baseline_sha256: 'a'.repeat(64), applied_sha256: 'b'.repeat(64),
  observed_sha256: 'b'.repeat(64), impact_sha256: 'c'.repeat(64),
  recovery_decision_sha256: 'f'.repeat(64),
  shared_impact: phpImpact(), warning: 'Shared service reload affects current sites.',
  baseline_values: {'pm.max_children': 50, 'pm.start_servers': 5,
    'pm.min_spare_servers': 5, 'pm.max_spare_servers': 20, 'pm.max_requests': 0},
  observed_values: {'pm.max_children': 20, 'pm.start_servers': 5,
    'pm.min_spare_servers': 5, 'pm.max_spare_servers': 10, 'pm.max_requests': 300},
  restoration_changes: [
    {setting:'pm.max_children', current:20, baseline:50},
    {setting:'pm.max_spare_servers', current:10, baseline:20},
    {setting:'pm.max_requests', current:300, baseline:0}
  ],
  ...overrides
});

test('A valid manual PHP-FPM action requires preview, fresh prepare and explicit approval', () => {
  const ui = loadUi();
  assert.notEqual(ui.state().fpmPrepareDisabled, false);
  const preview = ui.submitPhp();
  preview.respond(phpPreview());
  assert.equal(ui.state().fpmPrepareDisabled, false);
  const prep = ui.prepareFpm();
  assert.match(prep.options.url, /s=fpm_prepare$/);
  assert.equal(prep.options.data.php_version, '85');
  prep.respond(guardedPlan());
  assert.equal(ui.state().fpmReviewHidden, false);
  assert.match(ui.state().fpmDetails, /PHP 85 \[www\] shared/);
  assert.equal(ui.state().fpmCommitDisabled, true);
  ui.approveFpm(true);
  assert.equal(ui.state().fpmCommitDisabled, false);
  const changed = ui.commitFpm();
  assert.match(changed.options.url, /s=fpm_apply$/);
  assert.equal(changed.options.timeout, 120000);
  assert.equal(changed.options.data.expected_revision, 7);
  assert.equal(changed.options.data.expected_impact, 'c'.repeat(64));
  assert.equal(changed.options.data.expected_before, 'a'.repeat(64));
  assert.equal(changed.options.data.approved_scope, 'PHP85-www-shared-service');
  changed.respond({status:true, state:'Applied', operation_id:'d'.repeat(32), audit_logged:true});
  assert.match(ui.state().fpmPlan, /Applied/);
  assert.equal(ui.state().fpmPrepareDisabled, true);
  assert.notEqual(ui.state().fpmReviewHidden, false);
  const recovery = ui.inspectFpmRecovery();
  assert.match(recovery.options.url, /s=fpm_recovery$/);
  recovery.respond(recoveryPreview());
  assert.equal(ui.state().fpmRollbackHidden, false);
  assert.match(ui.state().fpmRecoveryImpact, /3: site-a.test/);
  assert.match(ui.state().fpmRecoveryImpact, /6: <img src=x/);
  assert.deepEqual(ui.state().fpmRestoreRows, [
    ['pm.max_children', '20', '50'],
    ['pm.start_servers', '5', '5'],
    ['pm.min_spare_servers', '5', '5'],
    ['pm.max_spare_servers', '10', '20'],
    ['pm.max_requests', '300', '0']
  ]);
  assert.equal(ui.state().fpmRollbackDisabled, true);
  ui.approveFpmRollback(true);
  assert.equal(ui.state().fpmRollbackDisabled, false);
  const rollback = ui.rollbackFpm();
  assert.match(rollback.options.url, /s=fpm_rollback$/);
  assert.equal(rollback.options.timeout, 120000);
  assert.equal(rollback.options.data.operation_id, 'd'.repeat(32));
  assert.equal(rollback.options.data.expected_impact, 'c'.repeat(64));
  assert.equal(rollback.options.data.expected_recovery, 'f'.repeat(64));
  rollback.respond({status:true, state:'Rolled Back', restored_sha256:'a'.repeat(64), audit_logged:true});
  assert.match(ui.state().fpmRecovery, /Rolled Back/);
  assert.equal(ui.state().fpmRollbackDisabled, true);
});

test('PHP-FPM form edits invalidate approval and prevent a stale UI Apply request', () => {
  const ui = loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  ui.changePhp('max_children', '19');
  assert.equal(ui.state().fpmCommitDisabled, true);
  assert.match(ui.state().fpmPlan, /fresh read-only preview/);
  const count = ui.requests.length;
  ui.commitFpm();
  assert.equal(ui.requests.length, count);
});

test('Unknown PHP impact or unsupported version never exposes an Apply workflow', () => {
  for (const [version, impact] of [
    ['84', phpImpact({version:'84'})],
    ['85', phpImpact({state:'Needs Review', unresolved_sites:[{id:9,site_key:'other',reason:'Unknown'}], site_count:4})]
  ]) {
    const ui = loadUi();
    ui.submitPhp(version).respond(phpPreview(impact));
    assert.equal(ui.state().fpmPrepareDisabled, true);
    const count = ui.requests.length;
    ui.prepareFpm();
    assert.equal(ui.requests.length, count);
  }
});

test('Malformed manual PHP-FPM preparation fails closed without write', () => {
  for (const bad of [guardedPlan({impact_sha256:'bad'}),
    guardedPlan({approval_scope:'no'}),
    guardedPlan({shared_impact:phpImpact({state:'Needs Review'})})]) {
    const ui = loadUi();
    ui.submitPhp().respond(phpPreview());
    ui.prepareFpm().respond(bad);
    assert.equal(ui.state().fpmCommitDisabled, true);
    assert.equal(ui.state().fpmPrepareDisabled, true);
    assert.match(ui.state().error, /API mismatch/);
  }
});

test('Unknown or stale recovery data cannot enable shared-service rollback', () => {
  for (const invalid of [
    recoveryPreview({shared_impact:phpImpact({state:'Needs Review',
      unresolved_sites:[{id:9,site_key:'uncertain',reason:'Indirect routing'}], site_count:4})}),
    recoveryPreview({recovery_decision_sha256:'bad'}),
    recoveryPreview({impact_sha256:'bad'}),
    recoveryPreview({baseline_values:null}),
    recoveryPreview({safe_rollback_file_match:false,
      manual_recovery:'Preserved; supervised manual restoration required.'})
  ]) {
    const ui = loadUi();
    ui.inspectFpmRecovery().respond(invalid);
    assert.equal(ui.state().fpmRollbackHidden, true);
    assert.equal(ui.state().fpmRollbackDisabled, true);
    assert.deepEqual(ui.state().fpmRestoreRows, []);
    const count = ui.requests.length;
    ui.approveFpmRollback(true);
    ui.rollbackFpm();
    assert.equal(ui.requests.length, count, 'No unapproved Rollback request');
  }
});

test('Changed recovery inspection revokes previous approval and clears stale values', () => {
  const ui = loadUi();
  ui.inspectFpmRecovery().respond(recoveryPreview());
  ui.approveFpmRollback(true);
  assert.equal(ui.state().fpmRollbackDisabled, false);
  ui.inspectFpmRecovery().respond(recoveryPreview({state:'Needs Review',
    safe_rollback_file_match:false, impact_reason:'site changed',
    manual_recovery:'Evidence preserved', shared_impact:phpImpact({state:'Needs Review'})}));
  assert.equal(ui.state().fpmRollbackHidden, true);
  assert.deepEqual(ui.state().fpmRestoreRows, []);
  assert.match(ui.state().fpmRecoveryImpact, /site changed/);
});

test('Failed Apply is not retried and user can inspect recovery status', () => {
  const ui = loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  ui.commitFpm().reject(null, 'timeout');
  assert.match(ui.state().error, /Outcome unknown/);
  assert.match(ui.state().fpmPlan, /Inspect saved recovery/);
  assert.equal(ui.state().fpmCommitDisabled, true);
  const requests = ui.requests.length;
  ui.commitFpm();
  assert.equal(ui.requests.length, requests);
  ui.inspectFpmRecovery().respond({status:true, state:'Needs Review',
    operation_id:'d'.repeat(32), safe_rollback_file_match:false});
  assert.equal(ui.state().fpmRollbackHidden, true);
});

test('Manual host change success never hides missing aaPanel audit persistence', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  ui.commitFpm().respond({status:true,state:'Applied',operation_id:'f'.repeat(32),
    audit_logged:false,audit_warning:'aaPanel activity-log persistence was not confirmed'});
  const state=ui.state();
  assert.match(state.fpmPlan,/Applied/);
  assert.equal(state.errorClass,true);
  assert.match(state.error,/activity-log persistence/);
});

test('Completed PHP Apply reports both missing audit and plugin Activity writes', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  ui.commitFpm().respond({status:true,state:'Applied',operation_id:'a'.repeat(32),
    audit_logged:false,audit_warning:'Native audit persistence failed',
    activity_logged:false,activity_warning:'Plugin Activity persistence failed'});
  assert.match(ui.state().fpmPlan,/Applied/);
  assert.match(ui.state().error,/Native audit persistence failed/);
  assert.match(ui.state().error,/Plugin Activity persistence failed/);
});

const brand = () => ({
  brand_name:'ACh', tagline:'WEB SYSTEMS', brand_url:'https://ach.li',
  brand_label:'ach.li',accent:'#008b92',background:'#f4f2eb',
  foreground:'#0b1718',footer_enabled:true
});
function statusPrefs(revision = 2, source = 'Global default', effective = brand()) {
  return {
    status:true, schema:1, revision, apply_supported:false, mode:'Preview only',
    global:brand(), effective, source, site_id:null,
    templates:['403','404','429','500','502','503','504','50x','new-site','stopped','unbound'],
    locales:['en','fa']
  };
}

test('Status Pages tab loads saved branding and safely renders sandbox-only preview', () => {
  const ui=loadUi();
  const initial=ui.openStatus();
  assert.match(initial.options.url, /s=status_preferences$/);
  assert.equal(initial.options.data.site_id,'');
  initial.respond(statusPrefs());
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.match(ui.state().statusSource,/Global default.*revision 2/);
  ui.statusSetValue('#ach-status-name','Acme');
  ui.statusSetValue('#ach-status-url','https://acme.example');
  const preview=ui.statusClick('#ach-status-preview-button');
  assert.match(preview.options.url,/s=status_preview$/);
  assert.equal(preview.options.data.brand_name,'Acme');
  assert.equal(preview.options.data.brand_url,'https://acme.example');
  assert.equal(preview.options.data.locale,'en');
  assert.equal(preview.options.data.template,'404');
  preview.respond({
    status:true,schema:1,locale:'en',template:'404',
    source:'Unsaved preview',apply_supported:false,
    html:'<!doctype html><html><body>Acme &amp; HQ</body></html>',
    source_sha256:'a'.repeat(64),rendered_sha256:'b'.repeat(64)
  });
  assert.match(ui.state().statusHtml,/Acme &amp; HQ/);
  assert.match(ui.state().statusHash,/Rendered SHA-256: b/);
  assert.match(ui.state().statusResult,/No site changes/);
  ui.statusSetValue('#ach-status-locale','fa','change');
  assert.equal(ui.state().statusHtml,'','Changed locale invalidates stale preview');
  assert.equal(ui.state().statusHash,'');
});

test('Status Pages save is revision-bound and failed response requires recheck', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs(4));
  ui.statusSetValue('#ach-status-name','New brand');
  const save=ui.statusClick('#ach-status-save');
  assert.match(save.options.url,/s=status_save$/);
  assert.equal(save.options.data.action,'save');
  assert.equal(save.options.data.expected_revision,'4');
  assert.equal(save.options.data.scope,'global');
  save.respond({status:false,stage:'status_settings',msg:'Branding was changed elsewhere'});
  assert.equal(ui.state().statusSaveDisabled,true);
  assert.match(ui.state().statusResult,/Recheck before retrying/);
  assert.match(ui.state().error,/Branding was changed elsewhere/);
});

test('Status Pages site override is explicit and reset needs confirmation', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.state().statusSaveDisabled,true,'Missing site ID must block mutations');
  ui.statusSetValue('#ach-status-site-id','7','change');
  const load=ui.requests.at(-1);
  assert.match(load.options.url,/s=status_preferences$/);
  assert.equal(load.options.data.site_id,'7');
  load.respond(statusPrefs(5,'Site override',{
    ...brand(),brand_name:'Site Seven',brand_url:'https://site7.example'
  }));
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.equal(ui.state().statusResetDisabled,true);
  ui.statusSetChecked('#ach-status-reset-approve',true);
  assert.equal(ui.state().statusResetDisabled,false);
  const reset=ui.statusClick('#ach-status-reset');
  assert.equal(reset.options.data.scope,'site');
  assert.equal(reset.options.data.site_id,'7');
  assert.equal(reset.options.data.action,'reset');
  assert.equal(reset.options.data.expected_revision,'5');
  reset.respond({
    status:true,schema:1,revision:6,changed:true,
    source:'Global default',effective:brand()
  });
  assert.equal(ui.state().statusResetDisabled,true);
  assert.match(ui.state().statusResult,/reset for this scope only/);
});

test('Status Pages rejects malformed preview and never renders fallback HTML', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs(1));
  ui.statusClick('#ach-status-preview-button').respond({
    status:true,schema:1,template:'404',locale:'en',
    html:'<script>alert(1)</script>',apply_supported:true,
    source_sha256:'a'.repeat(64),rendered_sha256:'b'.repeat(64)
  });
  assert.equal(ui.state().statusHtml,'');
  assert.match(ui.state().statusResult,/Preview failed or response incompatible/);
});

const statusInspection = (overrides = {}) => ({
  status:true, schema:1, site_id:7, site_key:'demo.test',
  locale:'en', template:'404', state:'Unmanaged', reason:'Not installed',
  read_only:true, apply_supported:false, nginx_runtime_verified:false,
  rendered_sha256:'a'.repeat(64), page_file:'404.html',
  page_file_state:'Absent',page_file_sha256:null,page_file_bytes:null,
  vhost_sha256:'b'.repeat(64),extension_include_textual:true,
  extensions_scanned:['site_total.conf'],error_page_sources:[],
  note:'Textual source only; no HTTP verification.',...overrides
});

test('Site inspection is scoped, read-only, renders a bounded disk/source diagnosis', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  assert.equal(ui.state().statusInspectDisabled,true, 'Global scope cannot inspect a site');
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.state().statusInspectDisabled,true, 'Site ID is required');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs(7));
  assert.equal(ui.state().statusInspectDisabled,false);
  ui.statusSetValue('#ach-status-site-id','8');
  const requestCount=ui.requests.length;
  ui.statusClick('#ach-status-inspect-button');
  assert.equal(ui.requests.length,requestCount,'Inspect cannot silently use branding loaded for another site ID');
  ui.statusSetValue('#ach-status-site-id','7');
  ui.statusSetValue('#ach-status-name','Acme');
  const req=ui.statusClick('#ach-status-inspect-button');
  assert.match(req.options.url,/s=status_inspect$/);
  assert.equal(req.options.data.site_id,'7');
  assert.equal(req.options.data.template,'404');
  assert.equal(req.options.data.brand_name,'Acme');
  assert.equal(ui.state().statusInspectDisabled,true, 'Prevent duplicate read while busy');
  req.respond(statusInspection());
  assert.match(ui.state().statusInspect,/State: Unmanaged/);
  assert.match(ui.state().statusInspect,/VHost SHA-256:/);
  assert.match(ui.state().statusInspect,/Textual source only/);
  assert.doesNotMatch(ui.state().statusInspect,/HTTP status verified|Apply ready/);
  assert.equal(ui.state().statusInspectDisabled,false);
  ui.statusSetValue('#ach-status-template','new-site','change');
  assert.equal(ui.state().statusInspectDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-inspect-button');
  assert.equal(ui.requests.length,count, 'Unsupported page does not invoke endpoint');
  assert.match(ui.state().statusInspect,/not run/);
});

test('Invalid, cross-site and routing-overclaim inspection replies fail closed', () => {
  for (const bad of [
    statusInspection({site_id:8}),
    statusInspection({schema:2}),
    statusInspection({read_only:false}),
    statusInspection({apply_supported:true}),
    statusInspection({nginx_runtime_verified:true}),
    statusInspection({vhost_sha256:'bad'}),
    statusInspection({state:'Installed'}),
    statusInspection({page_file_state:'Applied'}),
    statusInspection({extensions_scanned:['x'.repeat(512)]}),
    statusInspection({page_file:'../../etc/passwd'}),
    statusInspection({error_page_sources:null}),
    statusInspection({state:'File Match'}),
    statusInspection({state:'Unmanaged',page_file_state:'Same bytes',page_file_sha256:'a'.repeat(64),page_file_bytes:20}),
    statusInspection({state:'Conflict',page_file_state:'Absent'}),
    statusInspection({page_file_state:'Absent',page_file_sha256:'a'.repeat(64)}),
    statusInspection({page_file_state:'Same bytes',page_file_sha256:'b'.repeat(64),page_file_bytes:20}),
    statusInspection({page_file_state:'Different bytes',page_file_sha256:'a'.repeat(64),page_file_bytes:20})
  ]) {
    const ui=loadUi();
    ui.openStatus().respond(statusPrefs());
    ui.statusSetValue('#ach-status-scope','site','change');
    ui.statusSetValue('#ach-status-site-id','7','change');
    ui.requests.at(-1).respond(statusPrefs());
    ui.statusClick('#ach-status-inspect-button').respond(bad);
    assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
    assert.doesNotMatch(ui.state().statusInspect,/State: Installed|State: File Match/);
  }
});

test('Backend inspection failure does not display previous disk-match evidence', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
    state:'File Match',page_file_state:'Same bytes',
    page_file_sha256:'a'.repeat(64),page_file_bytes:50
  }));
  assert.match(ui.state().statusInspect,/State: File Match/);
  ui.statusClick('#ach-status-inspect-button').respond({
    status:false,stage:'status_inspect',msg:'Native VHost changed'
  });
  assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
  assert.match(ui.state().error,/Native VHost changed/);
});

test('Native sidebar sections are linked to panels and scrollable content', () => {
  for (const name of ['overview','websites','php','status','activity']) {
    assert.match(html, new RegExp('id="ach-tab-' + name + '"[^>]*aria-controls="ach-panel-' + name + '"'));
    assert.match(html, new RegExp('id="ach-panel-' + name + '"[^>]*aria-labelledby="ach-tab-' + name + '"'));
  }
  assert.match(html, /\.ach-main \{[^}]*overflow-y:auto/);
  assert.match(html, /\.ach-workspace \{[^}]*grid-template-columns:190px/);
  assert.match(html, /@media \(max-width:720px\)/);
  assert.doesNotMatch(html, /class="ach-tabs"/);
  assert.match(html, /function fitNativeLayer/);
});

test('Activity panel filters read-only structured events and uses text rendering', () => {
  const ui = loadUi();
  const req = ui.openActivity();
  assert.match(req.options.url, /s=get_activity$/);
  assert.equal(req.options.data.limit, 50);
  req.respond({
    status:true, schema:1, read_only:true, configured_level:'INFO',
    entries:[{schema:1,time_utc:'2026-11-03T00:00:00+00:00',
      level:'ERROR',module:'php_fpm',action:'fpm_apply',
      stage:'reload',outcome:'failed',error_class:'FpmApplyError',
      detail:'<img src=x onerror=alert(1)>',operation_id:'a'.repeat(32),
      recovery_id:'b'.repeat(32),target:'PHP85-www-shared-service'}]
  });
  assert.equal(ui.activityRows().length, 1);
  assert.equal(ui.activityRows()[0][3], 'failed · reload (FpmApplyError): <img src=x onerror=alert(1)>');
  assert.match(ui.activityMessage(), /1 record\(s\)/);
  const filtered = ui.activityFilter('#ach-activity-level', 'ERROR');
  assert.equal(filtered.options.data.level, 'ERROR');
  filtered.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.deepEqual(ui.activityRows(), [['No matching activity records.']]);
});

test('Activity errors clear stale records and do not invent successful logs', () => {
  const ui=loadUi();
  ui.openActivity().respond({status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[{schema:1,time_utc:'2026-11-03',level:'INFO',module:'websites',
      action:'inventory',stage:'complete',outcome:'success',error_class:'',
      detail:'',operation_id:'c'.repeat(32),recovery_id:'',target:''}]});
  assert.equal(ui.activityRows().length, 1);
  ui.activityFilter('#ach-activity-module','websites').respond({
    status:true,schema:1,read_only:true,configured_level:'INFO',entries:[
      {schema:1,level:'WARNING',time_utc:'x',operation_id:'malformed',detail:'',module:'websites',
       action:'inventory',stage:'complete',outcome:'success',error_class:'',recovery_id:''}]
  });
  assert.deepEqual(ui.activityRows(), []);
  assert.match(ui.activityMessage(), /unavailable or incompatible/);
});

test('Website-scope branding selects only native inventory IDs, not manually typed IDs', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const inventory = ui.requests.at(-1);
  assert.match(inventory.options.url, /s=status_sites$/);
  const seven = {...site(), id:7, name:'site-seven.test',
    bound_domains:[{name:'site-seven.test',port:80}],canonical_domain_bound:true};
  inventory.respond({...page([seven]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSiteChoices(), [
    {id:'',text:'Choose a website...'},
    {id:'7',text:'site-seven.test (ID 7)'}
  ]);
  assert.equal(ui.statusSiteDisabled(),false);
  assert.match(ui.statusSiteInfo(),/1 website\(s\) loaded/);
  ui.statusSetValue('#ach-status-site-id','7','change');
  const load=ui.requests.at(-1);
  assert.match(load.options.url,/s=status_preferences$/);
  assert.equal(load.options.data.site_id,'7');
});

test('Invalid website inventory prevents selecting a site to mutate branding', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.requests.at(-1).respond({status:true,inventory_schema:3,sites:[]});
  assert.equal(ui.statusSiteDisabled(),true);
  assert.match(ui.statusSiteInfo(), /inventory unavailable or changed/);
  assert.equal(ui.state().statusSaveDisabled,true);
});


test('Stale website inventory response cannot enable site selector in global branding mode', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const stale=ui.requests.at(-1);
  ui.statusSetValue('#ach-status-scope','global','change');
  stale.respond({...page([site()]),purpose:'status_site_selection'});
  assert.equal(ui.statusSiteDisabled(),true);
  assert.deepEqual(ui.statusSiteChoices(),
    [{id:'',text:'Select website scope first'}]);
});

test('Website inventory failure supports an explicit refresh and no inferred site', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.requests.at(-1).respond({status:true,inventory_schema:999});
  assert.equal(ui.statusSiteDisabled(),true);
  assert.match(ui.statusSiteInfo(),/inventory unavailable/);
  const refresh=ui.statusClick('#ach-status-sites-retry');
  assert.match(refresh.options.url,/s=status_sites$/);
  refresh.respond({...page([site()]),purpose:'status_site_selection'});
  assert.equal(ui.statusSiteDisabled(),false);
  assert.equal(ui.statusSiteChoices()[1].id,'3');
});

test('Legacy Monitor-only endpoint reply cannot be trusted for Status Pages selector', () => {
  const ui = loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const req=ui.requests.at(-1);
  assert.match(req.options.url,/s=status_sites$/);
  req.respond(page([site()])); // Old/mismatched backend without purpose marker.
  assert.equal(ui.statusSiteDisabled(),true);
  assert.match(ui.statusSiteInfo(), /inventory unavailable or changed/);
});


test('Returning to website scope cannot consume a prior in-flight site list', () => {
  const ui = loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const older = ui.requests.at(-1);
  ui.statusSetValue('#ach-status-scope','global','change');
  ui.statusSetValue('#ach-status-scope','site','change');
  const newer = ui.requests.at(-1);
  assert.notEqual(older, newer);
  const oldSite = {...site(),id:3,name:'old.example.test'};
  older.respond({...page([oldSite]),purpose:'status_site_selection'});
  assert.equal(ui.statusSiteDisabled(),true);
  const newSite = {...site(),id:7,name:'new.example.test',
    bound_domains:[{name:'new.example.test',port:80}]};
  newer.respond({...page([newSite]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSiteChoices(),[
    {id:'',text:'Choose a website...'},
    {id:'7',text:'new.example.test (ID 7)'}
  ]);
});

test('Newest Activity filter wins when responses arrive out of order', () => {
  const ui=loadUi();
  const earlier=ui.openActivity();
  const later=ui.activityFilter('#ach-activity-level','ERROR');
  assert.equal(later.options.data.level,'ERROR');
  const row = (level,id)=>({schema:1,time_utc:'2026-11-03T04:00:00+00:00',
    level,module:'php_fpm',action:'fpm_apply',stage:'complete',
    outcome:level==='ERROR'?'failed':'success',
    error_class:'',detail:'',operation_id:id.repeat(32),
    recovery_id:'',target:'PHP85-www-shared-service'});
  later.respond({status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[row('ERROR','e')]});
  earlier.respond({status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[row('INFO','a')]});
  assert.equal(ui.activityRows().length,1);
  assert.match(ui.activityRows()[0][1],/ERROR/);
  assert.match(ui.activityRows()[0][4],/^e{32}/);
  assert.match(ui.activityMessage(),/1 record/);
});


test('A stale Activity request error cannot replace the newest filter message', () => {
  const ui=loadUi();
  const earlier=ui.openActivity();
  const later=ui.activityFilter('#ach-activity-module','php_fpm');
  later.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  earlier.respond({status:false,stage:'activity_read',msg:'stale background error',
    operation_id:'a'.repeat(32)});
  assert.equal(ui.state().error,'');
  assert.match(ui.activityMessage(),/0 record/);
});

test('Oversized Activity record is rejected before it reaches a table row', () => {
  const ui=loadUi();
  ui.openActivity().respond({status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[{schema:1,time_utc:'2026-11-03',level:'ERROR',
      module:'status_pages',action:'status_preview',stage:'complete',
      outcome:'failed',error_class:'StatusPageError',detail:'x'.repeat(4096),
      operation_id:'d'.repeat(32),recovery_id:'',target:''}]});
  assert.deepEqual(ui.activityRows(),[]);
  assert.match(ui.activityMessage(),/unavailable or incompatible/);
});
