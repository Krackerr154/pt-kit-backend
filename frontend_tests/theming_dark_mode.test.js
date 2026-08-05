const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
function extract(name){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,'missing '+name);return m[0];}

// 5.1 dark theme scope and bootstrap
assert(html.includes('[data-theme="dark"] { --ink:'),'dark scope overrides the core variables');
for(const v of ['--ink','--muted','--line','--surface','--surface-soft','--navy']){
    assert(new RegExp('\\[data-theme="dark"\\] \\{[^}]*'+v.replace('-','\\-')).test(html),'dark override for '+v);
}
for(const sel of ['body { background','input, [data-theme="dark"] select',' .modal { background','.chart-overlay','.mode-summary','.utilities-menu { box-shadow','table.cycle-table th']){
    assert(html.includes('[data-theme="dark"]'+sel)||html.includes('[data-theme="dark"] '+sel.trim()),'dark rule covers '+sel.trim());
}
const boot=html.match(/<script>\s*\(function\(\)\{try\{var t=localStorage[^]*?\}\)\(\);\s*<\/script>/);
assert(boot,'head bootstrap script exists');
assert(boot[0].includes("localStorage.getItem('ptkit-theme')"),'bootstrap reads stored preference');
assert(boot[0].includes("prefers-color-scheme: dark"),'bootstrap falls back to system preference');
assert(boot[0].includes("document.documentElement.setAttribute('data-theme',t)"),'bootstrap sets data-theme before paint');
assert(html.indexOf(boot[0])<html.indexOf('<style>'),'bootstrap runs before styles apply');
assert(/id="themeToggle"[^>]*aria-pressed="false"[^>]*aria-label="Toggle dark mode"[^>]*onclick="toggleTheme\(\)"/.test(html),'header carries an accessible theme toggle');

// theme functions behave: stored wins, system fallback, persistence on toggle
const storage={v:null};const els={};
const ctx={
    localStorage:{getItem:k=>storage.v,setItem:(k,v)=>{storage.v=v;}},
    window:{matchMedia:q=>({matches:q.includes('dark')})},
    document:{documentElement:{attrs:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]??null}},getElementById:id=>els[id]||(els[id]={setAttribute(){},attrs:{}})},
    Chart:undefined,Number
};
ctx.window.localStorage=ctx.localStorage;
vm.createContext(ctx);
vm.runInContext(extract('getStoredTheme')+'\n'+extract('resolveInitialTheme')+'\n'+extract('getChartThemeColors')+'\n'+extract('applyChartTheme')+'\n'+extract('applyTheme')+'\n'+extract('toggleTheme'),ctx);
assert.strictEqual(ctx.resolveInitialTheme(),'dark','system dark used when nothing stored');
storage.v='light';
assert.strictEqual(ctx.resolveInitialTheme(),'light','stored preference wins over system');
storage.v=null;
ctx.applyTheme('dark',true);
assert.strictEqual(storage.v,'dark','explicit toggle persists');
assert.strictEqual(ctx.document.documentElement.attrs['data-theme'],'dark','data-theme applied');
ctx.applyTheme('light',false);
assert.strictEqual(storage.v,'dark','init sync does not overwrite storage');
ctx.toggleTheme();
assert.strictEqual(ctx.document.documentElement.attrs['data-theme'],'dark','toggle flips theme');

// 5.2 chart theming
const light=ctx.getChartThemeColors('light'),dark=ctx.getChartThemeColors('dark');
for(const k of ['text','grid','lux','luxTarget']){assert(light[k]&&dark[k],'chart theme key '+k);}
assert.notStrictEqual(light.grid,dark.grid,'grid contrast differs per theme');
assert.notStrictEqual(light.text,dark.text,'axis text differs per theme');
assert(extract('applyChartTheme').includes("typeof Chart==='undefined'"),'chart theming guards missing Chart.js');
assert(extract('initChart').includes('applyChartTheme(currentTheme)'),'charts pick up the theme at creation');
console.log('Theming & dark mode: PASS');
