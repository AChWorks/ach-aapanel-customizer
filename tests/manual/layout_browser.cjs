// Optional manual Chromium geometry check. No aaPanel backend or credentials.
// Example on AI Server Agent Dev:
// NODE_PATH=/opt/ai-server-agent/browser/node_modules \
// CHROMIUM_EXECUTABLE=/opt/ai-server-agent/browser/browsers/chromium-1228/chrome-linux64/chrome \
// node tests/manual/layout_browser.cjs
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const filename = path.join(__dirname, '../../plugin/ach_customizer/index.html');
  // Layout-only: remove inline behavior; JS interactive contract has separate tests.
  const html = fs.readFileSync(filename,'utf8').replace(/<script>[\s\S]*?<\/script>/i,'');
  const browser = await chromium.launch({
    headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE || chromium.executablePath(),
    args:['--no-sandbox','--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  const output = [];
  try {
    for(const [width,height] of [[1280,720],[1366,768],[1920,1080],[720,650],[375,650]]) {
      await page.setViewportSize({width,height});
      await page.setContent(html, {waitUntil:'domcontentloaded'});
      for(const name of ['overview','websites','status','php','activity']) {
        await page.evaluate((name)=>{
          document.querySelectorAll('[data-view]').forEach(v=>v.hidden=v.getAttribute('data-view')!==name);
        },name);
        const x = await page.evaluate(()=>{
          const root=document.querySelector('#ach-customizer'), main=document.querySelector('#ach-content'),
            nav=document.querySelector('.ach-sidebar'), body=document.body;
          const rb=root.getBoundingClientRect(), mb=main.getBoundingClientRect(), nb=nav.getBoundingClientRect();
          main.scrollTop=main.scrollHeight;
          return {viewport:[innerWidth,innerHeight],documentOverflow:document.documentElement.scrollWidth>innerWidth,
            rootVisible:rb.width>100 && rb.height>150,
            rootBottom:Math.round(rb.bottom),rootRight:Math.round(rb.right),
            mainHeight:Math.round(mb.height),mainScrolled:main.scrollTop>2,
            contentOverflowMode:getComputedStyle(main).overflowY,
            navVisible:nb.width>30 && nb.height>25,
            contentWithinViewport:mb.right<=innerWidth+1,
            contentBottom:Math.round(mb.bottom),
            controlsHiddenBehindBody:body.scrollHeight>innerHeight+1};
        });
        // The desktop active row must merge with the white content surface
        // without a visible right-side stroke; narrow layouts instead use
        // the existing horizontal bottom-border navigation treatment.
        if (name === 'overview') {
          const continuity = await page.evaluate(() => {
            const side = document.querySelector('.ach-sidebar');
            const active = side.querySelector('button[aria-selected="true"]');
            const main = document.querySelector('.ach-main');
            const root = document.querySelector('#ach-customizer');
            const note = document.querySelector('.ach-note');
            return {
              sideBorder: getComputedStyle(side).borderRightWidth,
              selectedFill: getComputedStyle(active).backgroundColor,
              contentFill: getComputedStyle(main).backgroundColor,
              corner: getComputedStyle(root).borderBottomLeftRadius,
              noteCorner: getComputedStyle(note).borderTopLeftRadius,
              sideDirection: getComputedStyle(side).flexDirection,
            };
          });
          if (continuity.corner !== '10px' || continuity.noteCorner !== '8px' ||
              (width > 720 && (continuity.sideBorder !== '0px' ||
                continuity.selectedFill !== continuity.contentFill))) {
            throw Error('Native dialog active-row continuity/corners failed ' +
              JSON.stringify({width,height,...continuity}));
          }
        }
        // Verify reusable control geometry in the actual rendered plugin DOM.
        // This detects aaPanel-style drift even if the parent layer still fits.
        const controls=await page.evaluate(()=>{
          const main=document.getElementById('ach-content');
          const edge=main.getBoundingClientRect();
          const found=[...main.querySelectorAll('button,input:not([type="checkbox"]),select')]
            .filter(el=>el.getClientRects().length>0 && !el.closest('[hidden]'));
          const failures=found.filter(el=>{
            const r=el.getBoundingClientRect();
            const css=getComputedStyle(el);
            return r.height<31 || r.height>96 || r.width<15 ||
              r.left<edge.left-1 || r.right>edge.right+1 ||
              css.borderRadius!==(el.tagName==='BUTTON' ? '6px' : '10px');
          }).map(el=>el.id||el.tagName);
          return {visible:found.length,failures};
        });
        if(controls.failures.length) {
          throw Error('Inconsistent native control sizing '+JSON.stringify({width,height,name,...controls}));
        }
        output.push({section:name,...x});
        if(x.documentOverflow || !x.rootVisible || !x.navVisible || !x.contentWithinViewport ||
          x.contentOverflowMode!=='auto') {
          throw Error('Layout invariant failed '+JSON.stringify({width,height,name,...x}));
        }
        if(name==='status' && !x.mainScrolled) throw Error('Long status page could not scroll');
        if(name==='php') {
          const picker=await page.evaluate(()=>{
            const input=document.querySelector('#ach-php-version'),
              refresh=document.querySelector('#ach-php-discover'),
              status=document.querySelector('#ach-php-discovery-status'),
              viewport=document.documentElement.clientWidth;
            return {tag:input?.tagName, disabled:input?.disabled,
              required:input?.required, refreshText:refresh?.textContent?.trim(),
              status:status?.getAttribute('role'),
              right:input?.getBoundingClientRect().right, viewport};
          });
          if(picker.tag!=='SELECT' || picker.disabled!==true || picker.required!==true ||
              !picker.refreshText?.includes('Refresh installed PHP') ||
              picker.status!=='status' || picker.right>picker.viewport+1) {
            throw Error('Native PHP version picker unsafe or inaccessible '+JSON.stringify(picker));
          }
        }
        if(name==='status') {
          // Save/Reset acknowledgement must be visible beside the Save action,
          // not under the 440px preview/diagnostics on a long scroll surface.
          const feedback=await page.evaluate(()=>{
            const button=document.getElementById('ach-status-save');
            const notice=document.getElementById('ach-status-result');
            const main=document.getElementById('ach-content');
            button.scrollIntoView({block:'center',inline:'nearest'});
            const a=button.getBoundingClientRect(), b=notice.getBoundingClientRect(),
              m=main.getBoundingClientRect();
            return {gap:Math.round(b.top-a.bottom),withinViewport:b.top>=m.top && b.bottom<=m.bottom+1,
              withinMain:b.left>=m.left-1 && b.right<=m.right+1,
              inSamePanel:notice.closest('.ach-view')===button.closest('.ach-view'),
              live:notice.getAttribute('aria-live')};
          });
          if(feedback.gap<0 || feedback.gap>70 || !feedback.withinViewport ||
             !feedback.withinMain || !feedback.inSamePanel || feedback.live!=='polite') {
            throw Error('Save acknowledgement hidden or detached from action '+JSON.stringify({width,height,feedback}));
          }
        }
        if(name==='websites') {
          // Inspect the shipped DOM, not a reconstructed control: discovery
          // is a select that remains disabled until native inventory arrives.
          const sitePicker = await page.evaluate(()=>{
            const picker=document.getElementById('ach-hosts-site-id');
            const label=document.querySelector('label[for="ach-hosts-site-id"]');
            const action=document.getElementById('ach-hosts-inspect-button');
            return {tag:picker?.tagName, disabled:picker?.disabled,
              label:label?.textContent?.trim(), actionDisabled:action?.disabled,
              right:picker?.getBoundingClientRect().right};
          });
          if(sitePicker.tag!=='SELECT' || sitePicker.disabled!==true ||
             sitePicker.actionDisabled!==true ||
             !sitePicker.label?.includes('Website') ||
             sitePicker.right>width+1) {
            throw Error('Native inventory-backed Hosts picker missing/unsafe '+
              JSON.stringify({width,height,...sitePicker}));
          }
        }
        if(name==='php' || name==='status') {
          const rows = await page.evaluate(name => {
            const section = name==='php' ? '#ach-php-form .ach-fields' :
              '#ach-panel-status .ach-status-fields';
            const row = document.querySelector(section + ' > div');
            const label = row?.querySelector('label');
            const input = row?.querySelector('input, select');
            const rect = x => x?.getBoundingClientRect().toJSON();
            return {label:rect(label),input:rect(input)};
          },name);
          if(!rows.label || !rows.input) throw Error('Native form row missing '+name);
          if(width>=900 && (
            rows.input.left<rows.label.right+5 ||
            Math.abs(rows.input.width-150)>2 ||
            Math.abs(rows.input.height-32)>2
          )) throw Error('Desktop label / 150px native control rhythm failed '+
              JSON.stringify({name,width,rows}));
          if(width<=460 && rows.input.top<rows.label.bottom) {
            throw Error('Mobile stacked label/control overlap '+JSON.stringify({name,width,rows}));
          }
        }
      }
    }
    // Inspect the real shipped, sandbox-free DOM with an explicitly TEXT-only
    // display of untrusted existing-site HTML. No backend/auth/native QA claim.
    for(const [width,height] of [[1280,720],[375,650]]) {
      await page.setViewportSize({width,height});
      await page.setContent(html, {waitUntil:'domcontentloaded'});
      const check=await page.evaluate(() => {
        document.querySelectorAll('[data-view]').forEach(view=>{
          view.hidden=view.getAttribute('data-view')!=='status';
        });
        const pre=document.getElementById('ach-status-comparison-excerpt');
        const summary=document.getElementById('ach-status-comparison-summary');
        const hostile='<img src=x onerror=alert(1)>';
        summary.textContent='Different - display-only source comparison; no Apply';
        pre.textContent='--- current 404.html\\n+++ proposed 404.html\\n' +
          Array.from({length:90},(_,i)=>'-'+i+' '+hostile+'\\n+'+i+' <p>Reviewed</p>').join('\\n');
        const rect=pre.getBoundingClientRect();
        const css=getComputedStyle(pre);
        return {right:rect.right,height:rect.height,maxHeight:css.maxHeight,
          overflowY:css.overflowY,scrollHeight:pre.scrollHeight,
          clientHeight:pre.clientHeight,containsLiteral:pre.textContent.includes(hostile),
          unexpectedImages:document.querySelectorAll('img[src="x"]').length,
          documentOverflow:document.documentElement.scrollWidth>innerWidth,
          statusVisible:summary.getBoundingClientRect().height>0};
      });
      if(check.documentOverflow || check.unexpectedImages || !check.containsLiteral ||
         !check.statusVisible || check.right>width+1 || check.overflowY!=='auto' ||
         check.scrollHeight<=check.clientHeight || check.height>260+1) {
        throw Error('Unsafe or unscrollable Status Pages diff at 100% zoom '+
          JSON.stringify({width,height,...check}));
      }
    }
    console.log('STATUS_COMPARE_VIEWPORT_PASS 2 responsive scroll/plain-text checks');
    // Verify actual table skeleton layout and reduced-motion support.
    await page.setViewportSize({width:375,height:650});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.setContent(html, {waitUntil:'domcontentloaded'});
    const skeletons = await page.evaluate(() => {
      return ['sites','activity'].map(name => {
        document.querySelectorAll('[data-view]').forEach(view => {
          view.hidden=view.getAttribute('data-view')!==(name==='sites'?'websites':'activity');
        });
        const loading=document.querySelector('#ach-'+name+'-loading');
        const rows=document.querySelector('#ach-'+name+'-rows');
        loading.hidden=false;rows.hidden=true;
        const r=loading.getBoundingClientRect();
        const bar=loading.querySelector('.ach-skeleton-row span');
        return {name,height:r.height,right:r.right,display:getComputedStyle(loading).display,
          animation:getComputedStyle(bar).animationName,rowsHidden:getComputedStyle(rows).display==='none'};
      });
    });
    for(const s of skeletons) {
      if(s.height<150 || s.right>375 || s.display==='none' ||
          s.animation!=='none' || !s.rowsHidden) {
        throw Error('Skeleton layout/reduced motion failure '+JSON.stringify(s));
      }
    }
    console.log('NATIVE_SKELETON_PASS '+skeletons.length+' mobile reduced-motion checks');
    await page.emulateMedia({reducedMotion:'no-preference'});
    // Inspect computed primary button colors in Chromium, including real hover.
    // This complements source token calculations; white-on-green text is 13px.
    await page.setViewportSize({width:1280,height:720});
    await page.setContent(html, {waitUntil:'domcontentloaded'});
    await page.evaluate(() => {
      document.querySelectorAll('[data-view]').forEach(view => {
        view.hidden = view.getAttribute('data-view') !== 'php';
      });
    });
    const primary = page.locator('#ach-php-form button.btn-success');
    const getPrimary = () => primary.evaluate(element => {
      const css = getComputedStyle(element);
      return {background:css.backgroundColor, foreground:css.color, disabled:element.disabled};
    });
    const normal = await getPrimary();
    await primary.hover();
    await page.waitForTimeout(220);
    const hover = await getPrimary();
    function luminance(value) {
      const channels = value.match(/[0-9]+/g)?.slice(0,3).map(Number);
      if (!channels || channels.length !== 3) throw Error('Invalid computed color ' + value);
      const [r,g,b] = channels.map(v => {
        const c = v / 255;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      });
      return 0.2126*r + 0.7152*g + 0.0722*b;
    }
    function contrast(a,b) {
      const x = luminance(a), y = luminance(b);
      return (Math.max(x,y) + .05) / (Math.min(x,y) + .05);
    }
    for (const [state,colors] of [['normal',normal],['hover',hover]]) {
      const ratio = contrast(colors.background,colors.foreground);
      if (colors.disabled || ratio < 4.5) {
        throw Error('Primary action contrast below AA ' + JSON.stringify({state,colors,ratio}));
      }
    }
    console.log('PRIMARY_CONTRAST_PASS '+JSON.stringify({
      normal:contrast(normal.background,normal.foreground).toFixed(3),
      hover:contrast(hover.background,hover.foreground).toFixed(3),
      normalFill:normal.background,hoverFill:hover.background
    }));
    // Exercise the shipped resize helper inside a simulated aaPanel layer.
    // This is NOT an authenticated aaPanel guest/browser acceptance test.
    const complete = fs.readFileSync(filename, 'utf8');
    const helperMatch = complete.match(/  function fitNativeLayer\(\) \{[\s\S]*?\n  \}\n  if \(typeof window/);
    if (!helperMatch) throw Error('Deployed native layer helper not found');
    const helper = helperMatch[0].replace(/\n  if \(typeof window$/, '');
    let layerCount = 0;
    for (const [width,height] of [[320,480],[375,650],[720,650],[1280,720],[1920,1080]]) {
      await page.setViewportSize({width,height});
      await page.setContent(
        '<div class="layui-layer" style="position:absolute;left:0;top:0;width:100px;height:100px;background:#fff">' +
        '<div class="layui-layer-title" style="height:42px">Plugin</div>' +
        '<div class="layui-layer-content">' + html + '</div></div>',
        {waitUntil:'domcontentloaded'});
      await page.addScriptTag({content:"(function(){ const root={0:document.getElementById('ach-customizer')}; " + helper + "\nfitNativeLayer(); })();"});
      const info = await page.evaluate(()=>{
        const layer=document.querySelector('.layui-layer');
        const main=document.getElementById('ach-content');
        const rect=layer.getBoundingClientRect();
        const m=main.getBoundingClientRect();
        return {right:rect.right,left:rect.left,top:rect.top,bottom:rect.bottom,
          mainHeight:m.height,rootHeight:document.getElementById('ach-customizer').getBoundingClientRect().height,
          mainOverflow:getComputedStyle(main).overflowY,
          direction:document.querySelector('.ach-sidebar').getAttribute('aria-orientation')};
      });
      if (info.left < 0 || info.top < 0 || info.right > width+1 || info.bottom > height+1 ||
          info.mainHeight < 120 || info.mainOverflow !== 'auto' ||
          info.direction !== (width <= 720 ? 'horizontal' : 'vertical')) {
        throw Error('Simulated native layer invariant failed '+
          JSON.stringify({width,height,...info}));
      }
      layerCount++;
    }
    // Reproduce aaPanel 8.0.7's actual fixed launcher: top:20% with a
    // 1100x672 area. The plugin's inline script may execute before aaPanel
    // attaches its wrapper; the shipped CSS must fit it without a resize.
    let launcherCount = 0;
    for (const [width,height] of [[1280,720],[900,700],[740,600],[390,844],[1280,500]]) {
      await page.setViewportSize({width,height});
      await page.setContent(
        '<div class="layui-layer" style="position:fixed;left:90px;top:20%;width:1100px;height:672px">' +
        '<div class="layui-layer-title" style="height:42px">ACh aaPanel Customizer</div>' +
        '<div class="layui-layer-content" style="height:630px;overflow:hidden">' + html +
        '</div></div>', {waitUntil:'domcontentloaded'});
      const actual = await page.evaluate(()=>{
        const layer=document.querySelector('.layui-layer');
        const content=layer.querySelector('.layui-layer-content');
        const main=document.querySelector('#ach-content');
        const bound=layer.getBoundingClientRect();
        const contentBound=content.getBoundingClientRect();
        return {left:bound.left,top:bound.top,right:bound.right,bottom:bound.bottom,
          contentBottom:contentBound.bottom,mainOverflow:getComputedStyle(main).overflowY,
          rootHeight:document.querySelector('#ach-customizer').getBoundingClientRect().height,
          cssSupported:CSS.supports('selector(.layui-layer:has(#ach-customizer))')};
      });
      if (!actual.cssSupported || actual.left<8 || actual.top<8 ||
          actual.right>width-8 || actual.bottom>height-8 ||
          actual.contentBottom>height-8 || actual.rootHeight<170 ||
          actual.mainOverflow!=='auto') {
        throw Error('Real aaPanel launcher overflow at 100% zoom '+
          JSON.stringify({width,height,...actual}));
      }
      launcherCount++;
    }
    console.log('NATIVE_LAUNCHER_LAYOUT_PASS '+launcherCount+' viewport checks');
    console.log('SIMULATED_LAYER_PASS '+layerCount+' viewport checks');
    console.log('LAYOUT_PASS '+output.length+' section/viewport combinations');
    for(const entry of output) console.log(JSON.stringify(entry));
  } finally {
    await browser.close();
  }
})().catch(err=>{console.error('LAYOUT_FAIL',err.stack);process.exitCode=1});
