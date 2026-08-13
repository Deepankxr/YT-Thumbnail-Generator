"""Self-contained browser UI for editing thumbnails, served at GET /preview.

Direct manipulation on the canvas: click an element to select it, drag to move,
pull a corner to resize, double-click the headline to type into it. The server
stays the only renderer — it returns a geometry manifest alongside the PNG, and
this page draws interactive handles on top of it. That is what keeps the studio
and the n8n automation pixel-identical; a second layout engine in JavaScript
would drift the moment either side changed.

Dragging is instant (CSS transform on the overlay). The re-render fires on
release, so nothing waits on a round trip mid-gesture.

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
 #panel{width:360px;flex:none;background:var(--panel);border-right:1px solid var(--line);
        padding:18px;overflow-y:auto}
 #stage{flex:1;padding:26px;overflow-y:auto}
 h1{font-size:16px;margin:0 0 4px}
 .sub{color:var(--muted);font-size:12px;margin-bottom:16px}
 label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
       color:var(--muted);margin:14px 0 5px}
 input[type=text],select,textarea{width:100%;padding:8px 10px;background:#0d0e10;
       border:1px solid var(--line);border-radius:6px;color:var(--fg);font-size:13px;font-family:inherit}
 textarea{resize:vertical;min-height:52px}
 .row{display:flex;gap:8px}.row>*{flex:1}
 .chk{display:flex;align-items:center;gap:8px;margin-top:14px}
 .chk input{width:auto}.chk label{margin:0;text-transform:none;letter-spacing:0;font-size:13px;color:var(--fg)}
 button{width:100%;margin-top:14px;padding:10px;background:var(--accent);border:0;border-radius:6px;
        color:#fff;font-weight:600;font-size:13px;cursor:pointer}
 button.ghost{background:#26292e;margin-top:8px}
 button.tiny{width:auto;padding:5px 10px;font-size:11px;margin:0}
 hr{border:0;border-top:1px solid var(--line);margin:18px 0}

 /* ---- canvas ---- */
 #wrap{position:relative;width:900px;max-width:100%;user-select:none}
 #wrap img{display:block;width:100%;border-radius:8px;background:#000;
           box-shadow:0 8px 34px rgba(0,0,0,.5)}
 #overlay{position:absolute;inset:0}
 .el{position:absolute;cursor:move;border:2px solid transparent;border-radius:3px}
 .el:hover{border-color:rgba(76,141,255,.55)}
 .el.sel{border-color:var(--sel)}
 .el .tag{position:absolute;top:-21px;left:-2px;background:var(--sel);color:#fff;
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
 .cap{font-size:11px;color:var(--muted);margin:16px 0 7px;text-transform:uppercase;letter-spacing:.06em}
 #feed{width:168px;border-radius:4px;box-shadow:0 2px 10px rgba(0,0,0,.5);display:block}
 #qa{font-size:12px;color:var(--muted);margin-top:12px}
 .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-weight:700;font-size:11px}
 .ok{background:#13361f;color:#5ddc8a}.weak{background:#3d2412;color:#ffab52}
 .err{color:#ff8b6b;font-size:12px;white-space:pre-wrap;margin-top:8px}
 #selinfo{background:#15171a;border:1px solid var(--line);border-radius:6px;padding:10px;
          margin-top:10px;font-size:12px;color:var(--muted);display:none}
 #selinfo b{color:var(--fg)}
 #words{display:flex;flex-wrap:wrap;gap:5px}
 .word{width:auto;margin:0;background:#0d0e10;border:1px solid var(--line);border-radius:5px;
       padding:4px 9px;font-size:12px;font-weight:400;cursor:pointer;color:var(--fg)}
 .word:hover{border-color:#3d4247}
 .word.on{border-color:var(--accent);background:#16202f}
 .word .sw{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:6px;
           vertical-align:middle;border:1px solid rgba(255,255,255,.25)}
 #swatches{margin-top:10px}
 .grp{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:8px 0 4px}
 .sws{display:flex;gap:5px;flex-wrap:wrap}
 .sw-btn{width:26px;height:26px;border-radius:5px;border:1px solid rgba(255,255,255,.18);
         cursor:pointer;padding:0;margin:0;flex:0 0 auto}
 .sw-btn:hover{outline:2px solid var(--accent);outline-offset:1px}
 .hint{font-size:11px;color:var(--muted);margin-top:10px;line-height:1.6}
 kbd{background:#26292e;border-radius:3px;padding:1px 5px;font-size:10px;font-family:inherit}
</style></head><body>
<div id="panel">
 <h1>Thumbnail Studio</h1>
 <div class="sub">Click anything on the canvas to move, resize, or retype it.</div>

 <label>Headline</label>
 <textarea id="headline">This changes everything.</textarea>

 <div class="row">
  <div><label>Style</label><select id="style"></select></div>
  <div><label>Palette</label><select id="palette"></select></div>
 </div>

 <label>Accent words <span style="text-transform:none">(comma separated)</span></label>
 <input type="text" id="accent" placeholder="everything.">

 <label>Word colours</label>
 <div id="words"></div>
 <div id="swatches"></div>
 <div class="row" style="margin-top:8px">
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

 <div id="selinfo"></div>

 <hr>
 <label>Your photo (cutout PNG)</label>
 <input type="file" id="subject" accept="image/*">
 <label>Hero image / logo</label>
 <input type="file" id="hero" accept="image/*">

 <hr>
 <label>Social card text (herk)</label>
 <input type="text" id="card" placeholder="The only kind of AI business that sells.">
 <div class="row">
  <div><label>Toast label</label><input type="text" id="toastt" placeholder="Payment received"></div>
  <div><label>Toast amount</label><input type="text" id="toasta" placeholder="$17,532"></div>
 </div>
 <div class="chk"><input type="checkbox" id="arrow" checked><label for="arrow">Show arrow</label></div>

 <button id="dl">Download PNG</button>
 <button class="ghost" id="reset">Reset all positions</button>
 <div class="hint">
   Drag to move &middot; corner to resize &middot; double-click the headline to type<br>
   <kbd>Esc</kbd> deselect &middot; <kbd>R</kbd> reset selected &middot; arrow keys nudge
 </div>
 <div id="err" class="err"></div>
</div>

<div id="stage">
 <div id="wrap">
   <img id="full" alt="thumbnail preview">
   <div id="overlay"></div>
   <div id="editor" contenteditable="true" spellcheck="false"></div>
 </div>
 <div class="cap">Feed size &mdash; 168px, how viewers actually see it</div>
 <img id="feed">
 <div id="qa"></div>
</div>

<script>
let STYLES=[], LAYOUT=[], OVERRIDES={}, last=null, timer=null, selected=null, editing=false;
const wrap=document.getElementById('wrap'), overlay=document.getElementById('overlay'),
      editor=document.getElementById('editor');
const $=id=>document.getElementById(id);

/* Every family the renderer can use, so the inline editor matches the render. */
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
  s.onchange=()=>{fillPalettes();render()};
  fillPalettes(); drawWords(); drawSwatches(); render();
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
/* ---------------- word colours ---------------- */
let WORDCOLORS={}, PALETTE=null, activeWord=null;

const wordKey=w=>w.toLowerCase().replace(/^[^\\w$]+|[^\\w$]+$/g,'');

function drawWords(){
  const box=$('words'); box.innerHTML='';
  const seen=new Set();
  ($('headline').value||'').split(/\\s+/).filter(Boolean).forEach(raw=>{
    const k=wordKey(raw);
    if(!k||seen.has(k))return; seen.add(k);
    const b=document.createElement('button');
    b.type='button';
    b.className='word'+(activeWord===k?' on':'');
    b.textContent=raw;
    if(WORDCOLORS[k]){
      const dot=document.createElement('span');
      dot.className='sw'; dot.style.background=WORDCOLORS[k];
      b.appendChild(dot);
    }
    b.onclick=()=>{ activeWord = activeWord===k ? null : k; drawWords(); };
    box.appendChild(b);
  });
  // Drop colours for words no longer in the headline, or they linger invisibly.
  Object.keys(WORDCOLORS).forEach(k=>{ if(!seen.has(k)) delete WORDCOLORS[k]; });
}

async function drawSwatches(){
  if(!PALETTE) PALETTE=await (await fetch('palette')).json();
  const box=$('swatches'); box.innerHTML='';
  PALETTE.groups.forEach(g=>{
    const h=document.createElement('div'); h.className='grp'; h.textContent=g.name;
    const row=document.createElement('div'); row.className='sws';
    g.swatches.forEach(s=>{
      const b=document.createElement('button');
      b.className='sw-btn'; b.type='button'; b.style.background=s.hex;
      b.title=s.name+' '+s.hex;
      b.onclick=()=>applyColor(s.hex);
      row.appendChild(b);
    });
    box.appendChild(h); box.appendChild(row);
  });
}
function applyColor(hex){
  if(!activeWord){ $('err').textContent='Pick a word above first, then choose a colour.'; return; }
  $('err').textContent='';
  WORDCOLORS[activeWord]=hex;
  drawWords(); render();
}
function ovFor(id){ return OVERRIDES[id] || (OVERRIDES[id]={dx:0,dy:0,scale:1}); }

async function render(){
  $('err').textContent='';
  const body={
    headline:$('headline').value||' ', style:$('style').value, palette:$('palette').value,
    accent_words:$('accent').value.split(',').map(s=>s.trim()).filter(Boolean),
    word_colors:WORDCOLORS,
    arrow:$('arrow').checked, overrides:OVERRIDES,
    output:'base64', include_qa:true, include_layout:true
  };
  const tp=$('textpos').value; if(tp)body.text_position=tp;
  const sd=$('side').value; if(sd)body.subject_side=sd;
  const card=$('card').value; if(card)body.card_text=card;
  const tt=$('toastt').value, ta=$('toasta').value;
  if(tt&&ta){body.toast_text=tt;body.toast_amount=ta;}
  const su=await fileAsDataURL($('subject')); if(su)body.subject=su;
  const he=await fileAsDataURL($('hero')); if(he)body.hero=he;

  const r=await fetch('generate',{method:'POST',headers:{'Content-Type':'application/json'},
                                  body:JSON.stringify(body)});
  if(!r.ok){ let d; try{d=(await r.json()).detail}catch(e){d=r.statusText}
             $('err').textContent='Error '+r.status+': '+(typeof d==='string'?d:JSON.stringify(d,null,1));
             return; }
  const j=await r.json(); last=j;
  const src='data:image/png;base64,'+j.data;
  $('full').src=src; $('feed').src=src;
  LAYOUT=j.layout||[]; drawOverlay();
  const q=j.qa;
  $('qa').innerHTML = q ? 'Feed legibility <span class="badge '+(q.verdict==='ok'?'ok':'weak')+'">'+
      q.verdict.toUpperCase()+'</span> &nbsp; contrast '+q.headline_contrast+
      ' &nbsp; edge energy '+q.edge_energy : '';
}
function debounce(){clearTimeout(timer);timer=setTimeout(render,220)}
$('headline').addEventListener('input',drawWords);

/* ---------------- overlay ---------------- */
function drawOverlay(){
  overlay.innerHTML='';
  LAYOUT.forEach(el=>{
    if(el.type==='arrow'){ drawArrow(el); return; }
    const d=document.createElement('div');
    d.className='el'+(selected===el.id?' sel':'');
    d.dataset.id=el.id;
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
    const dot=document.createElement('div');
    dot.className='dot';
    dot.style.left=(pt[0]*100)+'%'; dot.style.top=(pt[1]*100)+'%';
    dot.title='Arrow '+which;
    dot.addEventListener('pointerdown',e=>startArrow(e,el,which));
    overlay.appendChild(dot);
  });
}
function select(id){ selected=id; drawOverlay(); }
function updateSelInfo(){
  const box=$('selinfo');
  if(!selected){ box.style.display='none'; return; }
  const el=LAYOUT.find(e=>e.id===selected);
  if(!el){ box.style.display='none'; return; }
  const o=OVERRIDES[selected]||{dx:0,dy:0,scale:1};
  box.style.display='block';
  box.innerHTML='<b>'+el.label+'</b> selected &nbsp; scale '+(o.scale||1).toFixed(2)+
    ' &nbsp; offset '+(o.dx||0).toFixed(3)+', '+(o.dy||0).toFixed(3)+
    ' <button class="tiny ghost" id="rs">Reset</button>';
  $('rs').onclick=()=>{ delete OVERRIDES[selected]; render(); };
}

/* ---------------- gestures ---------------- */
let lastTap={id:null,t:0};

function startDrag(e,el,node){
  if(editing) return;
  // preventDefault below suppresses the native click/dblclick chain, so
  // double-click is detected here rather than with a dblclick listener.
  const now=Date.now();
  if(el.type==='text' && lastTap.id===el.id && now-lastTap.t<380){
    lastTap={id:null,t:0};
    e.preventDefault(); e.stopPropagation();
    openEditor(el);
    return;
  }
  lastTap={id:el.id,t:now};

  e.preventDefault(); e.stopPropagation();
  select(el.id);
  const corner=e.target.dataset.c;
  const rect=wrap.getBoundingClientRect();
  const x0=e.clientX, y0=e.clientY;
  const o=Object.assign({dx:0,dy:0,scale:1}, OVERRIDES[el.id]||{});
  const startScale=o.scale||1, startW=el.w*rect.width;

  const move=ev=>{
    const ddx=ev.clientX-x0, ddy=ev.clientY-y0;
    if(corner){
      const dir=(corner==='se'||corner==='ne')?1:-1;
      const f=Math.max(0.15,(startW+dir*ddx)/Math.max(startW,1));
      node.style.transform='scale('+f+')';
      node.style.transformOrigin='center';
    }else{
      node.style.transform='translate('+ddx+'px,'+ddy+'px)';
    }
  };
  const up=ev=>{
    document.removeEventListener('pointermove',move);
    document.removeEventListener('pointerup',up);
    node.style.transform='';
    const ddx=ev.clientX-x0, ddy=ev.clientY-y0;
    if(corner){
      const dir=(corner==='se'||corner==='ne')?1:-1;
      const f=Math.max(0.15,(startW+dir*ddx)/Math.max(startW,1));
      if(Math.abs(f-1)<0.005) return;
      ovFor(el.id).scale=Math.min(8,Math.max(0.1,startScale*f));
    }else{
      if(Math.abs(ddx)<2&&Math.abs(ddy)<2) return;   // a click, not a drag
      const t=ovFor(el.id);
      t.dx=(o.dx||0)+ddx/rect.width;
      t.dy=(o.dy||0)+ddy/rect.height;
    }
    render();
  };
  document.addEventListener('pointermove',move);
  document.addEventListener('pointerup',up);
}
function startArrow(e,el,which){
  e.preventDefault(); e.stopPropagation();
  select('arrow');
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
                 document.removeEventListener('pointerup',up); render(); };
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
  editor.style.left=(el.x*100)+'%';
  editor.style.top=(el.y*100)+'%';
  editor.style.width=(Math.max(el.w,0.25)*100)+'%';
  editor.style.fontFamily="'tf-"+fam+"',sans-serif";
  editor.style.fontWeight='900';
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
    drawWords();
    render();
  }
}
editor.addEventListener('keydown',e=>{
  // Match on keyCode as well as key: synthetic events (and some remote-control
  // stacks) report "Return" rather than "Enter".
  const enter = e.key==='Enter'||e.key==='Return'||e.keyCode===13;
  const esc   = e.key==='Escape'||e.key==='Esc'||e.keyCode===27;
  if(enter&&!e.shiftKey){e.preventDefault();closeEditor(true);}
  else if(esc){e.preventDefault();closeEditor(false);}
  e.stopPropagation();
});
editor.addEventListener('blur',()=>closeEditor(true));

/* ---------------- keyboard + wiring ---------------- */
document.addEventListener('keydown',e=>{
  if(editing) return;
  const tag=(e.target.tagName||'').toLowerCase();
  if(tag==='input'||tag==='textarea'||tag==='select') return;
  if(e.key==='Escape'){ selected=null; drawOverlay(); }
  if(!selected) return;
  if(e.key.toLowerCase()==='r'){ delete OVERRIDES[selected]; render(); }
  const step=e.shiftKey?0.02:0.005;
  const map={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]};
  if(map[e.key]){
    e.preventDefault();
    const t=ovFor(selected);
    t.dx=(t.dx||0)+map[e.key][0]; t.dy=(t.dy||0)+map[e.key][1];
    debounce();
  }
});
wrap.addEventListener('pointerdown',e=>{ if(e.target===$('full')){ selected=null; drawOverlay(); }});

document.querySelectorAll('#panel input,#panel select,#panel textarea').forEach(el=>{
  el.addEventListener(el.type==='file'||el.tagName==='SELECT'?'change':'input',debounce)});
$('reset').onclick=()=>{ OVERRIDES={}; selected=null; render(); };
$('clearcolor').onclick=()=>{ if(activeWord){ delete WORDCOLORS[activeWord]; drawWords(); render(); } };
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
