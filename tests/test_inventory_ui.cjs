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
  const content = {scrollTop:0};
  let focusedTab = null, tabScrollCalls = 0;
  const elements = new Map();
  const tabs = ['overview', 'websites', 'php', 'status', 'activity'].map(name => fakeNode('button', {
    'data-tab': name, 'aria-selected': name === 'overview' ? 'true' : 'false'
  }));
  const views = ['overview', 'websites', 'php', 'status', 'activity'].map(name => fakeNode('section', {
    'data-view': name
  }));
  root.querySelector = query => query === '#ach-content' ? content : null;
  root.querySelectorAll = query => query === '[data-tab]' ? tabs : [];
  for (const tab of tabs) {
    elements.set('#ach-tab-' + tab.attributes['data-tab'], tab);
    tab.focus = () => { focusedTab = tab; };
    tab.click = () => trigger(tab, 'click');
    tab.scrollIntoView = () => { tabScrollCalls++; };
  }
  for (const name of [
    '#ach-message', '#ach-overview-status', '#ach-overview-control-result', '#ach-overview-refresh',
    '#ach-sites-rows', '#ach-sites-loading', '#ach-sites-status', '#ach-sites-refresh',
    '#ach-site-changes-compare', '#ach-site-changes-approve',
    '#ach-site-changes-save', '#ach-site-changes-status', '#ach-site-changes-rows',
    '#ach-hosts-site-id', '#ach-hosts-inspect-button', '#ach-hosts-result',
    '#ach-cache-inspect-button', '#ach-cache-result',
    '#ach-cache-plan-button', '#ach-cache-plan-result',
    '#ach-cache-activation-preview', '#ach-cache-activation-recheck',
    '#ach-cache-activation-result', '#ach-cache-activation-reviewed',
    '#ach-cache-activation-apply', '#ach-cache-restore-reviewed',
    '#ach-cache-activation-restore',
    '#ach-vhost-inspect-button', '#ach-vhost-result',
    '#ach-nginx-candidate-button', '#ach-nginx-candidate-result',
    '#ach-page', '#ach-prev', '#ach-next', '#ach-php-form',
    '#ach-fpm-result', '#ach-diff-rows', '#ach-state-revision',
    '#ach-fpm-policy-recheck', '#ach-fpm-policy-recheck-status',
    '#ach-fpm-policy-diff-rows', '#ach-fpm-policy-impact', '#ach-fpm-policy-impact-rows',
    '#ach-fpm-policy-load', '#ach-fpm-policy-reviewed', '#ach-fpm-policy-save',
    '#ach-fpm-policy-status',
    '#ach-max-children', '#ach-start-servers', '#ach-min-spare',
    '#ach-max-spare', '#ach-max-requests',
    '#ach-impact-summary', '#ach-impact-rows',
    '#ach-php-version', '#ach-php-discover', '#ach-php-discovery-status',
    '#ach-php-runtime-check', '#ach-php-runtime-result',
    '#ach-php-topology-rows', '#ach-php-topology-summary',
    '#ach-fpm-prepare', '#ach-fpm-plan', '#ach-fpm-operation-notice', '#ach-fpm-review',
    '#ach-fpm-details', '#ach-fpm-approval', '#ach-fpm-commit',
    '#ach-fpm-recovery-version', '#ach-fpm-check-recovery', '#ach-fpm-recovery-status',
    '#ach-fpm-recovery-impact', '#ach-fpm-restore-rows',
    '#ach-fpm-rollback-controls', '#ach-fpm-rollback-approval', '#ach-fpm-rollback',
    '#ach-status-template', '#ach-status-locale', '#ach-status-scope', '#ach-status-site-id', '#ach-status-delivery',
    '#ach-status-name', '#ach-status-tagline', '#ach-status-url', '#ach-status-label',
    '#ach-status-accent', '#ach-status-background', '#ach-status-foreground',
    '#ach-status-footer', '#ach-status-load', '#ach-status-preview-button',
    '#ach-status-preview-surface', '#ach-status-site-audit', '#ach-status-site-preflight',
    '#ach-status-workflow-note',
    '#ach-status-manage-section', '#ach-status-default-section',
    '#ach-status-unbound-section', '#ach-status-stopped-section',
    '#ach-status-save', '#ach-status-reset', '#ach-status-reset-approve',
    '#ach-status-source', '#ach-status-result', '#ach-status-sha', '#ach-status-iframe',
    '#ach-status-inspect-button', '#ach-status-inspect-result',
    '#ach-status-probe-button', '#ach-status-probe-result', '#ach-status-adoption-result',
    '#ach-status-manage-recheck', '#ach-status-manage-apply',
    '#ach-status-manage-restore', '#ach-status-manage-apply-approve',
    '#ach-status-manage-restore-approve', '#ach-status-manage-result',
    '#ach-status-default-recheck', '#ach-status-default-apply',
    '#ach-status-default-restore', '#ach-status-default-apply-approve',
    '#ach-status-default-restore-approve', '#ach-status-default-result',
    '#ach-status-unbound-recheck', '#ach-status-unbound-apply',
    '#ach-status-unbound-restore', '#ach-status-unbound-apply-approve',
    '#ach-status-unbound-restore-approve', '#ach-status-unbound-result',
    '#ach-status-stopped-recheck', '#ach-status-stopped-apply',
    '#ach-status-stopped-restore', '#ach-status-stopped-apply-approve',
    '#ach-status-stopped-restore-approve', '#ach-status-stopped-result',
    '#ach-status-comparison-summary', '#ach-status-comparison-excerpt',
    '#ach-status-sites-more', '#ach-status-sites-retry', '#ach-status-sites-state',
    '#ach-activity-level', '#ach-activity-module', '#ach-activity-refresh',
    '#ach-activity-result', '#ach-activity-rows', '#ach-activity-loading'
  ]) elements.set(name, fakeNode('div'));
  for (const [selector, val] of [
    ['#ach-status-template','404'], ['#ach-status-locale','en'],
    ['#ach-status-scope','global'], ['#ach-status-site-id',''], ['#ach-status-delivery','extension'],
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
  elements.get('#ach-fpm-recovery-version').props.value = '85';
  elements.get('#ach-php-runtime-check').props.disabled = true;
  const requests = [];
  let allowStatusDiscard = false;
  const statusConfirmations = [];
  const browserWindow = {
    innerWidth:1280,
    confirm(message) {
      statusConfirmations.push(message);
      return allowStatusDiscard;
    }
  };

  function selection(nodes) {
    return {
      0: nodes[0],
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
        if (query.includes(',') && query.startsWith('#ach-')) {
          const selected = query.split(',').map(key => elements.get(key.trim()));
          assert.ok(selected.every(Boolean), 'Unknown plugin selector group: ' + query);
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
        for (const node of nodes) {
          node.props.value = value;
          for (const [selector, item] of elements) {
            if (item !== node) continue;
            const field = /^#ach-(max-children|start-servers|min-spare|max-spare|max-requests)$/.exec(selector);
            if (field) {
              const current = elements.get('#ach-php-form').props.fields || [];
              const name = { 'min-spare':'min_spare_servers',
                'max-spare':'max_spare_servers' }[field[1]] || field[1].replace(/-/g, '_');
              const target = current.find(entry => entry.name === name);
              if (target) target.value = String(value);
            }
          }
        }
        return this;
      },
      serializeArray() {
        return nodes[0]?.props.fields || [];
      },
      trigger(event) {
        for (const node of nodes) {
          const callback = node.handlers[event] || node.handlers['input change'];
          if (callback) callback.call(node, {preventDefault() {}});
        }
        return this;
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

  vm.runInNewContext(script, { $, encodeURIComponent, TextEncoder,
    window:browserWindow }, { timeout: 1000 });

  function trigger(node, event, details = {}) {
    assert.equal(typeof node.handlers[event], 'function', event + ' handler missing');
    const payload = { ...details, prevented:false,
      preventDefault() { this.prevented = true; } };
    node.handlers[event].call(node, payload);
    return payload;
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
      cacheResult: elements.get('#ach-cache-result').textContent,
      cachePlanResult: elements.get('#ach-cache-plan-result').textContent,
      cachePlanDisabled: elements.get('#ach-cache-plan-button').props.disabled,
      cacheActivationResult: elements.get('#ach-cache-activation-result').textContent,
      cacheActivationPreviewDisabled: elements.get('#ach-cache-activation-preview').props.disabled,
      cacheActivationRecheckDisabled: elements.get('#ach-cache-activation-recheck').props.disabled,
      cacheActivationApplyDisabled: elements.get('#ach-cache-activation-apply').props.disabled,
      cacheActivationRestoreDisabled: elements.get('#ach-cache-activation-restore').props.disabled,
      vhostResult: elements.get('#ach-vhost-result').textContent,
      nginxCandidateResult: elements.get('#ach-nginx-candidate-result').textContent,
      nginxCandidateDisabled: elements.get('#ach-nginx-candidate-button').props.disabled,
      vhostInspectDisabled: elements.get('#ach-vhost-inspect-button').props.disabled,
      cacheInspectDisabled: elements.get('#ach-cache-inspect-button').props.disabled,
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
      statusPreviewHidden: elements.get('#ach-status-preview-surface').props.hidden,
      statusWorkflowVisible: Object.fromEntries([
        ['audit','#ach-status-site-audit'], ['preflight','#ach-status-site-preflight'],
        ['manage','#ach-status-manage-section'],
        ['defaults','#ach-status-default-section'], ['unbound','#ach-status-unbound-section'],
        ['stopped','#ach-status-stopped-section'], ['previewOnly','#ach-status-workflow-note']
      ].map(([key,id]) => [key,elements.get(id).props.hidden === false])),
      statusHash: elements.get('#ach-status-sha').textContent,
      statusSaveDisabled: elements.get('#ach-status-save').props.disabled,
      statusResetDisabled: elements.get('#ach-status-reset').props.disabled,
      statusInspectDisabled: elements.get('#ach-status-inspect-button').props.disabled,
      statusProbeDisabled: elements.get('#ach-status-probe-button').props.disabled,
      statusProbe: elements.get('#ach-status-probe-result').textContent,
      statusManage: elements.get('#ach-status-manage-result').textContent,
      statusManageRecheckDisabled: elements.get('#ach-status-manage-recheck').props.disabled,
      statusManageApplyDisabled: elements.get('#ach-status-manage-apply').props.disabled,
      statusManageRestoreDisabled: elements.get('#ach-status-manage-restore').props.disabled,
      defaultSourceResult: elements.get('#ach-status-default-result').textContent,
      defaultSourceRecheckDisabled: elements.get('#ach-status-default-recheck').props.disabled,
      defaultSourceApplyDisabled: elements.get('#ach-status-default-apply').props.disabled,
      defaultSourceRestoreDisabled: elements.get('#ach-status-default-restore').props.disabled,
      unboundResult: elements.get('#ach-status-unbound-result').textContent,
      stoppedResult: elements.get('#ach-status-stopped-result').textContent,
      stoppedRecheckDisabled: elements.get('#ach-status-stopped-recheck').props.disabled,
      stoppedApplyDisabled: elements.get('#ach-status-stopped-apply').props.disabled,
      stoppedRestoreDisabled: elements.get('#ach-status-stopped-restore').props.disabled,
      unboundRecheckDisabled: elements.get('#ach-status-unbound-recheck').props.disabled,
      unboundApplyDisabled: elements.get('#ach-status-unbound-apply').props.disabled,
      unboundRestoreDisabled: elements.get('#ach-status-unbound-restore').props.disabled,
      statusAdoption: elements.get('#ach-status-adoption-result').textContent,
      statusInspect: elements.get('#ach-status-inspect-result').textContent,
      statusCompareSummary: elements.get('#ach-status-comparison-summary').textContent,
      statusCompareExcerpt: elements.get('#ach-status-comparison-excerpt').textContent,
      impactSummary: elements.get('#ach-impact-summary').textContent,
      phpDiscovery: elements.get('#ach-php-discovery-status').textContent,
      phpRuntime: elements.get('#ach-php-runtime-result').textContent,
      phpTopology: elements.get('#ach-php-topology-summary').textContent,
      phpTopologyRows: elements.get('#ach-php-topology-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      phpRuntimeDisabled: elements.get('#ach-php-runtime-check').props.disabled,
      phpVersion: elements.get('#ach-php-version').props.value,
      fpmFormFields: Object.fromEntries((elements.get('#ach-php-form').props.fields || [])
        .map(field => [field.name, field.value])),
      phpVersionDisabled: elements.get('#ach-php-version').props.disabled,
      phpOptions: elements.get('#ach-php-version').children.map(option => ({
        value:option.props.value, disabled:option.props.disabled, text:option.textContent
      })),
      fpmPlan: elements.get('#ach-fpm-plan').textContent,
      fpmOperationNotice: elements.get('#ach-fpm-operation-notice').textContent,
      fpmDetails: elements.get('#ach-fpm-details').textContent,
      fpmReviewHidden: elements.get('#ach-fpm-review').props.hidden,
      fpmPrepareDisabled: elements.get('#ach-fpm-prepare').props.disabled,
      fpmPolicyStatus: elements.get('#ach-fpm-policy-status').textContent,
      fpmPolicyRecheckStatus: elements.get('#ach-fpm-policy-recheck-status').textContent,
      fpmPolicyRecheckDisabled: elements.get('#ach-fpm-policy-recheck').props.disabled,
      fpmPolicyRecheckDiffRows: elements.get('#ach-fpm-policy-diff-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      fpmPolicyRecheckImpact: elements.get('#ach-fpm-policy-impact').textContent,
      fpmPolicyRecheckSiteRows: elements.get('#ach-fpm-policy-impact-rows').children.map(tr =>
        tr.children.map(td => td.textContent)),
      fpmPolicySaveDisabled: elements.get('#ach-fpm-policy-save').props.disabled,
      fpmPolicyLoadDisabled: elements.get('#ach-fpm-policy-load').props.disabled,
      fpmPolicyReviewedDisabled: elements.get('#ach-fpm-policy-reviewed').props.disabled,
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
    setViewportWidth:width => { browserWindow.innerWidth = width; },
    setMainScroll:value => { content.scrollTop = value; },
    mainScroll:() => content.scrollTop,
    selectedTab:() => tabs.find(tab => tab.attributes['aria-selected'] === 'true')?.attributes['data-tab'],
    keyTab:(name, key) => {
      const tab=tabs.find(item => item.attributes['data-tab'] === name);
      const event=trigger(tab, 'keydown', {key});
      return {prevented:event.prevented, focused:focusedTab?.attributes['data-tab'],
        selected:tabs.find(item => item.attributes['aria-selected'] === 'true')?.attributes['data-tab']};
    },
    tabScrollCalls:() => tabScrollCalls,
    statusPermitDiscard: value => { allowStatusDiscard = value; },
    statusConfirmations: () => statusConfirmations.slice(),
    statusSelection: () => ({
      scope:elements.get('#ach-status-scope').props.value,
      site:elements.get('#ach-status-site-id').props.value
    }),
    openStatus, statusSetValue, statusSetChecked, statusClick, openActivity,
    openPhp,
    loadFpmPolicy: () => { trigger(elements.get('#ach-fpm-policy-load'),'click'); return requests.at(-1); },
    recheckFpmPolicy: () => { trigger(elements.get('#ach-fpm-policy-recheck'),'click'); return requests.at(-1); },
    saveFpmPolicy: () => { trigger(elements.get('#ach-fpm-policy-save'),'click'); return requests.at(-1); },
    reviewFpmPolicy:checked => {
      elements.get('#ach-fpm-policy-reviewed').props.checked=checked;
      trigger(elements.get('#ach-fpm-policy-reviewed'),'change');
    },
    inspectPhpRuntime: () => { trigger(elements.get('#ach-php-runtime-check'), 'click'); return requests.at(-1); },
    selectPhpVersion: v => { elements.get('#ach-php-version').props.value=v; trigger(elements.get('#ach-php-version'), 'change'); },
    refreshPhp: () => { trigger(elements.get('#ach-php-discover'), 'click'); return requests.at(-1); }, phpVersions,
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
    selectRecoveryVersion: v => {
      elements.get('#ach-fpm-recovery-version').props.value=v;
      trigger(elements.get('#ach-fpm-recovery-version'), 'change');
    },
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
    statusFieldDisabled: (selector = '#ach-status-name') => elements.get(selector).props.disabled,
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

const fpmPolicyPreview = (overrides = {}) => ({
  ...phpPreview(),
  fpm_observation_sha256: 'c'.repeat(64),
  fpm_saved_policy: {
    schema:1, version:'85', policy_revision:0, monitor_revision:0,
    saved:false, desired:null, read_only:true, runtime_verified:false,
    auto_enforce:false, scope:'shared_service', pool:'www', note:'Monitor only'
  },
  ...overrides
});

const fpmPolicyRecheck = (overrides = {}) => ({
  status:true, schema:1, version:'85', policy_revision:4, monitor_revision:2,
  scope:'shared_service', pool:'www', saved:true, read_only:true,
  runtime_verified:false, auto_enforce:false, apply_eligible:false,
  state:'File Drift', reason:'', note:'Point-in-time file only',
  desired:{'pm.max_children':50,'pm.start_servers':5,
    'pm.min_spare_servers':5,'pm.max_spare_servers':10,'pm.max_requests':300},
  source:'/www/server/php/85/etc/php-fpm.conf',
  source_observation_sha256:'f'.repeat(64),
  changes:[{setting:'pm.max_children',desired:50,actual:80}],
  shared_impact:phpImpact(), ...overrides
});

test('Recheck saved PHP service intent reports real drift and affected file-linked sites', () => {
  const ui=loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  assert.equal(ui.state().fpmPolicyRecheckDisabled,false);
  const request=ui.recheckFpmPolicy();
  assert.match(request.options.url,/s=fpm_policy_recheck$/);
  assert.equal(request.options.data.php_version,'85');
  assert.equal(request.options.data.max_children,undefined,
    'browser must never supply desired policy values for a saved-policy recheck');
  request.respond(fpmPolicyRecheck());
  const actual=ui.state();
  assert.match(actual.fpmPolicyRecheckStatus,/PHP 85 shared \[www\]: File Drift/);
  assert.match(actual.fpmPolicyRecheckStatus,/separately approve guarded Apply/);
  assert.match(actual.fpmPolicyRecheckImpact,/2 PHP 85 file-linked site\(s\)/);
  assert.deepEqual(actual.fpmPolicyRecheckDiffRows,
    [['pm.max_children','50','80']]);
  assert.deepEqual(actual.fpmPolicyRecheckSiteRows,[
    ['3','site-a.test','PHP 85 (file only)'],
    ['6','<img src=x onerror=alert(1)>','PHP 85 (file only)']]);
  assert.equal(actual.fpmCommitDisabled,true);
  assert.equal(ui.requests.filter(req=>/s=fpm_apply$/.test(req.options.url)).length,0);
});

test('No saved PHP policy is distinguished from File Match and does not invent impact', () => {
  const ui=loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  ui.recheckFpmPolicy().respond(fpmPolicyRecheck({
    state:'No Policy', saved:false, desired:null, changes:[],
    shared_impact:null, reason:'No reviewed policy for this PHP version'
  }));
  assert.match(ui.state().fpmPolicyRecheckStatus,/No Policy/);
  assert.deepEqual(ui.state().fpmPolicyRecheckSiteRows,[]);
  assert.deepEqual(ui.state().fpmPolicyRecheckDiffRows,[]);
  ui.recheckFpmPolicy().respond(fpmPolicyRecheck({state:'File Match',changes:[]}));
  assert.match(ui.state().fpmPolicyRecheckStatus,/File Match/);
  assert.match(ui.state().fpmPolicyRecheckImpact,/file-linked site/);
});

test('Unresolved shared mapping stays visible, but recheck never enables Apply', () => {
  const ui=loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  ui.recheckFpmPolicy().respond(fpmPolicyRecheck({
    shared_impact:phpImpact({state:'Needs Review',site_count:4,
      unresolved_sites:[{id:99,site_key:'other.example',reason:'Unknown PHP include'}]})
  }));
  assert.match(ui.state().fpmPolicyRecheckImpact,/Needs Review/);
  assert.deepEqual(ui.state().fpmPolicyRecheckSiteRows.at(-1),
    ['99','other.example','Needs Review: Unknown PHP include']);
  assert.equal(ui.state().fpmCommitDisabled,true);
});

test('Stale version callback or forged recheck response cannot infer PHP policy status', () => {
  const ui=loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  const slow=ui.recheckFpmPolicy();
  ui.selectPhpVersion('81');
  slow.respond(fpmPolicyRecheck());
  assert.doesNotMatch(ui.state().fpmPolicyRecheckStatus,/File Drift/);
  assert.deepEqual(ui.state().fpmPolicyRecheckSiteRows,[]);
  ui.selectPhpVersion('85');
  ui.recheckFpmPolicy().respond(fpmPolicyRecheck({apply_eligible:true}));
  assert.match(ui.state().fpmPolicyRecheckStatus,/unavailable or incompatible/);
  assert.deepEqual(ui.state().fpmPolicyRecheckDiffRows,[]);
  assert.equal(ui.state().fpmCommitDisabled,true);
});

test('Saved PHP policy read failure preserves stage and Operation ID inline', () => {
  const ui=loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  ui.recheckFpmPolicy().respond({status:false,stage:'fpm_policy_recheck',
    msg:'Native PHP source changed during inspection',
    operation_id:'b'.repeat(32)});
  assert.match(ui.state().fpmPolicyRecheckStatus,/Saved policy read failed at fpm_policy_recheck/);
  assert.match(ui.state().fpmPolicyRecheckStatus,/Native PHP source changed/);
  assert.match(ui.state().fpmPolicyRecheckStatus,/Operation ID: b{32}/);
  assert.deepEqual(ui.state().fpmPolicyRecheckSiteRows,[]);
});

test('Fresh PHP preview permits reviewed desired-policy save without invoking FPM Apply', () => {
  const ui = loadUi();
  const preview = ui.submitPhp();
  preview.respond(fpmPolicyPreview());
  assert.equal(ui.state().fpmPolicyReviewedDisabled,false);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  ui.reviewFpmPolicy(true);
  assert.equal(ui.state().fpmPolicySaveDisabled,false);
  const saving = ui.saveFpmPolicy();
  assert.match(saving.options.url, /s=fpm_policy_save$/);
  assert.equal(saving.options.data.expected_policy_revision,0);
  assert.equal(saving.options.data.expected_monitor_revision,0);
  assert.equal(saving.options.data.expected_observation_sha256,'c'.repeat(64));
  assert.equal(saving.options.data.reviewed,'true');
  assert.equal(saving.options.data.php_version,'85');
  saving.respond({status:true,schema:1,state:'Policy Saved',version:'85',
    scope:'shared_service',auto_enforce:false,runtime_verified:false,
    policy_revision:1, changed:true});
  assert.match(ui.state().fpmPolicyStatus,/Policy Saved \(revision 1\)/);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.equal(ui.requests.filter(r=>/s=fpm_apply$/.test(r.options.url)).length,0);
});

test('Changing PHP values or missing a trusted source token revokes policy-save authorization', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.reviewFpmPolicy(true);
  ui.changePhp('max_children','81');
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  assert.equal(ui.state().fpmPolicyReviewedDisabled,true);
  const count = ui.requests.length;
  ui.saveFpmPolicy();
  assert.equal(ui.requests.length,count);
  ui.submitPhp('85',false).respond(fpmPolicyPreview({
    fpm_observation_sha256:'not-a-hash'
  }));
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  assert.equal(ui.state().fpmPolicyReviewedDisabled,true);
});

test('Rejected PHP policy save preserves actionable backend stage and Operation ID inline', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.reviewFpmPolicy(true);
  const req = ui.saveFpmPolicy();
  req.respond({status:false, stage:'fpm_policy_save',
    msg:'Saved PHP policy changed; reload and inspect again',
    operation_id:'a'.repeat(32)});
  assert.match(ui.state().fpmPolicyStatus, /Policy save rejected at fpm_policy_save/);
  assert.match(ui.state().fpmPolicyStatus, /Saved PHP policy changed/);
  assert.match(ui.state().fpmPolicyStatus, /Operation ID: a{32}/);
  assert.match(ui.state().fpmPolicyStatus, /Reload saved policy state before another save/);
  assert.doesNotMatch(ui.state().fpmPolicyStatus, /outcome unconfirmed/);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
});

test('Policy read authorization failure explains cause instead of a generic empty result', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  const req = ui.loadFpmPolicy();
  req.respond({status:false,stage:'fpm_policy_authorization',
    msg:'Full primary aaPanel administrator POST is required',
    operation_id:'b'.repeat(32)});
  assert.match(ui.state().fpmPolicyStatus,/Saved policy read failed at fpm_policy_authorization/);
  assert.match(ui.state().fpmPolicyStatus,/Full primary aaPanel administrator POST/);
  assert.match(ui.state().fpmPolicyStatus,/Operation ID: b{32}/);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
});

test('Transport-unknown policy save never pretends rejection or successful persistence', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.reviewFpmPolicy(true);
  const req = ui.saveFpmPolicy();
  req.reject(null,'timeout');
  assert.match(ui.state().fpmPolicyStatus,/Policy save outcome unconfirmed/);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
});

test('A stale policy save cannot claim a completed host operation or restore review', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.reviewFpmPolicy(true);
  const pending = ui.saveFpmPolicy();
  ui.changePhp('max_children','101');
  pending.respond({status:true,schema:1,state:'Policy Saved',version:'85',
    scope:'shared_service',auto_enforce:false,runtime_verified:false,
    policy_revision:1,changed:true});
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  assert.equal(ui.state().fpmPolicyReviewedDisabled,true);
  assert.doesNotMatch(ui.state().fpmPolicyStatus,/Policy Saved/);
});

test('Saved PHP policy loads reviewed values as draft and requires a new Preview', () => {
  const ui = loadUi();
  ui.submitPhp().respond(fpmPolicyPreview());
  ui.selectPhpVersion('85');
  assert.equal(ui.state().fpmPolicyLoadDisabled,false);
  const load = ui.loadFpmPolicy();
  assert.match(load.options.url,/s=fpm_policy_get$/);
  load.respond({status:true,schema:1,version:'85',policy_revision:4,
    monitor_revision:0,saved:true,
    desired:{'pm.max_children':30,'pm.start_servers':5,
      'pm.min_spare_servers':5,'pm.max_spare_servers':10,'pm.max_requests':300},
    read_only:true,runtime_verified:false,auto_enforce:false,
    scope:'shared_service',pool:'www'});
  assert.match(ui.state().fpmPolicyStatus,/Loaded saved shared PHP 85 desired values/);
  assert.equal(ui.state().fpmPolicySaveDisabled,true);
  assert.equal(ui.state().fpmPrepareDisabled,true);
  assert.equal(ui.state().fpmFormFields.max_children,'30');
  assert.equal(ui.state().fpmFormFields.max_requests,'300');
  assert.equal(ui.requests.filter(r=>/s=fpm_apply$/.test(r.options.url)).length,0);
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

test('Explicitly ineligible PHP file mapping remains visible but cannot enable Manual Apply', () => {
  const ui = loadUi();
  const request = ui.submitPhp();
  request.respond(phpPreview(phpImpact({
    manual_apply_eligible: false,
    note: 'Native assignment remains ineligible until its route is fully verified.'
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


function loadNativeStatusSiteSelection(ui, id='7', panelStatus='1') {
  const request = ui.requests.at(-1);
  assert.match(request.options.url,/s=status_sites$/);
  const native = {...site(),id:Number(id),name:'demo.test',
    document_root:'/www/demo.test',panel_status:panelStatus,
    bound_domains:[{name:'demo.test',port:80}],canonical_domain_bound:true};
  request.respond({...page([native]),purpose:'status_site_selection'});
  ui.statusSetValue('#ach-status-site-id',id,'change');
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

const nginxHelperAudit = (overrides={}) => ({
  schema:1,state:'Not Installed',version:null,active_verified:false,
  purge_method_verified:false,cache_path_verified:false,purge_safe_verified:false,
  reason:'',note:'No standard Nginx Helper plugin observed.',...overrides
});
const cacheInspection = (overrides={}) => ({
  status:true,schema:1,site_id:7,site_key:'site.test',
  read_only:true,runtime_verified:false,cache_safe_verified:false,
  purge_supported:false,fix_supported:false,
  state:'Source Observed',zone_state:'Direct Zone',cache_zone:'WORDPRESS',
  global_zone_directly_declared:false,
  aaPanel_global_include_observed:true,
  cache_directory:'/www/server/fastcgi_cache',
  global_ignore_headers:['Set-Cookie','Cache-Control'],
  purge_scope:'Shared Registered Directory',
  other_sites_same_directory:[{id:8,site_key:'other.test'}],
  bypass_directive_seen:true,no_cache_directive_seen:true,
  host_key_variable_seen:true,purge_directive_seen:true,
  ignore_headers:['Set-Cookie'],
  findings:['SHARED_ZONE_REFERENCES','SHARED_CACHE_DIRECTORY_PURGE_RISK',
    'GLOBAL_RESPONSE_CACHE_HEADER_IGNORED','RESPONSE_CACHE_HEADER_IGNORED',
    'PURGE_DIRECTIVE_OBSERVED','PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED'],
  other_sites_same_zone:[{id:8,site_key:'other.test'}],
  unresolved_other_sites:0,inspected_sites:2,source_sha256:'b'.repeat(64),
  reason:'',note:'Source-only observation. No loaded cache or Nginx Helper safety claim.',
  nginx_helper:nginxHelperAudit(),
  ...overrides
});

const cachePlan = (overrides={}) => ({
  status:true,schema:1,site_id:7,site_key:'site.test',source_sha256:'a'.repeat(64),
  state:'Reference Only',read_only:true,installed:false,runtime_verified:false,
  safe_verified:false,apply_supported:false,purge_supported:false,
  cache_zone:'ACHFC_7',cache_directory:'/www/server/ach-customizer-fastcgi/site-7',
  php_version:'85',proposal_sha256:'b'.repeat(64),reason:'',
  global_http_fragment:'fastcgi_cache_path /www/server/ach-customizer-fastcgi/site-7 ' +
    'keys_zone=ACHFC_7:10m;' + ' '.repeat(90),
  site_server_fragment:'location ~ \.php$ { fastcgi_no_cache $upstream_http_set_cookie; }' +
    ' '.repeat(90),
  note:'Preview only. No Apply, Reload or Purge.',
  ...overrides
});

const vhostInspection = (overrides={}) => ({
  status:true,schema:1,site_id:7,site_key:'site.test',
  state:'File Match',read_only:true,runtime_verified:false,fix_supported:false,
  vhost_sha256:'a'.repeat(64),native_root:'/www/site.test',
  vhost_root:'/www/site.test',native_names:['site.test'],
  vhost_names:['site.test'],listen_ports:[80],findings:[],reason:'',
  note:'Generated file only; no active Nginx routing proof.',...overrides
});

const nginxCandidate = (overrides={}) => ({
  status:true,schema:1,site_id:7,site_key:'site.test',
  state:'Candidate Included',read_only:true,runtime_verified:false,fix_supported:false,
  candidate_config_test_passed:true,candidate_vhost_included:true,
  candidate_config_sha256:'a'.repeat(64),vhost_content_sha256:'b'.repeat(64),
  origin_http:{state:'Response Observed',host:'site.test',
    http_status:200,site_identity_verified:false},
  reason:'',note:'Next-load source only; localhost HEAD does not identify selected site.',
  ...overrides
});

test('Selected native Nginx candidate check separates prospective config and HTTP status', () => {
  const ui=loadUi();selectHostsSite(ui);
  assert.equal(ui.state().nginxCandidateDisabled,false);
  const req=ui.statusClick('#ach-nginx-candidate-button');
  assert.match(req.options.url,/s=inspect_nginx_candidate$/);
  assert.equal(req.options.type,'POST');
  assert.deepEqual(Object.keys(req.options.data).sort(),[
    'expected_site_key','expected_site_snapshot','site_id']);
  assert.deepEqual(JSON.parse(req.options.data.expected_site_snapshot),[
    7,'site.test','/www/site.test','1',[['site.test',80]]]);
  assert.equal(ui.state().nginxCandidateDisabled,true);
  req.respond(nginxCandidate());
  assert.equal(ui.state().nginxCandidateDisabled,false);
  assert.match(ui.state().nginxCandidateResult,/Candidate Included/);
  assert.match(ui.state().nginxCandidateResult,/HTTP 200/);
  assert.match(ui.state().nginxCandidateResult,/Running-worker config verified: NO/);
  assert.match(ui.state().nginxCandidateResult,/responding site identity verified: NO/);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/safe to purge|enforcement enabled/);
});

test('Nginx candidate errors, missing native HTTP and invalid claims fail closed', () => {
  const ui=loadUi();selectHostsSite(ui);
  ui.statusClick('#ach-nginx-candidate-button').respond(nginxCandidate({
    state:'Candidate Not Included',candidate_vhost_included:false,
    origin_http:{state:'Unavailable',host:'site.test',http_status:null,
      site_identity_verified:false,reason:'localhost HTTP/80 HEAD unavailable (ConnectionRefusedError)'}
  }));
  assert.match(ui.state().nginxCandidateResult,/Candidate Not Included/);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/HTTP 200/);
  ui.statusClick('#ach-nginx-candidate-button').respond(nginxCandidate({
    state:'Needs Review',reason:'Unstable included source',
    candidate_config_test_passed:false,candidate_vhost_included:false,
    candidate_config_sha256:null,vhost_content_sha256:null,
    origin_http:{state:'Not Attempted',host:null,http_status:null,
      site_identity_verified:false}
  }));
  assert.match(ui.state().nginxCandidateResult,/Needs Review/);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/Candidate Included/);
  const forged = [
    {runtime_verified:true},{fix_supported:true},
    {candidate_config_sha256:'notsha'},
    {candidate_vhost_included:false},{candidate_config_test_passed:false},
    {origin_http:{state:'Response Observed',host:'other.test',
      http_status:200,site_identity_verified:true}},
    {origin_http:{state:'Response Observed',host:'site.test',
      http_status:700,site_identity_verified:false}}
  ];
  for (const change of forged) {
    ui.statusClick('#ach-nginx-candidate-button').respond(nginxCandidate(change));
    assert.match(ui.state().nginxCandidateResult,/incompatible or unconfirmed/);
    assert.doesNotMatch(ui.state().nginxCandidateResult,/Syntax check: PASS/);
  }
  const down=ui.statusClick('#ach-nginx-candidate-button');
  down.respond({status:false,stage:'website_nginx_observation',msg:'Native Nginx unavailable',
    operation_id:'e'.repeat(32)});
  assert.match(ui.state().nginxCandidateResult,/Read-only inspection failed at website_nginx_observation/);
  assert.match(ui.state().nginxCandidateResult,/Operation ID:/);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/Syntax check: PASS/);
});

test('Nginx candidate discards stale selection responses and locks on page refresh', () => {
  const ui=loadUi();selectHostsSite(ui);
  const pending=ui.statusClick('#ach-nginx-candidate-button');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  pending.respond(nginxCandidate());
  assert.match(ui.state().nginxCandidateResult,/selection or inventory changed/);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/Candidate Included/);
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  ui.statusClick('#ach-nginx-candidate-button').respond(nginxCandidate());
  assert.match(ui.state().nginxCandidateResult,/Candidate Included/);
  const refreshing=ui.refreshSites();
  assert.equal(ui.state().nginxCandidateDisabled,true);
  assert.doesNotMatch(ui.state().nginxCandidateResult,/Candidate Included/);
  refreshing.respond(hostsInventory());
  assert.equal(ui.state().nginxCandidateDisabled,true);
});

test('Generated VHost comparison binds native site snapshot, shows drift without offering writes', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  assert.equal(ui.state().vhostInspectDisabled,false);
  const req=ui.statusClick('#ach-vhost-inspect-button');
  assert.match(req.options.url,/s=inspect_native_vhost$/);
  assert.equal(req.options.type,'POST');
  assert.deepEqual(Object.keys(req.options.data).sort(),[
    'expected_site_key','expected_site_snapshot','site_id']);
  assert.deepEqual(JSON.parse(req.options.data.expected_site_snapshot),[
    7,'site.test','/www/site.test','1',[['site.test',80]]]);
  assert.equal(ui.state().vhostInspectDisabled,true);
  req.respond(vhostInspection({
    state:'File Drift',vhost_root:'/www/stale',vhost_names:['old.site.test'],
    findings:['DOCUMENT_ROOT_MISMATCH','BOUND_HOST_MISSING_IN_VHOST',
      'VHOST_HOST_NOT_IN_NATIVE_BINDINGS']
  }));
  assert.equal(ui.state().vhostInspectDisabled,false);
  assert.match(ui.state().vhostResult,/Generated VHost: File Drift/);
  assert.match(ui.state().vhostResult,/DOCUMENT_ROOT_MISMATCH/);
  assert.match(ui.state().vhostResult,/generated|Generated/);
  assert.doesNotMatch(ui.state().vhostResult,/Apply change|Fix automatically|runtime verified/);
});

test('VHost uncertain source and invalid replies never claim a matching file', () => {
  const invalid=[{site_id:8},{site_key:'other.test'},{runtime_verified:true},
    {fix_supported:true},{vhost_sha256:'forged'},
    {state:'File Match',findings:['DOCUMENT_ROOT_MISMATCH']},
    {state:'File Match',vhost_root:'/www/stale'},
    {state:'File Match',vhost_names:['other.site.test']},
    {state:'File Match',native_names:[],vhost_names:[]},
    {state:'File Match',native_names:['site.test..'],vhost_names:['site.test..']},
    {state:'File Drift',vhost_root:'/www/stale',findings:['BOUND_HOST_MISSING_IN_VHOST']},
    {state:'File Drift',vhost_names:['other.site.test'],
     findings:['VHOST_HOST_NOT_IN_NATIVE_BINDINGS','BOUND_HOST_MISSING_IN_VHOST']},
    {state:'File Drift',vhost_names:['site.test'],findings:['DOCUMENT_ROOT_MISMATCH']},
    {state:'File Drift',findings:[]},
    {native_names:['<img src=x onerror=alert(1)>']},
    {listen_ports:[99999]},
    {state:'Needs Review',reason:'Unsupported',vhost_sha256:'a'.repeat(64)}];
  for(const reply of invalid) {
    const ui=loadUi();selectHostsSite(ui);
    ui.statusClick('#ach-vhost-inspect-button').respond(vhostInspection(reply));
    assert.match(ui.state().vhostResult,/unavailable or incompatible/,JSON.stringify(reply));
  }
  const ui=loadUi();selectHostsSite(ui);
  ui.statusClick('#ach-vhost-inspect-button').respond(vhostInspection({
    state:'Needs Review',vhost_sha256:null,native_root:null,vhost_root:null,
    native_names:[],vhost_names:[],listen_ports:[],findings:[],
    reason:'Unsupported third-party Nginx extension'
  }));
  assert.match(ui.state().vhostResult,/Needs Review/);
  assert.doesNotMatch(ui.state().vhostResult,/File Match/);
});

test('VHost controlled backend failures keep stage, reason and correlation beside inspect', () => {
  const cases=[
    {stage:'website_vhost_inspection',msg:'Native site/root/bindings changed; refresh website inventory',
      operation_id:'a'.repeat(32)},
    {stage:'website_vhost_authorization',msg:'Full primary aaPanel administrator session and POST are required',
      operation_id:'b'.repeat(32)},
    {stage:'website_vhost_inspection',msg:'Native site changed during VHost comparison',
      operation_id:'c'.repeat(32)}
  ];
  for (const rejected of cases) {
    const ui=loadUi();selectHostsSite(ui);
    ui.statusClick('#ach-vhost-inspect-button').respond({status:false,...rejected});
    const info=ui.state().vhostResult;
    assert.match(info,/Read-only inspection failed at/);
    assert.ok(info.includes(rejected.stage),info);
    assert.ok(info.includes(rejected.msg),info);
    assert.ok(info.includes('Operation ID: ' + rejected.operation_id),info);
    assert.doesNotMatch(info,/Generated VHost: File Match/);
    assert.equal(ui.state().vhostInspectDisabled,false);
  }
});

test('VHost invalid backend reply and network failures are not mistaken for authoritative inspection', () => {
  const ui=loadUi();selectHostsSite(ui);
  ui.statusClick('#ach-vhost-inspect-button').respond({status:false,
    stage:'<script>',msg:'unsafe',operation_id:'invalid'});
  assert.match(ui.state().vhostResult,/failed or timed out/);
  assert.doesNotMatch(ui.state().vhostResult,/<script>/);
  const request=ui.statusClick('#ach-vhost-inspect-button');
  request.reject(null,'timeout');
  assert.match(ui.state().vhostResult,/failed or timed out/);
  assert.doesNotMatch(ui.state().vhostResult,/File Match/);
  assert.equal(ui.state().vhostInspectDisabled,false);
});

test('VHost stale rejection after site selection change never resurfaces old error detail', () => {
  const ui=loadUi();selectHostsSite(ui);
  const old=ui.statusClick('#ach-vhost-inspect-button');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  old.respond({status:false,stage:'website_vhost_inspection',
    msg:'stale-private-error',operation_id:'d'.repeat(32)});
  assert.doesNotMatch(ui.state().vhostResult,/stale-private-error|Operation ID:/);
  assert.match(ui.state().vhostResult,/changed/);
});

test('VHost results are revoked on selection changes and inventory refresh', () => {
  const ui=loadUi();selectHostsSite(ui);
  const pending=ui.statusClick('#ach-vhost-inspect-button');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  pending.respond(vhostInspection());
  assert.match(ui.state().vhostResult,/changed/);
  assert.doesNotMatch(ui.state().vhostResult,/File Match/);
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  ui.statusClick('#ach-vhost-inspect-button').respond(vhostInspection());
  assert.match(ui.state().vhostResult,/File Match/);
  const refresh=ui.refreshSites();
  assert.equal(ui.state().vhostInspectDisabled,true);
  assert.doesNotMatch(ui.state().vhostResult,/File Match/);
  refresh.respond(hostsInventory());
  assert.equal(ui.state().vhostInspectDisabled,true);
});

test('Isolated cache reference is native-site bound and rendered as inert text only', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  assert.equal(ui.state().cachePlanDisabled,false);
  const req=ui.statusClick('#ach-cache-plan-button');
  assert.match(req.options.url,/s=preview_cache_safety$/);
  assert.equal(req.options.type,'POST');
  assert.deepEqual(Object.keys(req.options.data).sort(),[
    'expected_site_key','expected_site_snapshot','site_id'
  ]);
  assert.equal(ui.state().cachePlanDisabled,true);
  req.respond(cachePlan());
  assert.equal(ui.state().cachePlanDisabled,false);
  assert.match(ui.state().cachePlanResult,/REFERENCE ONLY — NOT INSTALLED/);
  assert.match(ui.state().cachePlanResult,/ACHFC_7/);
  assert.match(ui.state().cachePlanResult,/NO PURGE/);
  assert.doesNotMatch(ui.state().cachePlanResult,/SAFE-VERIFIED: YES/);
});

const cacheActivationReady = (overrides={}) => ({
  status:true, schema:1, state:'Ready for Review', read_only:true,
  apply_supported:true, runtime_verified:false, site_id:7,
  site_key:'site.test', source_sha256:'a'.repeat(64),
  proposal_sha256:'b'.repeat(64), cache_generation:'c'.repeat(32),
  php_version:'85', php_probe_status:301, cache_zone:'ACHFC_7',
  cache_directory:'/www/server/ach-customizer-fastcgi/site-7',
  impact:'One selected HTTP/80 VHost and Nginx service reload',
  note:'Runtime WordPress and WooCommerce acceptance remains separate',
  ...overrides
});
const cacheOperationApplied = (overrides={}) => ({
  status:true,schema:1,state:'Applied',changed:true,site_id:7,
  site_key:'site.test',journal_phase:'applied',
  recovery_id:'f'.repeat(32),runtime_verified:true,
  purge_supported:false, ...overrides
});
const cacheOperationRestored = (overrides={}) => ({
  status:true,schema:1,state:'Restored',changed:true,site_id:7,
  site_key:'site.test',journal_phase:'restored',
  recovery_id:'f'.repeat(32),runtime_verified:true,
  purge_supported:false, ...overrides
});

test('Site Cache Apply and Restore require exact approval and recovery identity', () => {
  const ui=loadUi(); selectHostsSite(ui);
  assert.equal(ui.state().cacheActivationPreviewDisabled,false);
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  const preflight=ui.statusClick('#ach-cache-activation-preview');
  assert.match(preflight.options.url,/s=preview_cache_activation$/);
  assert.equal(preflight.options.type,'POST');
  assert.deepEqual(Object.keys(preflight.options.data).sort(),[
    'expected_site_key','expected_site_snapshot','site_id'
  ]);
  assert.equal(ui.state().cacheActivationPreviewDisabled,true);
  preflight.respond(cacheActivationReady());
  assert.match(ui.state().cacheActivationResult,/Ready|preflight ready/);
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
  const attempts=ui.requests.length;
  ui.statusClick('#ach-cache-activation-apply');
  assert.equal(ui.requests.length,attempts,'Apply cannot start before review');
  ui.statusSetChecked('#ach-cache-activation-reviewed',true);
  assert.equal(ui.state().cacheActivationApplyDisabled,false);
  const apply=ui.statusClick('#ach-cache-activation-apply');
  assert.match(apply.options.url,/s=manage_cache_policy$/);
  assert.equal(apply.options.type,'POST');
  assert.equal(apply.options.data.cache_action,'apply');
  assert.equal(apply.options.data.action,undefined,'aaPanel reserves form action for routing');
  assert.equal(apply.options.data.expected_source_sha256,'a'.repeat(64));
  assert.equal(apply.options.data.expected_proposal_sha256,'b'.repeat(64));
  assert.equal(apply.options.data.cache_generation,'c'.repeat(32));
  assert.equal(apply.options.timeout,45000);
  assert.equal(apply.options.data.approved,'true');
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
  apply.respond(cacheOperationApplied());
  assert.match(ui.state().cacheActivationResult,/Cache Apply observed/);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  const recheck=ui.statusClick('#ach-cache-activation-recheck');
  assert.equal(recheck.options.data.cache_action,'recheck');
  assert.equal(recheck.options.data.action,undefined);
  assert.equal(recheck.options.data.approved,undefined);
  recheck.respond({status:true,schema:1,state:'Applied',site_id:7,
    site_key:'site.test',journal_phase:'applied',recovery_id:'f'.repeat(32),read_only:true,
    runtime_verified:true,purge_supported:false,note:'Site-managed PHP marker'});
  assert.match(ui.state().cacheActivationResult,/Cache state: Applied/);
  ui.statusSetChecked('#ach-cache-restore-reviewed',true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,false);
  const restore=ui.statusClick('#ach-cache-activation-restore');
  assert.equal(restore.options.data.cache_action,'restore');
  assert.equal(restore.options.data.action,undefined);
  assert.equal(restore.options.data.recovery_id,'f'.repeat(32));
  assert.equal(restore.options.data.approved,'true');
  restore.respond(cacheOperationRestored());
  assert.match(ui.state().cacheActivationResult,/Cache Restore observed/);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
});

test('Cache Restore consent distinguishes conditional reload from no-op recovery', () => {
  assert.match(html,/I approve restoring this site's saved Cache state\. Nginx may reload; verified unactivated recovery does not\./);
  assert.match(html,/id="ach-cache-activation-restore"[^>]*>Restore saved Cache \/ recovery<\/button>/);
  assert.doesNotMatch(html,/Restore saved Cache \(reload Nginx\)/);
});

test('Prepublication Cache journal is recoverable from UI without false activation proof', () => {
  const ui=loadUi(); selectHostsSite(ui);
  const id='e'.repeat(32);
  const original=ui.requests.length;
  ui.statusClick('#ach-cache-activation-restore');
  assert.equal(ui.requests.length,original,'no Restore without recovery Recheck');
  const recheck=ui.statusClick('#ach-cache-activation-recheck');
  recheck.respond({status:true,schema:1,state:'Recovery Required',site_id:7,
    site_key:'site.test',journal_phase:'prepared',recovery_scope:'prepublication',
    recovery_id:id,read_only:true,runtime_verified:false,purge_supported:false,
    note:'Cache never activated; explicit Restore can finalize without reload.'});
  assert.match(ui.state().cacheActivationResult,/Cache state: Recovery Required/);
  assert.match(ui.state().cacheActivationResult,/Recovery ID: e{32}/);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  ui.statusSetChecked('#ach-cache-restore-reviewed',true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,false);
  const restore=ui.statusClick('#ach-cache-activation-restore');
  assert.equal(restore.options.data.cache_action,'restore');
  assert.equal(restore.options.data.recovery_id,id);
  assert.equal(restore.options.data.approved,'true');
  restore.respond({status:true,schema:1,state:'Restored',site_id:7,
    site_key:'site.test',journal_phase:'restored',recovery_id:id,
    changed:false,runtime_verified:false,
    recovery_scope:'prepublication',purge_supported:false});
  assert.match(ui.state().cacheActivationResult,/recovery finalized/);
  assert.match(ui.state().cacheActivationResult,/no Cache was activated or Nginx reloaded/);
  assert.doesNotMatch(ui.state().cacheActivationResult,/NOT CONFIRMED/);
  const finalized=ui.statusClick('#ach-cache-activation-recheck');
  finalized.respond({status:true,schema:1,state:'Restored',site_id:7,
    site_key:'site.test',journal_phase:'restored',recovery_scope:'prepublication',
    recovery_id:id,read_only:true,runtime_verified:false,purge_supported:false});
  assert.match(ui.state().cacheActivationResult,/Cache state: Restored/);
  assert.doesNotMatch(ui.state().cacheActivationResult,/Cache recovery state not verified|Recheck unavailable/i);
  ui.statusSetChecked('#ach-cache-restore-reviewed',true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
});

test('Restored Cache journal with resurrected files stays Needs Review and cannot authorize Restore', () => {
  const ui=loadUi(); selectHostsSite(ui);
  const id='e'.repeat(32);
  const recheck=ui.statusClick('#ach-cache-activation-recheck');
  recheck.respond({status:true,schema:1,state:'Needs Review',site_id:7,
    site_key:'site.test',journal_phase:'restored',recovery_id:id,
    read_only:true,runtime_verified:false,purge_supported:false,
    note:'Restored Cache sources reappeared without an approved Apply'});
  assert.match(ui.state().cacheActivationResult,/Needs Review/);
  ui.statusSetChecked('#ach-cache-restore-reviewed',true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  const before=ui.requests.length;
  ui.statusClick('#ach-cache-activation-restore');
  assert.equal(ui.requests.length,before);
  ui.statusClick('#ach-cache-activation-recheck').respond({
    status:true,schema:1,state:'Restored',site_id:7,journal_phase:'restored',
    recovery_id:id,read_only:true,runtime_verified:false,purge_supported:false});
  assert.match(ui.state().cacheActivationResult,/not verified|unavailable/i,
    'Restored with no runtime evidence must have exact prepublication proof');
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  ui.statusClick('#ach-cache-activation-recheck').respond({
    status:true,schema:1,state:'Applied',site_id:7,journal_phase:'restored',
    recovery_id:id,read_only:true,runtime_verified:true,purge_supported:false});
  assert.match(ui.state().cacheActivationResult,/not verified|unavailable/i,
    'Restored journal cannot authorize a forged Applied state');
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
});

test('Cache Recheck rejects contradictory phase, recovery scope, runtime and site identity', () => {
  const id='e'.repeat(32);
  const applied={status:true,schema:1,site_id:7,site_key:'site.test',
    state:'Applied',journal_phase:'applied',recovery_id:id,
    read_only:true,runtime_verified:true,purge_supported:false};
  const invalid=[
    {recovery_scope:'prepublication'},
    {journal_phase:'restored'},
    {site_key:'other.test'},
    {site_id:8},
    {runtime_verified:false},
    {state:'Restored',journal_phase:'restored',recovery_scope:'prepublication'},
    {state:'Restored',journal_phase:'restored',runtime_verified:false},
    {state:'Recovery Required',journal_phase:'applied',
      recovery_scope:'prepublication',runtime_verified:false},
    {state:'Recovery Required',journal_phase:'restored',runtime_verified:false},
    {state:'Recovery Required',journal_phase:'prepared',runtime_verified:true},
    {state:'Unmanaged',journal_phase:'applied',runtime_verified:false},
    {purge_supported:true},
  ];
  for(const bad of invalid){
    const ui=loadUi(); selectHostsSite(ui);
    ui.statusClick('#ach-cache-activation-recheck').respond({...applied,...bad});
    assert.match(ui.state().cacheActivationResult,/not verified|unavailable/i,
      'reject contradictory response '+JSON.stringify(bad));
    ui.statusSetChecked('#ach-cache-restore-reviewed',true);
    assert.equal(ui.state().cacheActivationRestoreDisabled,true,JSON.stringify(bad));
  }
  const valid=loadUi();selectHostsSite(valid);
  valid.statusClick('#ach-cache-activation-recheck').respond({...applied,
    state:'Restored',journal_phase:'restored',
    recovery_scope:'prepublication',runtime_verified:false});
  assert.match(valid.state().cacheActivationResult,/Cache state: Restored/);
  assert.equal(valid.state().cacheActivationRestoreDisabled,true);
});

test('Cache Restore refuses contradictory scope, phase, site identity and runtime', () => {
  const id='e'.repeat(32);
  const normal={status:true,schema:1,state:'Restored',site_id:7,
    site_key:'site.test',journal_phase:'restored',recovery_id:id,
    changed:true,runtime_verified:true,purge_supported:false};
  const badReplies=[
    {recovery_scope:'prepublication'},
    {journal_phase:'applied'},
    {site_key:'other.test'},
    {site_id:8},
    {changed:false},
    {runtime_verified:false},
    {recovery_id:'f'.repeat(32)},
    {purge_supported:true},
    {recovery_scope:'prepublication',changed:false,runtime_verified:true},
    {recovery_scope:'prepublication',changed:true,runtime_verified:false},
  ];
  for(const bad of badReplies){
    const ui=loadUi();selectHostsSite(ui);
    ui.statusClick('#ach-cache-activation-recheck').respond({
      status:true,schema:1,state:'Applied',site_id:7,site_key:'site.test',
      journal_phase:'applied',recovery_id:id,read_only:true,
      runtime_verified:true,purge_supported:false});
    ui.statusSetChecked('#ach-cache-restore-reviewed',true);
    assert.equal(ui.state().cacheActivationRestoreDisabled,false);
    const response=ui.statusClick('#ach-cache-activation-restore');
    assert.equal(response.options.data.recovery_id,id);
    response.respond({...normal,...bad});
    assert.match(ui.state().cacheActivationResult,/NOT CONFIRMED/,JSON.stringify(bad));
    assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  }
});

test('Cache no-op Restore response without prepublication proof is not confirmed', () => {
  const ui=loadUi(); selectHostsSite(ui);
  const id='e'.repeat(32);
  ui.statusClick('#ach-cache-activation-recheck').respond({status:true,schema:1,
    state:'Recovery Required',site_id:7,site_key:'site.test',journal_phase:'prepared',
    recovery_id:id,read_only:true,runtime_verified:false,purge_supported:false});
  ui.statusSetChecked('#ach-cache-restore-reviewed',true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,false);
  const restore=ui.statusClick('#ach-cache-activation-restore');
  restore.respond({status:true,schema:1,state:'Restored',site_id:7,
    recovery_id:id,changed:false,runtime_verified:false,purge_supported:false});
  assert.match(ui.state().cacheActivationResult,/NOT CONFIRMED/);
});

test('Forged Cache readiness never permits Apply, HTML text stays inert', () => {
  const ui=loadUi(); selectHostsSite(ui);
  for (const bad of [
    {site_id:8},{site_key:'foreign.test'},{apply_supported:false},
    {runtime_verified:true},{cache_zone:'WORDPRESS'},
    {cache_directory:'/var/cache/shared'},
    {source_sha256:'broken'},{proposal_sha256:'broken'},
    {cache_generation:'bad'},{cache_generation:'d'.repeat(31)},
    {php_probe_status:404},{php_probe_status:599},
    {state:'Needs Review'},{php_version:'86'}
  ]) {
    ui.statusClick('#ach-cache-activation-preview').respond(
      cacheActivationReady(bad));
    ui.statusSetChecked('#ach-cache-activation-reviewed',true);
    assert.equal(ui.state().cacheActivationApplyDisabled,true,JSON.stringify(bad));
  }
  const malicious='<img src=x onerror=evil()>';
  ui.statusClick('#ach-cache-activation-preview').respond(
    cacheActivationReady({note:malicious}));
  assert.match(ui.state().cacheActivationResult,/<img src=x onerror=evil\(\)>/);
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
});

test('A changed native website revokes in-flight Cache Apply approval and recovery', () => {
  const ui=loadUi(); selectHostsSite(ui);
  const pending=ui.statusClick('#ach-cache-activation-preview');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  pending.respond(cacheActivationReady());
  assert.match(ui.state().cacheActivationResult,/changed/);
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  const before=ui.requests.length;
  ui.statusClick('#ach-cache-activation-apply');
  assert.equal(ui.requests.length,before);
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  ui.statusClick('#ach-cache-activation-preview').respond(cacheActivationReady());
  ui.statusSetChecked('#ach-cache-activation-reviewed',true);
  assert.equal(ui.state().cacheActivationApplyDisabled,false);
  const next=ui.statusClick('#ach-cache-activation-apply');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  next.respond(cacheOperationApplied());
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
  assert.doesNotMatch(ui.state().cacheActivationResult,/Cache Apply observed/);
});

test('Cache reference rejects forged writer claims and never renders raw HTML', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  for(const x of [
    {apply_supported:true},{purge_supported:true},{installed:true},
    {safe_verified:true},{runtime_verified:true},{site_key:'other.test'},
    {site_id:8},{cache_zone:'WORDPRESS'},{cache_directory:'/var/cache/other'},
    {global_http_fragment:'<img src=x onerror=evil()>'},
    {php_version:'86'},{proposal_sha256:'bad'},
    {state:'Needs Review',global_http_fragment:'real data'}
  ]) {
    ui.statusClick('#ach-cache-plan-button').respond(cachePlan(x));
    assert.match(ui.state().cachePlanResult,/unavailable or incompatible/,JSON.stringify(x));
  }
  const literal='<img src=x onerror=evil()>';
  ui.statusClick('#ach-cache-plan-button').respond(cachePlan({
    site_server_fragment:literal + ' '.repeat(150)
  }));
  assert.match(ui.state().cachePlanResult,/<img src=x onerror=evil\(\)>/);
});

test('Cache reference revokes stale async response after native-site navigation', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  const old=ui.statusClick('#ach-cache-plan-button');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  old.respond(cachePlan());
  assert.match(ui.state().cachePlanResult,/changed/);
  assert.doesNotMatch(ui.state().cachePlanResult,/ACHFC_7/);
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  ui.statusClick('#ach-cache-plan-button').respond(cachePlan({
    state:'Needs Review',cache_zone:null,cache_directory:null,php_version:null,
    proposal_sha256:null,global_http_fragment:'',site_server_fragment:'',
    reason:'No verified direct cache zone'
  }));
  assert.match(ui.state().cachePlanResult,/No reference generated/);
  assert.doesNotMatch(ui.state().cachePlanResult,/HTTP-scope reference/);
});

test('FastCGI cache audit binds exact native website snapshot and never grants Apply/purge', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  assert.equal(ui.state().cacheInspectDisabled,false);
  const request=ui.statusClick('#ach-cache-inspect-button');
  assert.match(request.options.url,/s=inspect_fastcgi_cache$/);
  assert.equal(request.options.type,'POST');
  assert.deepEqual(Object.keys(request.options.data).sort(),[
    'expected_site_key','expected_site_snapshot','site_id']);
  assert.deepEqual(JSON.parse(request.options.data.expected_site_snapshot),[
    7,'site.test','/www/site.test','1',[['site.test',80]]
  ]);
  assert.equal(ui.state().cacheInspectDisabled,true);
  request.respond(cacheInspection());
  assert.equal(ui.state().cacheInspectDisabled,false);
  const state=ui.state().cacheResult;
  assert.match(state,/Cache source: Source Observed/);
  assert.match(state,/direct directive: Direct Zone/);
  assert.match(state,/Direct cache zone: WORDPRESS/);
  assert.match(state,/SHARED_ZONE_REFERENCES/);
  assert.match(state,/RESPONSE_CACHE_HEADER_IGNORED/);
  assert.match(state,/SHARED_CACHE_DIRECTORY_PURGE_RISK/);
  assert.match(state,/GLOBAL_RESPONSE_CACHE_HEADER_IGNORED/);
  assert.match(state,/aaPanel global include inspected: true/);
  assert.match(state,/other registered sites sharing that directory: 8: other.test/);
  assert.match(state,/site-scoped filesystem purge: NEVER inferred/);
  assert.match(state,/8: other.test/);
  assert.match(state,/DO NOT infer/);
  assert.doesNotMatch(state,/safe to purge|private content protected/);
});

test('Installed Nginx Helper inspection exposes key and Purge All mismatch without authorizing actions', () => {
  const ui=loadUi();selectHostsSite(ui);
  const text='Installed PHP files; <img src=x onerror=alert(1)> unlink_files, get_request and recursive Purge All remain unverified.';
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
    nginx_helper:nginxHelperAudit({state:'Installed',version:'2.4.1',note:text})
  }));
  const observed=ui.state().cacheResult;
  assert.match(observed,/Nginx Helper.*Installed v2\.4\.1/);
  assert.match(observed,/Plugin activation, purge method, effective purge directory and safe purge: NOT VERIFIED/);
  assert.match(observed,/unlink_files, get_request/);
  assert.match(observed,/\<img src=x onerror=alert\(1\)\>/);
  assert.equal(ui.state().cacheInspectDisabled,false);
  assert.equal(ui.state().cacheActivationApplyDisabled,true);
  assert.equal(ui.state().cacheActivationRestoreDisabled,true);
});

test('Nginx Helper incompatible source claims are never rendered as verified', () => {
  const invalid=[
    {active_verified:true},{purge_method_verified:true},
    {cache_path_verified:true},{purge_safe_verified:true},
    {state:'Installed',version:null},
    {state:'Installed',version:'2.4.1 <script>'},
    {state:'Not Installed',version:'2.4.1'},
    {state:'Needs Review',reason:''},
    {state:'Installed',reason:'conflict'},
    {note:'x'.repeat(601)}
  ];
  for(const change of invalid){
    const ui=loadUi();selectHostsSite(ui);
    ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
      nginx_helper:nginxHelperAudit(change)
    }));
    assert.match(ui.state().cacheResult,/unavailable or incompatible/,
      JSON.stringify(change));
    assert.doesNotMatch(ui.state().cacheResult,/safe purge: NOT VERIFIED/);
  }
});

test('Partial FastCGI cache source and Needs Review never claim verified isolation', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
    state:'Partial',inspected_sites:3,unresolved_other_sites:1,
    reason:'Unknown third-party Nginx site extension'
  }));
  assert.match(ui.state().cacheResult,/Cache source: Partial/);
  assert.match(ui.state().cacheResult,/unresolved sites: 1\/3/);
  assert.match(ui.state().cacheResult,/No loaded cache or Nginx Helper safety claim/);
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
    state:'Needs Review',zone_state:'Needs Review',cache_zone:null,
    global_zone_directly_declared:false,aaPanel_global_include_observed:false,
    global_ignore_headers:[],cache_directory:null,purge_scope:'Unknown',
    other_sites_same_directory:[],findings:[],other_sites_same_zone:[],
    inspected_sites:0,source_sha256:null,reason:'Unsupported site Nginx include'
  }));
  assert.match(ui.state().cacheResult,/Needs Review/);
  assert.doesNotMatch(ui.state().cacheResult,/Direct cache zone: WORDPRESS/);
});

test('Different canonical cache paths remain Unknown; UI never grants site purge', () => {
  const ui=loadUi();
  selectHostsSite(ui);
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
    purge_scope:'Unknown',
    other_sites_same_directory:[],
    other_sites_same_zone:[],
    findings:['PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED']
  }));
  const result=ui.state().cacheResult;
  assert.match(result,/Observed cache directory usage: Unknown/);
  assert.match(result,/site-scoped filesystem purge: NEVER inferred/);
  assert.doesNotMatch(result,/safe to purge|private content protected/);
});

test('Forged FastCGI cache source responses fail closed and do not enable mutation', () => {
  const forged = [
    {site_id:8},{site_key:'other.test'},{fix_supported:true},
    {purge_supported:true},{cache_safe_verified:true},{runtime_verified:true},
    {source_sha256:'fake'},{inspected_sites:101},
    {zone_state:'Direct Zone',cache_zone:null},{zone_state:'Direct Off'},
    {state:'Source Observed',unresolved_other_sites:1},
    {state:'Partial',unresolved_other_sites:0},
    {findings:['PERSONAL_DATA_LEAK']},
    {cache_directory:'../unauthorized'},
    {cache_directory:'/www/server/fastcgi_cache/'},
    {cache_directory:'/www/server/./fastcgi_cache'},
    {global_ignore_headers:['Unsafe']},
    {other_sites_same_directory:[{id:7,site_key:'forged.test'}]},
    {purge_scope:'Shared Registered Directory',other_sites_same_directory:[]},
    {purge_scope:'No Registered Directory Peer'},
    {aaPanel_global_include_observed:'yes'},
    {ignore_headers:['xss<script>']},
    {other_sites_same_zone:[{id:7,site_key:'selected.test'}]},
    {other_sites_same_zone:[{id:8,site_key:'other.test'},{id:8,site_key:'again.test'}]},
    {other_sites_same_zone:[{id:8,site_key:'other.test'}],inspected_sites:1}
  ];
  for (const changed of forged) {
    const ui=loadUi();
    selectHostsSite(ui);
    ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection(changed));
    assert.match(ui.state().cacheResult,/unavailable or incompatible/,JSON.stringify(changed));
    assert.equal(ui.state().cacheInspectDisabled,false);
  }
  const ui=loadUi();
  selectHostsSite(ui);
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection({
    findings:['<img src=x onerror=alert(1)>']
  }));
  assert.doesNotMatch(ui.state().cacheResult,/<img/);
});

test('FastCGI cache result is revoked on selected website, Refresh or policy changes', () => {
  const ui=loadUi();
  ui.respondOverview(monitorOverview({state_revision:9}));
  selectHostsSite(ui);
  const old=ui.statusClick('#ach-cache-inspect-button');
  ui.statusSetValue('#ach-hosts-site-id','8','input change');
  old.respond(cacheInspection());
  assert.match(ui.state().cacheResult,/selection changed/);
  assert.doesNotMatch(ui.state().cacheResult,/WORDPRESS/);
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  ui.statusClick('#ach-cache-inspect-button').respond(cacheInspection());
  assert.match(ui.state().cacheResult,/WORDPRESS/);
  const refresh=ui.refreshSites();
  assert.equal(ui.state().cacheInspectDisabled,true);
  assert.match(ui.state().cacheResult,/changed/);
  refresh.respond(hostsInventory());
  assert.equal(ui.state().cacheInspectDisabled,true,'Must reselect after inventory Refresh');
  ui.statusSetValue('#ach-hosts-site-id','7','input change');
  const pending=ui.statusClick('#ach-cache-inspect-button');
  ui.openOverview();
  const write=ui.toggleMonitor('site_inventory',false);
  assert.match(write.options.url,/s=set_control$/);
  assert.equal(ui.state().cacheInspectDisabled,true);
  // A monitor write/pending policy invalidates the selected source; old
  // in-flight callbacks never reattach a stale cache policy.
  pending.respond(cacheInspection());
  assert.doesNotMatch(ui.state().cacheResult,/Direct cache zone: WORDPRESS/);
  assert.match(ui.state().cacheResult,/changed|revoked/);
  write.reject(null,'timeout');
  assert.equal(ui.state().cacheInspectDisabled,true);
});

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
  assert.equal(ui.state().statusPreviewHidden,false,'Successful preview appears next to its control');
  assert.match(ui.state().statusHash,/Rendered SHA-256: b/);
  assert.match(ui.state().statusResult,/No site changes/);
  ui.statusSetValue('#ach-status-locale','fa','change');
  assert.equal(ui.state().statusHtml,'','Changed locale invalidates stale preview');
  assert.equal(ui.state().statusHash,'');
  assert.equal(ui.state().statusPreviewHidden,true,'Stale preview is removed on locale change');
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
  loadNativeStatusSiteSelection(ui,'7');
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
  assert.equal(ui.state().statusPreviewHidden,true,'Invalid preview remains hidden');
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
  loadNativeStatusSiteSelection(ui,'7');
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
function statusProbeUi(hasMore=false, panelStatus='1') {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const inventory = ui.requests.at(-1);
  assert.match(inventory.options.url,/s=status_sites$/);
  const selected={...site(),id:7,name:'demo.test',panel_status:panelStatus,
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
  assert.equal(ui.state().statusProbeDisabled,false);
  assert.match(ui.state().statusProbe,/not checked/);
  const source=ui.statusClick('#ach-status-probe-button');
  assert.match(source.options.url,/s=status_probe$/);
  assert.equal(source.options.data.template,'502');
  source.respond(statusProbe({template:'502',state:'Needs Review'}));
  assert.match(ui.state().statusProbe,/unconfirmed|incompatible/);
});

const managed404Original='b'.repeat(64);
const managed404Render='a'.repeat(64);
const managed404Vhost='c'.repeat(64);
const managed404Recovery='e'.repeat(32);
function native404Proposal() {
  return statusProbe({
    body_sha256:managed404Original,page_file_sha256:managed404Original,
    rendered_sha256:managed404Render,body_matches_file:true,body_matches_render:false,
    adoption_preview:{
      schema:1,state:'Backup Required',route_source_state:'Native VHost',
      current_sha256:managed404Original,proposed_sha256:managed404Render,
      vhost_sha256:managed404Vhost,
      requires_adoption:true,requires_backup:true,
      ownership_verified:false,recovery_verified:false,apply_supported:false,
      reason:'Explicit adoption and backup required'
    }
  });
}
function manage404Response(action,fields={}) {
  return {
    status:true,schema:1,site_id:7,site_action:action,
    verified_site_snapshot:probeSnapshot,locale:'en',template:'404',
    revision:2,mode:'native_status_extension',
    request_id:'d'.repeat(32),operation_id:'d'.repeat(32),
    read_only:action==='recheck',changed:action!=='recheck',
    state:action==='apply'?'Applied':action==='restore'?'Restored':'Applied',
    page_file_sha256:action==='restore'?managed404Original:managed404Render,
    recovery_id:managed404Recovery,
    ...(action==='recheck'?{
      rendered_sha256:managed404Render,
      before_sha256:managed404Original,after_sha256:managed404Render
    }:{}),
    ...fields
  };
}
test('Guarded existing-site 404 Apply/Recheck/Restore is operator-confirmed and snapshot-bound', () => {
  const ui=statusProbeUi();
  assert.equal(ui.state().statusManageRecheckDisabled,false);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,true,
    'Approval without verified live/source evidence does not grant Apply');
  ui.statusClick('#ach-status-probe-button').respond(native404Proposal());
  assert.equal(ui.state().statusManageApplyDisabled,true,
    'Live proof alone does not grant a write without a new confirmation');
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-manage-apply');
  assert.match(apply.options.url,/s=status_manage$/);
  assert.equal(apply.options.data.site_action,'apply');
  assert.equal(apply.options.data.scope,'site');
  assert.equal(apply.options.data.site_id,'7');
  assert.equal(apply.options.data.site_approval,'apply_exact_site_404_reload');
  assert.equal(apply.options.data.expected_site_snapshot,probeSnapshot);
  assert.equal(apply.options.data.expected_page_sha256,managed404Original);
  assert.equal(apply.options.data.expected_vhost_sha256,managed404Vhost);
  assert.equal(apply.options.data.expected_render_sha256,managed404Render);
  assert.equal(apply.options.timeout,45000);
  assert.equal(ui.state().statusManageRecheckDisabled,true);
  apply.respond(manage404Response('apply'));
  assert.match(ui.state().statusManage,/Applied/);
  assert.match(ui.state().statusManage,/confirmed managed extension change/);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  const recheck=ui.statusClick('#ach-status-manage-recheck');
  assert.match(recheck.options.url,/s=status_manage$/);
  assert.equal(recheck.options.data.site_action,'recheck');
  assert.equal(recheck.options.data.site_approval,'');
  recheck.respond(manage404Response('recheck',{changed:false}));
  assert.match(ui.state().statusManage,/Applied/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.equal(restore.options.data.site_action,'restore');
  assert.equal(restore.options.data.expected_recovery_id,managed404Recovery);
  assert.equal(restore.options.data.site_approval,'restore_exact_site_404_reload');
  restore.respond(manage404Response('restore'));
  assert.match(ui.state().statusManage,/Restored/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
});

test('Stopped website keeps read-only journal Recheck without HTTP probes or Restore', () => {
  const ui=statusProbeUi(false,'0');
  assert.equal(ui.state().statusProbeDisabled,true);
  assert.equal(ui.state().statusManageRecheckDisabled,false);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  const check=ui.statusClick('#ach-status-manage-recheck');
  assert.equal(check.options.data.site_action,'recheck');
  assert.equal(check.options.data.site_approval,'');
  const stoppedSnapshot=JSON.stringify([7,'demo.test','/www/demo.test','0',[['demo.test',80]]]);
  assert.equal(check.options.data.expected_site_snapshot,stoppedSnapshot);
  check.respond(manage404Response('recheck',{
    verified_site_snapshot:stoppedSnapshot,
    state:'Suspended',changed:false,
    journal_phase:'applied',verification_scope:'saved_journal_only',
    runtime_verified:false,
    note:'Native website is stopped; Start, refresh and Recheck before Restore.'
  }));
  assert.match(ui.state().statusManage,/Suspended/);
  assert.match(ui.state().statusManage,/saved journal ONLY/);
  assert.match(ui.state().statusManage,/NOT current HTTP/);
  assert.match(ui.state().statusManage,/Saved phase: applied/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-manage-restore');
  ui.statusClick('#ach-status-probe-button');
  assert.equal(ui.requests.length,count);
});

test('Source-drift journal is visible but malformed or unverified states cannot authorize Restore', () => {
  const ui=statusProbeUi();
  const check=ui.statusClick('#ach-status-manage-recheck');
  check.respond(manage404Response('recheck',{
    state:'Needs Review',changed:false,
    journal_phase:'applied',verification_scope:'saved_journal_only',
    runtime_verified:false,
    note:'Native VHost changed; reconcile source and Recheck before Restore.'
  }));
  assert.match(ui.state().statusManage,/saved journal ONLY/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  const forged=ui.statusClick('#ach-status-manage-recheck');
  forged.respond(manage404Response('recheck',{
    state:'Suspended',changed:false,
    journal_phase:'applied',verification_scope:'http404_body',
    runtime_verified:true,note:'Forged verification'
  }));
  assert.match(ui.state().statusManage,/incomplete or incompatible/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
});

test('Native site-file 404 approval and Restore are delivery-bound and never request reload', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-delivery','file','change');
  assert.equal(ui.state().statusManageApplyDisabled,true);
  const read=ui.statusClick('#ach-status-probe-button');
  assert.equal(read.options.data.site_delivery,'file');
  read.respond(native404Proposal());
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-manage-apply');
  assert.equal(apply.options.data.site_delivery,'file');
  assert.equal(apply.options.data.site_approval,'apply_exact_site_404_site_file');
  apply.respond(manage404Response('apply',{
    mode:'native_site_status_file',runtime_verified:true,
    verification_scope:'http404_body'
  }));
  assert.match(ui.state().statusManage,/confirmed native site-file replacement/);
  assert.match(ui.state().statusManage,/No Nginx reload was requested/);
  const check=ui.statusClick('#ach-status-manage-recheck');
  assert.equal(check.options.data.site_delivery,'file');
  check.respond(manage404Response('recheck',{
    changed:false,mode:'native_site_status_file',
    runtime_verified:true,verification_scope:'http404_body'
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.equal(restore.options.data.site_delivery,'file');
  assert.equal(restore.options.data.site_approval,'restore_exact_site_404_site_file');
  restore.respond(manage404Response('restore',{
    mode:'native_site_status_file',runtime_verified:true,
    verification_scope:'http404_body'
  }));
  assert.match(ui.state().statusManage,/Restored/);
  assert.match(ui.state().statusManage,/No Nginx reload was requested/);
});

test('Switching delivery invalidates prior preflight and rejects mismatched mode responses', () => {
  const ui=statusProbeUi();
  const old=ui.statusClick('#ach-status-probe-button');
  ui.statusSetValue('#ach-status-delivery','file','change');
  old.respond(native404Proposal());
  assert.equal(ui.state().statusManageApplyDisabled,true);
  const fresh=ui.statusClick('#ach-status-probe-button');
  fresh.respond(native404Proposal());
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  const apply=ui.statusClick('#ach-status-manage-apply');
  apply.respond(manage404Response('apply'));
  assert.match(ui.state().statusManage,/unconfirmed/i);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
});

test('Native file 404/502 rejects forged runtime and extension proof semantics', () => {
  for (const [template, invalid] of [
    ['404', {runtime_verified:true,verification_scope:'source_and_nonce_only'}],
    ['404', {runtime_verified:true,verification_scope:'http404_body',state:'Needs Review'}],
    ['502', {runtime_verified:true,verification_scope:'source_only'}],
    ['502', {runtime_verified:false,verification_scope:'source_and_nonce_only'}],
  ]) {
    const ui=statusProbeUi();
    ui.statusSetValue('#ach-status-delivery','file','change');
    if (template==='502') ui.statusSetValue('#ach-status-template','502','change');
    const read=ui.statusClick('#ach-status-manage-recheck');
    read.respond(manage404Response('recheck',{
      mode:'native_site_status_file',template,changed:false,
      runtime_verified:template==='404',
      verification_scope:template==='404'?'http404_body':'source_only',
      ...invalid
    }));
    assert.match(ui.state().statusManage,/incomplete or incompatible/i);
    ui.statusSetChecked('#ach-status-manage-restore-approve',true);
    assert.equal(ui.state().statusManageRestoreDisabled,true);
  }
});

test('Native site-file 502 is explicitly source-only, not fake HTTP 502', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-delivery','file','change');
  ui.statusSetValue('#ach-status-template','502','change');
  ui.statusClick('#ach-status-probe-button').respond(statusProbe({
    template:'502',state:'Source Ready',scope:'native_vhost_source_only',
    page_file_sha256:managed404Original,body_sha256:null,http_status:null,
    body_bytes:null,body_matches_file:false,body_matches_render:false,
    http_404_observed:false,
    adoption_preview:{
      schema:1,state:'Source Ready',route_source_state:'Native VHost',
      current_sha256:managed404Original,proposed_sha256:managed404Render,
      vhost_sha256:managed404Vhost,
      requires_adoption:true,requires_backup:true,
      ownership_verified:false,recovery_verified:false,apply_supported:false,
      reason:'Original site-file backup required'
    }
  }));
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-manage-apply');
  assert.equal(apply.options.data.site_approval,'apply_exact_site_502_site_file');
  apply.respond(manage404Response('apply',{
    template:'502',mode:'native_site_status_file',
    runtime_verified:false,verification_scope:'source_only'
  }));
  const check=ui.statusClick('#ach-status-manage-recheck');
  check.respond(manage404Response('recheck',{
    template:'502',mode:'native_site_status_file',
    runtime_verified:false,verification_scope:'source_only',changed:false
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.equal(restore.options.data.site_approval,'restore_exact_site_502_site_file');
  restore.respond(manage404Response('restore',{
    template:'502',mode:'native_site_status_file',
    state:'Source Restored',runtime_verified:false,verification_scope:'source_only'
  }));
  assert.match(ui.state().statusManage,/live HTTP 502 NOT verified/);
  assert.match(ui.state().statusManage,/No Nginx reload was requested/);
});

test('Native 502 source-only preview gates extension Apply and Restore with Nginx reload approval', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-template','502','change');
  ui.statusClick('#ach-status-probe-button').respond(statusProbe({
    template:'502',state:'Source Ready',scope:'native_vhost_source_only',
    page_file_sha256:managed404Original,body_sha256:null,http_status:null,
    body_bytes:null,body_matches_file:false,body_matches_render:false,
    http_404_observed:false,body_matches_file:false,
    adoption_preview:{
      schema:1,state:'Source Ready',route_source_state:'Native VHost',
      current_sha256:managed404Original,proposed_sha256:managed404Render,
      vhost_sha256:managed404Vhost,
      requires_adoption:false,requires_backup:false,
      ownership_verified:false,recovery_verified:false,
      apply_supported:false,reason:'Explicit reload required'
    }
  }));
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  const request=ui.statusClick('#ach-status-manage-apply');
  assert.equal(request.options.data.template,'502');
  assert.equal(request.options.data.site_approval,'apply_exact_site_502_reload');
  request.respond(manage404Response('apply',{template:'502'}));
  assert.match(ui.state().statusManage,/Applied/);
  const recheck=ui.statusClick('#ach-status-manage-recheck');
  recheck.respond(manage404Response('recheck',{template:'502',changed:false}));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.equal(restore.options.data.template,'502');
  assert.equal(restore.options.data.site_approval,'restore_exact_site_502_reload');
  restore.respond(manage404Response('restore',{template:'502',
    state:'Source Restored',runtime_verified:false,
    verification_scope:'source_and_nonce_only'}));
  assert.match(ui.state().statusManage,/Source Restored/);
  assert.match(ui.state().statusManage,/original 502 response NOT verified/);
  assert.match(ui.state().statusManage,/502.html SOURCE SHA-256/);
});

test('Generic native 50x requires extension, source preflight and verified four-code proof', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-template','50x','change');
  assert.equal(ui.state().statusProbeDisabled,false);
  assert.equal(ui.state().statusManageRecheckDisabled,false);
  ui.statusSetValue('#ach-status-delivery','file','change');
  assert.equal(ui.state().statusProbeDisabled,true);
  assert.equal(ui.state().statusManageRecheckDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-probe-button');
  assert.equal(ui.requests.length,count,'50x cannot invoke unsupported native file mode');
  ui.statusSetValue('#ach-status-delivery','extension','change');
  const probe=ui.statusClick('#ach-status-probe-button');
  assert.equal(probe.options.data.template,'50x');
  assert.equal(probe.options.data.site_delivery,'extension');
  const source=statusProbe({
    template:'50x',state:'Source Ready',scope:'native_vhost_source_only',
    page_file_sha256:managed404Original,
    body_sha256:null,http_status:null,body_bytes:null,
    body_matches_file:false,body_matches_render:false,http_404_observed:false,
    adoption_preview:{
      schema:1,state:'Source Ready',route_source_state:'Native VHost',
      current_sha256:managed404Original,proposed_sha256:managed404Render,
      vhost_sha256:managed404Vhost,
      requires_adoption:false,requires_backup:false,
      ownership_verified:false,recovery_verified:false,
      apply_supported:false,reason:'Exact 50x extension and reload approval required'
    }
  });
  probe.respond(source);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-manage-apply');
  assert.equal(apply.options.data.site_approval,'apply_exact_site_50x_reload');
  apply.respond(manage404Response('apply',{
    template:'50x',runtime_verified:false,verification_scope:'source_and_nonce_only'
  }));
  assert.match(ui.state().statusManage,/unconfirmed/i);
  const retry=ui.statusClick('#ach-status-manage-recheck');
  retry.respond(manage404Response('recheck',{
    template:'50x',state:'Recovery Required',changed:false,
    runtime_verified:false,verification_scope:'source_and_nonce_only'
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.equal(restore.options.data.site_approval,'restore_exact_site_50x_reload');
  restore.respond(manage404Response('restore',{
    template:'50x',state:'Source Restored',
    runtime_verified:false,verification_scope:'source_and_nonce_only'
  }));
  assert.match(ui.state().statusManage,/generic Nginx 50x route removed/);
  assert.match(ui.state().statusManage,/502.html SOURCE/);
});

test('Native 50x rejects forged Applied proof and accepts exact body-verified Recheck', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-template','50x','change');
  const forged=manage404Response('recheck',{
    template:'50x',state:'Applied',changed:false,
    runtime_verified:false,verification_scope:'source_and_nonce_only'
  });
  ui.statusClick('#ach-status-manage-recheck').respond(forged);
  assert.match(ui.state().statusManage,/incomplete or incompatible/i);
  ui.statusClick('#ach-status-manage-recheck').respond({
    ...forged,runtime_verified:true,verification_scope:'http50x_body'
  });
  assert.match(ui.state().statusManage,/Applied/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
});

test('Restored 502 Recheck accepts the verified previous source hash, including absent sources', () => {
  const emptySha = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
  for (const previous of [managed404Original, emptySha]) {
    const ui = statusProbeUi();
    ui.statusSetValue('#ach-status-template', '502', 'change');
    const backendResponse = manage404Response('recheck', {
      template:'502', state:'Source Restored', changed:false,
      page_file_sha256:previous, before_sha256:previous,
      after_sha256:managed404Render, runtime_verified:false,
      verification_scope:'source_and_nonce_only'
    });
    ui.statusClick('#ach-status-manage-recheck').respond(backendResponse);
    assert.match(ui.state().statusManage, /Source Restored/);
    assert.match(ui.state().statusManage, /Current restored 502.html SOURCE SHA-256:/);
    assert.match(ui.state().statusManage, /original 502 response NOT verified/);
    assert.match(ui.state().statusManage, new RegExp(previous));
    assert.doesNotMatch(ui.state().statusManage, /incomplete or incompatible/);
    assert.equal(ui.state().statusManageRestoreDisabled, true);

    // This was the previous backend defect: a Source Restored state carrying
    // the applied HTML hash cannot be accepted as a restored source.
    ui.statusClick('#ach-status-manage-recheck').respond({
      ...backendResponse, page_file_sha256:managed404Render
    });
    assert.match(ui.state().statusManage, /incomplete or incompatible/);
    assert.equal(ui.state().statusManageRestoreDisabled, true);
  }
});

test('Status 404 Restore confirms an interrupted earlier rollback without a second file write', () => {
  const ui=statusProbeUi();
  ui.statusClick('#ach-status-manage-recheck').respond(manage404Response('recheck',{
    state:'Recovery Required',changed:false,
    page_file_sha256:managed404Original
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  const restore=ui.statusClick('#ach-status-manage-restore');
  assert.match(restore.options.url,/s=status_manage$/);
  restore.respond(manage404Response('restore',{changed:false,state:'Restored'}));
  assert.match(ui.state().statusManage,/Restored — no managed extension change/);
  assert.doesNotMatch(ui.state().statusManage,/unconfirmed/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
});

test('Status 404 orphaned backup is visible but never grants Restore without a journal', () => {
  const ui=statusProbeUi();
  const recheck=ui.statusClick('#ach-status-manage-recheck');
  recheck.respond(manage404Response('recheck',{
    state:'Orphan Backup',changed:false,page_file_sha256:managed404Original,
    before_sha256:managed404Original,after_sha256:null,recovery_id:null
  }));
  assert.match(ui.state().statusManage,/Orphan Backup/);
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
  const calls=ui.requests.length;
  ui.statusClick('#ach-status-manage-restore');
  assert.equal(ui.requests.length,calls);
  const drift=ui.statusClick('#ach-status-manage-recheck');
  drift.respond(manage404Response('recheck',{
    state:'Orphan Drift',changed:false,page_file_sha256:managed404Render,
    before_sha256:managed404Original,after_sha256:null,recovery_id:null
  }));
  assert.match(ui.state().statusManage,/Orphan Drift/);
  assert.equal(ui.state().statusManageRestoreDisabled,true);
});

test('Forged 404 recovery-state acknowledgements cannot enable Restore or prove success', () => {
  for (const forged of [
    {state:'Unmanaged',changed:false,before_sha256:managed404Original,
     after_sha256:null,recovery_id:null},
    {state:'Orphan Backup',changed:false,before_sha256:managed404Original,
     after_sha256:null,recovery_id:managed404Recovery,
     page_file_sha256:managed404Original},
    {state:'Orphan Backup',changed:false,before_sha256:managed404Original,
     after_sha256:null,recovery_id:null,page_file_sha256:managed404Render},
    {state:'Orphan Drift',changed:false,before_sha256:managed404Original,
     after_sha256:null,recovery_id:null,page_file_sha256:managed404Original},
    {state:'Restored',changed:false,page_file_sha256:managed404Render}
  ]) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-manage-recheck').respond(
      manage404Response('recheck',forged));
    assert.match(ui.state().statusManage,/incomplete or incompatible/,
      'Do not accept an inconsistent recovery snapshot '+JSON.stringify(forged));
    ui.statusSetChecked('#ach-status-manage-restore-approve',true);
    assert.equal(ui.state().statusManageRestoreDisabled,true);
  }
  const ui=statusProbeUi();
  ui.statusClick('#ach-status-manage-recheck').respond(manage404Response('recheck',{
    state:'Recovery Required',changed:false,page_file_sha256:managed404Original
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  const restore=ui.statusClick('#ach-status-manage-restore');
  restore.respond(manage404Response('restore',{
    state:'Already Restored',changed:true,page_file_sha256:managed404Original
  }));
  assert.match(ui.state().statusManage,/unconfirmed/);
});

test('Status 404 Apply rejects stale evidence and forged positive acknowledgements', () => {
  for(const bad of [
    {state:'Restored'}, {site_id:8}, {changed:false}, {recovery_id:'bad'},
    {page_file_sha256:managed404Original},
    {verified_site_snapshot:'[7]'},
    {read_only:true},
    {request_id:'x'.repeat(32)}
  ]) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-probe-button').respond(native404Proposal());
    ui.statusSetChecked('#ach-status-manage-apply-approve',true);
    const action=ui.statusClick('#ach-status-manage-apply');
    action.respond(manage404Response('apply',bad));
    assert.match(ui.state().statusManage,/unconfirmed/);
    assert.equal(ui.state().statusManageRestoreDisabled,true);
    assert.equal(ui.state().statusManageApplyDisabled,true);
  }
  const ui=statusProbeUi();
  ui.statusClick('#ach-status-probe-button').respond(native404Proposal());
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  ui.statusSetValue('#ach-status-name','Changed after probe','input change');
  assert.equal(ui.state().statusManageApplyDisabled,true);
  const before=ui.requests.length;
  ui.statusClick('#ach-status-manage-apply');
  assert.equal(ui.requests.length,before);
});

test('Uncertain Status write exposes validated recovery ID without authorizing Restore', () => {
  for (const recovery of ['e'.repeat(32), 'not-a-recovery-id']) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-probe-button').respond(native404Proposal());
    ui.statusSetChecked('#ach-status-manage-apply-approve',true);
    const apply=ui.statusClick('#ach-status-manage-apply');
    apply.respond({status:false,stage:'status_manage_uncertain',msg:'Site exchange unconfirmed',
      operation_id:'d'.repeat(32),request_id:'d'.repeat(32),
      recovery_required:true,recovery_id:recovery});
    assert.match(ui.state().error,/Site exchange unconfirmed/);
    if (recovery.length===32) {
      assert.match(ui.state().error,/Recovery ID: e{32}; Recheck before Restore/);
    } else {
      assert.doesNotMatch(ui.state().error,/Recovery ID:/);
    }
    assert.equal(ui.state().statusManageRestoreDisabled,true);
    assert.equal(ui.state().statusManageRecheckDisabled,false);
  }
});

test('Status 404 writes return explicit uncertainty, preserving Recheck as recovery path', () => {
  const ui=statusProbeUi();
  ui.statusClick('#ach-status-probe-button').respond(native404Proposal());
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  const request=ui.statusClick('#ach-status-manage-apply');
  request.reject(null,'timeout');
  assert.match(ui.state().statusManage,/unconfirmed/);
  assert.match(ui.state().error,/Outcome unknown/);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  assert.equal(ui.state().statusManageRecheckDisabled,false);
  // A refreshed operator recheck may report an incomplete prepared transaction.
  ui.statusClick('#ach-status-manage-recheck').respond(manage404Response('recheck',{
    state:'Recovery Required',changed:false
  }));
  ui.statusSetChecked('#ach-status-manage-restore-approve',true);
  assert.equal(ui.state().statusManageRestoreDisabled,false);
});

test('Read-only 404 adoption preview preserves observed content conflicts and denies writes', () => {
  const ui=statusProbeUi();
  const sha='a'.repeat(64);
  const other='b'.repeat(64);
  const observed=statusProbe({
    body_sha256:other, page_file_sha256:other, body_matches_file:true,
    body_matches_render:false, rendered_sha256:sha,
    adoption_preview:{
      schema:1,state:'Backup Required',route_source_state:'Native VHost',
      current_sha256:other,proposed_sha256:sha,
      requires_adoption:true,requires_backup:true,
      ownership_verified:false,recovery_verified:false,apply_supported:false,
      reason:'Explicit adoption and recoverable backup required'
    }
  });
  ui.statusClick('#ach-status-probe-button').respond(observed);
  assert.match(ui.state().statusProbe,/HTTP Match/);
  assert.match(ui.state().statusAdoption,/Backup Required/);
  assert.match(ui.state().statusAdoption,/No write is authorized by this preview/);
  ui.statusSetValue('#ach-status-name','Changed during observation','input change');
  assert.match(ui.state().statusAdoption,/not checked/);
});

test('Tampered 404 adoption preflight never authorizes Apply or a trusted result', () => {
  const base={
    schema:1,state:'Matches Preview',route_source_state:'Native VHost',
    current_sha256:'a'.repeat(64),proposed_sha256:'a'.repeat(64),
    requires_adoption:false,requires_backup:false,
    ownership_verified:false,recovery_verified:false,apply_supported:false,
    reason:'Observed current site file matches selected preview'
  };
  for (const altered of [
    {apply_supported:true}, {ownership_verified:true},
    {recovery_verified:true},{route_source_state:'unknown'},
    {state:'Backup Required'}, {requires_backup:true},
    {proposed_sha256:'b'.repeat(64)},
    {current_sha256:'b'.repeat(64)},
    {reason:'x'.repeat(400)}
  ]) {
    const ui=statusProbeUi();
    ui.statusClick('#ach-status-probe-button').respond(
      statusProbe({adoption_preview:{...base,...altered}})
    );
    assert.match(ui.state().statusProbe,/unconfirmed or incompatible/);
    assert.match(ui.state().statusAdoption,/unavailable or incompatible/);
  }
  const ui=statusProbeUi();
  ui.statusClick('#ach-status-probe-button').respond(
    statusProbe({adoption_preview:base})
  );
  assert.match(ui.state().statusAdoption,/Matches Preview/);
  assert.match(ui.state().statusAdoption,/No write is authorized by this preview/);
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
  loadNativeStatusSiteSelection(ui,'7');
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

test('Read-only native status inspection makes its new Activity record visible on return', () => {
  const ui=loadUi();
  ui.openActivity().respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  loadNativeStatusSiteSelection(ui,'7');
  ui.requests.at(-1).respond(statusPrefs());
  const inspect=ui.statusClick('#ach-status-inspect-button');
  assert.match(inspect.options.url,/s=status_inspect$/);
  inspect.respond(statusInspection());
  assert.match(ui.state().statusInspect,/State: Unmanaged/);
  const activity=ui.openActivity();
  assert.match(activity.options.url,/s=get_activity$/,
    'Read-only site inspection writes a native Activity record');
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
    loadNativeStatusSiteSelection(ui,'7');
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
  loadNativeStatusSiteSelection(ui,'7');
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
  loadNativeStatusSiteSelection(ui,'7');
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
  loadNativeStatusSiteSelection(ui,'7');
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
    loadNativeStatusSiteSelection(ui,'7');
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
  loadNativeStatusSiteSelection(ui,'7');
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
    loadNativeStatusSiteSelection(ui,'7');
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
  loadNativeStatusSiteSelection(ui,'7');
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
  assert.match(html, /\.ach-sidebar \{[^}]*border-right:0/);
  assert.match(html, /\.ach-main \{[^}]*background:var\(--ach-surface\)/);
  assert.match(html, /\.ach-workspace \{[^}]*border-radius:0 0 10px 10px/);
  assert.match(html, /\.layui-layer:has\(#ach-customizer\) \{[^}]*border-radius:10px/);
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

test('Verified PHP81 adapter uses version-bound Prepare, Apply and saved recovery', () => {
  const ui=loadUi();
  const inventory=ui.phpVersions();
  inventory.versions[0].manual_apply_adapter='guarded_php81';
  ui.openPhp().respond(inventory);
  assert.match(ui.state().phpOptions[1].text,/guarded PHP81 adapter/);

  ui.submitPhp('81',false).respond({
    ...phpPreview(phpImpact({version:'81'})),version:'81',
    source:'/www/server/php/81/etc/php-fpm.conf'
  });
  assert.equal(ui.state().fpmPrepareDisabled,false);
  const prepared=ui.prepareFpm();
  assert.equal(prepared.options.data.php_version,'81');
  const plan81={
    ...guardedPlan().plan,version:'81',
    source:'/www/server/php/81/etc/php-fpm.conf'
  };
  prepared.respond(guardedPlan({
    plan:plan81,shared_impact:phpImpact({version:'81'}),
    approval_scope:'PHP81-www-shared-service'
  }));
  assert.equal(ui.state().fpmReviewHidden,false);
  assert.match(ui.state().fpmDetails,/PHP 81 \[www\] shared/);
  ui.approveFpm(true);
  const apply=ui.commitFpm();
  assert.equal(apply.options.data.php_version,'81');
  assert.equal(apply.options.data.approved_scope,'PHP81-www-shared-service');
  apply.respond(appliedResult({...plan81}));
  assert.match(ui.state().fpmPlan,/Applied/);
  ui.selectRecoveryVersion('81');
  const recovery=ui.inspectFpmRecovery();
  assert.equal(recovery.options.data.php_version,'81');
  recovery.respond(recoveryPreview({
    version:'81',shared_impact:phpImpact({version:'81'})
  }));
  assert.equal(ui.state().fpmRollbackHidden,false);
  ui.approveFpmRollback(true);
  const rollback=ui.rollbackFpm();
  assert.equal(rollback.options.data.php_version,'81');
  assert.equal(rollback.options.data.approved_scope,'PHP81-www-shared-service');
  rollback.respond(rolledBackResult({version:'81'}));
  assert.match(ui.state().fpmRecovery,/Rolled Back/);
});

test('PHP81 recovery rejects PHP85 evidence and selection changes revoke approval', () => {
  const ui=loadUi();
  const inventory=ui.phpVersions();
  inventory.versions[0].manual_apply_adapter='guarded_php81';
  ui.openPhp().respond(inventory);
  ui.selectPhpVersion('81');
  ui.selectRecoveryVersion('81');
  const recovery=ui.inspectFpmRecovery();
  assert.equal(recovery.options.data.php_version,'81');
  recovery.respond(recoveryPreview());
  assert.equal(ui.state().fpmRollbackHidden,true);
  const correct=ui.inspectFpmRecovery();
  correct.respond(recoveryPreview({
    version:'81',shared_impact:phpImpact({version:'81'})
  }));
  assert.equal(ui.state().fpmRollbackHidden,false);
  ui.approveFpmRollback(true);
  ui.selectPhpVersion('85');
  assert.equal(ui.state().fpmRollbackHidden,true);
  const count=ui.requests.length;
  ui.rollbackFpm();
  assert.equal(ui.requests.length,count);
});

test('PHP81 saved recovery is inspectable when PHP inventory fails, without authorizing blind Restore', () => {
  const ui=loadUi();
  const inventory=ui.openPhp();
  inventory.reject(null,'timeout');
  assert.equal(ui.state().phpVersionDisabled,true);
  ui.selectRecoveryVersion('81');
  const first=ui.inspectFpmRecovery();
  assert.match(first.options.url,/s=fpm_recovery$/);
  assert.equal(first.options.data.php_version,'81');
  first.respond(recoveryPreview({
    version:'81', safe_rollback_file_match:false,
    shared_impact:null, impact_reason:'Native site routing unavailable',
    manual_recovery:'Retain journal; operator-guided reconciliation required.'
  }));
  assert.match(ui.state().fpmRecovery,/Recovery state: Applied/);
  assert.match(ui.state().fpmRecovery,/operation: d{32}/);
  assert.match(ui.state().fpmRecoveryImpact,/operator-guided reconciliation/);
  assert.equal(ui.state().fpmRollbackHidden,true);
  const pending=ui.requests.length;
  ui.rollbackFpm();
  assert.equal(ui.requests.length,pending,'An incomplete source cannot authorize restoration');

  // A later native site inspection may safely restore the approved operation.
  ui.inspectFpmRecovery().respond(recoveryPreview({
    version:'81',shared_impact:phpImpact({version:'81'})
  }));
  assert.equal(ui.state().fpmRollbackHidden,false);
  ui.approveFpmRollback(true);
  const rollback=ui.rollbackFpm();
  assert.equal(rollback.options.data.php_version,'81');
  assert.equal(rollback.options.data.approved_scope,'PHP81-www-shared-service');
  rollback.respond(rolledBackResult({version:'81'}));
  assert.match(ui.state().fpmRecovery,/Rolled Back/);
});

test('Independent PHP81/85 saved recovery remains usable after invalid inventory and rejects stale responses', () => {
  const ui=loadUi();
  const discovered=ui.openPhp();
  const invalid=ui.phpVersions();
  invalid.versions[0].manual_apply_adapter='guarded_php99';
  discovered.respond(invalid);
  assert.equal(ui.state().phpVersionDisabled,true);
  ui.selectRecoveryVersion('81');
  const old=ui.inspectFpmRecovery();
  assert.equal(old.options.data.php_version,'81');
  ui.selectRecoveryVersion('85');
  old.respond(recoveryPreview({
    version:'81',shared_impact:phpImpact({version:'81'})
  }));
  assert.equal(ui.state().fpmRollbackHidden,true);
  const historic=ui.inspectFpmRecovery();
  assert.equal(historic.options.data.php_version,'85');
  historic.respond(recoveryPreview());
  assert.equal(ui.state().fpmRollbackHidden,false);
  ui.approveFpmRollback(true);
  ui.selectRecoveryVersion('81');
  assert.equal(ui.state().fpmRollbackHidden,true);
  const before=ui.requests.length;
  ui.rollbackFpm();
  assert.equal(ui.requests.length,before);
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

function phpRuntimeEvidence(overrides={}) {
  return {
    status:true,schema:1,version:'81',read_only:true,runtime_verified:false,
    apply_eligible:false,state:'Observed',
    master_state:'Matching Master',socket_state:'Bound Listener',
    master_pid:432,socket_path:'/tmp/php-cgi-81.sock',
    reason:'',note:'Read-only point-in-time Linux process/socket observation. No Apply permission.',
    ...overrides
  };
}

function phpTopologyEvidence(overrides={}) {
  return {
    schema:1,state:'File Mapping',version:'81',scope:'shared_service',
    read_only:true,runtime_verified:false,apply_eligible:false,
    pool:'www',config_path:'/www/server/php/81/etc/php-fpm.conf',
    socket_path:'/tmp/php-cgi-81.sock',site_count:3,
    matched_sites:[
      {id:3,site_key:'first.test'},{id:4,site_key:'wordpress.test'}],
    other_sites:[
      {id:6,site_key:'other.test',version:'85',socket_path:'/tmp/another-85.sock'}],
    unresolved_sites:[],source_sha256:'a'.repeat(64),
    reason:'',note:'Native Nginx FILE attribution only, not loaded configuration.',
    ...overrides
  };
}

test('Selected PHP81 runtime displays native cross-version file site mapping only', () => {
  const ui=loadUi();
  ui.openPhp().respond(ui.phpVersions());
  ui.selectPhpVersion('81');
  ui.inspectPhpRuntime().respond(phpRuntimeEvidence({
    site_mapping:phpTopologyEvidence()
  }));
  assert.match(ui.state().phpRuntime,/Observed/);
  assert.match(ui.state().phpTopology,/File Mapping/);
  assert.match(ui.state().phpTopology,/2 assigned to selected service/);
  assert.match(ui.state().phpTopology,/Apply\/Restore eligibility: NEVER inferred/);
  assert.deepEqual(ui.state().phpTopologyRows,[
    ['3','first.test','PHP 81 / www','File-assigned to selected shared socket'],
    ['4','wordpress.test','PHP 81 / www','File-assigned to selected shared socket'],
    ['6','other.test','PHP 85 / www','Other native file/socket assignment']
  ]);
  assert.equal(ui.state().fpmPrepareDisabled,true);
  ui.selectPhpVersion('85');
  assert.equal(ui.state().phpTopologyRows.length,0,'Version change revokes mapping');
  assert.match(ui.state().phpTopology,/revoked/);
});

test('Partial PHP topology honestly labels uninspected sites, not complete impact', () => {
  const ui=loadUi();
  ui.openPhp().respond(ui.phpVersions());
  ui.selectPhpVersion('81');
  ui.inspectPhpRuntime().respond(phpRuntimeEvidence({
    site_mapping:phpTopologyEvidence({
      state:'Partial',site_count:4,source_sha256:null,
      unresolved_sites:[{id:7,site_key:'operator-site.test',reason:'VHost PHP assignment needs review'}],
      reason:'Some website assignments are ambiguous; shared impact is incomplete'
    })
  }));
  assert.match(ui.state().phpTopology,/Partial/);
  assert.match(ui.state().phpTopology,/1 unresolved/);
  assert.deepEqual(ui.state().phpTopologyRows.at(-1),[
    '7','operator-site.test','Needs Review','VHost PHP assignment needs review'
  ]);
  assert.doesNotMatch(ui.state().phpTopology,/all sites proven|effective routing verified/i);
});

test('Untrusted site topology payloads never manufacture complete shared impact', () => {
  const wrong=[
    {apply_eligible:true},{runtime_verified:true},{site_count:10000},
    {version:'85'}, {socket_path:'/tmp/other.sock'},
    {source_sha256:null},
    {site_count:4},
    {unresolved_sites:[{id:7,site_key:'bad.test',reason:'Ambiguous'}]},
    {matched_sites:[{id:3,site_key:'first.test'},{id:3,site_key:'duplicate.test'}]},
    {other_sites:[{id:6,site_key:'other.test',version:'85',socket_path:'/tmp/../evil.sock'}]},
    {other_sites:[{id:6,site_key:'other.test',version:'81',socket_path:'/tmp/another.sock'}]},
    {other_sites:[{id:6,site_key:'other.test',version:'00',socket_path:'/tmp/other.sock'}]},
    {state:'File Mapping',reason:'Unknown'},
    {state:'Partial',source_sha256:null,reason:'Partial'},
    {config_path:'/outside/81/php-fpm.conf'}
  ];
  for(const patch of wrong){
    const ui=loadUi();
    ui.openPhp().respond(ui.phpVersions());
    ui.selectPhpVersion('81');
    ui.inspectPhpRuntime().respond(phpRuntimeEvidence({
      site_mapping:phpTopologyEvidence(patch)
    }));
    assert.match(ui.state().phpTopology,/missing or incompatible/,
      JSON.stringify(patch));
    assert.equal(ui.state().phpTopologyRows.length,0);
    assert.equal(ui.state().fpmPrepareDisabled,true);
  }
});

test('PHP topology Needs Review, absent backend adapter and source switch remain non-authorizing', () => {
  const ui=loadUi();
  ui.openPhp().respond(ui.phpVersions());
  ui.selectPhpVersion('81');
  ui.inspectPhpRuntime().respond(phpRuntimeEvidence({
    site_mapping:phpTopologyEvidence({
      state:'Needs Review',pool:null,socket_path:null,config_path:null,
      site_count:0,matched_sites:[],other_sites:[],unresolved_sites:[],
      source_sha256:null,reason:'Unsupported aaPanel PHP pool layout'
    })
  }));
  assert.match(ui.state().phpTopology,/Needs Review/);
  assert.equal(ui.state().phpTopologyRows.length,0);
  ui.inspectPhpRuntime().respond(phpRuntimeEvidence());
  assert.match(ui.state().phpTopology,/missing or incompatible/);
  const previous=ui.inspectPhpRuntime();
  ui.refreshPhp().respond(ui.phpVersions());
  previous.respond(phpRuntimeEvidence({site_mapping:phpTopologyEvidence()}));
  assert.equal(ui.state().phpTopologyRows.length,0);
  assert.match(ui.state().phpTopology,/revoked/);
});

test('PHP85 manual Apply/Restore attempts revoke any earlier file-to-service mapping', () => {
  const mapped85 = phpTopologyEvidence({
    version:'85',config_path:'/www/server/php/85/etc/php-fpm.conf',
    socket_path:'/tmp/php-cgi-85.sock',
    matched_sites:[{id:6,site_key:'php85.test'}],
    other_sites:[{id:3,site_key:'php81.test',version:'81',
      socket_path:'/tmp/php-cgi-81.sock'}],site_count:2
  });
  const evidence85 = phpRuntimeEvidence({
    version:'85',socket_path:'/tmp/php-cgi-85.sock',site_mapping:mapped85
  });
  const apply=loadUi();
  apply.openPhp().respond(apply.phpVersions());
  apply.selectPhpVersion('85');
  apply.inspectPhpRuntime().respond(evidence85);
  assert.equal(apply.state().phpTopologyRows.length,2);
  apply.submitPhp('85',false).respond(phpPreview());
  apply.prepareFpm().respond(guardedPlan());
  apply.approveFpm(true);
  const commit=apply.commitFpm();
  assert.equal(apply.state().phpTopologyRows.length,0);
  assert.match(apply.state().phpTopology,/revoked/);
  assert.match(apply.state().phpRuntime,/Apply attempt invalidated/);
  commit.respond(appliedResult());

  const restore=loadUi();
  restore.openPhp().respond(restore.phpVersions());
  restore.selectPhpVersion('85');
  restore.inspectPhpRuntime().respond(evidence85);
  assert.equal(restore.state().phpTopologyRows.length,2);
  restore.inspectFpmRecovery().respond(recoveryPreview());
  restore.approveFpmRollback(true);
  const rollback=restore.rollbackFpm();
  assert.equal(restore.state().phpTopologyRows.length,0);
  assert.match(restore.state().phpRuntime,/Restore attempt invalidated/);
  rollback.respond(rolledBackResult());
});

test('Read-only PHP 8.1 runtime inspection requires a discovered version and preserves no Apply claim', () => {
  const ui=loadUi();
  assert.equal(ui.state().phpRuntimeDisabled,true);
  ui.openPhp().respond(ui.phpVersions());
  assert.equal(ui.state().phpRuntimeDisabled,true,'No version selected yet');
  ui.selectPhpVersion('81');
  assert.equal(ui.state().phpRuntimeDisabled,false);
  const req=ui.inspectPhpRuntime();
  assert.match(req.options.url,/s=inspect_php_runtime$/);
  assert.equal(req.options.data.php_version,'81');
  assert.equal(Object.keys(req.options.data).length,1);
  assert.equal(ui.state().phpRuntimeDisabled,true,'No duplicate concurrent runtime reads');
  req.respond(phpRuntimeEvidence());
  assert.equal(ui.state().phpRuntimeDisabled,false);
  assert.match(ui.state().phpRuntime,/PHP 81 — Observed/);
  assert.match(ui.state().phpRuntime,/Master process: Matching Master/);
  assert.match(ui.state().phpRuntime,/Master PID: 432/);
  assert.match(ui.state().phpRuntime,/Socket listener: Bound Listener/);
  assert.match(ui.state().phpRuntime,/Apply eligibility: not inferred/);
  assert.equal(ui.state().fpmPrepareDisabled,true,
    'Runtime process evidence never enables a new PHP81 write adapter');
});

test('PHP runtime observation discards stale selected-version and inventory-refresh callbacks', () => {
  const ui=loadUi();
  ui.openPhp().respond(ui.phpVersions());
  ui.selectPhpVersion('81');
  const first=ui.inspectPhpRuntime();
  ui.selectPhpVersion('85');
  first.respond(phpRuntimeEvidence());
  assert.match(ui.state().phpRuntime,/version changed/);
  assert.doesNotMatch(ui.state().phpRuntime,/Bound Listener/);
  const next=ui.inspectPhpRuntime();
  const refreshing=ui.refreshPhp();
  next.respond(phpRuntimeEvidence({version:'85'}));
  assert.match(ui.state().phpRuntime,/inventory refresh invalidated/);
  refreshing.respond(ui.phpVersions());
  assert.equal(ui.state().phpVersion,'85');
  assert.match(ui.state().phpRuntime,/inventory refresh invalidated/);
  assert.equal(ui.state().phpRuntimeDisabled,false);
});

test('Invalid PHP runtime replies never masquerade as proven service or Apply permission', () => {
  for (const tampered of [
    {runtime_verified:true},{apply_eligible:true},{version:'85'},
    {state:'Observed',socket_state:'Missing'},
    {state:'Observed',master_pid:null},
    {socket_path:'../../etc/passwd'},
    {socket_path:'/tmp/evil.sock\\n<script>'},
    {state:'Observed',reason:'source unknown'},
    {master_state:'unexpected'}, {master_pid:'432'},
    {note:'x'.repeat(800)}
  ]) {
    const ui=loadUi();
    ui.openPhp().respond(ui.phpVersions());
    ui.selectPhpVersion('81');
    const request=ui.inspectPhpRuntime();
    request.respond(phpRuntimeEvidence(tampered));
    assert.match(ui.state().phpRuntime,/unavailable\/incompatible/,JSON.stringify(tampered));
    assert.equal(ui.state().phpRuntimeDisabled,false);
    assert.equal(ui.state().fpmPrepareDisabled,true);
  }
  for(const observed of [
    phpRuntimeEvidence({state:'Partial',socket_state:'Missing',
      reason:'Current socket is absent'}),
    phpRuntimeEvidence({state:'Needs Review',master_state:'Not Observed',
      master_pid:null,socket_state:'Needs Review',reason:'No matching master observed'})
  ]) {
    const ui=loadUi();
    ui.openPhp().respond(ui.phpVersions());
    ui.selectPhpVersion('81');
    ui.inspectPhpRuntime().respond(observed);
    assert.match(ui.state().phpRuntime,new RegExp(observed.state));
    assert.match(ui.state().phpRuntime,/Apply eligibility: not inferred/);
  }
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

test('Native tabs retain per-section scroll, including a repeated tab click', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.setMainScroll(412);
  ui.openActivity().respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  assert.equal(ui.mainScroll(),0,'First Activity visit starts at its own top');
  ui.setMainScroll(133);
  ui.openStatus();
  assert.equal(ui.mainScroll(),412,'Returning to a long Status form keeps reading position');
  ui.openStatus();
  assert.equal(ui.mainScroll(),412,'Clicking the selected sidebar tab must not jump to top');
  ui.openActivity();
  assert.equal(ui.mainScroll(),133,'Activity keeps its independent scroll position');
  assert.equal(ui.tabScrollCalls(),0,'Desktop sidebar does not scroll the host dialog');
  ui.setViewportWidth(375);
  ui.openStatus();
  assert.equal(ui.tabScrollCalls(),1,'Narrow tab strip scrolls the selected item into view');
});

test('Native tab arrow keys follow actual desktop/mobile orientation', () => {
  const ui=loadUi();
  ui.setViewportWidth(1280);
  assert.equal(ui.keyTab('overview','ArrowRight').prevented,false);
  assert.equal(ui.selectedTab(),'overview','Horizontal arrows must remain available on desktop');
  const desktop=ui.keyTab('overview','ArrowDown');
  assert.equal(desktop.prevented,true);
  assert.equal(desktop.focused,'websites');
  assert.equal(desktop.selected,'websites');
  assert.equal(ui.keyTab('websites','ArrowLeft').prevented,false);
  ui.setViewportWidth(375);
  assert.equal(ui.keyTab('websites','ArrowDown').prevented,false);
  const mobile=ui.keyTab('websites','ArrowRight');
  assert.equal(mobile.prevented,true);
  assert.equal(mobile.focused,'php');
  assert.equal(mobile.selected,'php');
  assert.equal(ui.keyTab('php','Home').selected,'overview');
  assert.equal(ui.keyTab('overview','End').selected,'activity');
  assert.equal(ui.keyTab('activity','ArrowRight').selected,'overview',
    'Horizontal keyboard navigation wraps around');
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
  const unchanged=ui.requests.length;
  ui.statusClick('#ach-status-load');
  assert.equal(ui.requests.length,unchanged,'Dirty Recheck requires explicit discard');
  assert.equal(ui.state().statusName,'Unsaved operator change');
  ui.statusPermitDiscard(true);
  ui.statusClick('#ach-status-load').respond(statusPrefs());
  assert.notEqual(ui.state().statusName,'Unsaved operator change');
});

test('Status Pages scope switch Cancel keeps dirty inputs and original scope', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-name','Working brand','input change');
  const before=ui.requests.length;
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.requests.length,before);
  assert.deepEqual(ui.statusSelection(),{scope:'global',site:''});
  assert.equal(ui.state().statusName,'Working brand');
  assert.match(ui.state().statusResult,/Unsaved changes kept/);
  assert.equal(ui.statusConfirmations().length,1);
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:''});
  assert.equal(ui.state().statusSaveDisabled,true);
  assert.match(ui.requests.at(-1).options.url,/s=status_sites$/);
});

test('Status Pages dirty site switch restores previous site on Cancel', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  const seven={...site(),id:7,name:'seven.test',
    bound_domains:[{name:'seven.test',port:80}]};
  const eight={...site(),id:8,name:'eight.test',
    bound_domains:[{name:'eight.test',port:80}]};
  ui.requests.at(-1).respond({...page([seven,eight]),purpose:'status_site_selection'});
  ui.statusSetValue('#ach-status-site-id','7','change');
  ui.requests.at(-1).respond(statusPrefs(3,'Site override',{
    ...brand(),brand_name:'Site seven'
  }));
  ui.statusSetValue('#ach-status-name','Uncommitted seven','input change');
  const before=ui.requests.length;
  ui.statusSetValue('#ach-status-site-id','8','change');
  assert.equal(ui.requests.length,before);
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusName,'Uncommitted seven');
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-site-id','8','change');
  const load=ui.requests.at(-1);
  assert.match(load.options.url,/s=status_preferences$/);
  assert.equal(load.options.data.site_id,'8');
  load.respond(statusPrefs(4,'Site override',{...brand(),brand_name:'Site eight'}));
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'8'});
  assert.equal(ui.state().statusName,'Site eight');
});

test('Status Pages dirty Recheck guarded, clean and reverted values never prompt', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs(3));
  ui.statusSetValue('#ach-status-name','Changed','input change');
  const before=ui.requests.length;
  ui.statusClick('#ach-status-load');
  assert.equal(ui.requests.length,before);
  assert.equal(ui.state().statusName,'Changed');
  assert.equal(ui.statusConfirmations().length,1);
  ui.statusPermitDiscard(true);
  const recheck=ui.statusClick('#ach-status-load');
  assert.match(recheck.options.url,/s=status_preferences$/);
  recheck.respond(statusPrefs(4));
  ui.statusPermitDiscard(false);
  const withoutDirty=ui.statusClick('#ach-status-load');
  assert.match(withoutDirty.options.url,/s=status_preferences$/);
  withoutDirty.respond(statusPrefs(4));
  const unchanged=ui.statusConfirmations().length;
  ui.statusSetValue('#ach-status-name','Changed','input change');
  ui.statusSetValue('#ach-status-name',brand().brand_name,'input change');
  const reverted=ui.statusClick('#ach-status-load');
  assert.equal(ui.statusConfirmations().length,unchanged);
  assert.match(reverted.options.url,/s=status_preferences$/);
});

function statusSiteDraftFixture(ui, selectedId=7) {
  const seven = {...site(), id:selectedId, name:'seven.test',
    bound_domains:[{name:'seven.test',port:80}]};
  const eight = {...site(), id:8, name:'eight.test',
    bound_domains:[{name:'eight.test',port:80}]};
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  ui.requests.at(-1).respond({...page([seven,eight].sort((a,b)=>a.id-b.id)),purpose:'status_site_selection'});
  ui.statusSetValue('#ach-status-site-id',String(selectedId),'change');
  ui.requests.at(-1).respond(statusPrefs(3,'Site override',
    {...brand(),brand_name:'Saved seven'}));
  ui.statusSetValue('#ach-status-name','Dirty seven','input change');
  return {seven,eight};
}

test('Reviewed R1: dirty site remains selected through a successful native site-list refresh', () => {
  const ui=loadUi();
  const {seven,eight}=statusSiteDraftFixture(ui);
  const prompts=ui.statusConfirmations().length;
  assert.equal(ui.statusFieldDisabled(),false);
  assert.equal(ui.state().statusSaveDisabled,false);
  const refresh=ui.statusClick('#ach-status-sites-retry');
  assert.match(refresh.options.url,/s=status_sites$/);
  assert.equal(ui.statusSiteDisabled(),true,'Unverified selector must be temporarily frozen');
  assert.equal(ui.state().statusSaveDisabled,true,'Refreshing list is not authorization to Save');
  assert.equal(ui.statusFieldDisabled(),false,'Editable draft must remain available');
  assert.equal(ui.state().statusName,'Dirty seven');
  refresh.respond({...page([seven,eight]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusName,'Dirty seven');
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.equal(ui.statusConfirmations().length,prompts,'No modal for no-loss refresh');
  const save=ui.statusClick('#ach-status-save');
  assert.match(save.options.url,/s=status_save$/);
  assert.equal(save.options.data.site_id,'7');
  assert.equal(save.options.data.brand_name,'Dirty seven');
});

test('Reviewed R1: vanished site preserves draft and explicit Cancel restores lost option', () => {
  const ui=loadUi();
  const {eight}=statusSiteDraftFixture(ui);
  const refresh=ui.statusClick('#ach-status-sites-retry');
  refresh.respond({...page([eight]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusName,'Dirty seven');
  assert.equal(ui.statusFieldDisabled(),false);
  assert.equal(ui.state().statusSaveDisabled,true);
  assert.equal(ui.state().statusInspectDisabled,true);
  assert.equal(ui.state().statusProbeDisabled,true);
  assert.match(ui.statusSiteInfo(),/no longer in refreshed inventory/);
  assert.deepEqual(ui.statusSiteChoices().map(v=>v.id),['','8','7']);
  const before=ui.requests.length;
  ui.statusClick('#ach-status-save');
  ui.statusClick('#ach-status-preview-button');
  assert.equal(ui.requests.length,before,'A ghost site must not authorize operations');
  ui.statusSetValue('#ach-status-site-id','8','change');
  assert.equal(ui.requests.length,before);
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusName,'Dirty seven');
  assert.equal(ui.statusConfirmations().length,1);
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-site-id','8','change');
  const next=ui.requests.at(-1);
  assert.equal(ui.requests.length,before+1);
  assert.match(next.options.url,/s=status_preferences$/);
  next.respond(statusPrefs(4,'Site override',{...brand(),brand_name:'Saved eight'}));
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'8'});
  assert.equal(ui.state().statusName,'Saved eight');
  assert.equal(ui.state().statusSaveDisabled,false);
});

test('Reviewed R1: dirty selection found on later inventory page re-enables Save only after discovery', () => {
  const ui=loadUi();
  const {seven}=statusSiteDraftFixture(ui,70);
  const otherSites=Array.from({length:25},(_,i) => ({
    ...site(),id:i+1,name:'batch'+(i+1)+'.test',
    document_root:'/www/batch'+(i+1)+'.test',
    bound_domains:[{name:'batch'+(i+1)+'.test',port:80}],
    canonical_domain_bound:true
  }));
  const refresh=ui.statusClick('#ach-status-sites-retry');
  refresh.respond({...page(otherSites),purpose:'status_site_selection',has_more:true});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'70'});
  assert.match(ui.statusSiteInfo(),/Load more websites/);
  assert.equal(ui.state().statusSaveDisabled,true);
  const next=ui.loadMoreSites();
  assert.equal(next.options.data.page,2);
  next.respond({...page([seven]),page:2,purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'70'});
  assert.equal(ui.state().statusName,'Dirty seven');
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.equal(ui.statusConfirmations().length,0);
  assert.equal(ui.statusSiteChoices().filter(v=>v.id==='70').length,1);
});

test('Reviewed R1: failed or stale inventory does not erase draft or authorize stale Save', () => {
  const ui=loadUi();
  const {seven}=statusSiteDraftFixture(ui);
  const first=ui.statusClick('#ach-status-sites-retry');
  const newest=ui.statusClick('#ach-status-sites-retry');
  assert.equal(newest,first,'Pending retry must not start concurrent inventory reads');
  first.respond({...page([seven]),purpose:'status_site_selection'});
  assert.equal(ui.state().statusSaveDisabled,false);
  const second=ui.statusClick('#ach-status-sites-retry');
  second.respond({status:true,inventory_schema:999});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusName,'Dirty seven');
  assert.equal(ui.state().statusSaveDisabled,true);
  assert.equal(ui.statusSiteDisabled(),true);
  assert.match(ui.statusSiteInfo(),/inventory unavailable/);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-save');
  assert.equal(ui.requests.length,count);
  const recovery=ui.statusClick('#ach-status-sites-retry');
  recovery.respond({...page([seven]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSelection(),{scope:'site',site:'7'});
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.equal(ui.state().statusName,'Dirty seven');
});

test('Reviewed R1: delayed site-list response cannot replace a newly accepted global draft', () => {
  const ui=loadUi();
  const {seven}=statusSiteDraftFixture(ui);
  const stale=ui.statusClick('#ach-status-sites-retry');
  assert.equal(ui.state().statusName,'Dirty seven');
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-scope','global','change');
  const global=ui.requests.at(-1);
  assert.notEqual(global,stale);
  assert.match(global.options.url,/s=status_preferences$/);
  global.respond(statusPrefs(11,'Global default',
    {...brand(),brand_name:'New global'}));
  assert.deepEqual(ui.statusSelection(),{scope:'global',site:''});
  assert.equal(ui.state().statusName,'New global');
  stale.respond({...page([seven]),purpose:'status_site_selection'});
  assert.deepEqual(ui.statusSelection(),{scope:'global',site:''});
  assert.equal(ui.state().statusName,'New global');
  assert.equal(ui.state().statusSaveDisabled,false);
  assert.deepEqual(ui.statusSiteChoices().map(x=>x.id),['']);
  assert.equal(ui.statusConfirmations().length,1);
});

test('Reviewed R1: no unsaved branding can be entered before a valid loaded baseline', () => {
  const ui=loadUi();
  const initial=ui.openStatus();
  assert.equal(ui.statusFieldDisabled(),true);
  assert.equal(ui.state().statusSaveDisabled,true);
  initial.respond(statusPrefs());
  assert.equal(ui.statusFieldDisabled(),false);
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.statusFieldDisabled(),true);
  assert.equal(ui.state().statusSaveDisabled,true);
  const list=ui.requests.at(-1);
  const seven={...site(),id:7,name:'seven.test',
    bound_domains:[{name:'seven.test',port:80}]};
  list.respond({...page([seven]),purpose:'status_site_selection'});
  assert.equal(ui.statusFieldDisabled(),true);
  ui.statusSetValue('#ach-status-site-id','7','change');
  const preference=ui.requests.at(-1);
  assert.match(preference.options.url,/s=status_preferences$/);
  assert.equal(ui.statusFieldDisabled(),true);
  preference.respond({status:false,stage:'preferences_read'});
  assert.equal(ui.statusFieldDisabled(),true);
  assert.equal(ui.state().statusSaveDisabled,true);
  ui.statusClick('#ach-status-load').respond(statusPrefs(8,'Site override',
    {...brand(),brand_name:'Seven'}));
  assert.equal(ui.statusFieldDisabled(),false);
  assert.equal(ui.state().statusSaveDisabled,false);
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
const siteChangesPayload = (overrides = {}) => {
  const response = {
    status:true, schema:1, state:'Baseline Missing', scope:'native_site_records',
    read_only:true, runtime_verified:false, baseline_revision:0,
    monitor_revision:0, baseline_sha256:null, source_sha256:'a'.repeat(64),
    site_count:1, initial_sites:[nativeSiteForDrift(3,'initial.test')], changes:[],
    note:'aaPanel database only; runtime not verified.', ...overrides
  };
  if (!Object.hasOwn(overrides,'initial_sites') && response.baseline_revision !== 0)
    response.initial_sites=[];
  return response;
};

test('Site lifecycle comparison requires reviewed baseline and refuses blind retry', () => {
  const ui=loadUi();
  ui.openSites().respond(page());
  const compare=ui.siteChangesCompare();
  assert.match(compare.options.url,/s=compare_site_changes$/);
  compare.respond(siteChangesPayload());
  assert.match(ui.state().siteChangesStatus,/Baseline Missing/);
  assert.deepEqual(ui.state().siteChangesRows,[
    ['3','Initial','initial.test',
     'Name: initial.test; root: /srv/3; status: 1; domains/ports: initial.test:80']]);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  ui.siteChangesApprove(true);
  assert.equal(ui.state().siteChangesSaveDisabled,false);
  const save=ui.siteChangesSave();
  assert.match(save.options.url,/s=save_site_baseline$/);
  assert.equal(save.options.data.expected_revision,0);
  assert.equal(save.options.data.expected_monitor_revision,0);
  assert.equal(save.options.data.expected_source_sha256,'a'.repeat(64));
  assert.equal(save.options.data.reviewed,'true');
  assert.deepEqual(Object.keys(save.options.data).sort(),
    ['expected_monitor_revision','expected_revision','expected_source_sha256','reviewed']);
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
    ['3','Changed','<svg onload=alert(1)>',
     'name: old.example.test -> <svg onload=alert(1)>; bound_domains: old.example.test:80 -> <svg onload=alert(1)>:80']]);
  ui.siteChangesApprove(true);
  assert.equal(ui.state().siteChangesSaveDisabled,false);
  ui.refreshSites();
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  assert.deepEqual(ui.state().siteChangesRows,[]);
});

test('Site lifecycle review exposes actual before/after roots, statuses and bindings', () => {
  const ui=loadUi();
  ui.openSites().respond(page());
  const previous=nativeSiteForDrift(3,'old.test');
  const current={...previous,document_root:'/srv/new-root',panel_status:'0',
    bound_domains:[['private.test',443],['alias.test',80]]};
  ui.siteChangesCompare().respond(siteChangesPayload({
    state:'Changes Observed',baseline_revision:1,baseline_sha256:'b'.repeat(64),
    changes:[{id:3,kind:'Changed',
      fields:['document_root','panel_status','bound_domains'],
      before:previous,after:current}]
  }));
  assert.deepEqual(ui.state().siteChangesRows,[
    ['3','Changed','old.test',
     'document_root: /srv/3 -> /srv/new-root; panel_status: 1 -> 0; '+
     'bound_domains: old.test:80 -> private.test:443, alias.test:80']]);
  ui.siteChangesApprove(true);
  const save=ui.siteChangesSave();
  assert.equal(save.options.data.expected_monitor_revision,0);
});

test('Initial baseline payload must carry validated actual site records', () => {
  const bad=[
    siteChangesPayload({initial_sites:[]}),
    siteChangesPayload({monitor_revision:'0'}),
    siteChangesPayload({initial_sites:[nativeSiteForDrift(3,'a'),nativeSiteForDrift(3,'b')],
      site_count:2}),
    siteChangesPayload({initial_sites:[nativeSiteForDrift(3,'<img src=x onerror=alert(1)>'),
      nativeSiteForDrift(1,'x')],site_count:2}),
    siteChangesPayload({initial_sites:[{...nativeSiteForDrift(3,'a'),bound_domains:[['bad',0]]}]}),
  ];
  for(const value of bad) {
    const ui=loadUi();
    ui.openSites().respond(page());
    ui.siteChangesCompare().respond(value);
    assert.equal(ui.state().siteChangesSaveDisabled,true);
    assert.deepEqual(ui.state().siteChangesRows,[]);
  }
  const ui=loadUi();
  ui.openSites().respond(page());
  ui.siteChangesCompare().respond(siteChangesPayload({
    initial_sites:[nativeSiteForDrift(3,'<img src=x onerror=alert(1)>')]
  }));
  assert.match(ui.state().siteChangesRows[0][3],/<img src=x onerror=alert\(1\)>/);
  assert.equal(ui.state().siteChangesSaveDisabled,true);
  ui.siteChangesApprove(true);
  assert.equal(ui.state().siteChangesSaveDisabled,false);
  ui.refreshSites();
  assert.equal(ui.state().siteChangesSaveDisabled,true);
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


const defaultSourceNames = {'new-site':'defaultDoc.html','404':'404.html','502':'502.html'};
function defaultReply(action, template='404', state='Source Ready', overrides={}) {
  const source='9'.repeat(64), rendered='8'.repeat(64), operation='c'.repeat(32);
  return {
    status:true,schema:1,default_action:action,scope:'global',site_id:null,
    mode:'native_new_site_sources',template,source_file:defaultSourceNames[template],
    locale:'en',revision:2,request_id:'b'.repeat(32),operation_id:'b'.repeat(32),
    state,current_sha256:state==='Applied'?rendered:source,
    rendered_sha256:rendered,
    before_sha256:['Applied','Recovery Required','Restored'].includes(state)?source:null,
    after_sha256:['Applied','Recovery Required','Restored'].includes(state)?rendered:null,
    recovery_id:['Applied','Recovery Required','Restored'].includes(state)?operation:null,
    changed:action==='apply'&&state==='Applied',read_only:action==='recheck',
    runtime_verified:false,
    impact:'New sites only; does not change existing sites or live Nginx routing',
    ...overrides,
  };
}

test('New-site defaults require global scope and a fresh source recheck', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  assert.equal(ui.state().defaultSourceRecheckDisabled,false);
  assert.equal(ui.state().defaultSourceApplyDisabled,true);
  assert.equal(ui.state().defaultSourceRestoreDisabled,true);
  const current=ui.statusClick('#ach-status-default-recheck');
  assert.match(current.options.url,/s=status_defaults$/);
  assert.equal(current.options.data.default_action,'recheck');
  assert.equal(current.options.data.scope,'global');
  assert.equal(current.options.data.template,'404');
  current.respond(defaultReply('recheck'));
  assert.match(ui.state().defaultSourceResult,/Source Ready/);
  assert.equal(ui.state().defaultSourceApplyDisabled,true);
  ui.statusSetChecked('#ach-status-default-apply-approve',true);
  assert.equal(ui.state().defaultSourceApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-default-apply');
  assert.match(apply.options.url,/s=status_defaults$/);
  assert.equal(apply.options.data.default_approval,'apply_new_site_default_404');
  assert.equal(apply.options.data.expected_current_sha256,'9'.repeat(64));
  assert.equal(apply.options.data.expected_render_sha256,'8'.repeat(64));
  apply.respond(defaultReply('apply','404','Applied'));
  assert.match(ui.state().defaultSourceResult,/Applied.*source bytes changed/);
  assert.equal(ui.state().defaultSourceRestoreDisabled,true,
    'After Apply a fresh persisted recovery Recheck is mandatory');
  const check=ui.statusClick('#ach-status-default-recheck');
  check.respond(defaultReply('recheck','404','Applied'));
  ui.statusSetChecked('#ach-status-default-restore-approve',true);
  assert.equal(ui.state().defaultSourceRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-default-restore');
  assert.equal(restore.options.data.expected_recovery_id,'c'.repeat(32));
  assert.equal(restore.options.data.default_approval,'restore_new_site_default_404');
  restore.respond(defaultReply('restore','404','Restored',{
    current_sha256:'9'.repeat(64),changed:true
  }));
  assert.match(ui.state().defaultSourceResult,/Restored/);
  assert.match(ui.state().defaultSourceResult,/Existing sites and Nginx are unchanged/);
  const recheckRestored=ui.statusClick('#ach-status-default-recheck');
  recheckRestored.respond(defaultReply('recheck','404','Restored'));
  ui.statusSetChecked('#ach-status-default-apply-approve',true);
  assert.equal(ui.state().defaultSourceApplyDisabled,false,
    'Confirmed restored original remains eligible for an explicit new Apply');
});

test('New-site defaults revoke source evidence on branding, locale, scope changes and bad results', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusClick('#ach-status-default-recheck').respond(defaultReply('recheck'));
  ui.statusSetChecked('#ach-status-default-apply-approve',true);
  assert.equal(ui.state().defaultSourceApplyDisabled,false);
  ui.statusSetValue('#ach-status-locale','fa','change');
  assert.equal(ui.state().defaultSourceApplyDisabled,true);
  ui.statusSetValue('#ach-status-template','new-site','change');
  const wrong=ui.statusClick('#ach-status-default-recheck');
  wrong.respond(defaultReply('recheck','new-site','Source Ready',{source_file:'502.html'}));
  assert.match(ui.state().defaultSourceResult,/Read-only Recheck incomplete or incompatible/);
  ui.statusSetValue('#ach-status-locale','en','change');
  ui.statusClick('#ach-status-default-recheck').respond(defaultReply('recheck','new-site'));
  ui.statusSetChecked('#ach-status-default-apply-approve',true);
  assert.equal(ui.state().defaultSourceApplyDisabled,false);
  ui.statusSetValue('#ach-status-name','Different','input change');
  assert.equal(ui.state().defaultSourceApplyDisabled,true);
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.state().defaultSourceRecheckDisabled,true);
  assert.equal(ui.state().defaultSourceApplyDisabled,true);
});


const unboundImpact = 'Unknown HTTP Host on port 80 (IPv4/IPv6) only; no HTTPS or stopped-site change';
function unboundReply(action, state='Source Ready', overrides={}) {
  const recovery='c'.repeat(32);
  const changed=action!=='recheck';
  return {
    status:true, schema:1, mode:'native_http_unbound', unbound_action:action,
    scope:'global', site_id:null, template:'unbound', locale:'en', revision:2,
    request_id:'b'.repeat(32), operation_id:'b'.repeat(32),
    state, source_sha256:'9'.repeat(64), rendered_sha256:'8'.repeat(64),
    recovery_id:['Applied','Recovery Required','Restored'].includes(state)?recovery:null,
    before_ipv4_status:200, before_ipv6_status:200,
    changed, read_only:!changed, runtime_verified:changed || state==='Applied',
    impact:unboundImpact, ...overrides
  };
}

test('HTTP unbound Nginx operation has bounded timeout, Activity refresh and uncertain outcome guidance', () => {
  const ui=loadUi();
  ui.openActivity().respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  const recheck=ui.statusClick('#ach-status-unbound-recheck');
  assert.equal(recheck.options.timeout,45000,'Nginx source/probe path uses same budget as other status managers');
  recheck.respond(unboundReply('recheck'));
  const afterRead=ui.openActivity();
  assert.match(afterRead.options.url,/s=get_activity$/,
    'Successful native HTTP source inspection invalidates earlier Activity');
  afterRead.respond({status:true,schema:1,read_only:true,configured_level:'INFO',entries:[]});
  ui.openStatus();
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  const apply=ui.statusClick('#ach-status-unbound-apply');
  assert.equal(apply.options.timeout,45000);
  apply.reject({},'timeout');
  assert.match(ui.state().error,/Outcome unknown: inspect saved recovery before any retry/);
  assert.match(ui.state().unboundResult,/outcome unconfirmed.*Recheck saved recovery/);
  const afterFailure=ui.openActivity();
  assert.match(afterFailure.options.url,/s=get_activity$/,
    'Timed-out global Nginx Apply must invalidate Activity and require a fresh read');
});

test('HTTP/80 unbound requires explicit approvals and fresh recovery Recheck', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  assert.equal(ui.state().unboundRecheckDisabled,true);
  ui.statusSetValue('#ach-status-template','unbound','change');
  assert.equal(ui.state().unboundRecheckDisabled,false);
  assert.equal(ui.state().unboundApplyDisabled,true);
  assert.equal(ui.state().unboundRestoreDisabled,true);
  const recheck=ui.statusClick('#ach-status-unbound-recheck');
  assert.match(recheck.options.url,/s=status_unbound$/);
  assert.equal(recheck.options.data.unbound_action,'recheck');
  assert.equal(recheck.options.data.scope,'global');
  recheck.respond(unboundReply('recheck'));
  assert.match(ui.state().unboundResult,/Source Ready/);
  assert.equal(ui.state().unboundApplyDisabled,true);
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-unbound-apply');
  assert.equal(apply.options.data.unbound_approval,'apply_global_http_unbound_reload');
  assert.equal(apply.options.data.expected_source_sha256,'9'.repeat(64));
  assert.equal(apply.options.data.expected_render_sha256,'8'.repeat(64));
  assert.equal(apply.options.data.expected_ipv4_status,'200');
  assert.equal(apply.options.data.expected_ipv6_status,'200');
  apply.respond(unboundReply('apply','Applied'));
  assert.match(ui.state().unboundResult,/Applied/);
  assert.equal(ui.state().unboundRestoreDisabled,true);
  const current=ui.statusClick('#ach-status-unbound-recheck');
  current.respond(unboundReply('recheck','Applied'));
  ui.statusSetChecked('#ach-status-unbound-restore-approve',true);
  assert.equal(ui.state().unboundRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-unbound-restore');
  assert.equal(restore.options.data.expected_recovery_id,'c'.repeat(32));
  assert.equal(restore.options.data.unbound_approval,'restore_global_http_unbound_reload');
  restore.respond(unboundReply('restore','Restored'));
  assert.match(ui.state().unboundResult,/Restored/);
  assert.equal(ui.state().unboundApplyDisabled,true);
});

test('HTTP unbound wrong replies, brand edits and scope/locale changes revoke authorization', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  ui.statusClick('#ach-status-unbound-recheck').respond(
    unboundReply('recheck','Source Ready',{mode:'not_http_unbound'})
  );
  assert.match(ui.state().unboundResult,/Read-only Recheck incomplete or incompatible/);
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,true);
  ui.statusClick('#ach-status-unbound-recheck').respond(unboundReply('recheck'));
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,false);
  ui.statusSetValue('#ach-status-name','Changed brand','input change');
  assert.equal(ui.state().unboundApplyDisabled,true);
  ui.statusClick('#ach-status-unbound-recheck').respond(unboundReply('recheck'));
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,false);
  ui.statusSetValue('#ach-status-locale','fa','change');
  assert.equal(ui.state().unboundApplyDisabled,true);
  ui.statusPermitDiscard(true);
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.equal(ui.state().unboundRecheckDisabled,true);
  assert.equal(ui.state().unboundApplyDisabled,true);
});


test('Native HTTP unbound read-only failure shows backend cause at its own control', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  const inspect=ui.statusClick('#ach-status-unbound-recheck');
  inspect.respond({status:false,stage:'status_unbound_probe',
    msg:'Unbound loopback HTTP request unavailable',operation_id:'a'.repeat(32)});
  const shown=ui.state().unboundResult;
  assert.match(shown,/Read-only Recheck failed at status_unbound_probe/);
  assert.match(shown,/Unbound loopback HTTP request unavailable/);
  assert.match(shown,/127\.0\.0\.1 and \[::1\]/);
  assert.match(shown,/No routing change was requested/);
  assert.match(shown,/Request ID: a{32}/);
  assert.doesNotMatch(shown,/Write outcome|saved recovery before any retry/i);
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,true);
  assert.equal(ui.state().unboundRestoreDisabled,true);
  assert.match(ui.state().error,/status_unbound_probe.*Unbound loopback HTTP request unavailable/);
});

test('Rejected HTTP unbound write reports recovery without authorizing blind retry', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  ui.statusClick('#ach-status-unbound-recheck').respond(unboundReply('recheck'));
  ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
  assert.equal(ui.state().unboundApplyDisabled,false);
  const write=ui.statusClick('#ach-status-unbound-apply');
  write.respond({status:false,stage:'status_unbound_uncertain',
    msg:'Reload outcome not verified',recovery_id:'c'.repeat(32),
    operation_id:'b'.repeat(32),request_id:'b'.repeat(32)});
  const shown=ui.state().unboundResult;
  assert.match(shown,/Write outcome not confirmed at status_unbound_uncertain/);
  assert.match(shown,/Reload outcome not verified/);
  assert.match(shown,/Recheck saved recovery before any retry/);
  assert.match(shown,/Recovery ID: c{32}/);
  assert.match(shown,/Request ID: b{32}/);
  assert.doesNotMatch(shown,/No routing change was requested/);
  assert.equal(ui.state().unboundApplyDisabled,true);
  assert.equal(ui.state().unboundRestoreDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-unbound-apply');
  assert.equal(ui.requests.length,count,'Rejected Apply cannot be blindly retried');
});

test('Other native Status Pages Rechecks share inline backend-error diagnostics', () => {
  const defaults=loadUi();
  defaults.openStatus().respond(statusPrefs());
  defaults.statusClick('#ach-status-default-recheck').respond({
    status:false,stage:'status_defaults_source',msg:'Existing default file needs inspection'
  });
  assert.match(defaults.state().defaultSourceResult,
    /Read-only Recheck failed at status_defaults_source: Existing default file needs inspection/);
  assert.equal(defaults.state().defaultSourceApplyDisabled,true);

  const site=statusProbeUi();
  site.statusClick('#ach-status-manage-recheck').respond({
    status:false,stage:'status_manage_source',msg:'Native VHost requires a fresh source check'
  });
  assert.match(site.state().statusManage,
    /Read-only Recheck failed at status_manage_source: Native VHost requires a fresh source check/);
  assert.equal(site.state().statusManageRestoreDisabled,true);

  const stopped=loadUi();
  chooseStoppedSite(stopped);
  stopped.statusClick('#ach-status-stopped-recheck').respond({
    status:false,stage:'status_stopped_probe',msg:'Native site state changed'
  });
  assert.match(stopped.state().stoppedResult,
    /Read-only Recheck failed at status_stopped_probe: Native site state changed/);
  assert.equal(stopped.state().stoppedApplyDisabled,true);
  assert.equal(stopped.state().stoppedRestoreDisabled,true);
});

test('Malformed native Status Page failure remains untrusted and cannot expose approvals', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  ui.statusClick('#ach-status-unbound-recheck').respond({
    status:false,stage:'<img onerror=alert(1)>',msg:'Unexpected hostile stage'
  });
  assert.doesNotMatch(ui.state().unboundResult,/img|onerror|Unexpected hostile stage/);
  assert.match(ui.state().unboundResult,/Read-only Recheck incomplete or incompatible/);
  assert.match(ui.state().unboundResult,/No write was requested/);
  assert.doesNotMatch(ui.state().unboundResult,/write outcome|saved recovery/i);
  assert.equal(ui.state().unboundApplyDisabled,true);
  assert.equal(ui.state().unboundRestoreDisabled,true);
});


test('Status Page backend error IDs use the native operation correlation, distinct from recovery', () => {
  const id=(char)=>char.repeat(32);
  for (const scenario of [
    {label:'ordinary backend failure, operation ID only',
      failure:{operation_id:id('a')},expected:id('a'),recovery:null},
    {label:'backend recovery with matching request alias',
      failure:{operation_id:id('b'),request_id:id('b'),recovery_id:id('c')},
      expected:id('b'),recovery:id('c')},
    {label:'invalid request alias, valid native operation',
      failure:{operation_id:id('d'),request_id:'not-a-valid-id',recovery_id:id('e')},
      expected:id('d'),recovery:id('e')},
    {label:'contradictory valid alias, native operation wins',
      failure:{operation_id:id('f'),request_id:id('1'),recovery_id:id('2')},
      expected:id('f'),recovery:id('2'),reject:id('1')},
    {label:'valid request alias, invalid operation ID',
      failure:{operation_id:'BAD_OPERATION',request_id:id('3')},
      expected:id('3'),recovery:null},
    {label:'both identifiers malformed, no invented correlation or recovery',
      failure:{operation_id:'BAD_OPERATION',request_id:'BAD_REQUEST',
        recovery_id:'BAD_RECOVERY'},expected:null,recovery:null}
  ]) {
    const ui=loadUi();
    ui.openStatus().respond(statusPrefs());
    ui.statusSetValue('#ach-status-template','unbound','change');
    ui.statusClick('#ach-status-unbound-recheck').respond({
      status:false,stage:'status_unbound_probe',
      msg:'Unbound loopback HTTP request unavailable',...scenario.failure
    });
    const shown=ui.state().unboundResult;
    assert.match(shown,/Read-only Recheck failed at status_unbound_probe/,scenario.label);
    if (scenario.expected) assert.match(shown,new RegExp('Request ID: '+scenario.expected),scenario.label);
    else assert.doesNotMatch(shown,/Request ID:/,scenario.label);
    if (scenario.recovery) assert.match(shown,new RegExp('Recovery ID: '+scenario.recovery),scenario.label);
    else assert.doesNotMatch(shown,/Recovery ID:/,scenario.label);
    if (scenario.reject) assert.doesNotMatch(shown,new RegExp(scenario.reject),scenario.label);
    assert.equal(ui.state().unboundApplyDisabled,true,scenario.label);
    assert.equal(ui.state().unboundRestoreDisabled,true,scenario.label);
  }
});

test('Read-only defaults and Unbound Recheck errors never imply an uncertain write', () => {
  for (const mode of ['defaults','unbound']) {
    for (const failureMode of ['timeout','missing','malformed','incompatible']) {
      const ui=loadUi();
      ui.openStatus().respond(statusPrefs());
      if (mode==='unbound') ui.statusSetValue('#ach-status-template','unbound','change');
      const selector=mode==='defaults'?'#ach-status-default-recheck':'#ach-status-unbound-recheck';
      const request=ui.statusClick(selector);
      if (failureMode==='timeout') request.reject({},'timeout');
      else if (failureMode==='missing') request.respond(null);
      else if (failureMode==='malformed') request.respond({
        status:false,stage:'<invalid>',msg:'Untrusted diagnostic',
        operation_id:'<fake>'
      });
      else if (mode==='defaults') request.respond(defaultReply('recheck','404','Source Ready',{
        source_file:'not-the-selected-native-file'
      }));
      else request.respond(unboundReply('recheck','Source Ready',{mode:'wrong_http_mode'}));
      const shown=mode==='defaults' ? ui.state().defaultSourceResult : ui.state().unboundResult;
      assert.match(shown,/Read-only Recheck incomplete or incompatible/,mode+':'+failureMode);
      assert.match(shown,/No write was requested/,mode+':'+failureMode);
      assert.doesNotMatch(shown,/write outcome|saved recovery|retry before|unconfirmed/i,
        mode+':'+failureMode);
      if (failureMode==='timeout') assert.doesNotMatch(ui.state().error,/Outcome unknown/i,
        mode+':timeout');
      if (mode==='defaults') {
        ui.statusSetChecked('#ach-status-default-apply-approve',true);
        assert.equal(ui.state().defaultSourceApplyDisabled,true,mode+':'+failureMode);
      } else {
        ui.statusSetChecked('#ach-status-unbound-apply-approve',true);
        assert.equal(ui.state().unboundApplyDisabled,true,mode+':'+failureMode);
        assert.equal(ui.state().unboundRestoreDisabled,true,mode+':'+failureMode);
      }
    }
  }
});

test('Defaults and Unbound rejected Apply/Restore never claim a completed write', () => {
  for (const mode of ['defaults','unbound']) {
    for (const action of ['apply','restore']) {
      const ui=loadUi();
      ui.openStatus().respond(statusPrefs());
      if (mode==='unbound') ui.statusSetValue('#ach-status-template','unbound','change');
      const prefix=mode==='defaults'?'#ach-status-default-':'#ach-status-unbound-';
      const reply=mode==='defaults'?
        (a,state)=>defaultReply(a,'404',state):
        (a,state)=>unboundReply(a,state);
      ui.statusClick(prefix+'recheck').respond(reply('recheck','Source Ready'));
      ui.statusSetChecked(prefix+'apply-approve',true);
      assert.equal(mode==='defaults' ? ui.state().defaultSourceApplyDisabled :
        ui.state().unboundApplyDisabled,false,mode+':'+action+' preparation');
      if (action==='restore') {
        ui.statusClick(prefix+'apply').respond(reply('apply','Applied'));
        ui.statusClick(prefix+'recheck').respond(reply('recheck','Applied'));
        ui.statusSetChecked(prefix+'restore-approve',true);
        assert.equal(mode==='defaults'?ui.state().defaultSourceRestoreDisabled:
          ui.state().unboundRestoreDisabled,false,mode+':restore preparation');
      }
      const request=ui.statusClick(prefix+action);
      request.reject({},'timeout');
      const shown=mode==='defaults'?ui.state().defaultSourceResult:ui.state().unboundResult;
      assert.match(shown,/write outcome unconfirmed/i,mode+':'+action);
      assert.match(shown,/Recheck .*recovery before any retry/,mode+':'+action);
      assert.doesNotMatch(shown,/No write was requested|Read-only Recheck/i,mode+':'+action);
      assert.match(ui.state().error,/Outcome unknown: inspect saved recovery before any retry/,
        mode+':'+action);
      const before=ui.requests.length;
      ui.statusClick(prefix+action);
      assert.equal(ui.requests.length,before,mode+':'+action+' cannot be blindly retried');
    }
  }
});

test('Status Page diagnostics render literal bounded messages and ignore stale selection', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  const hostile='<svg onload=alert(1)>'; // untrusted response, not HTML
  ui.statusClick('#ach-status-unbound-recheck').respond({
    status:false,stage:'status_unbound_probe',operation_id:'a'.repeat(32),
    msg:hostile+'q'.repeat(700)
  });
  const displayed=ui.state().unboundResult;
  assert.match(displayed,/<svg onload=alert\(1\)>/,'diagnostic text kept literal');
  assert.doesNotMatch(displayed,/q{321}/,'diagnostic text bounded at 320 chars');
  assert.match(displayed,/Request ID: a{32}/);
  const old=ui.statusClick('#ach-status-unbound-recheck');
  ui.statusSetValue('#ach-status-template','404','change');
  old.respond({status:false,stage:'status_unbound_probe',
    msg:'STALE_SELECTION_SHOULD_NOT_RENDER',operation_id:'b'.repeat(32)});
  assert.doesNotMatch(ui.state().unboundResult,/STALE_SELECTION_SHOULD_NOT_RENDER/);
  assert.equal(ui.state().unboundApplyDisabled,true);
});

function stoppedAck(request, state='Source Ready', extras={}) {
  const fields=request.options.data;
  const action=fields.stopped_action;
  const result = {
    status:true,schema:1,mode:'native_stopped_http503',
    stopped_action:action,scope:'site',template:'stopped',
    locale:fields.locale,revision:Number(fields.expected_revision),
    site_id:7,site_key:'demo.test',site_status:'1',
    verified_site_snapshot:fields.expected_site_snapshot,
    request_id:'a'.repeat(32),operation_id:'a'.repeat(32),
    vhost_sha256:'b'.repeat(64),rendered_sha256:'c'.repeat(64),
    served_sha256:'d'.repeat(64),recovery_id:null,
    read_only:action==='recheck',changed:action!=='recheck',runtime_verified:false,
    state,impact:'Native aaPanel SiteStop/Start; shared Nginx reload, HTTPS unchanged.',
    ...extras
  };
  result.proof_kind = extras.proof_kind ||
    (result.state === 'Applied' && result.runtime_verified ? 'stopped_http503' :
      result.state === 'Restored' && result.runtime_verified ?
        (result.site_status === '0' ? 'native_http200' : 'running_non503') :
      ['Source Ready','Armed','Restored'].includes(result.state) ? 'source_only' : 'none');
  return result;
}
function chooseStoppedSite(ui, panelStatus='1') {
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-scope','site','change');
  loadNativeStatusSiteSelection(ui,'7',panelStatus);
  const saved=ui.requests.at(-1);
  assert.match(saved.options.url,/s=status_preferences$/);
  saved.respond(statusPrefs(2,'Global default'));
  ui.statusSetValue('#ach-status-template','stopped','change');
  assert.equal(ui.state().stoppedRecheckDisabled,false);
}

test('Stopped-site 503 requires selected live site, exact Recheck and explicit Apply/Restore', () => {
  const ui=loadUi();
  chooseStoppedSite(ui);
  assert.equal(ui.state().stoppedApplyDisabled,true);
  const pre=ui.statusClick('#ach-status-stopped-recheck');
  assert.match(pre.options.url,/s=status_stopped$/);
  assert.equal(pre.options.type,'POST');
  assert.equal(pre.options.timeout,45000);
  assert.equal(pre.options.data.stopped_action,'recheck');
  assert.equal(pre.options.data.template,'stopped');
  assert.equal(pre.options.data.scope,'site');
  assert.equal(pre.options.data.site_id,'7');
  assert.equal(pre.options.data.expected_site_key,'demo.test');
  pre.respond(stoppedAck(pre));
  assert.equal(ui.state().stoppedApplyDisabled,true);
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  assert.equal(ui.state().stoppedApplyDisabled,false);
  const apply=ui.statusClick('#ach-status-stopped-apply');
  assert.match(apply.options.url,/s=status_stopped$/);
  assert.equal(apply.options.data.stopped_approval,'apply_exact_native_stopped503_reload');
  assert.equal(apply.options.data.expected_vhost_sha256,'b'.repeat(64));
  assert.equal(apply.options.data.expected_render_sha256,'c'.repeat(64));
  assert.equal(ui.state().stoppedApplyDisabled,true);
  apply.respond(stoppedAck(apply,'Armed',{
    read_only:false,changed:true,recovery_id:'f'.repeat(32),
    vhost_sha256:'e'.repeat(64)
  }));
  assert.match(ui.state().stoppedResult,/Armed/);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
  const saved=ui.statusClick('#ach-status-stopped-recheck');
  saved.respond(stoppedAck(saved,'Armed',{
    recovery_id:'f'.repeat(32),vhost_sha256:'e'.repeat(64)
  }));
  ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
  assert.equal(ui.state().stoppedRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-stopped-restore');
  assert.equal(restore.options.data.expected_recovery_id,'f'.repeat(32));
  assert.equal(restore.options.data.stopped_approval,'restore_exact_native_stopped503_reload');
  restore.respond(stoppedAck(restore,'Restored',{
    read_only:false,changed:true,runtime_verified:true,recovery_id:'f'.repeat(32)
  }));
  assert.match(ui.state().stoppedResult,/Restored/);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
});

test('Restored-site foreign 503 rule is Conflict and never permits Apply/Restore', () => {
  const ui=loadUi();chooseStoppedSite(ui);
  const read=ui.statusClick('#ach-status-stopped-recheck');
  read.respond(stoppedAck(read,'Conflict',{
    recovery_id:'f'.repeat(32),vhost_sha256:'e'.repeat(64)
  }));
  assert.match(ui.state().stoppedResult,/Conflict/);
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
  assert.equal(ui.state().stoppedApplyDisabled,true);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
  const count=ui.requests.length;
  ui.statusClick('#ach-status-stopped-restore');
  assert.equal(ui.requests.length,count);
});

test('Stopped-site prepared/restoring recovery accepts verified no-write Restore', () => {
  const ui=loadUi();chooseStoppedSite(ui);
  const read=ui.statusClick('#ach-status-stopped-recheck');
  read.respond(stoppedAck(read,'Recovery Required',{
    recovery_id:'f'.repeat(32),vhost_sha256:'e'.repeat(64)
  }));
  ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
  assert.equal(ui.state().stoppedRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-stopped-restore');
  assert.equal(restore.options.data.expected_recovery_id,'f'.repeat(32));
  restore.respond(stoppedAck(restore,'Restored',{
    read_only:false,changed:false,runtime_verified:true,recovery_id:'f'.repeat(32)
  }));
  assert.match(ui.state().stoppedResult,/Restored/);
  assert.doesNotMatch(ui.state().stoppedResult,/Outcome unknown/);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
});

test('Stopped-site stale response or unknown write cannot authorize retry', () => {
  const ui=loadUi();chooseStoppedSite(ui);
  const bad=ui.statusClick('#ach-status-stopped-recheck');
  bad.respond(stoppedAck(bad,'Source Ready',{verified_site_snapshot:'stale'}));
  assert.match(ui.state().stoppedResult,/incompatible/);
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  assert.equal(ui.state().stoppedApplyDisabled,true);
  const pre=ui.statusClick('#ach-status-stopped-recheck');
  pre.respond(stoppedAck(pre));
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  const apply=ui.statusClick('#ach-status-stopped-apply');
  apply.reject(null,'timeout');
  assert.match(ui.state().error,/Outcome unknown/);
  assert.match(ui.state().stoppedResult,/Outcome unknown/);
  assert.equal(ui.state().stoppedApplyDisabled,true);
  ui.statusClick('#ach-status-stopped-apply');
  assert.equal(ui.requests.at(-1),apply,'No blind write retry');
});

test('Stopped-site proof labels distinguish expected from observed and stopped Restore', () => {
  for (const scenario of [
    {state:'Source Ready',status:'1',runtime:false,kind:'source_only',
      label:/Expected stopped HTML SHA-256/,proof:/no HTTP 503 delivery observed/i},
    {state:'Armed',status:'1',runtime:false,kind:'source_only',
      label:/Prepared stopped HTML SHA-256/,proof:/has not been observed/},
    {state:'Restored',status:'1',runtime:false,kind:'source_only',
      label:/Previous stopped HTML SHA-256 \(not active\)/,proof:/no live stopped HTTP result observed/},
    {state:'Recovery Required',status:'1',runtime:false,kind:'none',
      label:/Saved stopped HTML SHA-256 \(not verified\)/,proof:/No confirmed live delivery/},
    {state:'Needs Review',status:'1',runtime:false,kind:'none',
      label:/Saved stopped HTML SHA-256 \(not verified\)/,proof:/managed delivery is unconfirmed/},
    {state:'Applied',status:'0',runtime:true,kind:'stopped_http503',
      label:/Observed HTTP 503 HTML SHA-256/,proof:/Observed HTTP 503, exact HTML digest and text\/html/}
  ]) {
    const ui=loadUi();chooseStoppedSite(ui,scenario.status);
    const req=ui.statusClick('#ach-status-stopped-recheck');
    req.respond(stoppedAck(req,scenario.state,{
      site_status:scenario.status,runtime_verified:scenario.runtime,
      recovery_id:scenario.state==='Source Ready'?null:'f'.repeat(32),
      proof_kind:scenario.kind
    }));
    const shown=ui.state().stoppedResult;
    assert.match(shown,scenario.label,scenario.state);
    assert.match(shown,scenario.proof,scenario.state);
    if (scenario.state!=='Applied') assert.doesNotMatch(shown,/Observed HTTP 503, exact HTML/);
    if (scenario.state!=='Applied') assert.doesNotMatch(shown,/Observed HTTP 503 HTML SHA-256/);
  }
});

test('Stopped-site Restore verification describes native HTTP 200 or running-only evidence, not HTTP 503', () => {
  for (const status of ['0','1']) {
    const ui=loadUi();chooseStoppedSite(ui,status);
    const pre=ui.statusClick('#ach-status-stopped-recheck');
    const state=status==='0'?'Applied':'Armed';
    pre.respond(stoppedAck(pre,state,{
      site_status:status,runtime_verified:status==='0',
      recovery_id:'f'.repeat(32)
    }));
    ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
    const req=ui.statusClick('#ach-status-stopped-restore');
    req.respond(stoppedAck(req,'Restored',{
      read_only:false,changed:true,runtime_verified:true,
      site_status:status,recovery_id:'f'.repeat(32)
    }));
    const shown=ui.state().stoppedResult;
    assert.match(shown,/Previous stopped HTML SHA-256 \(not active\)/);
    assert.doesNotMatch(shown,/Observed HTTP 503 HTML SHA-256/);
    if (status==='0') assert.match(shown,/Native stopped-page HTTP 200 observed after Restore/);
    else assert.match(shown,/No claim about old Nginx workers or stopped delivery/);
  }
});

test('Stopped Needs Review with drifted VHost permits explicit guarded Restore', () => {
  const ui=loadUi();chooseStoppedSite(ui,'0');
  const inspection=ui.statusClick('#ach-status-stopped-recheck');
  inspection.respond(stoppedAck(inspection,'Needs Review',{
    site_status:'0',runtime_verified:false,proof_kind:'none',
    vhost_sha256:'e'.repeat(64),recovery_id:'f'.repeat(32)
  }));
  const shown=ui.state().stoppedResult;
  assert.match(shown,/Needs Review/);
  assert.match(shown,/Native VHost or stopped-route proof requires review/);
  assert.match(shown,/Saved recovery remains available after explicit approval/);
  assert.match(shown,/Recovery ID: f{32}/);
  assert.doesNotMatch(shown,/Observed HTTP 503 HTML SHA-256/);
  assert.doesNotMatch(shown,/unavailable or incompatible/);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
  ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
  assert.equal(ui.state().stoppedRestoreDisabled,false);
  const restore=ui.statusClick('#ach-status-stopped-restore');
  assert.equal(restore.options.data.expected_recovery_id,'f'.repeat(32));
  assert.equal(restore.options.data.expected_vhost_sha256,'e'.repeat(64));
  assert.equal(restore.options.data.stopped_approval,
    'restore_exact_native_stopped503_reload');
  restore.respond(stoppedAck(restore,'Restored',{
    site_status:'0',read_only:false,changed:true,runtime_verified:true,
    recovery_id:'f'.repeat(32),proof_kind:'native_http200'
  }));
  assert.match(ui.state().stoppedResult,/Native stopped-page HTTP 200 observed after Restore/);
  assert.doesNotMatch(ui.state().stoppedResult,/Observed HTTP 503 HTML SHA-256/);
  assert.equal(ui.state().stoppedRestoreDisabled,true);
});

test('Stopped forged Applied proof cannot authorize Restore', () => {
  for (const proof of [
    {runtime_verified:false,proof_kind:'none'},
    {runtime_verified:true,proof_kind:'source_only'}
  ]) {
    const ui=loadUi();chooseStoppedSite(ui,'0');
    const req=ui.statusClick('#ach-status-stopped-recheck');
    req.respond(stoppedAck(req,'Applied',{
      site_status:'0',recovery_id:'f'.repeat(32),...proof
    }));
    assert.match(ui.state().stoppedResult,/unavailable or incompatible/);
    assert.equal(ui.state().stoppedRestoreDisabled,true);
    ui.statusSetChecked('#ach-status-stopped-restore-approve',true);
    assert.equal(ui.state().stoppedRestoreDisabled,true);
    assert.doesNotMatch(ui.state().stoppedResult,/Observed HTTP 503 HTML SHA-256/);
  }
});

test('Stopped-site forged proof kind cannot be rendered as verified HTTP 503', () => {
  const ui=loadUi();chooseStoppedSite(ui);
  const req=ui.statusClick('#ach-status-stopped-recheck');
  req.respond(stoppedAck(req,'Source Ready',{proof_kind:'stopped_http503',runtime_verified:true}));
  assert.match(ui.state().stoppedResult,/incompatible/);
  assert.doesNotMatch(ui.state().stoppedResult,/Observed HTTP 503 HTML SHA-256/);
  assert.equal(ui.state().stoppedApplyDisabled,true);
});

test('Stopped-site selection/branding changes invalidate prior Apply proof', () => {
  const ui=loadUi();chooseStoppedSite(ui);
  const ready=ui.statusClick('#ach-status-stopped-recheck');
  ready.respond(stoppedAck(ready));
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  assert.equal(ui.state().stoppedApplyDisabled,false);
  ui.statusSetValue('#ach-status-name','New brand','input change');
  assert.equal(ui.state().stoppedApplyDisabled,true);
  ui.statusSetChecked('#ach-status-stopped-apply-approve',true);
  assert.equal(ui.state().stoppedApplyDisabled,true);
  assert.match(ui.state().stoppedResult,/Recheck/);
});


test('Status workflow shows only compatible operations and preserves recovery entry', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  const expectMode=(visible,name) => {
    const modes=ui.state().statusWorkflowVisible;
    for (const [mode,isVisible] of Object.entries(modes))
      assert.equal(isVisible,visible.includes(mode),name+': '+mode);
  };
  expectMode(['defaults'],'global 404');
  ui.statusSetValue('#ach-status-template','new-site','change');
  expectMode(['defaults'],'global new-site');
  ui.statusSetValue('#ach-status-template','unbound','change');
  expectMode(['unbound'],'global unbound');
  assert.equal(ui.state().unboundRecheckDisabled,false);
  ui.statusSetValue('#ach-status-template','50x','change');
  expectMode(['previewOnly'],'unsupported global 50x');
  assert.equal(ui.state().unboundRecheckDisabled,true);

  ui.statusSetValue('#ach-status-scope','site','change');
  expectMode(['preflight','manage'],'site 50x');
  assert.equal(ui.state().statusManageRecheckDisabled,true,
    'Selection is not a valid site until the new inventory and brand load');
  loadNativeStatusSiteSelection(ui);
  ui.requests.at(-1).respond(statusPrefs());
  assert.equal(ui.state().statusManageRecheckDisabled,false,
    'Site 50x retains the guarded extension Recheck');
  ui.statusSetValue('#ach-status-delivery','file','change');
  expectMode(['preflight','manage'],'50x file delivery still shows guarded site context');
  assert.equal(ui.state().statusManageRecheckDisabled,true,
    '50x file mode is explicitly unsupported and never grants Recheck/Apply');
  ui.statusSetValue('#ach-status-delivery','extension','change');
  assert.equal(ui.state().statusManageRecheckDisabled,false,
    'Verified extension mode remains selectable without a new server action');
  ui.statusSetValue('#ach-status-template','404','change');
  expectMode(['audit','preflight','manage'],'site 404');
  ui.statusSetValue('#ach-status-template','502','change');
  expectMode(['audit','preflight','manage'],'site 502');
  ui.statusSetValue('#ach-status-template','stopped','change');
  expectMode(['stopped'],'site stopped');
  assert.equal(ui.state().stoppedRecheckDisabled,false);
  ui.statusSetValue('#ach-status-template','403','change');
  expectMode(['previewOnly'],'site 403');
  assert.equal(ui.state().stoppedRecheckDisabled,true);
  ui.statusSetValue('#ach-status-template','stopped','change');
  expectMode(['stopped'],'reselect stopped recovery');
  assert.equal(ui.state().stoppedRestoreDisabled,true,
    'Template changes revoke stale Restore evidence');
  assert.equal(ui.state().stoppedRecheckDisabled,false,
    'The current stopped-site Recovery Recheck is available');
});

test('Status contextual workflow preserves dirty branding after cancelled scope switch', () => {
  const ui=loadUi();
  ui.openStatus().respond(statusPrefs());
  ui.statusSetValue('#ach-status-template','unbound','change');
  assert.equal(ui.state().statusWorkflowVisible.unbound,true);
  ui.statusSetValue('#ach-status-name','Unsaved unique','input change');
  ui.statusSetValue('#ach-status-scope','site','change');
  assert.deepEqual(ui.statusSelection(),{scope:'global',site:''});
  assert.equal(ui.state().statusName,'Unsaved unique');
  assert.equal(ui.state().statusWorkflowVisible.unbound,true);
  assert.equal(ui.state().statusWorkflowVisible.stopped,false);
  assert.equal(ui.state().statusSaveDisabled,false);
});


test('Shipped Status HTML places contextual preview near Preview and hides unused modes at startup', () => {
  const previewButton=html.indexOf('id="ach-status-preview-button"');
  const previewSurface=html.indexOf('id="ach-status-preview-surface"');
  const defaultSection=html.indexOf('id="ach-status-default-section"');
  const audit=html.indexOf('id="ach-status-site-audit"');
  assert.ok(previewButton>0 && previewSurface>previewButton);
  assert.ok(defaultSection>previewSurface && audit>previewSurface,
    'Sandbox preview must be near its control, before site/global management');
  assert.match(html, /id="ach-status-preview-surface"[^>]*hidden>/);
  for (const name of ['site-audit','site-preflight','manage-section','unbound-section','stopped-section']) {
    const selector='id="ach-status-'+name+'"';
    assert.equal(html.split(selector).length,2,'Unique scope-specific section '+name);
    assert.match(html.slice(html.indexOf(selector),html.indexOf(selector)+170),/hidden>/,
      'Unselected or site-only operations must be hidden before JS initialization');
  }
  const auditStart=html.indexOf('id="ach-status-site-audit"');
  const probeSection=html.indexOf('id="ach-status-site-preflight"');
  const probeButton=html.indexOf('id="ach-status-probe-button"');
  const managedSection=html.indexOf('id="ach-status-manage-section"');
  assert.ok(auditStart<probeSection && probeSection<probeButton && probeButton<managedSection,
    'Source probe must be in a separate sibling panel, not inside 404/502-only audit');
  assert.match(html.slice(probeSection,managedSection),/Nginx-generated 50x check source only/);
  assert.equal(html.split('id="ach-status-iframe"').length,2,'Exactly one sandbox iframe');
  assert.equal(html.split('id="ach-status-comparison-excerpt"').length,2,
    'Existing source comparison must remain available for site 404/502');
});

test('Selected 50x shows source-only preflight and still gates fresh Apply independently of managed Recheck', () => {
  const ui=statusProbeUi();
  ui.statusSetValue('#ach-status-template','50x','change');
  assert.equal(ui.state().statusWorkflowVisible.preflight,true);
  assert.equal(ui.state().statusWorkflowVisible.audit,false);
  assert.equal(ui.state().statusProbeDisabled,false);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  const request=ui.statusClick('#ach-status-probe-button');
  assert.match(ui.state().statusProbe,/Nginx-generated 50x source only/);
  assert.equal(request.options.data.template,'50x');
  assert.equal(request.options.data.site_delivery,'extension');
  const source=statusProbe({
    template:'50x',state:'Source Ready',scope:'native_vhost_source_only',
    page_file_sha256:managed404Original,body_sha256:null,http_status:null,body_bytes:null,
    http_404_observed:false,body_matches_file:false,body_matches_render:false,
    adoption_preview:{
      schema:1,state:'Source Ready',route_source_state:'Native VHost',
      current_sha256:managed404Original,proposed_sha256:managed404Render,
      vhost_sha256:managed404Vhost,
      requires_adoption:false,requires_backup:false,
      ownership_verified:false,recovery_verified:false,apply_supported:false,
      reason:'Exact 50x extension and reload approval required'
    }
  });
  request.respond(source);
  assert.match(ui.state().statusProbe,/HTTP status: Unavailable/);
  assert.equal(ui.state().statusManageApplyDisabled,true);
  ui.statusSetChecked('#ach-status-manage-apply-approve',true);
  assert.equal(ui.state().statusManageApplyDisabled,false);
  ui.statusSetValue('#ach-status-delivery','file','change');
  assert.equal(ui.state().statusManageApplyDisabled,true);
  assert.equal(ui.state().statusProbeDisabled,true);
});
