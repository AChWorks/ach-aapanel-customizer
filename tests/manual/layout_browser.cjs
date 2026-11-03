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
      }
    }
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
