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
      for(const name of ['overview','status','php','activity']) {
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
    console.log('SIMULATED_LAYER_PASS '+layerCount+' viewport checks');
    console.log('LAYOUT_PASS '+output.length+' section/viewport combinations');
    for(const entry of output) console.log(JSON.stringify(entry));
  } finally {
    await browser.close();
  }
})().catch(err=>{console.error('LAYOUT_FAIL',err.stack);process.exitCode=1});
