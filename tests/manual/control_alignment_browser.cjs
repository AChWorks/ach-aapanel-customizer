// Manual geometry regression for mixed label/select/button rows in the actual
// shipped aaPanel plugin markup. No backend requests or credentials.
// Run with provisioned Playwright and Chromium on AI Dev Server (choose
// a TMPDIR with free space; the system /tmp may be full):
// mkdir -p "$HOME/.cache/aac-browser-temp"
// TMPDIR="$HOME/.cache/aac-browser-temp" \
// NODE_PATH=/opt/ai-server-agent/browser/node_modules \
// CHROMIUM_EXECUTABLE=/opt/ai-server-agent/browser/browsers/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell \
// /opt/ai-server-agent/browser/node/bin/node tests/manual/control_alignment_browser.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.join(__dirname,'../../plugin/ach_customizer/index.html'),'utf8');
const html = source.replace(/<script(?:\s[^>]*)?>[\s\S]*?<\/script>/i,'');
const document = '<div style="width:min(980px,calc(100vw - 32px));margin:16px auto">' + html + '</div>';

(async () => {
  const browser = await chromium.launch({
    headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args:['--no-sandbox','--disable-dev-shm-usage']
  });
  let compared = 0;
  const samples = [];
  const observed = new Set();
  try {
    for (const width of [1280,1024,800,720,480,375,320]) {
      const page=await browser.newPage({viewport:{width,height:850}});
      await page.setContent(document,{waitUntil:'domcontentloaded'});
      for(const view of ['overview','websites','routing','cache','php','status','activity']) {
        await page.evaluate((name)=>{
          document.querySelectorAll('.ach-view').forEach(el=>el.hidden=el.dataset.view!==name);
          document.getElementById('ach-website-context').hidden =
            !['websites','routing','cache'].includes(name);
          document.querySelectorAll('.ach-view:not([hidden]) details').forEach(el=>el.open=true);
        },view);
        const geometry=await page.evaluate(()=>{
          const rows=[];
          const visible=el=>{const r=el.getBoundingClientRect();return r.height>0&&r.width>0};
          for (const row of document.querySelectorAll('#ach-customizer .ach-controls')) {
            if (!visible(row)) continue;
            const fieldNodes=[...row.querySelectorAll(':scope > .ach-inline-field')].filter(visible);
            if (!fieldNodes.length)continue;
            const fields=fieldNodes.map(f=>({field:f,control:f.querySelector('select,input:not([type="checkbox"])')}))
              .filter(f=>f.control&&visible(f.control));
            const buttons=[...row.querySelectorAll(':scope > button')].filter(visible);
            const children=[...fields.map(f=>({name:f.control.id||f.control.tagName,
              outer:f.field.getBoundingClientRect(),rect:f.control.getBoundingClientRect(),type:'field'})),
              ...buttons.map(b=>({name:b.id||b.textContent.trim().slice(0,30),
              outer:b.getBoundingClientRect(),rect:b.getBoundingClientRect(),type:'button'}))];
            const pairs=[];
            for(let i=0;i<children.length;i++)for(let j=i+1;j<children.length;j++){
              const a=children[i],b=children[j];
              if(a.type==='button'&&b.type==='button')continue;
              // Compare only controls whose flex items occupy the same visual flex row.
              if(Math.min(a.outer.bottom,b.outer.bottom)<=Math.max(a.outer.top,b.outer.top)+1)continue;
              pairs.push({a:a.name,b:b.name,delta:Math.abs(a.rect.bottom-b.rect.bottom)});
            }
            if(pairs.length) rows.push({ids:children.map(x=>x.name),pairs});
          }
          const main=document.getElementById('ach-content');
          return {rows,overflow:main.scrollWidth>main.clientWidth+1,
            documentOverflow:document.documentElement.scrollWidth>innerWidth+1};
        });
        assert.equal(geometry.overflow,false,'Main overflow '+width+'/'+view);
        assert.equal(geometry.documentOverflow,false,'Document overflow '+width+'/'+view);
        for(const row of geometry.rows) {
          if(width===1024 && view==='routing') {
            if(row.ids.includes('ach-hosts-alias-select') &&
               row.ids.includes('ach-hosts-alias-refresh')) observed.add('hosts');
            if(row.ids.includes('ach-scan-orphan-choice') &&
               row.ids.includes('ach-scan-orphan-list')) observed.add('scanner-recovery');
            if(row.ids.includes('ach-scan-maxretry') &&
               row.ids.includes('ach-scan-bantime')) observed.add('scanner-fields');
          }
          for(const pair of row.pairs){
            compared++;
            if(pair.delta>1.5) samples.push({width,view,ids:row.ids,pair});
          }
        }
      }
      await page.close();
    }
    // Expand the label on one field in each multi-field row to expose
    // accidental top-aligned inputs masked by short English labels.
    const page=await browser.newPage({viewport:{width:980,height:850}});
    await page.setContent(document,{waitUntil:'domcontentloaded'});
    await page.evaluate(()=>{
      const row=document.getElementById('ach-scan-maxretry').closest('.ach-controls');
      row.querySelector('.ach-inline-field > label').textContent =
        'Attempts per selected native website (additional explanatory words)';
      document.querySelectorAll('.ach-view').forEach(el=>el.hidden=el.dataset.view!=='routing');
      document.querySelectorAll('#ach-panel-routing details').forEach(el=>el.open=true);
    });
    const longLabel=await page.evaluate(()=>{
      const row=document.getElementById('ach-scan-maxretry').closest('.ach-controls');
      return [...row.querySelectorAll('.ach-inline-field input')].map(x=>({id:x.id,bottom:x.getBoundingClientRect().bottom}));
    });
    const drift=Math.max(...longLabel.map(x=>x.bottom))-Math.min(...longLabel.map(x=>x.bottom));
    if(drift>1.5)samples.push({width:980,view:'routing',case:'wrapped label',drift,longLabel});
    await page.close();
    assert.deepEqual([...observed].sort(),
      ['hosts','scanner-fields','scanner-recovery'],
      'The reported forms and a multi-field control row must be exercised');
    assert.ok(compared>=30,'Expected control comparisons across the seven viewports');
    assert.deepEqual(samples,[],'Mixed controls must align by their actual input/button bottoms');
    process.stdout.write(JSON.stringify({result:'PASS',compared,viewports:7,views:7,
      verified:[...observed].sort(),wrappedLabel:true})+'\n');
  } finally {await browser.close();}
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
