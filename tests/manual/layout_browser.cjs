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
    console.log('LAYOUT_PASS '+output.length+' section/viewport combinations');
    for(const entry of output) console.log(JSON.stringify(entry));
  } finally {
    await browser.close();
  }
})().catch(err=>{console.error('LAYOUT_FAIL',err.stack);process.exitCode=1});
