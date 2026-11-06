'use strict';

// Execute the shipped inline script against a narrow jQuery-like DOM harness.
// No copied validator logic, browser installation, network or npm dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {TextEncoder} = require('node:util');

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
  for (const tab of tabs) elements.set('#ach-tab-' + tab.attributes['data-tab'], tab);
  for (const name of [
    '#ach-message', '#ach-overview-status', '#ach-overview-control-result', '#ach-overview-refresh',
    '#ach-sites-rows', '#ach-sites-loading', '#ach-sites-status', '#ach-sites-refresh',
    '#ach-site-changes-compare', '#ach-site-changes-approve',
    '#ach-site-changes-save', '#ach-site-changes-status', '#ach-site-changes-rows',
    '#ach-hosts-site-id', '#ach-hosts-inspect-button', '#ach-hosts-result',
    '#ach-page', '#ach-prev', '#ach-next', '#ach-php-form',
    '#ach-fpm-result', '#ach-diff-rows', '#ach-state-revision',
    '#ach-impact-summary', '#ach-impact-rows',
    '#ach-php-version', '#ach-php-discover', '#ach-php-discovery-status',
    '#ach-fpm-prepare', '#ach-fpm-plan', '#ach-fpm-operation-notice', '#ach-fpm-review',
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
    '#ach-status-probe-button', '#ach-status-probe-result',
    '#ach-status-comparison-summary', '#ach-status-comparison-excerpt',
    '#ach-status-sites-more', '#ach-status-sites-retry', '#ach-status-sites-state',
    '#ach-activity-level', '#ach-activity-module', '#ach-activity-refresh',
    '#ach-activity-result', '#ach-activity-rows', '#ach-activity-loading'
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
  elements.get('#ach-php-version').props.value = '';
  elements.get('#ach-php-version').props.disabled = true;
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

  vm.runInNewContext(script, { $, encodeURIComponent, TextEncoder }, { timeout: 1000 });

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
  function refreshSites() {
    trigger(elements.get('#ach-sites-refresh'), 'click');
    return requests.at(-1);
  }
  function refreshOverview() {
    trigger(elements.get('#ach-overview-refresh'), 'click');
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
      hostsResult: elements.get('#ach-hosts-result').textContent,
      hostsInspectDisabled: elements.get('#ach-hosts-inspect-button').props.disabled,
      hostsSelectorDisabled: elements.get('#ach-hosts-site-id').props.disabled,
      hostsChoices: elements.get('#ach-hosts-site-id').children.map(option => ({
        id:option.props.value, text:option.textContent
      })),
      error: elements.get('#ach-message').textContent,
      errorClass: elements.get('#ach-message').classes.has('ach-error'),
      prevDisabled: elements.get('#ach-prev').props.disabled,
      nextDisabled: elements.get('#ach-next').props.disabled,
      page: elements.get('#ach-page').textContent,
      overview: elements.get('#ach-overview-status').textContent,
      overviewControlResult: elements.get('#ach-overview-control-result').textContent,
      overviewFeedbackState: elements.get('#ach-overview-control-result').attributes['data-state'],
      stateRevision: elements.get('#ach-state-revision').textContent,
      statusResult: elements.get('#ach-status-result').textContent,
      statusFeedbackState: elements.get('#ach-status-result').attributes['data-state'],
      statusSource: elements.get('#ach-status-source').textContent,
      statusName: elements.get('#ach-status-name').props.value,
      siteStatus: elements.get('#ach-sites-status').textContent,
      siteChangesStatus: elements.get('#ach-site-changes-status').textContent,
      siteChangesSaveDisabled: elements.get('#ach-site-changes-save').props.disabled,
      siteChangesApproveDisabled: elements.get('#ach-site-changes-approve').props.disabled,
      siteChangesRows: elements.get('#ach-site-changes-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      sitesSkeletonHidden: elements.get('#ach-sites-loading').props.hidden,
      sitesTableRowsHidden: elements.get('#ach-sites-rows').props.hidden,
      activitySkeletonHidden: elements.get('#ach-activity-loading').props.hidden,
      activityTableRowsHidden: elements.get('#ach-activity-rows').props.hidden,
      statusHtml: elements.get('#ach-status-iframe').props.srcdoc,
      statusHash: elements.get('#ach-status-sha').textContent,
      statusSaveDisabled: elements.get('#ach-status-save').props.disabled,
      statusResetDisabled: elements.get('#ach-status-reset').props.disabled,
      statusInspectDisabled: elements.get('#ach-status-inspect-button').props.disabled,
      statusProbeDisabled: elements.get('#ach-status-probe-button').props.disabled,
      statusProbe: elements.get('#ach-status-probe-result').textContent,
      statusInspect: elements.get('#ach-status-inspect-result').textContent,
      statusCompareSummary: elements.get('#ach-status-comparison-summary').textContent,
      statusCompareExcerpt: elements.get('#ach-status-comparison-excerpt').textContent,
      impactSummary: elements.get('#ach-impact-summary').textContent,
      phpDiscovery: elements.get('#ach-php-discovery-status').textContent,
      phpVersion: elements.get('#ach-php-version').props.value,
      phpVersionDisabled: elements.get('#ach-php-version').props.disabled,
      phpOptions: elements.get('#ach-php-version').children.map(option => ({
        value:option.props.value, disabled:option.props.disabled, text:option.textContent
      })),
      fpmPlan: elements.get('#ach-fpm-plan').textContent,
      fpmOperationNotice: elements.get('#ach-fpm-operation-notice').textContent,
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
  function phpVersions(versions = [
    {code:'81',label:'PHP 8.1',state:'File Preview Candidate',
      binary_present:true,config_present:true,preview_candidate:true,
      manual_apply_adapter:'none',apply_eligible:false,reason:'Preview only'},
    {code:'84',label:'PHP 8.4',state:'File Preview Candidate',
      binary_present:true,config_present:true,preview_candidate:true,
      manual_apply_adapter:'none',apply_eligible:false,reason:'Preview only'},
    {code:'85',label:'PHP 8.5',state:'File Preview Candidate',
      binary_present:true,config_present:true,preview_candidate:true,
      manual_apply_adapter:'guarded_php85',apply_eligible:false,reason:'Prepare required'}
  ]) {
    return {status:true,schema:1,state:'Observed',read_only:true,
      runtime_verified:false,versions,reason:'',note:'File presence, not process verification'};
  }
  function openPhp() {
    trigger(tabs.find(node => node.attributes['data-tab'] === 'php'), 'click');
    return requests.at(-1);
  }
  function submitPhp(version = '85', autoDiscover = true) {
    if (autoDiscover && elements.get('#ach-php-version').props.disabled !== false) {
      const discovered = openPhp();
      assert.match(discovered.options.url, /s=get_php_versions$/);
      discovered.respond(phpVersions());
    }
    elements.get('#ach-php-version').props.value = version;
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
  return { openSites, refreshSites, openOverview, refreshOverview,
    openStatus, statusSetValue, statusSetChecked, statusClick, openActivity,
    openPhp, refreshPhp: () => { trigger(elements.get('#ach-php-discover'), 'click'); return requests.at(-1); }, phpVersions,
    activityRefresh: () => { trigger(elements.get('#ach-activity-refresh'), 'click'); return requests.at(-1); },
    respond, respondOverview, toggleMonitor, submitPhp,
    siteChangesCompare: () => { trigger(elements.get('#ach-site-changes-compare'), 'click'); return requests.at(-1); },
    siteChangesApprove: checked => {
      elements.get('#ach-site-changes-approve').props.checked = checked;
      trigger(elements.get('#ach-site-changes-approve'), 'change');
    },
    siteChangesSave: () => { trigger(elements.get('#ach-site-changes-save'), 'click'); return requests.at(-1); },
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
  panel_status: '1',
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
    assert.equal(output.hostsInspectDisabled,true);
    assert.equal(output.hostsSelectorDisabled,true);
    assert.match(output.hostsResult,/inventory unavailable/);
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
invalidCase('Missing panel status is rejected before any hosts selector is populated',
  r => { delete r.sites[0].panel_status; });
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
  ui.refreshSites();
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
// Successful set_control acknowledgements include the backend CAS changed bit.
// Read-only get_overview responses do not carry this mutation field.
const monitorAck = (overrides = {}) => monitorOverview({changed:true, ...overrides});

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
  ui.respondControl(monitorAck({
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


test('Overview Monitor write provides nearby pending/success and unconfirmed feedback', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview());
  assert.match(ui.state().overviewControlResult,/Monitor settings verified.*Revision 0/);
  const saved=ui.toggleMonitor('overall',false);
  assert.match(ui.state().overviewControlResult,/Saving overall Monitor setting/);
  saved.respond(monitorAck({overall_enabled:false,state_revision:1,mode:'Disabled'}));
  assert.equal(ui.state().overviewFeedbackState,'saved');
  assert.match(ui.state().overviewControlResult,/Saved overall: disabled.*Revision 1/);

  const failed=ui.toggleMonitor('overall',true);
  assert.match(ui.state().overviewControlResult,/Saving overall/);
  failed.respond({status:false,stage:'monitor_state_write',msg:'revision conflict'});
  assert.equal(ui.state().overviewFeedbackState,'error');
  assert.match(ui.state().overviewControlResult,/Monitor change not confirmed.*Refresh state/);
  assert.equal(ui.state().controls.overall.disabled,true);
});

test('Module-level disable does not enable enforcement or disable unrelated modules', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  ui.toggleMonitor('site_inventory', false);
  assert.equal(ui.requests.at(-1).options.data.control, 'site_inventory');
  assert.equal(ui.requests.at(-1).options.data.enabled, 'false');
  assert.equal(ui.requests.at(-1).options.data.expected_revision, 0);
  ui.respondControl(monitorAck({
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
  assert.equal(current.controls.overall.disabled, true);
  assert.equal(current.stateRevision, 'State revision: 0');
  assert.match(current.overview, /Refresh state before retrying/);
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
  assert.equal(current.controls.overall.disabled, true);
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
  dependency_sha256: 'e'.repeat(64), manual_apply_eligible: true,
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

test('Native extension or WordPress cache mapping is visible but cannot enable Manual Apply', () => {
  const ui = loadUi();
  const request = ui.submitPhp();
  request.respond(phpPreview(phpImpact({
    manual_apply_eligible: false,
    note: 'Native extension/wpcache mapping is read-only; Apply/Restore requires clone QA.'
  })));
  const state = ui.state();
  assert.match(state.impactSummary, /File mapping: 2 site\(s\)/);
  assert.match(state.fpmPlan, /Native file mapping is read-only/);
  assert.equal(state.fpmPrepareDisabled, true);
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

const appliedResult = (overrides = {}) => ({
  status:true,state:'Applied',operation_id:'d'.repeat(32),
  version:'85',scope:'shared_service',pool:'www',
  source:'/www/server/php/85/etc/php-fpm.conf',
  before_sha256:'a'.repeat(64),after_sha256:'b'.repeat(64),
  audit_logged:true,activity_logged:true,...overrides
});
const rolledBackResult = (overrides = {}) => ({
  status:true,state:'Rolled Back',operation_id:'d'.repeat(32),
  restored_sha256:'a'.repeat(64),audit_logged:true,activity_logged:true,...overrides
});
const noChangeResult = (overrides = {}) => ({
  status:true,state:'No Change',operation_id:null,
  version:'85',scope:'shared_service',pool:'www',
  source:'/www/server/php/85/etc/php-fpm.conf',
  before_sha256:'a'.repeat(64),after_sha256:'a'.repeat(64),
  audit_logged:true,activity_logged:true,...overrides
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
  changed.respond(appliedResult());
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
  rollback.respond(rolledBackResult());
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
    recoveryPreview({baseline_sha256:'bad'}),
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
  ui.commitFpm().respond(appliedResult({operation_id:'f'.repeat(32),
    audit_logged:false,audit_warning:'aaPanel activity-log persistence was not confirmed'}));
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
  ui.commitFpm().respond(appliedResult({operation_id:'a'.repeat(32),
    audit_logged:false,audit_warning:'Native audit persistence failed',
    activity_logged:false,activity_warning:'Plugin Activity persistence failed'}));
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


const hostsInspection = (overrides={}) => ({
  status:true,schema:1,site_id:7,site_key:'site.test',
  read_only:true,fix_supported:false,resolver_verified:false,
  remote_dns_verified:false,gateway_verified:false,
  state:'Local Loopback Entry',reason:'Exact hosts entry observed',
  hosts_sha256:'a'.repeat(64),domains:['site.test'],
  uninspected_wildcards:[],
  entries:[{domain:'site.test',address:'127.0.0.2',line:3,loopback:true}],
  note:'Origin local only; Gateway unverified.',...overrides
});

const hostsInventory = (name = 'site.test') => page([
  {...site(), id:7, name, document_root:'/www/site.test',
   bound_domains:[{name:'site.test',port:80}], canonical_domain_bound:name === 'site.test'},
  {...site(), id:8, name:'other.test', document_root:'/www/other.test',
   bound_domains:[{name:'other.test',port:80}], canonical_domain_bound:true}
]);
function selectHostsSite(ui, id='7', inventory=hostsInventory()) {
  ui.openSites();
  ui.respond(inventory);
  ui.statusSetValue('#ach-hosts-site-id',id,'input change');
}

test('Native-site local hosts inspection reports loopback without claiming Gateway failure', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  const query=ui.statusClick('#ach-hosts-inspect-button');
  assert.match(query.options.url,/s=inspect_local_hosts$/);
  assert.equal(query.options.data.site_id,'7');
  assert.equal(query.options.data.expected_site_key,'site.test');
  assert.deepEqual(JSON.parse(query.options.data.expected_site_snapshot), [
    7, 'site.test', '/www/site.test', '1', [['site.test', 80]]
  ]);
  assert.equal(ui.state().hostsInspectDisabled,true);
  query.respond(hostsInspection());
  assert.match(ui.state().hostsResult,/State: Local Loopback Entry/);
  assert.match(ui.state().hostsResult,/127.0.0.2 \(loopback\)/);
  assert.match(ui.state().hostsResult,/Gateway unverified/);
  assert.equal(ui.state().hostsInspectDisabled,false);
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  assert.match(ui.state().hostsResult,/Site selection changed/);
});

test('Invalid or cross-site hosts responses cannot masquerade as confirmed result', () => {
  for (const bad of [
    hostsInspection({site_id:8}),
    hostsInspection({fix_supported:true}),
    hostsInspection({gateway_verified:true}),
    hostsInspection({resolver_verified:true}),
    hostsInspection({hosts_sha256:'bad'}),
    hostsInspection({entries:null}),
    hostsInspection({state:'Installed'}),
    hostsInspection({state:'Local Loopback Entry', entries:[]}),
    hostsInspection({state:'No Local Loopback Entry'}),
    hostsInspection({uninspected_wildcards:null}),
    hostsInspection({entries:[{domain:'wrong.test',address:'127.0.0.1',line:1,loopback:true}]})
  ]) {
    const ui=loadUi();
    selectHostsSite(ui);
    ui.statusClick('#ach-hosts-inspect-button').respond(bad);
    assert.match(ui.state().hostsResult,/unconfirmed/);
    assert.doesNotMatch(ui.state().hostsResult,/State: Local Loopback Entry/);
  }
});

test('Inventory identity mismatch rejects unrelated site keys; failed inspection clears stale evidence', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  ui.statusClick('#ach-hosts-inspect-button').respond(hostsInspection({
    site_key:'<img src=x onerror=alert(1)>'
  }));
  assert.match(ui.state().hostsResult,/unconfirmed/);
  const request=ui.statusClick('#ach-hosts-inspect-button');
  request.respond({status:false,stage:'hosts_inspection',msg:'Hosts source changed'});
  assert.match(ui.state().hostsResult,/unconfirmed/);
  assert.match(ui.state().error,/Hosts source changed/);
});

test('Discovered site selection is bounded to current inventory and text-rendered safely', () => {
  const ui=loadUi();
  const malicious='<img src=x onerror=alert(1)>';
  selectHostsSite(ui,'7',hostsInventory(malicious));
  assert.deepEqual(ui.state().hostsChoices.map(x => x.id),['','7','8']);
  assert.match(ui.state().hostsChoices[1].text,/<img src=x onerror=alert\(1\)>/);
  const r=hostsInspection({site_key:malicious});
  const request=ui.statusClick('#ach-hosts-inspect-button');
  assert.equal(request.options.data.expected_site_key,malicious);
  assert.deepEqual(JSON.parse(request.options.data.expected_site_snapshot), [
    7, malicious, '/www/site.test', '1', [['site.test', 80]]
  ]);
  request.respond(r);
  assert.match(ui.state().hostsResult,/<img src=x onerror=alert\(1\)>/);
  ui.statusSetValue('#ach-hosts-site-id','9','input change');
  assert.equal(ui.state().hostsInspectDisabled,true);
});

test('Hosts optimistic snapshot binds domains, ports, root and native status', () => {
  const ui=loadUi();
  const chosen=hostsInventory();
  const record=chosen.sites[0];
  record.panel_status='0';
  record.document_root='/www/relocated';
  record.bound_domains=[
    {name:'sub.site.test',port:8443},
    {name:'site.test',port:80},
    {name:'sub.site.test',port:443}
  ];
  record.canonical_domain_bound=true;
  selectHostsSite(ui,'7',chosen);
  const request=ui.statusClick('#ach-hosts-inspect-button');
  assert.deepEqual(JSON.parse(request.options.data.expected_site_snapshot), [
    7,'site.test','/www/relocated','0',
    [['site.test',80],['sub.site.test',443],['sub.site.test',8443]]
  ]);
  request.respond(hostsInspection());
  assert.match(ui.state().hostsResult,/State: Local Loopback Entry/);
  // Native tab reentry preserves the accepted page and selection, unlike a
  // deliberate Refresh, which revokes the snapshot before a new read.
  const requestCount=ui.requests.length;
  ui.openOverview();
  ui.openSites();
  assert.equal(ui.requests.length,requestCount,'No redundant inventory read on tab reentry');
  assert.equal(ui.state().hostsInspectDisabled,false);
  const reload=ui.refreshSites();
  assert.match(reload.options.url,/s=get_sites$/);
  assert.equal(ui.state().hostsInspectDisabled,true);
  reload.respond(hostsInventory());
});

test('Oversized website binding snapshots never create an inspectable option', () => {
  const ui=loadUi();
  const inventory=hostsInventory();
  inventory.sites[0].bound_domains=Array.from({length:101},(_,n)=>({
    name:'site'+n+'.test',port:80
  }));
  inventory.sites[0].canonical_domain_bound=false;
  ui.openSites();ui.respond(inventory);
  assert.deepEqual(ui.state().hostsChoices.map(x=>x.id),['','8']);
  assert.equal(ui.state().hostsInspectDisabled,true);
});

test('Inventory reload invalidates pending hosts inspection and stale site selection', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  const older=ui.statusClick('#ach-hosts-inspect-button');
  const reload=ui.refreshSites(); // Explicit fresh snapshot revokes old confirmation.
  assert.match(reload.options.url,/s=get_sites$/);
  assert.equal(ui.state().hostsInspectDisabled,true);
  older.respond(hostsInspection());
  assert.doesNotMatch(ui.state().hostsResult,/State: Local Loopback Entry/);
  reload.respond(page([]));
  assert.equal(ui.state().hostsSelectorDisabled,true);
  assert.equal(ui.state().hostsInspectDisabled,true);
  assert.deepEqual(ui.state().hostsChoices.map(x=>x.id),['']);
});

test('Hosts selection and pending inspection are invalidated by Monitor policy uncertainty', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:9}));
  selectHostsSite(ui);
  assert.equal(ui.state().hostsInspectDisabled,false);
  const old=ui.statusClick('#ach-hosts-inspect-button');
  ui.openOverview();
  const write=ui.toggleMonitor('site_inventory',false);
  assert.match(write.options.url,/s=set_control$/);
  assert.equal(ui.state().hostsInspectDisabled,true);
  assert.equal(ui.state().hostsSelectorDisabled,true);
  assert.deepEqual(ui.state().hostsChoices.map(x=>x.id),['']);
  const count=ui.requests.length;
  ui.openSites(); // No inventory read is permitted while policy is pending.
  ui.refreshSites(); // Even artificially dispatched disabled control must not bypass.
  assert.equal(ui.requests.length,count);
  old.respond(hostsInspection());
  assert.doesNotMatch(ui.state().hostsResult,/State: Local Loopback Entry/);
  write.reject(null,'timeout');
  ui.openSites();
  assert.equal(ui.requests.length,count);
  assert.equal(ui.state().hostsInspectDisabled,true);
  ui.openOverview();
  const refresh=ui.refreshOverview();
  assert.match(refresh.options.url,/s=get_overview$/);
  refresh.respond(monitorOverview({state_revision:9}));
  const current=ui.openSites();
  assert.match(current.options.url,/s=get_sites$/);
  assert.equal(ui.state().hostsInspectDisabled,true,'No stale selection before verified inventory read');
  current.respond(hostsInventory());
  assert.deepEqual(ui.state().hostsChoices.map(x=>x.id),['','7','8']);
  assert.equal(ui.state().hostsInspectDisabled,true,'Explicit new selection is still required');
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  assert.equal(ui.state().hostsInspectDisabled,false);
});

test('Failed or stale Website inventory cannot retain a Hosts inspection target', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  const old=ui.statusClick('#ach-hosts-inspect-button');
  const refresh=ui.refreshSites();
  assert.equal(ui.state().hostsInspectDisabled,true);
  refresh.reject(null,'timeout');
  old.respond(hostsInspection());
  assert.deepEqual(ui.state().hostsChoices.map(x=>x.id),['']);
  assert.equal(ui.state().hostsInspectDisabled,true);
  assert.doesNotMatch(ui.state().hostsResult,/State: Local Loopback Entry/);
  const retry=ui.refreshSites();
  retry.respond({status:true,inventory_schema:1});
  assert.equal(ui.state().hostsInspectDisabled,true);
  assert.equal(ui.state().hostsSelectorDisabled,true);
});

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
  assert.equal(save.options.url,'/plugin?action=a&name=ach_customizer&s=status_save');
  assert.equal(save.options.data.branding_action,'save');
  assert.equal(Object.prototype.hasOwnProperty.call(save.options.data, 'action'), false,
    'aaPanel reserves action for native plugin routing; POST must not override URL action=a');
  assert.equal(save.options.data.expected_revision,'4');
  assert.equal(save.options.data.scope,'global');
  save.respond({status:false,stage:'status_settings',msg:'Branding was changed elsewhere'});
  assert.equal(ui.state().statusSaveDisabled,true);
  assert.match(ui.state().statusResult,/Recheck saved branding before retrying/);
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
  assert.equal(reset.options.url,'/plugin?action=a&name=ach_customizer&s=status_save');
  assert.equal(reset.options.data.scope,'site');
  assert.equal(reset.options.data.site_id,'7');
  assert.equal(reset.options.data.branding_action,'reset');
  assert.equal(Object.prototype.hasOwnProperty.call(reset.options.data, 'action'), false,
    'Reset must not overwrite the native aaPanel action=a route');
  assert.equal(reset.options.data.expected_revision,'5');
  reset.respond({
    status:true,schema:1,revision:6,changed:true,
    scope:'site',site_id:7,source:'Global default',effective:brand()
  });
  assert.equal(ui.state().statusResetDisabled,true);
  assert.match(ui.state().statusResult,/reset for this scope only/);
});


test('All tabs place routine feedback by its operation rather than below long content', () => {
  function ordered(...ids) {
    const positions=ids.map(id => {
      const offset=html.indexOf('id="' + id + '"');
      assert.ok(offset > 0, 'Missing feedback/action anchor ' + id);
      return offset;
    });
    for (let i=1;i<positions.length;i++)
      assert.ok(positions[i]>positions[i-1], ids.join(' > '));
  }
  ordered('ach-overview-refresh','ach-monitor-enabled','ach-overview-control-result','ach-state-revision');
  ordered('ach-sites-status','ach-sites-refresh','ach-hosts-inspect-button','ach-hosts-result');
  ordered('ach-fpm-prepare','ach-fpm-plan','ach-fpm-operation-notice','ach-fpm-commit');
  ordered('ach-fpm-check-recovery','ach-fpm-recovery-status','ach-fpm-rollback');
  ordered('ach-status-save','ach-status-result','ach-status-reset-approve','ach-status-inspect-button');
  ordered('ach-activity-result','ach-activity-rows');
  assert.equal((html.match(/id="ach-status-result"/g) || []).length,1);
  assert.match(html,/id="ach-status-result"[^>]*aria-live="polite"/);
});

test('Status Pages Save visibly distinguishes changed, no-op, in-flight, unsaved, and uncertainty', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs(4));
  assert.match(ui.state().statusResult,/Saved preferences loaded.*Revision 4/);
  const noop=ui.statusClick('#ach-status-save');
  assert.match(ui.state().statusResult,/Saving global branding preferences/);
  noop.respond({status:true,schema:1,revision:4,changed:false,scope:'global',
    site_id:null,source:'Global default',effective:brand()});
  assert.equal(ui.state().statusFeedbackState,'saved');
  assert.match(ui.state().statusResult,/No changes needed.*Revision 4/);
  assert.equal(ui.state().statusSaveDisabled,false);
  ui.statusSetValue('#ach-status-name','Distinct brand','input change');
  assert.match(ui.state().statusResult,/Unsaved changes/);
  const save=ui.statusClick('#ach-status-save');
  assert.match(ui.state().statusResult,/Saving global branding preferences/);
  save.respond({status:true,schema:1,revision:5,changed:true,scope:'global',
    site_id:null,source:'Global default',effective:{...brand(),brand_name:'Distinct brand'}});
  assert.equal(ui.state().statusFeedbackState,'saved');
  assert.match(ui.state().statusResult,/Saved global branding preferences.*Revision 5/);
  assert.match(ui.state().statusSource,/revision 5/);
  assert.equal(ui.state().statusName,'Distinct brand');
  ui.statusSetValue('#ach-status-name','Distinct brand','input change');
  assert.match(ui.state().statusResult,/Fields match saved preferences.*Revision 5/);
  const incompatible=ui.statusClick('#ach-status-save');
  incompatible.respond({status:true,schema:1,revision:6,changed:true,
    source:'Global default',effective:brand()});
  assert.equal(ui.state().statusFeedbackState,'error');
  assert.match(ui.state().statusResult,/Save not confirmed.*Recheck/);
  assert.equal(ui.state().statusSaveDisabled,true);
});

test('Status Pages Reset distinguishes no-op and refuses mismatched acknowledgement', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs(2));
  ui.statusSetChecked('#ach-status-reset-approve',true);
  const noop=ui.statusClick('#ach-status-reset');
  assert.match(ui.state().statusResult,/Resetting global branding preferences/);
  noop.respond({status:true,schema:1,revision:2,changed:false,scope:'global',
    site_id:null,source:'Global default',effective:brand()});
  assert.match(ui.state().statusResult,/No changes needed.*Revision 2/);
  assert.equal(ui.state().statusFeedbackState,'saved');
  assert.equal(ui.state().statusResetDisabled,true);
  ui.statusSetChecked('#ach-status-reset-approve',true);
  const bad=ui.statusClick('#ach-status-reset');
  bad.respond({status:true,schema:1,revision:3,changed:true,scope:'site',
    site_id:7,source:'Global default',effective:brand()});
  assert.equal(ui.state().statusFeedbackState,'error');
  assert.match(ui.state().statusResult,/Reset not confirmed/);
  assert.equal(ui.state().statusSaveDisabled,true);
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
  comparison:{
    schema:1,state:'New File',reason:'Absent document-root page; preview only',
    excerpt:'',truncated:false,old_lines:0,new_lines:60
  },
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
  assert.match(ui.state().statusCompareSummary,/New File/);
  assert.equal(ui.state().statusCompareExcerpt,'');
  assert.doesNotMatch(ui.state().statusInspect,/HTTP status verified|Apply ready/);
  assert.equal(ui.state().statusInspectDisabled,false);
  ui.statusSetValue('#ach-status-template','new-site','change');
  assert.equal(ui.state().statusInspectDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-inspect-button');
  assert.equal(ui.requests.length,count, 'Unsupported page does not invoke endpoint');
  assert.match(ui.state().statusInspect,/not run/);
  assert.match(ui.state().statusCompareSummary,/not run/);
  assert.equal(ui.state().statusCompareExcerpt,'');
});

const probeSnapshot=JSON.stringify([7,'demo.test','/www/demo.test','1',[['demo.test',80]]]);
function statusProbe(overrides={}) {
  const sha='a'.repeat(64);
  return {
    status:true,schema:1,site_id:7,site_key:'demo.test',
    verified_site_snapshot:probeSnapshot,
    template:'404',locale:'en',scope:'loopback_http_80',
    state:'HTTP Match',reason:'Observed HTTP 404 with byte-identical site page',
    read_only:true,apply_supported:false,nginx_runtime_verified:false,
    revision:2,http_status:404,http_404_observed:true,
    body_sha256:sha,body_bytes:50,page_file_sha256:sha,rendered_sha256:sha,
    body_matches_file:true,body_matches_render:true,
    note:'One explicit local-only HTTP/80 GET. No Apply permission.',
    ...overrides
  };
}
function statusProbeUi(hasMore=false) {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const inventory = ui.requests.at(-1);
  assert.match(inventory.options.url,/s=status_sites$/);
  const selected={...site(),id:7,name:'demo.test',
    document_root:'/www/demo.test',bound_domains:[{name:'demo.test',port:80}],
    canonical_domain_bound:true};
  const remaining=hasMore ? Array.from({length:24},(_,i) => ({
    ...site(),id:100+i,name:'other'+i+'.test',
    document_root:'/www/other'+i+'.test',
    bound_domains:[{name:'other'+i+'.test',port:80}],canonical_domain_bound:true
  })) : [];
  inventory.respond({...page([selected,...remaining]),has_more:hasMore,purpose:'status_site_selection'});
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  return ui;
}

test('Explicit live 404 probe reports HTTP/body evidence without granting Apply', () => {
  const ui=statusProbeUi();
  assert.equal(ui.state().statusProbeDisabled,false);
  const request=ui.statusClick('#ach-status-probe-button');
  assert.match(request.options.url,/s=status_probe$/);
  assert.equal(request.options.data.site_id,'7');
  assert.equal(request.options.data.locale,'en');
  assert.equal(request.options.data.template,'404');
  assert.equal(request.options.data.expected_site_key,'demo.test');
  assert.equal(request.options.data.expected_site_snapshot,probeSnapshot);
  assert.equal(ui.state().statusProbeDisabled,true);
  request.respond(statusProbe());
  assert.match(ui.state().statusProbe,/HTTP Match/);
  assert.match(ui.state().statusProbe,/HTTP status: 404/);
  assert.match(ui.state().statusProbe,/body matches site file: Yes/);
  assert.match(ui.state().statusProbe,/not proof|No Apply permission/);
  assert.equal(ui.state().statusProbeDisabled,false);
  ui.statusSetValue('#ach-status-template','502','change');
  assert.equal(ui.state().statusProbeDisabled,true);
  assert.match(ui.state().statusProbe,/not checked/);
  const before=ui.requests.length;
  ui.statusClick('#ach-status-probe-button');
  assert.equal(ui.requests.length,before,'Cannot probe a 502 through the 404-only endpoint');
});

test('HTTP mismatch, soft success, and unknown evidence stay distinguishable', () => {
  const responses=[
    statusProbe({state:'HTTP Mismatch',http_status:200,http_404_observed:false,
      body_matches_file:false,body_matches_render:false}),
    statusProbe({state:'HTTP Mismatch',http_status:404,http_404_observed:true,
      body_sha256:'b'.repeat(64),body_matches_file:false,body_matches_render:false}),
    statusProbe({state:'Needs Review',http_status:null,http_404_observed:false,
      body_sha256:null,body_bytes:null,page_file_sha256:null,
      body_matches_file:false,body_matches_render:false,reason:'Local HTTP unavailable'})
  ];
  for (const response of responses) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-probe-button').respond(response);
    assert.match(ui.state().statusProbe,/HTTP Mismatch|Needs Review/);
    assert.doesNotMatch(ui.state().statusProbe,/Apply ready|verified Nginx config/i);
  }
});

test('Untrusted, stale, cross-site, overclaiming HTTP probe responses fail closed', () => {
  const sha='a'.repeat(64);
  const invalid=[
    statusProbe({site_id:8}),statusProbe({status:false}),
    statusProbe({site_key:'moved.test'}),
    statusProbe({verified_site_snapshot:JSON.stringify([
      7,'demo.test','/www/reassigned','1',[['demo.test',80]]
    ])}),
    statusProbe({schema:2}),statusProbe({revision:3}),statusProbe({read_only:false}),
    statusProbe({apply_supported:true}),statusProbe({nginx_runtime_verified:true}),
    statusProbe({scope:'remote_http'}),statusProbe({body_sha256:'wrong'}),
    statusProbe({body_bytes:65537}),statusProbe({http_status:200,http_404_observed:true}),
    statusProbe({state:'HTTP Match',body_matches_file:false}),
    statusProbe({state:'HTTP Mismatch',http_status:404,
      http_404_observed:true,body_matches_file:false}),
    statusProbe({body_matches_render:true,body_sha256:'b'.repeat(64)}),
    statusProbe({state:'Needs Review',body_sha256:sha,http_status:null}),
    statusProbe({site_key:'<img onerror=alert(1)>'}),
    statusProbe({reason:'x'.repeat(400)})
  ];
  for (const bad of invalid) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-probe-button').respond(bad);
    assert.match(ui.state().statusProbe,/unconfirmed or incompatible/);
  }
  const ui=statusProbeUi();
  const pending=ui.statusClick('#ach-status-probe-button');
  ui.statusSetValue('#ach-status-name','Changed after request','input change');
  pending.respond(statusProbe());
  assert.match(ui.state().statusProbe,/unconfirmed or incompatible/);
  assert.doesNotMatch(ui.state().statusProbe,/HTTP Match/);
});

test('A late site-inventory response cannot unlock an active HTTP probe', () => {
  const ui=statusProbeUi(true);
  const laterInventory=ui.loadMoreSites();
  assert.match(laterInventory.options.url,/s=status_sites$/);
  const probe=ui.statusClick('#ach-status-probe-button');
  assert.match(probe.options.url,/s=status_probe$/);
  assert.equal(ui.state().statusProbeDisabled,true);
  laterInventory.respond({...page([{
    ...site(),id:8,name:'another.test',document_root:'/www/another.test',
    bound_domains:[{name:'another.test',port:80}],canonical_domain_bound:true
  }]),page:2,has_more:false,purpose:'status_site_selection'});
  assert.equal(ui.state().statusProbeDisabled,true,
    'Concurrent inventory reply cannot release the probe form lock');
  const before=ui.requests.length;
  ui.statusClick('#ach-status-probe-button');
  assert.equal(ui.requests.length,before,'A probe remains single-flight');
  probe.respond(statusProbe());
  assert.match(ui.state().statusProbe,/HTTP Match/);
  assert.equal(ui.state().statusProbeDisabled,false);
});

test('Native site inventory errors revoke previously selected HTTP probe capability', () => {
  const ui=statusProbeUi();
  assert.equal(ui.state().statusProbeDisabled,false);
  ui.statusClick('#ach-status-sites-retry');
  assert.equal(ui.state().statusProbeDisabled,true);
  const invalid=ui.requests.at(-1);
  assert.match(invalid.options.url,/s=status_sites$/);
  invalid.respond({status:true, inventory_schema:1});
  assert.equal(ui.state().statusProbeDisabled,true);
  assert.match(ui.state().statusProbe,/not checked/);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-probe-button');
  assert.equal(ui.requests.length,count);
});

test('Existing native status-file reference is reviewable without false conflict or Apply', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  const result=statusInspection({
    state:'Needs Review',
    reason:'An existing source declaration references the native 404.html page; runtime unverified',
    error_page_sources:['site VHost']
  });
  ui.statusClick('#ach-status-inspect-button').respond(result);
  assert.match(ui.state().statusInspect,/State: Needs Review/);
  assert.match(ui.state().statusInspect,/Selected-status error_page source references: site VHost/);
  assert.doesNotMatch(ui.state().statusInspect,/State: Conflict|Apply ready|HTTP verified/);
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
    page_file_sha256:'a'.repeat(64),page_file_bytes:50,
    comparison:{
      schema:1,state:'Identical',reason:'Matched bytes',
      excerpt:'',truncated:false,old_lines:5,new_lines:5
    }
  }));
  assert.match(ui.state().statusInspect,/State: File Match/);
  ui.statusClick('#ach-status-inspect-button').respond({
    status:false,stage:'status_inspect',msg:'Native VHost changed'
  });
  assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
  assert.equal(ui.state().statusCompareExcerpt,'');
  assert.match(ui.state().statusCompareSummary,/unavailable or incompatible/);
  assert.match(ui.state().error,/Native VHost changed/);
});


test('In-flight offline Status Pages preview cannot restore stale branded HTML after editing', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  const pending=ui.statusClick('#ach-status-preview-button');
  ui.statusSetValue('#ach-status-name','Another brand','input change');
  pending.respond({
    status:true,schema:1,template:'404',locale:'en',
    html:'<p>Old-brand preview</p>',apply_supported:false,
    source:'Unsaved preview',
    source_sha256:'a'.repeat(64),rendered_sha256:'b'.repeat(64)
  });
  assert.equal(ui.state().statusHtml,'');
  assert.match(ui.state().statusResult,/Preview failed or response incompatible/);
});

test('Site 404/502 compare shows untrusted on-disk HTML strictly as text, never Apply', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  const dangerous='<img src=x onerror=alert(1)>';
  const diff='--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n-'+dangerous+'\\n+<h1>Safe preview</h1>';
  const req=ui.statusClick('#ach-status-inspect-button');
  assert.match(req.options.url,/s=status_inspect$/);
  req.respond(statusInspection({
    state:'Conflict',reason:'Owner HTML differs',
    page_file_state:'Different bytes',page_file_sha256:'b'.repeat(64),page_file_bytes:96,
    comparison:{
      schema:1,state:'Different',reason:'Display only; never Apply',
      excerpt:diff,truncated:false,old_lines:1,new_lines:1
    }
  }));
  assert.match(ui.state().statusCompareSummary,/Different/);
  assert.match(ui.state().statusCompareSummary,/Nginx routing is not verified/);
  assert.ok(ui.state().statusCompareExcerpt.includes(dangerous));
  assert.equal(ui.state().statusCompareExcerpt,diff);
  assert.equal(ui.state().statusInspectDisabled,false);
  ui.statusSetValue('#ach-status-name','New brand name','input change');
  assert.equal(ui.state().statusCompareExcerpt,'', 'Branding edit must revoke the old diff');
  assert.match(ui.state().statusCompareSummary,/not run/);
  ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
    state:'Conflict',reason:'Owner HTML differs',
    page_file_state:'Different bytes',page_file_sha256:'b'.repeat(64),page_file_bytes:96,
    comparison:{
      schema:1,state:'Different',reason:'Display only; never Apply',
      excerpt:diff,truncated:false,old_lines:1,new_lines:1
    }
  }));
  assert.ok(ui.state().statusCompareExcerpt.includes(dangerous));
  ui.statusSetValue('#ach-status-locale','fa','change');
  assert.equal(ui.state().statusCompareExcerpt,'', 'Old site/locale comparison is revoked');
});

test('Branding field changes while a compare request is in flight reject its old response', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  const req=ui.statusClick('#ach-status-inspect-button');
  assert.equal(req.options.data.brand_name,'ACh');
  ui.statusSetValue('#ach-status-name','Updated while pending','input change');
  req.respond(statusInspection());
  assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
  assert.equal(ui.state().statusCompareExcerpt,'');
  assert.match(ui.state().statusCompareSummary,/unavailable or incompatible/);
});


test('Malformed, mismatched or enormous compare responses cannot display stale diff evidence', () => {
  const valid={
    schema:1,state:'Different',reason:'bounded textual diff',
    excerpt:'--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n-old\n+new',
    truncated:false,old_lines:1,new_lines:1
  };
  for (const comparison of [
    null,
    {...valid,schema:2},
    {...valid,state:'Apply Ready'},
    {...valid,excerpt:'X'.repeat(7000)},
    {...valid,old_lines:Infinity},
    {...valid,truncated:'yes'},
    {...valid,state:'Identical'},
    {...valid,state:'New File'},
    {...valid,excerpt:'--- current 502.html\n+++ proposed 502.html'},
    {...valid,state:'Unavailable'},
  ]) {
    const ui=loadUi();
    ui.openStatus().respond(statusPrefs());
    ui.statusSetValue('#ach-status-scope','site','change');
    ui.statusSetValue('#ach-status-site-id','7','change');
    ui.requests.at(-1).respond(statusPrefs());
    ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
      state:'Conflict',page_file_state:'Different bytes',
      page_file_sha256:'b'.repeat(64),page_file_bytes:32,comparison
    }));
    assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
    assert.equal(ui.state().statusCompareExcerpt,'');
    assert.match(ui.state().statusCompareSummary,/unavailable or incompatible/);
  }
});


test('UTF-8 byte limit rejects multibyte excerpts that fit UTF-16 and per-line limits', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  const marker='--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n';
  const manyArabic=Array.from({length:12},()=>'-'+'پ'.repeat(300)).join('\n');
  const excerpt=marker+manyArabic;
  assert.ok(excerpt.length<6144, 'UTF-16 guard alone incorrectly accepts this');
  assert.ok(new TextEncoder().encode(excerpt).length>6144);
  assert.ok(excerpt.split('\n').every(line=>Array.from(line).length<=360));
  ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
    state:'Conflict',page_file_state:'Different bytes',
    page_file_sha256:'b'.repeat(64),page_file_bytes:3800,
    comparison:{
      schema:1,state:'Different',reason:'bad multibyte payload',
      excerpt,truncated:false,old_lines:12,new_lines:1
    }
  }));
  assert.equal(ui.state().statusCompareExcerpt,'');
  assert.match(ui.state().statusCompareSummary,/unavailable or incompatible/);
  assert.doesNotMatch(ui.state().statusInspect,/State: Conflict/);
});

test('Diff validation rejects oversized line counts and malformed unified headers/hunks', () => {
  const valid='--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n-قبلی ID-404\n+به‌روزرسانی ID-404';
  const base={schema:1,state:'Different',reason:'display-only',
    excerpt:valid,truncated:false,old_lines:1,new_lines:1};
  const failures=[
    {...base,old_lines:241},
    {...base,new_lines:241},
    {...base,old_lines:-1},
    {...base,new_lines:null},
    {...base,excerpt:valid.replace('@@ -1 +1 @@','@@ missing counts @@')},
    {...base,excerpt:valid.replace('+++ proposed 404.html','+++ proposed 502.html')},
    {...base,excerpt:valid.replace('--- current 404.html','--- current 502.html')},
    {...base,excerpt:'--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@'},
    {...base,excerpt:'--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\nXmalformed'},
    {...base,excerpt:'--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n-'+'a'.repeat(361)},
    {...base,state:'New File',excerpt:'',old_lines:0,new_lines:32769},
    {...base,state:'Identical',excerpt:'',old_lines:32769,new_lines:32769},
    {...base,state:'Unavailable',excerpt:'',old_lines:null,new_lines:0},
  ];
  for(const malformed of failures) {
    const ui=loadUi();
    ui.openStatus().respond(statusPrefs());
    ui.statusSetValue('#ach-status-scope','site','change');
    ui.statusSetValue('#ach-status-site-id','7','change');
    ui.requests.at(-1).respond(statusPrefs());
    ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
      state:'Conflict',page_file_state:'Different bytes',
      page_file_sha256:'b'.repeat(64),page_file_bytes:99,
      comparison:malformed
    }));
    assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
    assert.equal(ui.state().statusCompareExcerpt,'');
  }
});

test('A valid Persian diff still renders, then stale content disappears on invalid reinspection', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs());
  const valid='--- current 404.html\n+++ proposed 404.html\n@@ -1 +1 @@\n-درخواست‌ها ID-404\n+به‌روزرسانی‌شده ID-404';
  const response=statusInspection({
    state:'Conflict',page_file_state:'Different bytes',
    page_file_sha256:'b'.repeat(64),page_file_bytes:99,
    comparison:{schema:1,state:'Different',reason:'display-only',
      excerpt:valid,truncated:false,old_lines:1,new_lines:1}
  });
  ui.statusClick('#ach-status-inspect-button').respond(response);
  assert.equal(ui.state().statusCompareExcerpt,valid);
  ui.statusClick('#ach-status-inspect-button').respond(statusInspection({
    ...response,comparison:{...response.comparison,excerpt:valid+'😀'.repeat(1800)}
  }));
  assert.match(ui.state().statusInspect,/unconfirmed or incompatible/);
  assert.equal(ui.state().statusCompareExcerpt,'');
  assert.match(ui.state().statusCompareSummary,/unavailable or incompatible/);
});


test('Native sidebar sections are linked to panels and scrollable content', () => {
  for (const name of ['overview','websites','php','status','activity']) {
    assert.match(html, new RegExp('id="ach-tab-' + name + '"[^>]*aria-controls="ach-panel-' + name + '"'));
    assert.match(html, new RegExp('id="ach-panel-' + name + '"[^>]*aria-labelledby="ach-tab-' + name + '"'));
  }
  assert.match(html, /\.ach-main \{[^}]*overflow-y:auto/);
  assert.match(html, /\.ach-workspace \{[^}]*grid-template-columns:170px/);
  assert.match(html, /@media \(max-width:720px\)/);
  assert.doesNotMatch(html, /class="ach-tabs"/);
  assert.match(html, /function fitNativeLayer/);
  assert.match(html, /--ach-green:#20a53a/);
  assert.match(html, /--ach-sidebar-bg:#f0f0f1/);
  assert.doesNotMatch(html, /class="ach-sidebar-label"/);
  assert.match(html, /\.ach-main button \{[^}]*min-height:32px/);
  assert.match(html, /\.ach-toolbar \[role="status"\] \{[^}]*flex:1 1 220px/);
  assert.match(html, /<h4 class="ach-sr-only">Overview<\/h4>/);
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


test('FPM preview arriving after input edit never enables Prepare for a changed form', () => {
  const ui=loadUi();
  const previous=ui.submitPhp();
  ui.changePhp('max_children','101');
  previous.respond(phpPreview());
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.deepEqual(ui.state().impactRows,[]);
  assert.match(ui.state().fpmPlan,/fresh read-only preview/);
});

test('Newer FPM preview wins and a duplicate older response cannot revive approvals', () => {
  const ui=loadUi();
  const older=ui.submitPhp();
  const newer=ui.submitPhp();
  newer.respond(phpPreview());
  assert.equal(ui.state().fpmPrepareDisabled,false);
  older.respond({status:false,stage:'php_fpm_file_preview',msg:'OLD failure'});
  assert.equal(ui.state().fpmPrepareDisabled,false);
  assert.doesNotMatch(ui.state().error,/OLD failure/);
});

test('Edited PHP form invalidates an in-flight Prepare and never revives approval', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const pending=ui.prepareFpm();
  assert.match(pending.options.url,/s=fpm_prepare$/);
  ui.changePhp('max_children','177');
  pending.respond(guardedPlan());
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.equal(ui.state().fpmCommitDisabled,true);
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.match(ui.state().fpmPlan,/fresh read-only preview/);
});

test('An obsolete failed Prepare response cannot overwrite fresh-form feedback', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const pending=ui.prepareFpm();
  ui.changePhp('max_children','151');
  pending.respond({status:false,stage:'fpm_prepare',msg:'OBSOLETE ERROR'});
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.equal(ui.state().fpmCommitDisabled,true);
  assert.doesNotMatch(ui.state().error,/OBSOLETE ERROR/);
});

test('Confirmed Apply warnings stay in PHP panel despite unrelated Activity traffic', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  const apply=ui.commitFpm();
  const activity=ui.openActivity();
  apply.respond(appliedResult({
    audit_logged:false,audit_warning:'Native audit unavailable',
    activity_logged:false,activity_warning:'Plugin log unavailable'}));
  activity.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.match(ui.state().fpmPlan,/Apply result: Applied/);
  assert.match(ui.state().fpmOperationNotice,/Native audit unavailable/);
  assert.match(ui.state().fpmOperationNotice,/Plugin log unavailable/);
});

test('Confirmed Restore warning persists after unrelated read and response', () => {
  const ui=loadUi();
  ui.inspectFpmRecovery().respond(recoveryPreview());
  ui.approveFpmRollback(true);
  const restore=ui.rollbackFpm();
  const activity=ui.openActivity();
  restore.respond(rolledBackResult({
    activity_logged:false,activity_warning:'Plugin Restore log unavailable'}));
  activity.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.match(ui.state().fpmRecovery,/Recovery result: Rolled Back/);
  assert.match(ui.state().fpmOperationNotice,/Plugin Restore log unavailable/);
});

test('Old successful PHP preview cannot override newer failed preview', () => {
  const ui=loadUi();
  const old=ui.submitPhp();
  const recent=ui.submitPhp();
  recent.respond({status:false,stage:'php_fpm_file_preview',msg:'Current source unavailable'});
  old.respond(phpPreview());
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.deepEqual(ui.state().impactRows,[]);
  assert.doesNotMatch(ui.state().error,/Old response/);
});

test('A second Prepare click while pending sends no duplicate approval request', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const first=ui.prepareFpm();
  const before=ui.requests.length;
  ui.prepareFpm();
  assert.equal(ui.requests.length,before);
  first.respond(guardedPlan());
  assert.equal(ui.state().fpmCommitDisabled,true);
  ui.approveFpm(true);
  assert.equal(ui.state().fpmCommitDisabled,false);
  ui.changePhp('max_children','211');
  assert.equal(ui.state().fpmCommitDisabled,true);
  assert.equal(ui.state().fpmReviewHidden,true);
});

test('Restore warning retains both audit and Activity failures across unrelated refresh', () => {
  const ui=loadUi();
  ui.inspectFpmRecovery().respond(recoveryPreview());
  ui.approveFpmRollback(true);
  const restore=ui.rollbackFpm();
  const activity=ui.openActivity();
  restore.respond(rolledBackResult({
    audit_logged:false,audit_warning:'Native restore audit missing',
    activity_logged:false,activity_warning:'Plugin restore Activity missing'}));
  activity.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.match(ui.state().fpmRecovery,/Recovery result: Rolled Back/);
  assert.match(ui.state().fpmOperationNotice,/Native restore audit missing/);
  assert.match(ui.state().fpmOperationNotice,/Plugin restore Activity missing/);
});

test('Lifecycle Activity can be filtered and displayed with canonical fields', () => {
  const ui=loadUi();
  const first=ui.openActivity();
  first.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  const req=ui.activityFilter('#ach-activity-module','lifecycle');
  assert.equal(req.options.data.module,'lifecycle');
  req.respond({status:true,schema:1,read_only:true,configured_level:'INFO',
    entries:[{schema:1,time_utc:'2026-11-03T09:00:00+00:00',
      module:'lifecycle',level:'WARNING',action:'uninstall',
      stage:'icon_cleanup',outcome:'preserved',error_class:'IconCleanupFailed',
      operation_id:'a'.repeat(32),target:'ach_customizer',detail:'Icon retained',
      recovery_id:''}]});
  assert.equal(ui.activityRows().length,1);
  assert.match(ui.activityRows()[0][2],/lifecycle \/ uninstall/);
  assert.match(ui.activityRows()[0][3],/IconCleanupFailed/);
});

test('Reviewer: pending Prepare A cannot revive approval after a newer identical Preview B fails', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const oldPrepare=ui.prepareFpm();
  const newPreview=ui.submitPhp(); // Same fields; a newer user intent.
  oldPrepare.respond(guardedPlan());
  assert.equal(ui.state().fpmReviewHidden,true);
  newPreview.respond({status:false,stage:'php_fpm_file_preview',msg:'Latest preview failed'});
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.equal(ui.state().fpmPrepareDisabled,true);
  ui.approveFpm(true);
  const before=ui.requests.length;
  ui.commitFpm();
  assert.equal(ui.requests.length,before,'No Apply can follow stale Prepare and failed preview');
});

test('Reviewer: newer identical Preview B succeeds before Prepare A, which must stay stale', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const oldPrepare=ui.prepareFpm();
  const newerPreview=ui.submitPhp();
  newerPreview.respond(phpPreview());
  oldPrepare.respond(guardedPlan());
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.equal(ui.state().fpmCommitDisabled,true);
  assert.equal(ui.state().fpmPrepareDisabled,false);
  const fresh=ui.prepareFpm();
  assert.notEqual(fresh,oldPrepare);
  fresh.respond(guardedPlan());
  assert.equal(ui.state().fpmReviewHidden,false);
  assert.equal(ui.state().fpmCommitDisabled,true);
});

test('Reviewer: stale Prepare failure after newer identical Preview does not replace current feedback', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  const oldPrepare=ui.prepareFpm();
  const newerPreview=ui.submitPhp();
  oldPrepare.respond({status:false,stage:'fpm_prepare',msg:'STALE PREPARE ERROR'});
  newerPreview.respond(phpPreview());
  assert.equal(ui.state().fpmPrepareDisabled,false);
  assert.equal(ui.state().fpmReviewHidden,true);
  assert.doesNotMatch(ui.state().error,/STALE PREPARE ERROR/);
});

test('Reviewer: malformed successful Apply replies never imply a completed host change', () => {
  const replies=[
    {status:true,audit_logged:true,activity_logged:true},
    {status:true,state:'Applied',operation_id:'bad',audit_logged:true,activity_logged:true},
    {status:true,state:'Applied',operation_id:'c'.repeat(32),audit_logged:true,activity_logged:true},
    {status:true,state:'Rolled Back',operation_id:'c'.repeat(32),audit_logged:true,activity_logged:true},
    {status:true,state:'No Change',operation_id:'c'.repeat(32),audit_logged:true,activity_logged:true},
  ];
  for(const reply of replies) {
    const ui=loadUi();
    ui.submitPhp().respond(phpPreview());
    ui.prepareFpm().respond(guardedPlan());
    ui.approveFpm(true);
    ui.commitFpm().respond(reply);
    assert.match(ui.state().fpmOperationNotice,/NOT confirmed/,JSON.stringify(reply));
    assert.doesNotMatch(ui.state().fpmOperationNotice,/Apply confirmed/);
    assert.match(ui.state().fpmPlan,/Inspect saved recovery/);
    assert.equal(ui.state().fpmCommitDisabled,true);
  }
});

test('Reviewer: malformed successful Restore replies never imply completed rollback', () => {
  const valid=rolledBackResult();
  for (const reply of [
    {status:true,audit_logged:true,activity_logged:true},
    {...valid,operation_id:'bad'},
    {...valid,operation_id:'e'.repeat(32)},
    {...valid,restored_sha256:'bad'},
    {...valid,restored_sha256:'b'.repeat(64)},
    {...valid,state:'Applied'}
  ]) {
    const ui=loadUi();
    ui.inspectFpmRecovery().respond(recoveryPreview());
    ui.approveFpmRollback(true);
    ui.rollbackFpm().respond(reply);
    assert.match(ui.state().fpmOperationNotice,/NOT confirmed/,JSON.stringify(reply));
    assert.match(ui.state().fpmRecovery,/Inspect saved recovery/);
    assert.doesNotMatch(ui.state().fpmRecovery,/Recovery result: Rolled Back/);
  }
});

test('Reviewer: valid No Change is explicitly non-mutating and never invents recovery', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  ui.commitFpm().respond(noChangeResult());
  assert.match(ui.state().fpmOperationNotice,/No host change performed/);
  assert.doesNotMatch(ui.state().fpmOperationNotice,/Apply confirmed/);
  assert.doesNotMatch(ui.state().fpmPlan,/recovery operation: none/);
});

test('Reviewer: incomplete successful Apply preserves independent persistence warnings', () => {
  const ui=loadUi();
  ui.submitPhp().respond(phpPreview());
  ui.prepareFpm().respond(guardedPlan());
  ui.approveFpm(true);
  const write=ui.commitFpm();
  const background=ui.openActivity();
  write.respond({status:true,audit_logged:false,audit_warning:'Native audit missing',
    activity_logged:false,activity_warning:'Plugin Activity missing'});
  background.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.match(ui.state().fpmOperationNotice,/NOT confirmed/);
  assert.match(ui.state().fpmOperationNotice,/Native audit missing/);
  assert.match(ui.state().fpmOperationNotice,/Plugin Activity missing/);
});


test('Reviewer: failed Apply and Restore never fabricate confirmation', () => {
  const apply=loadUi();
  apply.submitPhp().respond(phpPreview());
  apply.prepareFpm().respond(guardedPlan());
  apply.approveFpm(true);
  apply.commitFpm().respond({status:false,stage:'fpm_apply',msg:'Reload uncertain',
    operation_id:'f'.repeat(32),audit_logged:false,
    audit_warning:'Native audit failed',activity_logged:false,
    activity_warning:'Plugin Activity failed'});
  assert.match(apply.state().fpmOperationNotice,/Apply NOT confirmed/);
  assert.match(apply.state().fpmOperationNotice,/Native audit failed/);
  assert.match(apply.state().fpmOperationNotice,/Plugin Activity failed/);
  assert.match(apply.state().fpmPlan,/Inspect saved recovery/);

  const restore=loadUi();
  restore.inspectFpmRecovery().respond(recoveryPreview());
  restore.approveFpmRollback(true);
  restore.rollbackFpm().reject(null,'timeout');
  assert.match(restore.state().fpmOperationNotice,/Restore NOT confirmed/);
  assert.match(restore.state().fpmRecovery,/Inspect saved recovery/);
});

test('Reviewer: mismatched native Apply identities, config digests and source are never confirmed', () => {
  const tampered=[
    appliedResult({operation_id:'not-an-operation'}),
    appliedResult({before_sha256:'e'.repeat(64)}),
    appliedResult({after_sha256:'f'.repeat(64)}),
    appliedResult({source:'/www/server/php/84/etc/php-fpm.conf'}),
    appliedResult({version:'84'}),
    appliedResult({state:'No Change',operation_id:null}),
    noChangeResult({operation_id:'d'.repeat(32)}),
    noChangeResult({after_sha256:'b'.repeat(64)})
  ];
  for(const response of tampered) {
    const ui=loadUi();
    ui.submitPhp().respond(phpPreview());
    ui.prepareFpm().respond(guardedPlan());
    ui.approveFpm(true);
    ui.commitFpm().respond(response);
    assert.match(ui.state().fpmOperationNotice,/NOT confirmed/,JSON.stringify(response));
    assert.equal(ui.state().fpmCommitDisabled,true);
  }
});

test('Native PHP discovery selects actual PHP 8.1+ file candidates without enabling Apply', () => {
  const ui=loadUi();
  const discovered=ui.openPhp();
  assert.match(discovered.options.url,/s=get_php_versions$/);
  assert.equal(ui.state().phpVersionDisabled,true);
  discovered.respond(ui.phpVersions());
  const state=ui.state();
  assert.equal(state.phpVersionDisabled,false);
  assert.deepEqual(state.phpOptions.map(o=>o.value),['','81','84','85']);
  assert.match(state.phpDiscovery,/3 file-preview candidate/);
  assert.match(state.phpDiscovery,/not process verification/);
  const preview=ui.submitPhp('81');
  assert.match(preview.options.url,/s=preview_php_fpm$/);
  assert.equal(preview.options.data.php_version,'81');
  preview.respond(phpPreview(phpImpact({version:'81'})));
  assert.equal(ui.state().fpmPrepareDisabled,true,
    'An 8.1 file mapping must never open the PHP85 Manual Apply gate');
  assert.match(ui.state().fpmPlan,/manual Apply unavailable/);
});

test('Partial PHP installation inventory disables missing and unsupported versions', () => {
  const ui=loadUi();
  const supported=ui.phpVersions().versions[0];
  const obsolete={code:'80',label:'PHP 8.0',state:'Unsupported',
    binary_present:true,config_present:true,preview_candidate:false,
    manual_apply_adapter:'none',apply_eligible:false,reason:'Unsupported'};
  const partial={code:'85',label:'PHP 8.5',state:'Needs Review',
    binary_present:false,config_present:true,preview_candidate:false,
    manual_apply_adapter:'none',apply_eligible:false,reason:'Missing binary'};
  ui.openPhp().respond({...ui.phpVersions([obsolete,supported,partial]),state:'Partial',
    reason:'One installation is incomplete'});
  const rows=ui.state().phpOptions;
  assert.equal(rows.find(o=>o.value==='80').disabled,true);
  assert.equal(rows.find(o=>o.value==='85').disabled,true);
  assert.equal(rows.find(o=>o.value==='81').disabled,undefined);
  assert.match(ui.state().phpDiscovery,/incomplete/);
  const previous=ui.requests.length;
  ui.submitPhp('85');
  assert.equal(ui.requests.length,previous,
    'An unsupported or unverified PHP version must not even start Preview');
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.match(ui.state().error,/not selected from the verified inventory/);
});

test('Missing, malformed and privilege-escalating PHP inventory never enables a selection', () => {
  for (const invalid of [
    null,
    {status:true,schema:2},
    {...uiPhpVersionsFixture(),read_only:false},
    {...uiPhpVersionsFixture(),runtime_verified:true},
    {...uiPhpVersionsFixture(),versions:[{...uiPhpVersionsFixture().versions[0],
      apply_eligible:true}]},
    {...uiPhpVersionsFixture(),versions:[{...uiPhpVersionsFixture().versions[0],
      label:'<img src=x onerror=alert(1)>'}]},
    {...uiPhpVersionsFixture(),versions:[uiPhpVersionsFixture().versions[0],
      uiPhpVersionsFixture().versions[0]]}
  ]) {
    const ui=loadUi();
    const request=ui.openPhp();
    request.respond(invalid);
    assert.equal(ui.state().phpVersionDisabled,true);
    assert.equal(ui.state().phpOptions.length,1);
    assert.match(ui.state().phpDiscovery,/unavailable or incompatible/);
  }
  function uiPhpVersionsFixture() {
    const ui=loadUi();
    return ui.phpVersions();
  }
});

test('Stale PHP discovery response after a refresh cannot restore old version choices', () => {
  const ui=loadUi();
  const prior=ui.openPhp();
  const pendingCount=ui.requests.length;
  ui.openOverview(); ui.openPhp();
  assert.equal(ui.requests.length,pendingCount,'Pending PHP discovery is not duplicated on tab reentry');
  const current=ui.refreshPhp();
  current.respond({...ui.phpVersions([]),state:'Needs Review',reason:'Not installed'});
  prior.respond(ui.phpVersions());
  assert.equal(ui.state().phpVersionDisabled,true);
  assert.equal(ui.state().phpOptions.length,1);
  assert.match(ui.state().phpDiscovery,/Not installed/);
  const previous=ui.requests.length;
  ui.submitPhp('85', false);
  assert.equal(ui.requests.length,previous);
});


test('Changed PHP source path fails closed after Refresh, revoking prior selection and approval', () => {
  const ui=loadUi();
  ui.requests[0].respond(monitorOverview());
  ui.openPhp().respond(ui.phpVersions());
  const preview=ui.submitPhp('85', false);
  preview.respond(phpPreview());
  assert.equal(ui.state().phpVersion,'85');
  const refresh=ui.refreshPhp();
  refresh.respond({...ui.phpVersions([]), state:'Needs Review',
    reason:'aaPanel PHP source pathname or file changed during inspection; Refresh installed PHP'});
  const state=ui.state();
  assert.equal(state.phpVersionDisabled,true);
  assert.deepEqual(state.phpOptions.map(o=>o.value),['']);
  assert.equal(state.fpmPrepareDisabled,true);
  assert.match(state.phpDiscovery,/changed during inspection/);
  const requests=ui.requests.length;
  ui.submitPhp('85', false);
  assert.equal(ui.requests.length,requests,
    'A former PHP85 file candidate must not survive a changed-path inventory');
});

test('PHP tab return reuses valid discovery and selected preview until explicit Refresh', () => {
  const ui=loadUi();
  ui.requests[0].respond(monitorOverview());
  const discovery=ui.openPhp();
  discovery.respond(ui.phpVersions());
  const preview=ui.submitPhp('85', false);
  preview.respond(phpPreview());
  assert.equal(ui.state().phpVersion,'85');
  const before=ui.requests.length;
  ui.openOverview(); ui.openPhp();
  assert.equal(ui.requests.length,before,'Tab revisit must preserve verified native PHP discovery');
  assert.equal(ui.state().phpVersion,'85','Do not silently erase operator choice');
  const refresh=ui.refreshPhp();
  assert.equal(ui.requests.length,before+1);
  assert.match(refresh.options.url,/s=get_php_versions$/);
  assert.equal(ui.state().phpVersionDisabled,true,'Refresh must invalidate old selected version');
  assert.equal(ui.state().fpmPrepareDisabled,true,'Old Preview never survives Refresh');
  ui.openOverview(); ui.openPhp();
  assert.equal(ui.requests.length,before+1,'Pending PHP refresh is not repeated by navigation');
  refresh.respond(ui.phpVersions());
  assert.equal(ui.state().phpVersion,'85','The reverified version may stay selected');
  assert.equal(ui.state().fpmPrepareDisabled,true,'Reverified version does not revive old Preview or approval');
  assert.equal(ui.state().phpVersionDisabled,false);
  ui.openOverview(); ui.openPhp();
  assert.equal(ui.requests.length,before+1,'Successful Refresh result remains cached');
});

test('PHP discovery Activity invalidation does not disrupt unrelated cached tabs', () => {
  const ui=loadUi();
  ui.requests[0].respond(monitorOverview());
  const activity=ui.openActivity();
  activity.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  const fetch=ui.openPhp();
  fetch.respond(ui.phpVersions());
  assert.match(ui.activityMessage(),/may have changed/);
  const current=ui.openActivity();
  assert.match(current.options.url,/s=get_activity$/);
  current.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  const count=ui.requests.length;
  ui.openPhp(); ui.openActivity();
  assert.equal(ui.requests.length,count,'Read-only PHP tab reentry does not spur another Activity invalidation');
});

test('Native tab navigation reuses loaded panels and explicit Refresh fetches latest', () => {
  const ui=loadUi();
  ui.requests[0].respond(monitorOverview({state_revision:9}));
  ui.openSites();
  ui.respond(page());
  assert.match(ui.state().siteStatus,/Page 1/);
  const before=ui.requests.length;
  ui.openOverview(); ui.openSites();
  assert.equal(ui.requests.length,before,'revisit must not re-fetch');
  const refresh=ui.refreshSites();
  assert.equal(ui.requests.length,before+1);
  assert.match(refresh.options.url,/s=get_sites$/);
  refresh.respond(page([]));
  assert.match(ui.state().siteStatus,/0 website/);
  const monitor=ui.refreshOverview();
  assert.match(monitor.options.url,/s=get_overview$/);
  monitor.respond(monitorOverview({state_revision:10}));
  assert.equal(ui.state().stateRevision,'State revision: 10');
});

test('Status Pages unsaved brand values survive native tab switching', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-name','Unsaved operator change');
  ui.openSites(); ui.respond(page());
  const before=ui.requests.length;
  ui.openStatus();
  assert.equal(ui.requests.length,before,'no unnecessary status_preferences request');
  assert.equal(ui.state().statusName,'Unsaved operator change');
  ui.statusClick('#ach-status-load').respond(statusPrefs());
  assert.notEqual(ui.state().statusName,'Unsaved operator change');
});

test('Native lazy navigation uses per-view loading state, not a global flash', () => {
  const ui=loadUi();
  assert.equal(ui.state().error,'');
  const inventory=ui.openSites();
  assert.match(inventory.options.url,/s=get_sites$/);
  assert.match(ui.state().siteStatus,/Loading website inventory/);
  assert.equal(ui.state().error,'');
  const activity=ui.openActivity();
  assert.match(activity.options.url,/s=get_activity$/);
  assert.equal(ui.state().error,'');
  inventory.respond(page());
  assert.equal(ui.state().error,'');
});

test('Review R1: primary action white text meets AA against normal and hover fills', () => {
  const match = html.match(/--ach-primary-fill:(#[0-9a-f]{6}); --ach-primary-fill-hover:(#[0-9a-f]{6});/i);
  assert.ok(match, 'Primary action must have distinct readable fill tokens');
  function lum(hex) {
    const parts = hex.slice(1).match(/.{2}/g).map(v => parseInt(v, 16) / 255)
      .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return parts[0] * 0.2126 + parts[1] * 0.7152 + parts[2] * 0.0722;
  }
  for (const fill of match.slice(1)) {
    const contrast = 1.05 / (lum(fill) + 0.05);
    assert.ok(contrast >= 4.5, fill + ' white-on-green contrast ' + contrast.toFixed(3));
  }
  assert.match(html, /button\.btn-success \{\s*color:#fff; background:var\(--ach-primary-fill\)/);
  assert.match(html, /button\.btn-success:hover:not\(:disabled\) \{[\s\S]*?background:var\(--ach-primary-fill-hover\)/);
});

test('Review R2: an older Overview read completing BEFORE Monitor acknowledgement cannot replace it', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_revision:10}));
  const oldRead = ui.refreshOverview();
  const update = ui.toggleMonitor('overall', false);
  assert.match(update.options.url, /s=set_control$/);
  const pendingCount = ui.requests.length;
  ui.refreshOverview();
  ui.toggleMonitor('site_inventory', false);
  assert.equal(ui.requests.length, pendingCount, 'No duplicate read or control mutation while writing');
  oldRead.respond(monitorOverview({state_revision:10, overall_enabled:true}));
  assert.equal(ui.state().controls.overall.disabled, true);
  update.respond(monitorAck({state_revision:11, overall_enabled:false, mode:'Disabled'}));
  assert.equal(ui.state().stateRevision, 'State revision: 11');
  assert.equal(ui.state().controls.overall.checked, false);
  assert.equal(ui.state().controls.overall.disabled, false);
});

test('Review R2: an older Overview read completing AFTER Monitor acknowledgement is discarded', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_revision:10}));
  const oldRead = ui.refreshOverview();
  const update = ui.toggleMonitor('overall', false);
  update.respond(monitorAck({state_revision:11, overall_enabled:false, mode:'Disabled'}));
  oldRead.respond(monitorOverview({state_revision:10, overall_enabled:true}));
  assert.equal(ui.state().stateRevision, 'State revision: 11');
  assert.equal(ui.state().controls.overall.checked, false);
  const lateServerRead = ui.refreshOverview();
  lateServerRead.respond(monitorOverview({state_revision:9, overall_enabled:true}));
  assert.equal(ui.state().stateRevision, 'State revision: 11');
  assert.match(ui.state().overview, /Older Monitor state ignored/);
});

test('Review R2: failed or conflicted Monitor write retains known controls and explicit recovery', () => {
  for (const outcome of ['timeout','conflict']) {
    const ui = loadUi();
    ui.respondOverview(monitorOverview({state_revision:4}));
    const oldRead = ui.refreshOverview();
    const mutation = ui.toggleMonitor('overall', false);
    if (outcome === 'timeout') mutation.reject(null, 'timeout');
    else mutation.respond({status:false, stage:'monitor_state_write', msg:'Revision conflict'});
    oldRead.respond(monitorOverview({state_revision:4, overall_enabled:false}));
    assert.equal(ui.state().stateRevision, 'State revision: 4');
    assert.equal(ui.state().controls.overall.checked, true);
    assert.equal(ui.state().controls.overall.disabled, true);
    assert.match(ui.state().overview, /not confirmed/);
    const newest = ui.refreshOverview();
    assert.match(newest.options.url, /s=get_overview$/);
    newest.respond(monitorOverview({state_revision:5, overall_enabled:false}));
    assert.equal(ui.state().stateRevision, 'State revision: 5');
    assert.equal(ui.state().controls.overall.checked, false);
    assert.equal(ui.state().controls.overall.disabled, false);
  }
});

test('Review R2: failed Monitor write stays locked after failed refresh; only verified GET re-enables', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:10}));
  ui.openSites().respond(page());
  ui.openOverview();
  const write=ui.toggleMonitor('overall',false);
  assert.deepEqual(ui.state().rows,[],'Possible backend change immediately invalidates inventory');
  write.reject(null,'timeout');
  assert.equal(ui.state().stateRevision,'State revision: 10');
  assert.equal(ui.state().controls.overall.checked,true);
  assert.equal(ui.state().controls.overall.disabled,true);
  const initialCount=ui.requests.length;
  ui.toggleMonitor('site_inventory',false);
  assert.equal(ui.requests.length,initialCount,'Unconfirmed state must not allow another mutation');
  const badRead=ui.refreshOverview();
  badRead.reject(null,'timeout');
  assert.equal(ui.state().controls.overall.disabled,true);
  assert.equal(ui.state().controls.overall.checked,true);
  assert.equal(ui.state().stateRevision,'State revision: 10','Keep last-known revision for diagnosis');
  const retry=ui.refreshOverview();
  retry.respond(monitorOverview({state_revision:11,overall_enabled:false,mode:'Disabled'}));
  assert.equal(ui.state().stateRevision,'State revision: 11');
  assert.equal(ui.state().controls.overall.checked,false);
  assert.equal(ui.state().controls.overall.disabled,false);
  const updated=ui.openSites();
  assert.match(updated.options.url,/s=get_sites$/);
  updated.respond({status:false,stage:'monitor_disabled',msg:'Monitor disabled'});
  assert.deepEqual(ui.state().rows,[]);
});

test('Review R2: a malformed refresh does not unlock after an uncertain write', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:2}));
  const write=ui.toggleMonitor('overall',false);
  write.reject(null,'timeout');
  const refresh=ui.refreshOverview();
  refresh.respond(monitorOverview({state_schema:2,state_revision:3,overall_enabled:false}));
  assert.equal(ui.state().controls.overall.checked,true);
  assert.equal(ui.state().controls.overall.disabled,true);
  assert.equal(ui.state().stateRevision,'State revision: 2');
  assert.match(ui.state().overview,/unverified|Refresh state/);
  const count=ui.requests.length;
  ui.toggleMonitor('overall',false);
  assert.equal(ui.requests.length,count);
  ui.refreshOverview().respond(monitorOverview({state_revision:3,overall_enabled:false,mode:'Disabled'}));
  assert.equal(ui.state().controls.overall.disabled,false);
  assert.equal(ui.state().controls.overall.checked,false);
});

test('Review R2: inconsistent successful Monitor acknowledgements are rejected and locked', () => {
  const invalid=[
    ['missing changed',monitorOverview({state_revision:5,overall_enabled:false})],
    ['changed false despite changed flag',monitorAck({changed:false,state_revision:5,overall_enabled:false})],
    ['no revision increment',monitorAck({state_revision:4,overall_enabled:false})],
    ['unexpected revision jump',monitorAck({state_revision:6,overall_enabled:false})],
    ['requested value unchanged',monitorAck({state_revision:5,overall_enabled:true})],
    ['unrelated module altered',monitorAck({state_revision:5,overall_enabled:false,
      modules_enabled:{site_inventory:false,php_fpm_file_preview:true}})]
  ];
  for(const [reason,reply] of invalid){
    const ui=loadUi();
    ui.respondOverview(monitorOverview({state_revision:4}));
    const write=ui.toggleMonitor('overall',false);
    write.respond(reply);
    assert.equal(ui.state().stateRevision,'State revision: 4',reason);
    assert.equal(ui.state().controls.overall.checked,true,reason);
    assert.equal(ui.state().controls.overall.disabled,true,reason);
    assert.match(ui.state().overview,/stale or incompatible/,reason);
    const count=ui.requests.length;
    ui.toggleMonitor('site_inventory',false);
    assert.equal(ui.requests.length,count,'Failed closed: '+reason);
    ui.refreshOverview().respond(monitorOverview({state_revision:5,overall_enabled:false,mode:'Disabled'}));
    assert.equal(ui.state().controls.overall.disabled,false,'Recovered: '+reason);
    assert.equal(ui.state().controls.overall.checked,false,'Recovered: '+reason);
  }
});

test('Review R2: consistent no-op acknowledgment is accepted without inventing a revision', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:8}));
  const change=ui.toggleMonitor('overall',true);
  assert.equal(change.options.data.enabled,'true');
  change.respond(monitorAck({changed:false,state_revision:8,overall_enabled:true}));
  assert.equal(ui.state().stateRevision,'State revision: 8');
  assert.equal(ui.state().controls.overall.checked,true);
  assert.equal(ui.state().controls.overall.disabled,false);
});

test('Review R3: Websites navigation while policy write is pending never caches a pre-transition page', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:10}));
  ui.openSites().respond(page());
  ui.openOverview();
  const write=ui.toggleMonitor('site_inventory',false);
  assert.deepEqual(ui.state().rows,[]);
  assert.equal(ui.state().nextDisabled,true);
  const pendingRequests=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,pendingRequests,
    'A get_sites request must not launch under an unsettled Monitor policy');
  assert.deepEqual(ui.state().rows,[]);
  assert.match(ui.state().siteStatus,/Monitor update pending/);
  write.respond(monitorAck({state_revision:11,
    modules_enabled:{site_inventory:false,php_fpm_file_preview:true}}));
  const confirmedRead=ui.requests.at(-1);
  assert.match(confirmedRead.options.url,/s=get_sites$/);
  assert.equal(ui.requests.length,pendingRequests+1,
    'The next read must be initiated only after a confirmed policy transition');
  confirmedRead.respond({status:false,stage:'monitor_disabled',msg:'Website inventory disabled'});
  assert.deepEqual(ui.state().rows,[]);
  assert.equal(ui.state().nextDisabled,true);
  const afterLoad=ui.requests.length;
  ui.openOverview(); ui.openSites();
  assert.equal(ui.requests.length,afterLoad+1,
    'A failed current-policy read must keep explicit retry available');
});

test('Review R3: pending inventory is discarded after conflicted Website Monitor write', () => {
  for(const outcome of ['conflict','timeout','incompatible-success']){
    const ui=loadUi();
    ui.respondOverview(monitorOverview({state_revision:6}));
    const stale=ui.openSites();
    ui.openOverview();
    const write=ui.toggleMonitor('site_inventory',false);
    if(outcome==='conflict') write.respond({status:false,stage:'monitor_state_write',msg:'Revision conflict'});
    else if(outcome==='timeout') write.reject(null,'timeout');
    else write.respond(monitorAck({state_revision:7,
      modules_enabled:{site_inventory:true,php_fpm_file_preview:true}}));
    stale.respond(page());
    assert.deepEqual(ui.state().rows,[],'Stale inventory must not return: '+outcome);
    assert.match(ui.state().siteStatus,/Monitor policy unverified/,outcome);
    assert.equal(ui.state().controls.site_inventory.disabled,true,outcome);
    const blockedCount=ui.requests.length;
    ui.openSites();
    assert.equal(ui.requests.length,blockedCount,'Do not fetch under unverified policy: '+outcome);
    assert.equal(ui.state().nextDisabled,true);
    ui.openOverview();
    ui.refreshOverview().respond(monitorOverview({state_revision:7,
      modules_enabled:{site_inventory:false,php_fpm_file_preview:true}}));
    assert.equal(ui.state().controls.site_inventory.checked,false,outcome);
    assert.equal(ui.state().controls.site_inventory.disabled,false,outcome);
    const recovered=ui.openSites();
    assert.match(recovered.options.url,/s=get_sites$/);
    recovered.respond({status:false,stage:'monitor_disabled',msg:'Monitor state not verified'});
    assert.equal(ui.state().nextDisabled,true);
  }
});

test('Review R3: uncertain policy outcomes require a verified GET before any Websites read', () => {
  for (const outcome of ['timeout','conflict','contradictory-success']) {
    const ui=loadUi();
    ui.respondOverview(monitorOverview({state_revision:10}));
    ui.openSites().respond(page());
    ui.openOverview();
    const write=ui.toggleMonitor('overall',false);
    const pendingCount=ui.requests.length;
    ui.openSites();
    ui.refreshSites(); // Even a synthetic disabled-button click must not dispatch.
    assert.equal(ui.requests.length,pendingCount,'Pending policy blocks get_sites: '+outcome);
    assert.deepEqual(ui.state().rows,[],outcome);
    assert.match(ui.state().siteStatus,/Monitor update pending/,outcome);
    if (outcome==='timeout') write.reject(null,'timeout');
    else if (outcome==='conflict') write.respond({
      status:false,stage:'monitor_state_write',msg:'Revision conflict'});
    else write.respond(monitorAck({state_revision:11,overall_enabled:true}));
    assert.match(ui.state().siteStatus,/Monitor policy unverified/,outcome);
    assert.equal(ui.state().controls.overall.disabled,true,outcome);
    const blocked=ui.requests.length;
    ui.openSites(); ui.refreshSites();
    assert.equal(ui.requests.length,blocked,'Unconfirmed policy blocks retries: '+outcome);
    ui.openOverview();
    const bad=ui.refreshOverview();
    bad.respond(monitorOverview({state_schema:2,state_revision:11,overall_enabled:false}));
    const afterBad=ui.requests.length;
    ui.openSites();
    assert.equal(ui.requests.length,afterBad,'Malformed recheck cannot unlock Websites: '+outcome);
    ui.openOverview().respond(monitorOverview({state_revision:9,overall_enabled:true}));
    const afterStale=ui.requests.length;
    ui.openSites();
    assert.equal(ui.requests.length,afterStale,'Older recheck cannot unlock Websites: '+outcome);
    ui.openOverview().reject(null,'timeout');
    const afterFailed=ui.requests.length;
    ui.openSites();
    assert.equal(ui.requests.length,afterFailed,'Failed recheck cannot unlock Websites: '+outcome);
    ui.openOverview();
    ui.refreshOverview().respond(monitorOverview({state_revision:11,overall_enabled:false,mode:'Disabled'}));
    assert.equal(ui.state().controls.overall.disabled,false,outcome);
    const afterGood=ui.requests.length;
    const fresh=ui.openSites();
    assert.equal(ui.requests.length,afterGood+1,'Fresh policy read permits inventory: '+outcome);
    assert.match(fresh.options.url,/s=get_sites$/);
    fresh.respond(page([]));
    assert.deepEqual(ui.state().rows,[['No sites in this page']],outcome);
    assert.equal(ui.state().page,'1',outcome);
    assert.equal(ui.state().nextDisabled,true,outcome);
  }
});

test('Review R3: pre-mutation inventory response cannot replace post-acknowledgment data', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:4}));
  const oldRead=ui.openSites();
  ui.openOverview();
  const mutation=ui.toggleMonitor('site_inventory',false);
  const pendingCount=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,pendingCount,'Do not launch during mutation');
  mutation.respond(monitorAck({state_revision:5,
    modules_enabled:{site_inventory:false,php_fpm_file_preview:true}}));
  const fresh=ui.requests.at(-1);
  assert.match(fresh.options.url,/s=get_sites$/);
  oldRead.respond(page());
  assert.deepEqual(ui.state().rows,[],'Pre-mutation request discarded after newer policy');
  fresh.respond(page([]));
  assert.deepEqual(ui.state().rows,[['No sites in this page']]);
  assert.equal(ui.state().nextDisabled,true);
  const afterFresh=ui.requests.length;
  ui.openOverview(); ui.openSites();
  assert.equal(ui.requests.length,afterFresh,'Successful current-policy read remains cached');
  ui.refreshSites().respond(page());
  assert.equal(ui.state().rows.length,1,'Explicit Refresh still fetches new data');
});

test('Review R3: valid no-op policy acknowledgment safely releases deferred inventory read', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:8}));
  ui.openSites().respond(page());
  ui.openOverview();
  const write=ui.toggleMonitor('site_inventory',true);
  const count=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,count,'No data read during even a no-op write');
  write.respond(monitorAck({changed:false,state_revision:8}));
  assert.equal(ui.state().stateRevision,'State revision: 8');
  const fresh=ui.requests.at(-1);
  assert.match(fresh.options.url,/s=get_sites$/);
  assert.equal(ui.requests.length,count+1);
  fresh.respond(page([]));
  assert.deepEqual(ui.state().rows,[['No sites in this page']]);
  assert.equal(ui.state().nextDisabled,true);
});

test('Review R3: PHP-only Monitor update does not stall or invalidate Websites inventory', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:8}));
  ui.openSites().respond(page());
  ui.openOverview();
  const mutation=ui.toggleMonitor('php_fpm_file_preview',false);
  const pendingCount=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,pendingCount,'Unrelated policy does not invalidate cached Websites');
  assert.equal(ui.state().rows.length,1);
  mutation.respond(monitorAck({state_revision:9,
    modules_enabled:{site_inventory:true,php_fpm_file_preview:false}}));
  ui.openOverview(); ui.openSites();
  assert.equal(ui.requests.length,pendingCount,'No duplicate Websites request after PHP-only update');
  assert.equal(ui.state().rows.length,1);
});

test('Review R3: changing Website Monitor invalidates cached and in-flight inventory only', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_revision:5}));
  const old = ui.openSites();
  ui.openOverview();
  const mutation = ui.toggleMonitor('site_inventory',false);
  mutation.respond(monitorAck({
    state_revision:6, modules_enabled:{site_inventory:false,php_fpm_file_preview:true}
  }));
  old.respond(page());
  assert.deepEqual(ui.state().rows, [], 'Old pending inventory must not be displayed');
  assert.equal(ui.state().nextDisabled, true);
  assert.match(ui.state().siteStatus, /Monitor settings changed/);
  const fresh = ui.openSites();
  assert.match(fresh.options.url, /s=get_sites$/);
  fresh.respond({status:false, stage:'monitor_disabled', msg:'Website inventory disabled'});
  assert.deepEqual(ui.state().rows, []);
  assert.equal(ui.state().nextDisabled, true);
});

test('Review R3: a loaded Website snapshot reloads once after Overall Monitor change', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview({state_revision:1}));
  ui.openSites().respond(page());
  ui.openOverview();
  ui.toggleMonitor('overall', false).respond(monitorAck({
    state_revision:2,overall_enabled:false,mode:'Disabled'
  }));
  assert.deepEqual(ui.state().rows, []);
  const count = ui.requests.length;
  const fresh = ui.openSites();
  assert.equal(ui.requests.length, count + 1);
  fresh.respond(page([]));
  const rereadCount = ui.requests.length;
  ui.openOverview(); ui.openSites();
  assert.equal(ui.requests.length, rereadCount, 'Clean tab return must remain cached');
});

const reviewActivity = (entries = []) => ({
  status:true,schema:1,read_only:true,configured_level:'INFO',entries
});
const reviewActivityEntry = () => ({
  schema:1,time_utc:'2026-11-04T00:00:00Z',level:'INFO',module:'monitor',
  action:'set_control',stage:'complete',outcome:'success',
  operation_id:'f'.repeat(32),target:'overall',detail:'Changed',
  recovery_id:'',error_class:''
});

test('Review R3: operation completion invalidates Activity and reveals new evidence once', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  ui.openActivity().respond(reviewActivity());
  ui.openOverview();
  ui.toggleMonitor('overall',false).respond(monitorAck({state_revision:1,overall_enabled:false}));
  assert.deepEqual(ui.activityRows(), [], 'Old Activity rows must not masquerade as current');
  assert.match(ui.activityMessage(), /may have changed/);
  const next = ui.openActivity();
  assert.match(next.options.url, /s=get_activity$/);
  next.respond(reviewActivity([reviewActivityEntry()]));
  assert.equal(ui.activityRows().length,1);
  const count=ui.requests.length;
  ui.openOverview(); ui.openActivity();
  assert.equal(ui.requests.length,count,'Unrelated navigation does not refetch a clean snapshot');
});

test('Review R3: completion while Activity is already open invalidates in-flight results', () => {
  const ui = loadUi();
  ui.respondOverview(monitorOverview());
  const write=ui.toggleMonitor('overall',false);
  const pending=ui.openActivity();
  write.respond(monitorAck({state_revision:1,overall_enabled:false}));
  const fresh=ui.requests.at(-1);
  assert.notEqual(fresh,pending);
  assert.match(fresh.options.url,/s=get_activity$/);
  pending.respond(reviewActivity());
  fresh.respond(reviewActivity([reviewActivityEntry()]));
  assert.equal(ui.activityRows().length,1);
});

test('Review R3: successful and failed PHP-FPM Apply mark Activity stale, including warnings', () => {
  for (const result of ['success','failure']) {
    const ui=loadUi();
    ui.openActivity().respond(reviewActivity([reviewActivityEntry()]));
    ui.openOverview();
    ui.submitPhp().respond(phpPreview());
    ui.prepareFpm().respond(guardedPlan());
    ui.approveFpm(true);
    const operation=ui.commitFpm();
    if (result==='success') operation.respond(appliedResult({
      activity_logged:false, activity_warning:'Plugin Activity persistence uncertain'
    }));
    else operation.reject(null,'timeout');
    assert.deepEqual(ui.activityRows(), []);
    assert.match(ui.activityMessage(),/may have changed/);
    const read=ui.openActivity();
    assert.match(read.options.url,/s=get_activity$/);
    read.respond(reviewActivity());
    assert.deepEqual(ui.activityRows(),[['No matching activity records.']]);
  }
});

test('Review R3: Status Pages writes invalidate Activity without clearing unrelated unsaved fields', () => {
  const ui=loadUi();
  ui.openActivity().respond(reviewActivity());
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-name','Unsaved ACh');
  const save=ui.statusClick('#ach-status-save');
  save.respond({status:true,schema:1,revision:3,effective:brand(),changed:true,source:'Global'});
  assert.match(ui.activityMessage(),/may have changed/);
  const read=ui.openActivity();
  assert.match(read.options.url,/s=get_activity$/);
  read.respond(reviewActivity());
  ui.openStatus();
  assert.equal(ui.requests.at(-1),read,'Cached status panel was not reloaded');
});


test('Review R2: a malformed or older acknowledged Monitor revision is not shown as success', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:7}));
  const mutation=ui.toggleMonitor('overall',false);
  mutation.respond(monitorOverview({state_revision:6,overall_enabled:false}));
  assert.equal(ui.state().stateRevision,'State revision: 7');
  assert.equal(ui.state().controls.overall.checked,true);
  assert.match(ui.state().overview,/stale or incompatible/);
  ui.refreshOverview().respond(monitorOverview({state_revision:8,overall_enabled:false}));
  assert.equal(ui.state().controls.overall.checked,false);
  assert.equal(ui.state().controls.overall.disabled,false);
});

test('Review R3: Status Pages reset and failed save each invalidate prior Activity snapshot', () => {
  for (const action of ['reset','failed-save']) {
    const ui=loadUi();
    ui.openActivity().respond(reviewActivity([reviewActivityEntry()]));
    ui.openStatus().respond(statusPrefs());
    let operation;
    if (action==='reset') {
      ui.statusSetChecked('#ach-status-reset-approve',true);
      operation=ui.statusClick('#ach-status-reset');
      operation.respond({status:true,schema:1,revision:3,effective:brand(),source:'Global'});
    } else {
      operation=ui.statusClick('#ach-status-save');
      operation.reject(null,'timeout');
    }
    assert.deepEqual(ui.activityRows(),[]);
    assert.match(ui.activityMessage(),/may have changed/);
    ui.openActivity().respond(reviewActivity());
    assert.deepEqual(ui.activityRows(),[['No matching activity records.']]);
  }
});

test('Review R3: PHP-FPM Restore confirmation and uncertain result both invalidate Activity', () => {
  for (const action of ['success','timeout']) {
    const ui=loadUi();
    ui.openActivity().respond(reviewActivity([reviewActivityEntry()]));
    ui.openOverview();
    ui.inspectFpmRecovery().respond(recoveryPreview());
    ui.approveFpmRollback(true);
    const operation=ui.rollbackFpm();
    if (action==='success') operation.respond(rolledBackResult({
      activity_logged:false,activity_warning:'Plugin Activity log not persisted'
    }));
    else operation.reject(null,'timeout');
    assert.deepEqual(ui.activityRows(),[]);
    assert.match(ui.activityMessage(),/may have changed/);
    const next=ui.openActivity();
    assert.match(next.options.url,/s=get_activity$/);
    next.respond(reviewActivity());
  }
});


test('Native Nginx form rhythm: compact left labels, 150px inputs and responsive reflow', () => {
  assert.match(html, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/,
    'Desktop setting groups must have two balanced columns');
  assert.match(html, /grid-template-columns:minmax\(0,1fr\) minmax\(0,150px\)/,
    'Each setting has a 150px Nginx-style input with a neighboring label');
  assert.match(html, /@media \(max-width:880px\)/);
  assert.match(html, /@media \(max-width:460px\)/);
  assert.match(html, /class="ach-field-site"/);
  assert.match(html, /#ach-customizer \.ach-table-skeleton\[hidden\]/);
  assert.match(html, /prefers-reduced-motion:reduce/);
});

test('Website initial pending shows skeleton, never a fabricated empty inventory', () => {
  const ui=loadUi();
  const request=ui.openSites();
  assert.equal(ui.state().sitesSkeletonHidden,false);
  assert.equal(ui.state().sitesTableRowsHidden,true);
  assert.equal(ui.state().prevDisabled,true);
  assert.equal(ui.state().nextDisabled,true);
  assert.match(ui.state().siteStatus,/Loading website inventory/);
  assert.doesNotMatch(ui.state().siteStatus,/No sites/);
  request.respond(page([]));
  assert.equal(ui.state().sitesSkeletonHidden,true);
  assert.equal(ui.state().sitesTableRowsHidden,false);
  assert.deepEqual(ui.state().rows,[['No sites in this page']]);
});

test('Website refresh and errors always settle skeleton; retry remains available', () => {
  const ui=loadUi();
  ui.openSites().respond(page());
  const req=ui.refreshSites();
  assert.equal(ui.state().sitesSkeletonHidden,false);
  assert.equal(ui.state().sitesTableRowsHidden,true);
  req.respond({status:false,stage:'inventory_disabled',msg:'Monitor disabled'});
  assert.equal(ui.state().sitesSkeletonHidden,true);
  assert.equal(ui.state().sitesTableRowsHidden,false);
  assert.equal(ui.state().rows.length,0);
  assert.match(ui.state().siteStatus,/unavailable/i);
  const retry=ui.refreshSites();
  assert.equal(ui.state().sitesSkeletonHidden,false);
  retry.respond(page([]));
  assert.equal(ui.state().sitesSkeletonHidden,true);
  assert.equal(ui.state().sitesTableRowsHidden,false);
});

test('Old invalidated Website read cannot cancel current request skeleton', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:3}));
  const old=ui.openSites();
  ui.openOverview();
  // A valid set_control ack includes the CAS changed bit. An ordinary
  // get_overview fixture must not unlock pending Website reads.
  ui.toggleMonitor('site_inventory',false).respond(monitorAck({
    state_revision:4,modules_enabled:{site_inventory:false,php_fpm_file_preview:true}
  }));
  const fresh=ui.openSites();
  assert.equal(ui.state().sitesSkeletonHidden,false);
  old.respond(page());
  assert.equal(ui.state().sitesSkeletonHidden,false,'Stale reply must not hide fresh pending skeleton');
  fresh.respond({status:false,stage:'monitor_disabled',msg:'Website inventory disabled'});
  assert.equal(ui.state().sitesSkeletonHidden,true);
});

test('Policy uncertainty hides Websites skeleton without pretending a read is pending', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:7}));
  const old=ui.openSites();
  assert.equal(ui.state().sitesSkeletonHidden,false);
  ui.openOverview();
  const mutation=ui.toggleMonitor('site_inventory',false);
  assert.equal(ui.state().sitesSkeletonHidden,true,'Old request skeleton was invalidated');
  const count=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,count,'Pending policy must block new website reads');
  assert.equal(ui.state().sitesSkeletonHidden,true);
  assert.equal(ui.state().sitesTableRowsHidden,false);
  old.respond(page());
  assert.deepEqual(ui.state().rows,[]);
  mutation.reject(null,'timeout');
  assert.match(ui.state().siteStatus,/unverified/i);
  assert.equal(ui.state().sitesSkeletonHidden,true);
  ui.openOverview();
  ui.refreshOverview().respond(monitorOverview({state_schema:2,state_revision:8,
    modules_enabled:{site_inventory:false,php_fpm_file_preview:true}}));
  const blocked=ui.requests.length;
  ui.openSites();
  assert.equal(ui.requests.length,blocked,'Invalid recovery GET cannot enable Website reads');
  assert.equal(ui.state().sitesSkeletonHidden,true);
  ui.openOverview();
  ui.refreshOverview().respond(monitorOverview({state_revision:8,
    modules_enabled:{site_inventory:false,php_fpm_file_preview:true}}));
  const fresh=ui.openSites();
  assert.match(fresh.options.url,/s=get_sites$/);
  assert.equal(ui.state().sitesSkeletonHidden,false);
  assert.equal(ui.state().sitesTableRowsHidden,true);
  fresh.respond(page([]));
  assert.equal(ui.state().sitesSkeletonHidden,true);
  assert.equal(ui.state().sitesTableRowsHidden,false);
});

test('Activity loading, empty/error and retry states maintain truthful loading feedback', () => {
  const ui=loadUi();
  const initial=ui.openActivity();
  assert.equal(ui.state().activitySkeletonHidden,false);
  assert.equal(ui.state().activityTableRowsHidden,true);
  assert.match(ui.activityMessage(),/Loading recent activity/);
  initial.respond(reviewActivity());
  assert.equal(ui.state().activitySkeletonHidden,true);
  assert.equal(ui.state().activityTableRowsHidden,false);
  assert.deepEqual(ui.activityRows(),[['No matching activity records.']]);
  const retry=ui.activityRefresh();
  assert.equal(ui.state().activitySkeletonHidden,false);
  retry.reject(null,'timeout');
  assert.equal(ui.state().activitySkeletonHidden,true);
  assert.equal(ui.state().activityTableRowsHidden,false);
  assert.match(ui.activityMessage(),/unavailable/i);
});

test('Changing Activity filter keeps only newest pending request visible', () => {
  const ui=loadUi();
  const old=ui.openActivity();
  const fresh=ui.activityFilter('#ach-activity-level','ERROR');
  assert.equal(ui.state().activitySkeletonHidden,false);
  old.respond(reviewActivity([reviewActivityEntry()]));
  assert.equal(ui.state().activitySkeletonHidden,false);
  fresh.respond(reviewActivity());
  assert.equal(ui.state().activitySkeletonHidden,true);
  assert.deepEqual(ui.activityRows(),[['No matching activity records.']]);
});

test('Review optional: rapid reentry does not duplicate same pending Status or Activity reads', () => {
  const ui=loadUi();
  const status=ui.openStatus();
  ui.openSites();
  const afterSites=ui.requests.length;
  ui.openStatus();
  assert.equal(ui.requests.length,afterSites);
  status.respond(statusPrefs());
  const pendingActivity=ui.openActivity();
  const activityCount=ui.requests.length;
  ui.openStatus(); ui.openActivity();
  assert.equal(ui.requests.length,activityCount);
  pendingActivity.reject(null,'timeout');
  ui.openSites(); ui.openActivity();
  assert.equal(ui.requests.length,activityCount+1,'Retry after failure remains possible');
});

const nativeSiteForDrift = (id, name) => ({
  id, name, document_root:'/srv/' + id, panel_status:'1', bound_domains:[[name, 80]]
});
const siteChangesPayload = (overrides = {}) => ({
  status:true, schema:1, state:'Baseline Missing', scope:'native_site_records',
  read_only:true, runtime_verified:false, baseline_revision:0,
  baseline_sha256:null, source_sha256:'a'.repeat(64), site_count:1, changes:[],
  note:'aaPanel database only; runtime not verified.', ...overrides
});

test('Site lifecycle comparison requires reviewed baseline and refuses blind retry', () => {
  const ui=loadUi();
  ui.openSites().respond(page());
  const compare=ui.siteChangesCompare();
  assert.match(compare.options.url,/s=compare_site_changes$/);
  compare.respond(siteChangesPayload());
  assert.match(ui.state().siteChangesStatus,/Baseline Missing/);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  ui.siteChangesApprove(true);
  assert.equal(ui.state().siteChangesSaveDisabled,false);
  const save=ui.siteChangesSave();
  assert.match(save.options.url,/s=save_site_baseline$/);
  assert.equal(save.options.data.expected_revision,0);
  assert.equal(save.options.data.expected_source_sha256,'a'.repeat(64));
  assert.equal(save.options.data.reviewed,'true');
  assert.deepEqual(Object.keys(save.options.data).sort(),
    ['expected_revision','expected_source_sha256','reviewed']);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  save.respond({status:true,schema:1,state:'Baseline Saved',changed:true,
    baseline_revision:1,source_sha256:'a'.repeat(64)});
  assert.match(ui.state().siteChangesStatus,/Baseline Saved/);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
});

test('Website lifecycle Monitor renders HTML as text and invalidates old approval on Refresh', () => {
  const ui=loadUi();
  ui.openSites().respond(page());
  const before=nativeSiteForDrift(3,'old.example.test');
  const after=nativeSiteForDrift(3,'<svg onload=alert(1)>');
  ui.siteChangesCompare().respond(siteChangesPayload({
    state:'Changes Observed',baseline_revision:1,baseline_sha256:'b'.repeat(64),
    changes:[{id:3,kind:'Changed',fields:['name','bound_domains'],before,after}]
  }));
  assert.deepEqual(ui.state().siteChangesRows,[
    ['3','Changed','<svg onload=alert(1)>','name, bound_domains']]);
  ui.siteChangesApprove(true);
  assert.equal(ui.state().siteChangesSaveDisabled,false);
  ui.refreshSites();
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  assert.deepEqual(ui.state().siteChangesRows,[]);
});

test('Malformed website lifecycle payload and uncertain save outcome fail closed', () => {
  for (const bad of [
    siteChangesPayload({read_only:false}),
    siteChangesPayload({source_sha256:'x'}),
    siteChangesPayload({baseline_revision:5,baseline_sha256:null}),
    siteChangesPayload({state:'No Changes',changes:[{id:1}]}),
    siteChangesPayload({changes:[{id:3,kind:'Added',before:null,
      after:nativeSiteForDrift(3,'new.example.test'),fields:[]}]}),
    siteChangesPayload({state:'Changes Observed',baseline_revision:1,
      baseline_sha256:'b'.repeat(64),changes:[{id:3,kind:'Changed',
        fields:['document_root'],before:nativeSiteForDrift(3,'old'),
        after:nativeSiteForDrift(3,'new')}]})
  ]) {
    const ui=loadUi();
    ui.openSites().respond(page());
    ui.siteChangesCompare().respond(bad);
    assert.equal(ui.state().siteChangesSaveDisabled,true);
    assert.match(ui.state().siteChangesStatus,/unconfirmed or incompatible/);
    assert.deepEqual(ui.state().siteChangesRows,[]);
  }
  const ui=loadUi();
  ui.openSites().respond(page());
  ui.siteChangesCompare().respond(siteChangesPayload());
  ui.siteChangesApprove(true);
  ui.siteChangesSave().respond({status:true,schema:1,state:'Baseline Saved',
    changed:true,baseline_revision:9,source_sha256:'a'.repeat(64)});
  assert.match(ui.state().siteChangesStatus,/outcome unconfirmed/);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  assert.equal(ui.state().siteChangesApproveDisabled,true);
  assert.match(ui.siteChangesCompare().options.url,/s=compare_site_changes$/);
});
