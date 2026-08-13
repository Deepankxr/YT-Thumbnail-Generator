"""Self-contained browser UI for editing thumbnails, served at GET /preview.

Three columns: controls on the left, canvas in the middle, AI chat on the right.

Direct manipulation on the canvas — click to select, drag to move, corner to
resize, double-click the headline to type. The server stays the only renderer:
it returns a geometry manifest alongside the PNG and this page draws handles
from it, so the studio can never drift from what n8n renders.

The chat panel talks to /edit with the viewer's own OpenRouter key. Every turn
keeps its result, so a bad edit is one click to undo rather than a re-render
from scratch.

No CDN, no build step — one string, so it works on a locked-down box.
"""

PREVIEW_HTML = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Thumbnail Studio</title>
<style>
 :root{--bg:#111214;--panel:#1a1c1f;--line:#2a2d31;--fg:#e8eaed;--muted:#9aa0a6;
       --accent:#4c8dff;--sel:#4c8dff}
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      background:var(--bg);color:var(--fg);display:flex;height:100vh;overflow:hidden}
 .col{overflow-y:auto;flex:none}
 #panel{width:340px;background:var(--panel);border-right:1px solid var(--line);padding:16px}
 #stage{flex:1;min-width:0;padding:22px;overflow-y:auto}
 #chat{width:340px;background:var(--panel);border-left:1px solid var(--line);
       padding:16px;display:flex;flex-direction:column}
 h1{font-size:15px;margin:0 0 3px}
 h2{font-size:13px;margin:0 0 3px}
 .sub{color:var(--muted);font-size:11.5px;margin-bottom:14px}
 label{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
       color:var(--muted);margin:13px 0 5px}
 input[type=text],input[type=password],select,textarea{width:100%;padding:7px 9px;background:#0d0e10;
       border:1px solid var(--line);border-radius:6px;color:var(--fg);font-size:12.5px;font-family:inherit}
 textarea{resize:vertical;min-height:46px}
 .row{display:flex;gap:7px}.row>*{flex:1}
 .chk{display:flex;align-items:center;gap:7px;margin-top:12px}
 .chk input{width:auto}.chk label{margin:0;text-transform:none;letter-spacing:0;font-size:12.5px;color:var(--fg)}
 button{width:100%;margin-top:12px;padding:9px;background:var(--accent);border:0;border-radius:6px;
        color:#fff;font-weight:600;font-size:12.5px;cursor:pointer}
 button.ghost{background:#26292e;margin-top:7px}
 button.tiny{width:auto;padding:4px 9px;font-size:10.5px;margin:0;font-weight:500}
 button:disabled{opacity:.5;cursor:default}
 hr{border:0;border-top:1px solid var(--line);margin:16px 0}

 #wrap{position:relative;width:100%;max-width:980px;user-select:none}
 #wrap img{display:block;width:100%;border-radius:8px;background:#000;
           box-shadow:0 8px 34px rgba(0,0,0,.5)}
 #proxy{position:absolute;inset:0;display:none;pointer-events:none;will-change:transform;
        border-radius:8px;background:none!important;box-shadow:none!important}
 #overlay{position:absolute;inset:0}
 .el{position:absolute;cursor:move;border:2px solid transparent;border-radius:3px}
 .el:hover{border-color:rgba(76,141,255,.55)}
 .el.sel{border-color:var(--sel)}
 .el .tag{position:absolute;top:-20px;left:-2px;background:var(--sel);color:#fff;
          font-size:10px;padding:1px 6px;border-radius:3px;white-space:nowrap;
          opacity:0;pointer-events:none}
 .el:hover .tag,.el.sel .tag{opacity:1}
 .h{position:absolute;width:11px;height:11px;background:#fff;border:2px solid var(--sel);
    border-radius:2px;display:none}
 .el.sel .h{display:block}
 .h.nw{left:-6px;top:-6px;cursor:nwse-resize}.h.ne{right:-6px;top:-6px;cursor:nesw-resize}
 .h.sw{left:-6px;bottom:-6px;cursor:nesw-resize}.h.se{right:-6px;bottom:-6px;cursor:nwse-resize}
 .dot{position:absolute;width:15px;height:15px;margin:-7px 0 0 -7px;background:#fff;
      border:2px solid var(--sel);border-radius:50%;cursor:grab}
 #editor{position:absolute;margin:0;padding:0;border:0;outline:2px solid var(--sel);
         background:rgba(0,0,0,.35);color:#fff;display:none;white-space:pre-wrap;
         line-height:.98;letter-spacing:-.02em;overflow:hidden;border-radius:2px}
 .cap{font-size:10.5px;color:var(--muted);margin:15px 0 6px;text-transform:uppercase;letter-spacing:.06em}
 #feed{width:168px;border-radius:4px;box-shadow:0 2px 10px rgba(0,0,0,.5);display:block}
 #qa{font-size:11.5px;color:var(--muted);margin-top:11px}
 .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-weight:700;font-size:10.5px}
 .ok{background:#13361f;color:#5ddc8a}.weak{background:#3d2412;color:#ffab52}
 .err{color:#ff8b6b;font-size:11.5px;white-space:pre-wrap;margin-top:7px}
 #selinfo{background:#15171a;border:1px solid var(--line);border-radius:6px;padding:9px;
          margin-top:9px;font-size:11.5px;color:var(--muted);display:none}
 #selinfo b{color:var(--fg)}
 #words{display:flex;flex-wrap:wrap;gap:5px}
 .word{width:auto;margin:0;background:#0d0e10;border:1px solid var(--line);border-radius:5px;
       padding:4px 8px;font-size:11.5px;font-weight:400;cursor:pointer;color:var(--fg)}
 .word:hover{border-color:#3d4247}
 .word.on{border-color:var(--accent);background:#16202f}
 .word .sw{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:6px;
           vertical-align:middle;border:1px solid rgba(255,255,255,.25)}
 .grp{font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:7px 0 4px}
 .sws{display:flex;gap:5px;flex-wrap:wrap}
 .sw-btn{width:24px;height:24px;border-radius:5px;border:1px solid rgba(255,255,255,.18);
         cursor:pointer;padding:0;margin:0;flex:0 0 auto}
 .sw-btn:hover{outline:2px solid var(--accent);outline-offset:1px}
 .lrow{display:flex;gap:6px;align-items:center;margin-top:6px}
 .lrow input[type=text]{flex:1}
 .lrow button{flex:0 0 auto}
 .hint{font-size:10.5px;color:var(--muted);margin-top:9px;line-height:1.55}
 kbd{background:#26292e;border-radius:3px;padding:1px 5px;font-size:9.5px;font-family:inherit}

 /* ---- chat ---- */
 #log{flex:1;overflow-y:auto;margin:12px 0;display:flex;flex-direction:column;gap:10px;min-height:120px}
 .msg{font-size:12px;border-radius:8px;padding:8px 10px;max-width:100%}
 .msg.me{background:#1d2a3f;align-self:flex-end}
 .msg.ai{background:#15171a;border:1px solid var(--line)}
 .msg img{width:100%;border-radius:5px;margin-top:7px;display:block;cursor:pointer}
 .msg .meta{color:var(--muted);font-size:10.5px;margin-top:5px}
 .msg.err{background:#2a1512;border:1px solid #4a2119;color:#ffb4a2}
 #chatempty{color:var(--muted);font-size:11.5px}
</style></head><body>

<div class="col" id="panel">
 <h1>Thumbnail Studio</h1>
 <div class="sub">Click anything on the canvas to move, resize, or retype it.</div>

 <label>Headline</label>
 <textarea id="headline">This changes everything.</textarea>

 <div class="row">
  <div><label>Style</label><select id="style"></select></div>
  <div><label>Palette</label><select id="palette"></select></div>
 </div>

 <label>Accent words</label>
 <input type="text" id="accent" placeholder="everything.">

 <label>Word colours</label>
 <div id="words"></div>
 <div id="swatches"></div>
 <div class="row" style="margin-top:7px">
   <input type="text" id="customhex" placeholder="#RRGGBB" maxlength="7">
   <button class="tiny ghost" id="clearcolor" style="flex:0 0 auto">Clear word</button>
 </div>

 <div class="row">
  <div><label>Text position</label><select id="textpos">
    <option value="">style default</option><option value="top">top</option><option value="bottom">bottom</option>
  </select></div>
  <div><label>Subject side</label><select id="side">
    <option value="">style default</option><option value="left">left</option><option value="right">right</option>
  </select></div>
 </div>
 <div class="chk"><input type="checkbox" id="arrow" checked><label for="arrow">Show arrow</label></div>

 <div id="selinfo"></div>
 <div id="hiddenchip" class="sub" style="display:none;margin-top:8px"></div>

 <hr>
 <h2>Labels</h2>
 <div class="sub" style="margin-bottom:0">Small callouts like &ldquo;opus&rdquo; / &ldquo;fable&rdquo;. Drag them on the canvas.</div>
 <div id="labels"></div>
 <button class="ghost tiny" id="addlabel" style="margin-top:9px">+ Add label</button>

 <hr>
 <h2>Node diagram</h2>
 <div class="sub" style="margin-bottom:0">One node per line. Blank turns it off.</div>
 <textarea id="dnodes" placeholder="Business idea&#10;Sales&#10;Brand&#10;Operations"></textarea>
 <input type="text" id="dcenter" placeholder="Centre label (optional)" style="margin-top:7px">

 <hr>
 <label>Your photo (cutout PNG)</label>
 <input type="file" id="subject" accept="image/*">
 <label>Hero image / logo</label>
 <input type="file" id="hero" accept="image/*">

 <hr>
 <h2>Social card</h2>
 <label>Card text</label>
 <input type="text" id="card" placeholder="The only kind of AI business that sells.">
 <div class="row" style="margin-top:7px">
  <div><label>Display name</label><input type="text" id="cardname" placeholder="Your Name"></div>
  <div><label>Handle</label><input type="text" id="cardhandle" placeholder="@yourhandle"></div>
 </div>
 <div class="row" style="margin-top:7px">
  <div><label>Toast label</label><input type="text" id="toastt" placeholder="Payment received"></div>
  <div><label>Toast amount</label><input type="text" id="toasta" placeholder="$17,532"></div>
 </div>

 <hr>
 <button id="dl">Download PNG</button>
 <button class="ghost" id="reset">Reset all positions</button>
 <div class="hint">
   Drag to move &middot; corner to resize &middot; double-click the headline to type<br>
   <kbd>Esc</kbd> deselect &middot; <kbd>R</kbd> reset &middot; <kbd>Del</kbd> delete &middot; arrows nudge
 </div>
 <div id="err" class="err"></div>
</div>

<div id="stage">
 <div id="wrap">
   <img id="full" alt="thumbnail preview">
   <img id="proxy" alt="">
   <div id="overlay"></div>
   <div id="editor" contenteditable="true" spellcheck="false"></div>
 </div>
 <div class="cap">Feed size &mdash; 168px, how viewers actually see it</div>
 <img id="feed">
 <div id="qa"></div>
</div>

<div class="col" id="chat">
 <h2>AI edit</h2>
 <div class="sub">Describe a change to the artwork. Text is always redrawn on top,
   so typography survives every edit.</div>

 <label>OpenRouter key</label>
 <input type="password" id="orkey" placeholder="sk-or-v1-..." autocomplete="off">
 <div class="sub" style="margin:5px 0 0;font-size:10.5px">
   Billed to your key. Kept in this tab only &mdash; never stored on the server.
 </div>

 <label>Model</label>
 <select id="ormodel"></select>

 <div id="log"><div id="chatempty">No edits yet. Try &ldquo;cinematic teal and orange grade,
   soft rim light on the subject&rdquo;.</div></div>

 <textarea id="orinstr" placeholder="What should change about the artwork?"></textarea>
 <div class="chk"><input type="checkbox" id="orredraw" checked>
   <label for="orredraw">Redraw text after editing</label></div>
 <button id="orgo">Send</button>
 <button class="ghost tiny" id="orrevert" style="margin-top:7px">Back to clean render</button>
</div>

<script>
let STYLES=[], LAYOUT=[], OVERRIDES={}, WORDCOLORS={}, LABELS=[], PALETTE=null, HIDDEN=[];
let last=null, timer=null, selected=null, editing=false, activeWord=null, lastTap={id:null,t:0};
const wrap=document.getElementById('wrap'), overlay=document.getElementById('overlay'),
      editor=document.getElementById('editor');
const $=id=>document.getElementById(id);

['poppins','inter','montserrat','archivo'].forEach(f=>{
  const s=document.createElement('style');
  s.textContent="@font-face{font-family:'tf-"+f+"';src:url('fonts/"+f+"') format('truetype');font-weight:100 900;font-display:swap}";
  document.head.appendChild(s);
});

async function boot(){
  STYLES=(await (await fetch('styles')).json()).styles;
  const s=$('style');
  STYLES.forEach(st=>{const o=document.createElement('option');o.value=st.name;
    o.textContent=st.name+' \\u2014 '+st.accent;s.appendChild(o)});
  s.onchange=()=>{fillPalettes();schedule()};
  fillPalettes(); drawWords(); drawSwatches(); drawLabels(); loadEditModels(); render(false);
}
function fillPalettes(){
  const st=STYLES.find(x=>x.name===$('style').value), p=$('palette');
  p.innerHTML='';
  st.palettes.forEach(pl=>{const o=document.createElement('option');o.value=pl;o.textContent=pl;p.appendChild(o)});
}
function fileAsDataURL(el){
  return new Promise(res=>{ if(!el.files||!el.files[0])return res(null);
    const r=new FileReader(); r.onload=()=>res(r.result); r.readAsDataURL(el.files[0]); });
}
/* Photos are read once on pick. Re-reading a multi-megabyte file on every
   render — and re-uploading it — was pure overhead on each drag. */
const FILES={subject:null, hero:null};
['subject','hero'].forEach(id=>{
  $(id).addEventListener('change', async e=>{ FILES[id]=await fileAsDataURL(e.target); schedule(); });
});
function ovFor(id){ return OVERRIDES[id] || (OVERRIDES[id]={dx:0,dy:0,scale:1}); }

/* ---------------- word colours ---------------- */
const wordKey=w=>w.toLowerCase().replace(/^[^\\w$]+|[^\\w$]+$/g,'');
function drawWords(){
  const box=$('words'); box.innerHTML=''; const seen=new Set();
  ($('headline').value||'').split(/\\s+/).filter(Boolean).forEach(raw=>{
    const k=wordKey(raw);
    if(!k||seen.has(k))return; seen.add(k);
    const b=document.createElement('button');
    b.type='button'; b.className='word'+(activeWord===k?' on':''); b.textContent=raw;
    if(WORDCOLORS[k]){ const d=document.createElement('span'); d.className='sw';
      d.style.background=WORDCOLORS[k]; b.appendChild(d); }
    b.onclick=()=>{ activeWord = activeWord===k ? null : k; drawWords(); };
    box.appendChild(b);
  });
  Object.keys(WORDCOLORS).forEach(k=>{ if(!seen.has(k)) delete WORDCOLORS[k]; });
}
async function drawSwatches(){
  if(!PALETTE) PALETTE=await (await fetch('palette')).json();
  const box=$('swatches'); box.innerHTML='';
  PALETTE.groups.forEach(g=>{
    const h=document.createElement('div'); h.className='grp'; h.textContent=g.name;
    const row=document.createElement('div'); row.className='sws';
    g.swatches.forEach(sw=>{ const b=document.createElement('button');
      b.className='sw-btn'; b.type='button'; b.style.background=sw.hex;
      b.title=sw.name+' '+sw.hex; b.onclick=()=>applyColor(sw.hex); row.appendChild(b); });
    box.appendChild(h); box.appendChild(row);
  });
}
function applyColor(hex){
  if(!activeWord){ $('err').textContent='Pick a word above first, then choose a colour.'; return; }
  $('err').textContent=''; WORDCOLORS[activeWord]=hex; drawWords(); schedule();
}

/* ---------------- labels ---------------- */
function drawLabels(){
  const box=$('labels'); box.innerHTML='';
  LABELS.forEach((lab,i)=>{
    const row=document.createElement('div'); row.className='lrow';
    const t=document.createElement('input'); t.type='text'; t.value=lab.text;
    t.placeholder='label text';
    t.oninput=e=>{ lab.text=e.target.value; debounce(); };
    const a=document.createElement('button'); a.type='button'; a.className='tiny ghost';
    a.textContent=lab.arrow_to?'arrow':'no arrow'; a.title='Toggle this label\\u2019s arrow';
    a.onclick=()=>{ lab.arrow_to = lab.arrow_to ? null : [Math.min(0.92,lab.x+0.14), Math.min(0.92,lab.y+0.30)];
                    drawLabels(); schedule(); };
    const x=document.createElement('button'); x.type='button'; x.className='tiny ghost';
    x.textContent='\\u2715';
    x.onclick=()=>{ LABELS.splice(i,1); delete OVERRIDES['label'+i]; drawLabels(); schedule(); };
    row.appendChild(t); row.appendChild(a); row.appendChild(x); box.appendChild(row);
  });
}
$('addlabel').onclick=()=>{
  LABELS.push({text:'label', x:0.07+0.02*LABELS.length, y:0.10+0.08*LABELS.length, size:0.055});
  drawLabels(); schedule();
};

/* ---------------- request ---------------- */
async function buildSpec(){
  const body={
    headline:$('headline').value||' ', style:$('style').value, palette:$('palette').value,
    accent_words:$('accent').value.split(',').map(s=>s.trim()).filter(Boolean),
    word_colors:WORDCOLORS, arrow:$('arrow').checked, overrides:OVERRIDES, hidden:HIDDEN,
    labels:LABELS.filter(l=>(l.text||'').trim()),
    output:'base64', include_qa:true, include_layout:true
  };
  const tp=$('textpos').value; if(tp)body.text_position=tp;
  const sd=$('side').value; if(sd)body.subject_side=sd;
  const card=$('card').value; if(card)body.card_text=card;
  const cn=$('cardname').value.trim(); if(cn)body.card_name=cn;
  const ch=$('cardhandle').value.trim(); if(ch)body.card_handle=ch;
  const tt=$('toastt').value, ta=$('toasta').value;
  if(tt&&ta){body.toast_text=tt;body.toast_amount=ta;}

  const nodes=$('dnodes').value.split('\\n').map(s=>s.trim()).filter(Boolean);
  if(nodes.length){
    body.diagram={nodes:nodes.map(n=>({label:n}))};
    const cl=$('dcenter').value.trim(); if(cl)body.diagram.center_label=cl;
  }
  if(FILES.subject)body.subject=FILES.subject;
  if(FILES.hero)body.hero=FILES.hero;
  return body;
}

let seq=0, finalTimer=null;

async function render(fast){
  const my=++seq;
  $('err').textContent='';
  const spec=await buildSpec();
  if(fast){
    // Two thirds of the pixels and a JPEG encode: ~60ms of work instead of
    // ~180ms. Nobody can see the difference at preview size, and the full
    // quality render lands a moment later anyway.
    spec.width=854; spec.height=480; spec.format='jpeg'; spec.include_qa=false;
  }
  const r=await fetch('generate',{method:'POST',headers:{'Content-Type':'application/json'},
                                  body:JSON.stringify(spec)});
  if(my!==seq) return;    // superseded mid-flight; drop the stale frame
  if(!r.ok){ let d; try{d=(await r.json()).detail}catch(e){d=r.statusText}
             $('err').textContent='Error '+r.status+': '+(typeof d==='string'?d:JSON.stringify(d,null,1));
             return; }
  const j=await r.json();
  if(my!==seq) return;
  const src='data:'+(j.mimeType||'image/png')+';base64,'+j.data;
  $('full').src=src; $('feed').src=src;
  LAYOUT=j.layout||[]; drawOverlay();
  if(!fast){
    last=j;               // only a full-quality frame is worth downloading
    const q=j.qa;
    $('qa').innerHTML = q ? 'Feed legibility <span class="badge '+(q.verdict==='ok'?'ok':'weak')+'">'+
        q.verdict.toUpperCase()+'</span> &nbsp; contrast '+q.headline_contrast+
        ' &nbsp; edge energy '+q.edge_energy : '';
  }
}

/* Paint immediately at preview quality, then settle to full quality once the
   user stops. This is what makes dragging feel live. */
function schedule(){
  render(true);
  clearTimeout(finalTimer);
  finalTimer=setTimeout(()=>render(false), 320);
}
function debounce(){clearTimeout(timer);timer=setTimeout(schedule,90)}

/* ---------------- overlay ---------------- */
function drawOverlay(){
  overlay.innerHTML='';
  LAYOUT.forEach(el=>{
    if(el.type==='arrow'){ drawArrow(el); return; }
    const d=document.createElement('div');
    d.className='el'+(selected===el.id?' sel':''); d.dataset.id=el.id;
    d.style.left=(el.x*100)+'%'; d.style.top=(el.y*100)+'%';
    d.style.width=(el.w*100)+'%'; d.style.height=(el.h*100)+'%';
    d.innerHTML='<span class="tag">'+el.label+'</span>'+
      ['nw','ne','sw','se'].map(c=>'<div class="h '+c+'" data-c="'+c+'"></div>').join('');
    d.addEventListener('pointerdown',e=>startDrag(e,el,d));
    overlay.appendChild(d);
  });
  updateSelInfo();
}
function drawArrow(el){
  [['from',el.from],['to',el.to]].forEach(([which,pt])=>{
    const dot=document.createElement('div'); dot.className='dot';
    dot.style.left=(pt[0]*100)+'%'; dot.style.top=(pt[1]*100)+'%';
    dot.title='Arrow '+which;
    dot.addEventListener('pointerdown',e=>startArrow(e,el,which));
    overlay.appendChild(dot);
  });
}
function select(id){ selected=id; drawOverlay(); }
function updateSelInfo(){
  const box=$('selinfo');
  const el=LAYOUT.find(e=>e.id===selected);
  if(!selected||!el){ box.style.display='none'; return; }
  const o=OVERRIDES[selected]||{dx:0,dy:0,scale:1};
  box.style.display='block';
  box.innerHTML='<b>'+el.label+'</b> selected &nbsp; scale '+(o.scale||1).toFixed(2)+
    ' &nbsp; offset '+(o.dx||0).toFixed(3)+', '+(o.dy||0).toFixed(3)+
    '<div style="margin-top:7px;display:flex;gap:6px">'+
    '<button class="tiny ghost" id="rs">Reset</button>'+
    '<button class="tiny ghost" id="del">Delete</button></div>';
  $('rs').onclick=()=>{ delete OVERRIDES[selected]; schedule(); };
  $('del').onclick=()=>deleteSelected();
}

/* ---------------- drag proxy ----------------
   Dragging used to move an empty outline while the picture sat frozen until
   release. Now the element is fetched as its own transparent layer and the rest
   as a backdrop, so the real pixels track the cursor with no network in the
   gesture at all. */
const proxy=$('proxy');
let proxyReady=false, proxyToken=0;

async function loadProxy(id){
  const token=++proxyToken;
  proxyReady=false;
  const base=await buildSpec();
  const mk=extra=>{
    const b=Object.assign({},base,extra);
    b.width=854; b.height=480; b.include_qa=false; b.include_layout=false;
    return fetch('generate',{method:'POST',headers:{'Content-Type':'application/json'},
                             body:JSON.stringify(b)}).then(r=>r.ok?r.json():null);
  };
  const [back,solo]=await Promise.all([
    mk({hidden:HIDDEN.concat([id]), format:'jpeg'}),
    mk({only:[id]}),
  ]);
  if(token!==proxyToken || !back || !solo) return;
  $('full').src='data:'+(back.mimeType||'image/jpeg')+';base64,'+back.data;
  proxy.src='data:image/png;base64,'+solo.data;
  proxy.style.display='block';
  proxyReady=true;
}
function clearProxy(){
  proxyToken++; proxyReady=false;
  proxy.style.display='none'; proxy.style.transform=''; proxy.removeAttribute('src');
}

/* ---------------- gestures ---------------- */
function startDrag(e,el,node){
  if(editing) return;
  const now=Date.now();
  if(el.type==='text' && lastTap.id===el.id && now-lastTap.t<380){
    lastTap={id:null,t:0}; e.preventDefault(); e.stopPropagation(); openEditor(el); return;
  }
  lastTap={id:el.id,t:now};
  e.preventDefault(); e.stopPropagation();
  select(el.id);
  const corner=e.target.dataset.c;
  loadProxy(el.id);   // in flight while the gesture starts
  const rect=wrap.getBoundingClientRect();
  const x0=e.clientX, y0=e.clientY;
  const o=Object.assign({dx:0,dy:0,scale:1}, OVERRIDES[el.id]||{});
  const startScale=o.scale||1, startW=el.w*rect.width;

  const move=ev=>{
    const ddx=ev.clientX-x0, ddy=ev.clientY-y0;
    if(corner){
      const dir=(corner==='se'||corner==='ne')?1:-1;
      const f=Math.max(0.15,(startW+dir*ddx)/Math.max(startW,1));
      node.style.transform='scale('+f+')'; node.style.transformOrigin='center';
      if(proxyReady){
        // Scale about the element's own centre, not the canvas centre.
        proxy.style.transformOrigin=((el.x+el.w/2)*100)+'% '+((el.y+el.h/2)*100)+'%';
        proxy.style.transform='scale('+f+')';
      }
    }else{
      node.style.transform='translate('+ddx+'px,'+ddy+'px)';
      if(proxyReady) proxy.style.transform='translate('+ddx+'px,'+ddy+'px)';
    }
  };
  const up=ev=>{
    document.removeEventListener('pointermove',move);
    document.removeEventListener('pointerup',up);
    // Deliberately keep the transform. Clearing it here snapped the element
    // back to its old spot until the new render arrived, which read as lag
    // even though the drag itself was instant. drawOverlay() replaces this
    // node with a correctly positioned one when the frame lands.
    const ddx=ev.clientX-x0, ddy=ev.clientY-y0;
    if(corner){
      const dir=(corner==='se'||corner==='ne')?1:-1;
      const f=Math.max(0.15,(startW+dir*ddx)/Math.max(startW,1));
      if(Math.abs(f-1)<0.005) return;
      ovFor(el.id).scale=Math.min(8,Math.max(0.1,startScale*f));
    }else{
      if(Math.abs(ddx)<2&&Math.abs(ddy)<2){ node.style.transform=''; clearProxy(); render(true); return; }
      const t=ovFor(el.id);
      t.dx=(o.dx||0)+ddx/rect.width; t.dy=(o.dy||0)+ddy/rect.height;
    }
    clearProxy();
    schedule();
  };
  document.addEventListener('pointermove',move);
  document.addEventListener('pointerup',up);
}
function startArrow(e,el,which){
  e.preventDefault(); e.stopPropagation(); select('arrow');
  const rect=wrap.getBoundingClientRect();
  const move=ev=>{
    const nx=Math.min(1,Math.max(0,(ev.clientX-rect.left)/rect.width));
    const ny=Math.min(1,Math.max(0,(ev.clientY-rect.top)/rect.height));
    const t=ovFor('arrow');
    t.from = which==='from' ? [nx,ny] : (t.from||el.from);
    t.to   = which==='to'   ? [nx,ny] : (t.to||el.to);
    e.target.style.left=(nx*100)+'%'; e.target.style.top=(ny*100)+'%';
  };
  const up=()=>{ document.removeEventListener('pointermove',move);
                 document.removeEventListener('pointerup',up); schedule(); };
  document.addEventListener('pointermove',move);
  document.addEventListener('pointerup',up);
}

/* ---------------- inline text ---------------- */
function openEditor(el){
  const rect=wrap.getBoundingClientRect();
  const st=STYLES.find(x=>x.name===$('style').value);
  const fam=(st.font||'inter').split(' ')[0];
  editing=true; select(el.id);
  editor.style.display='block';
  editor.style.left=(el.x*100)+'%'; editor.style.top=(el.y*100)+'%';
  editor.style.width=(Math.max(el.w,0.25)*100)+'%';
  editor.style.fontFamily="'tf-"+fam+"',sans-serif"; editor.style.fontWeight='900';
  editor.style.fontSize=(el.font_px*rect.width/1280)+'px';
  editor.style.textAlign=el.align||'left';
  editor.textContent=$('headline').value;
  editor.focus();
  const r=document.createRange(); r.selectNodeContents(editor);
  const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
}
function closeEditor(commit){
  if(!editing) return;
  editing=false; editor.style.display='none';
  if(commit && editor.textContent.trim()){
    $('headline').value=editor.textContent.replace(/\\n+/g,' ').trim();
    drawWords(); schedule();
  }
}
editor.addEventListener('keydown',e=>{
  const enter=e.key==='Enter'||e.key==='Return'||e.keyCode===13;
  const esc=e.key==='Escape'||e.key==='Esc'||e.keyCode===27;
  if(enter&&!e.shiftKey){e.preventDefault();closeEditor(true);}
  else if(esc){e.preventDefault();closeEditor(false);}
  e.stopPropagation();
});
editor.addEventListener('blur',()=>closeEditor(true));

/* ---------------- AI chat ---------------- */
async function loadEditModels(){
  const sel=$('ormodel');
  try{
    const {models}=await (await fetch('edit/models')).json();
    models.forEach(m=>{ const o=document.createElement('option'); o.value=m.id;
      const c=m.estimated_cost_per_image?' \\u2014 ~$'+m.estimated_cost_per_image.toFixed(3):'';
      o.textContent=m.label+c; o.title=m.note; sel.appendChild(o); });
  }catch(e){ const o=document.createElement('option');
    o.textContent='could not reach OpenRouter'; sel.appendChild(o); }
  const saved=sessionStorage.getItem('orkey'); if(saved) $('orkey').value=saved;
  $('orkey').addEventListener('change',e=>sessionStorage.setItem('orkey',e.target.value.trim()));
}
function addMsg(kind, text, imgSrc, meta){
  const empty=$('chatempty'); if(empty) empty.remove();
  const d=document.createElement('div'); d.className='msg '+kind;
  d.textContent=text;
  if(imgSrc){
    const im=document.createElement('img'); im.src=imgSrc;
    im.title='Click to put this version back on the canvas';
    im.onclick=()=>{ $('full').src=imgSrc; $('feed').src=imgSrc;
                     overlay.innerHTML=''; LAYOUT=[]; selected=null; };
    d.appendChild(im);
  }
  if(meta){ const m=document.createElement('div'); m.className='meta'; m.textContent=meta; d.appendChild(m); }
  $('log').appendChild(d); $('log').scrollTop=$('log').scrollHeight;
  return d;
}
async function runEdit(){
  const key=$('orkey').value.trim(), instr=$('orinstr').value.trim();
  if(!key){ addMsg('err','Paste your OpenRouter key above first.'); return; }
  if(instr.length<3){ return; }

  addMsg('me', instr);
  $('orinstr').value='';
  const pending=addMsg('ai','Editing artwork\\u2026');
  $('orgo').disabled=true;
  try{
    const r=await fetch('edit',{method:'POST',
      headers:{'Content-Type':'application/json','x-openrouter-key':key},
      body:JSON.stringify({spec:await buildSpec(), instruction:instr,
                           model:$('ormodel').value, redraw_text:$('orredraw').checked,
                           include_qa:true, output:'base64'})});
    if(!r.ok){ let d; try{d=(await r.json()).detail}catch(e){d=r.statusText}
               pending.className='msg err'; pending.textContent=String(d); return; }
    const j=await r.json();
    const src='data:image/png;base64,'+j.data;
    $('full').src=src; $('feed').src=src; last=j;
    overlay.innerHTML=''; LAYOUT=[]; selected=null;
    pending.textContent='Done.';
    const im=document.createElement('img'); im.src=src;
    im.title='Click to put this version back on the canvas';
    im.onclick=()=>{ $('full').src=src; $('feed').src=src; };
    pending.appendChild(im);
    const m=document.createElement('div'); m.className='meta';
    m.textContent=j.model + (j.qa? ' \\u00b7 legibility '+j.qa.verdict : '');
    pending.appendChild(m);
  }catch(e){ pending.className='msg err'; pending.textContent='Failed: '+e.message; }
  finally{ $('orgo').disabled=false; }
}
$('orgo').onclick=runEdit;
$('orinstr').addEventListener('keydown',e=>{
  if((e.key==='Enter'||e.keyCode===13)&&!e.shiftKey){ e.preventDefault(); runEdit(); }
});
$('orrevert').onclick=()=>render(false);

function deleteSelected(){
  if(!selected) return;
  const m=selected.match(/^label(\\d+)$/);
  if(m){
    // Labels are user-created, so remove them outright rather than hiding.
    LABELS.splice(+m[1],1);
    Object.keys(OVERRIDES).filter(k=>k.startsWith('label')).forEach(k=>delete OVERRIDES[k]);
    drawLabels();
  }else if(!HIDDEN.includes(selected)){
    HIDDEN.push(selected);
  }
  selected=null; clearProxy(); updateHiddenChip(); schedule();
}
function updateHiddenChip(){
  const el=$('hiddenchip');
  if(!HIDDEN.length){ el.style.display='none'; return; }
  el.style.display='block';
  el.innerHTML='Hidden: '+HIDDEN.join(', ')+
    ' <button class="tiny ghost" id="unhide">Restore all</button>';
  $('unhide').onclick=()=>{ HIDDEN=[]; updateHiddenChip(); schedule(); };
}

/* ---------------- keyboard + wiring ---------------- */
document.addEventListener('keydown',e=>{
  if(editing) return;
  const tag=(e.target.tagName||'').toLowerCase();
  if(tag==='input'||tag==='textarea'||tag==='select') return;
  if(e.key==='Escape'){ selected=null; drawOverlay(); }
  if(!selected) return;
  if(e.key==='Delete'||e.key==='Backspace'){ e.preventDefault(); deleteSelected(); return; }
  if(e.key.toLowerCase()==='r'){ delete OVERRIDES[selected]; schedule(); }
  const step=e.shiftKey?0.02:0.005;
  const map={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]};
  if(map[e.key]){ e.preventDefault(); const t=ovFor(selected);
    t.dx=(t.dx||0)+map[e.key][0]; t.dy=(t.dy||0)+map[e.key][1]; debounce(); }
});
wrap.addEventListener('pointerdown',e=>{ if(e.target===$('full')){ selected=null; drawOverlay(); }});
document.querySelectorAll('#panel input,#panel select,#panel textarea').forEach(el=>{
  el.addEventListener(el.type==='file'||el.tagName==='SELECT'?'change':'input',debounce)});
$('headline').addEventListener('input',drawWords);
$('reset').onclick=()=>{ OVERRIDES={}; HIDDEN=[]; selected=null; updateHiddenChip(); schedule(); };
$('clearcolor').onclick=()=>{ if(activeWord){ delete WORDCOLORS[activeWord]; drawWords(); schedule(); } };
$('customhex').addEventListener('change',e=>{
  const v=e.target.value.trim();
  if(/^#?[0-9a-fA-F]{6}$/.test(v)) applyColor(v.startsWith('#')?v:'#'+v);
  else if(v) $('err').textContent='Custom colour must be a 6-digit hex, e.g. #FFD400';
});
$('dl').onclick=()=>{ if(!last)return;
  const a=document.createElement('a'); a.href='data:image/png;base64,'+last.data;
  a.download=last.filename; a.click(); };
window.addEventListener('resize',()=>drawOverlay());
boot();
</script></body></html>
"""
