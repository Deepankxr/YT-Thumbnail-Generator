"""Self-contained browser UI for editing thumbnails, served at GET /preview.

Every field the API accepts is exposed as a control, re-rendering on change.
The point is the side-by-side: full size next to a 168px feed-size preview,
because a headline that reads beautifully at 100% is often mush in the actual
YouTube feed, and that is the failure that costs clicks.

No CDN, no build step — the page is one string so it works on a locked-down box.
"""

PREVIEW_HTML = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Thumbnail Studio</title>
<style>
 :root{--bg:#111214;--panel:#1a1c1f;--line:#2a2d31;--fg:#e8eaed;--muted:#9aa0a6;--accent:#4c8dff}
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      background:var(--bg);color:var(--fg);display:flex;height:100vh;overflow:hidden}
 #panel{width:380px;flex:none;background:var(--panel);border-right:1px solid var(--line);
        padding:18px;overflow-y:auto}
 #stage{flex:1;padding:26px;overflow-y:auto;display:flex;flex-direction:column;gap:22px;align-items:flex-start}
 h1{font-size:16px;margin:0 0 4px}
 .sub{color:var(--muted);font-size:12px;margin-bottom:18px}
 label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
       color:var(--muted);margin:14px 0 5px}
 input[type=text],select,textarea{width:100%;padding:8px 10px;background:#0d0e10;
       border:1px solid var(--line);border-radius:6px;color:var(--fg);font-size:13px;font-family:inherit}
 textarea{resize:vertical;min-height:52px}
 .row{display:flex;gap:8px}.row>*{flex:1}
 .chk{display:flex;align-items:center;gap:8px;margin-top:14px}
 .chk input{width:auto}.chk label{margin:0;text-transform:none;letter-spacing:0;font-size:13px;color:var(--fg)}
 button{width:100%;margin-top:18px;padding:10px;background:var(--accent);border:0;border-radius:6px;
        color:#fff;font-weight:600;font-size:13px;cursor:pointer}
 button.ghost{background:#26292e;margin-top:8px}
 img{display:block;border-radius:8px;background:#000}
 #full{width:768px;max-width:100%;box-shadow:0 8px 34px rgba(0,0,0,.5)}
 #feed{width:168px;image-rendering:auto;box-shadow:0 2px 10px rgba(0,0,0,.5)}
 .cap{font-size:11px;color:var(--muted);margin-bottom:7px;text-transform:uppercase;letter-spacing:.06em}
 #qa{font-size:12px;color:var(--muted)}
 .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-weight:700;font-size:11px}
 .ok{background:#13361f;color:#5ddc8a}.weak{background:#3d2412;color:#ffab52}
 .err{color:#ff8b6b;font-size:12px;white-space:pre-wrap}
 hr{border:0;border-top:1px solid var(--line);margin:18px 0}
</style></head><body>
<div id="panel">
 <h1>Thumbnail Studio</h1>
 <div class="sub">Edits re-render instantly. Nothing costs money unless you use AI hero art.</div>

 <label>Headline</label>
 <textarea id="headline">This changes everything.</textarea>

 <div class="row">
  <div><label>Style</label><select id="style"></select></div>
  <div><label>Palette</label><select id="palette"></select></div>
 </div>

 <label>Accent words <span style="text-transform:none">(comma separated)</span></label>
 <input type="text" id="accent" placeholder="everything.">

 <label>Word colours <span style="text-transform:none">(word:#hex, comma separated)</span></label>
 <input type="text" id="wordcolors" placeholder="stop:#FFD400">

 <div class="row">
  <div><label>Text position</label><select id="textpos">
    <option value="">style default</option><option value="top">top</option><option value="bottom">bottom</option>
  </select></div>
  <div><label>Subject side</label><select id="side">
    <option value="">style default</option><option value="left">left</option><option value="right">right</option>
  </select></div>
 </div>

 <hr>
 <label>Your photo (cutout PNG)</label>
 <input type="file" id="subject" accept="image/*">
 <div class="sub" style="margin:6px 0 0">Transparent PNG works best. Run prepare_subject.py first.</div>

 <label>Hero image / logo (optional)</label>
 <input type="file" id="hero" accept="image/*">

 <hr>
 <label>Social card text (herk)</label>
 <input type="text" id="card" placeholder="The only kind of AI business that sells.">
 <div class="row">
  <div><label>Toast label</label><input type="text" id="toastt" placeholder="Payment received"></div>
  <div><label>Toast amount</label><input type="text" id="toasta" placeholder="$17,532"></div>
 </div>

 <div class="chk"><input type="checkbox" id="arrow" checked><label for="arrow">Show arrow</label></div>

 <button id="go">Render</button>
 <button class="ghost" id="dl">Download PNG</button>
 <div id="err" class="err"></div>
</div>

<div id="stage">
 <div><div class="cap">Full size &mdash; 1280&times;720</div><img id="full"></div>
 <div>
   <div class="cap">Feed size &mdash; 168px, how viewers actually see it</div>
   <img id="feed">
 </div>
 <div id="qa"></div>
</div>

<script>
let STYLES=[], lastBlob=null, timer=null;

async function boot(){
  STYLES=(await (await fetch('styles')).json()).styles;
  const s=document.getElementById('style');
  STYLES.forEach(st=>{const o=document.createElement('option');o.value=st.name;
    o.textContent=st.name+' \\u2014 '+st.accent;s.appendChild(o)});
  s.onchange=()=>{fillPalettes();render()};
  fillPalettes(); render();
}
function fillPalettes(){
  const name=document.getElementById('style').value;
  const st=STYLES.find(x=>x.name===name); const p=document.getElementById('palette');
  p.innerHTML='';
  st.palettes.forEach(pl=>{const o=document.createElement('option');o.value=pl;o.textContent=pl;p.appendChild(o)});
}
function fileAsDataURL(el){
  return new Promise(res=>{
    if(!el.files||!el.files[0])return res(null);
    const r=new FileReader(); r.onload=()=>res(r.result); r.readAsDataURL(el.files[0]);
  });
}
function parsePairs(raw){
  const out={};
  raw.split(',').map(s=>s.trim()).filter(Boolean).forEach(pair=>{
    const i=pair.lastIndexOf(':'); if(i<1)return;
    out[pair.slice(0,i).trim()]=pair.slice(i+1).trim();
  });
  return out;
}
async function render(){
  const err=document.getElementById('err'); err.textContent='';
  const body={
    headline:document.getElementById('headline').value||' ',
    style:document.getElementById('style').value,
    palette:document.getElementById('palette').value,
    accent_words:document.getElementById('accent').value.split(',').map(s=>s.trim()).filter(Boolean),
    word_colors:parsePairs(document.getElementById('wordcolors').value),
    arrow:document.getElementById('arrow').checked,
    output:'base64', include_qa:true
  };
  const tp=document.getElementById('textpos').value; if(tp)body.text_position=tp;
  const sd=document.getElementById('side').value; if(sd)body.subject_side=sd;
  const card=document.getElementById('card').value; if(card)body.card_text=card;
  const tt=document.getElementById('toastt').value, ta=document.getElementById('toasta').value;
  if(tt&&ta){body.toast_text=tt;body.toast_amount=ta;}
  const subj=await fileAsDataURL(document.getElementById('subject')); if(subj)body.subject=subj;
  const hero=await fileAsDataURL(document.getElementById('hero')); if(hero)body.hero=hero;

  const r=await fetch('generate',{method:'POST',headers:{'Content-Type':'application/json'},
                                 body:JSON.stringify(body)});
  if(!r.ok){ let d; try{d=(await r.json()).detail}catch(e){d=r.statusText}
             err.textContent='Error '+r.status+': '+(typeof d==='string'?d:JSON.stringify(d,null,1)); return; }
  const j=await r.json();
  const src='data:image/png;base64,'+j.data;
  document.getElementById('full').src=src; document.getElementById('feed').src=src;
  lastBlob={data:j.data,name:j.filename};
  const q=j.qa;
  document.getElementById('qa').innerHTML= q ?
    'Feed legibility <span class="badge '+(q.verdict==='ok'?'ok':'weak')+'">'+q.verdict.toUpperCase()+
    '</span> &nbsp; contrast '+q.headline_contrast+' &nbsp; edge energy '+q.edge_energy : '';
}
function debounce(){clearTimeout(timer);timer=setTimeout(render,220)}
document.querySelectorAll('input,select,textarea').forEach(el=>{
  el.addEventListener(el.type==='file'||el.tagName==='SELECT'?'change':'input',debounce)});
document.getElementById('go').onclick=render;
document.getElementById('dl').onclick=()=>{
  if(!lastBlob)return;
  const a=document.createElement('a');
  a.href='data:image/png;base64,'+lastBlob.data; a.download=lastBlob.name; a.click();
};
boot();
</script></body></html>
"""
