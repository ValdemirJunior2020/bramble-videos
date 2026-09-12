import { useEffect, useMemo, useState } from 'react'

type Asset={id:string,name:string,type:string,aliases:string[],description:string,traits:string,image_paths:string[]}
type Scene={scene_number:number,narration:string,characters:string[],location:string,emotion:string,action:string,image_prompt:string,image_path?:string,duration_seconds:number}
type Project={id:string,title:string,script:string,language:string,aspect:string,voice:string,consistency_lock:boolean,scenes:Scene[],state:string,progress:number,stage:string,error?:string,output_path?:string,video_encoder?:string}
const API='http://127.0.0.1:8000/api'

export default function App(){
  const [tab,setTab]=useState<'studio'|'assets'|'system'>('studio')
  const [assets,setAssets]=useState<Asset[]>([])
  const [voices,setVoices]=useState<any[]>([])
  const [health,setHealth]=useState<any>({})
  const [title,setTitle]=useState('Bramble & Grace Episode')
  const [script,setScript]=useState('')
  const [language,setLanguage]=useState('en')
  const [aspect,setAspect]=useState('16:9')
  const [voice,setVoice]=useState('')
  const [lock,setLock]=useState(true)
  const [project,setProject]=useState<Project|null>(null)
  const [busy,setBusy]=useState(false)
  const [assetName,setAssetName]=useState('Bramble')
  const [assetType,setAssetType]=useState('character')
  const [assetFile,setAssetFile]=useState<File|null>(null)
  const chars=useMemo(()=>assets.filter(a=>a.type==='character'),[assets])

  async function refresh(){
    try{setAssets(await (await fetch(`${API}/assets`)).json())}catch{}
    try{setVoices(await (await fetch(`${API}/voices`)).json())}catch{}
    try{setHealth(await (await fetch(`${API}/health`)).json())}catch{}
  }
  useEffect(()=>{refresh()},[])
  useEffect(()=>{
    if(!project || project.state!=='rendering')return
    const t=setInterval(async()=>{const p=await (await fetch(`${API}/projects/${project.id}`)).json();setProject(p)},1800)
    return()=>clearInterval(t)
  },[project?.id,project?.state])

  async function plan(){
    if(!script.trim())return alert('Paste the episode script first.')
    setBusy(true)
    try{
      const r=await fetch(`${API}/projects`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,script,language,aspect,voice,narration_style:'Warm',consistency_lock:lock,generate_images:true,transition:'Gentle Fade'})})
      const data=await r.json(); if(!r.ok)throw new Error(data.detail||'Planning failed'); setProject(data)
    }catch(e:any){alert(e.message)}finally{setBusy(false)}
  }

  async function render(){
    if(!project)return
    const r=await fetch(`${API}/projects/${project.id}/render`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({regenerate_all_images:false})})
    const data=await r.json(); if(!r.ok)return alert(data.detail||'Render failed')
    setProject({...project,state:'rendering',stage:'Starting',progress:1})
  }

  async function saveScene(scene:Scene){
    if(!project)return
    const r=await fetch(`${API}/projects/${project.id}/scenes/${scene.scene_number}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({narration:scene.narration,characters:scene.characters,location:scene.location,emotion:scene.emotion,action:scene.action,image_prompt:scene.image_prompt})})
    const updated=await r.json(); setProject({...project,scenes:project.scenes.map(s=>s.scene_number===updated.scene_number?updated:s)})
  }

  async function regen(scene:Scene){
    if(!project)return
    setBusy(true)
    try{
      const r=await fetch(`${API}/projects/${project.id}/scenes/${scene.scene_number}/regenerate`,{method:'POST'})
      const data=await r.json();if(!r.ok)throw new Error(data.detail||'Generation failed')
      setProject({...project,scenes:project.scenes.map(s=>s.scene_number===data.scene_number?data:s)})
    }catch(e:any){alert(e.message)}finally{setBusy(false)}
  }

  async function uploadAsset(){
    if(!assetFile)return alert('Choose an image first.')
    const f=new FormData();f.append('name',assetName);f.append('asset_type',assetType);f.append('file',assetFile)
    const r=await fetch(`${API}/assets`,{method:'POST',body:f});const data=await r.json();if(!r.ok)return alert(data.detail||'Upload failed');setAssetFile(null);await refresh()
  }

  async function removeAsset(a:Asset){await fetch(`${API}/assets/${a.id}`,{method:'DELETE'});await refresh()}

  return <div className="app">
    <header><div><div className="brand">Bramble Videos</div><div className="tag">Growing good hearts, one story at a time.</div></div><nav><button onClick={()=>setTab('studio')} className={tab==='studio'?'active':''}>Studio</button><button onClick={()=>setTab('assets')} className={tab==='assets'?'active':''}>Character Library</button><button onClick={()=>setTab('system')} className={tab==='system'?'active':''}>System</button></nav></header>

    {tab==='studio'&&<main>
      <section className="panel hero"><h1>Scene-by-scene Bramble production</h1><p>Phrase-timed narration, subtitles, character references and images all share the same timeline.</p></section>
      <section className="grid two"><div className="panel"><label>Episode title<input value={title} onChange={e=>setTitle(e.target.value)}/></label><label>Script<textarea rows={13} value={script} onChange={e=>setScript(e.target.value)} placeholder="Paste the complete episode script here..."/></label><div className="grid three"><label>Language<select value={language} onChange={e=>setLanguage(e.target.value)}><option value="en">English</option><option value="pt-BR">Português BR</option></select></label><label>Format<select value={aspect} onChange={e=>setAspect(e.target.value)}><option>16:9</option><option>9:16</option><option>1:1</option><option>4:5</option></select></label><label>Voice<select value={voice} onChange={e=>setVoice(e.target.value)}><option value="">Automatic local voice</option>{voices.filter(v=>language==='pt-BR'?v.culture==='pt-BR':v.culture.startsWith('en')).map(v=><option key={v.name}>{v.name}</option>)}</select></label></div><label className="check"><input type="checkbox" checked={lock} onChange={e=>setLock(e.target.checked)}/> Bramble Consistency Lock — require approved reference images for named characters</label><button className="primary" onClick={plan} disabled={busy}>{busy?'Working...':'Plan Episode'}</button></div>
      <div className="panel"><h2>Reference readiness</h2>{chars.map(c=><div className="assetRow" key={c.id}><b>{c.name}</b><span className={c.image_paths.length?'good':'warn'}>{c.image_paths.length?`${c.image_paths.length} reference image(s)`:'Needs reference'}</span></div>)}<p className="small">When a character is named in a scene, the planner attaches that character profile automatically. With Consistency Lock on, rendering stops before generation if a required reference is missing.</p></div></section>
      {project&&<><section className="panel status"><div><b>{project.title}</b><span>{project.stage}</span></div><progress value={project.progress} max={100}/><span>{project.progress}%</span>{project.error&&<div className="error">{project.error}</div>}</section><section className="sceneList">{project.scenes.map(s=><SceneCard key={s.scene_number} scene={s} assets={assets} onChange={next=>setProject({...project,scenes:project.scenes.map(x=>x.scene_number===next.scene_number?next:x)})} onSave={()=>saveScene(s)} onRegen={()=>regen(s)}/>)}</section><section className="panel renderBar"><button className="primary" onClick={render} disabled={project.state==='rendering'}>{project.state==='rendering'?'Rendering...':'Render Full Video'}</button>{project.state==='complete'&&<><span className="good">Complete · {project.video_encoder}</span><video controls src={`${API}/projects/${project.id}/video`}/></>}</section></>}
    </main>}

    {tab==='assets'&&<main><section className="grid two"><div className="panel"><h1>Upload approved references</h1><label>Name<input value={assetName} onChange={e=>setAssetName(e.target.value)}/></label><label>Type<select value={assetType} onChange={e=>setAssetType(e.target.value)}><option value="character">Character</option><option value="location">Location</option><option value="prop">Prop</option><option value="group">Group</option></select></label><label>Image<input type="file" accept="image/*" onChange={e=>setAssetFile(e.target.files?.[0]||null)}/></label><button className="primary" onClick={uploadAsset}>Add Reference Image</button><p className="small">You can upload more than one image for the same character. Front, full-body, back, expressions and costume sheets can all live under one name.</p></div><div className="panel"><h2>Asset library</h2>{assets.map(a=><div className="library" key={a.id}><div><b>{a.name}</b><div className="small">{a.type} · {a.image_paths.length} image(s)</div><div className="small">{a.traits}</div></div><button onClick={()=>removeAsset(a)}>Clear</button></div>)}</div></section></main>}

    {tab==='system'&&<main><section className="panel"><h1>Local system</h1><div className="systemGrid"><Stat name="Backend" value="Ready" ok/><Stat name="ComfyUI" value={health.comfyui?'Ready':'Offline'} ok={!!health.comfyui}/><Stat name="Ollama" value={health.ollama?'Ready':'Offline'} ok={!!health.ollama}/><Stat name="Video Encoder" value={health.ffmpeg_encoder||'Unknown'} ok={health.ffmpeg_encoder==='h264_amf'}/><Stat name="Ollama VRAM" value={health.ollama_gpu_vram_bytes?`${(health.ollama_gpu_vram_bytes/1024/1024/1024).toFixed(1)} GB`:'Model not loaded'} ok={health.ollama_gpu_vram_bytes>0}/></div><button onClick={refresh}>Refresh</button></section></main>}
  </div>
}

function SceneCard({scene,assets,onChange,onSave,onRegen}:{scene:Scene,assets:Asset[],onChange:(s:Scene)=>void,onSave:()=>void,onRegen:()=>void}){
  const chars=assets.filter(a=>a.type==='character')
  return <article className="panel scene"><div className="sceneTop"><h3>Scene {scene.scene_number}</h3><span>{scene.duration_seconds?`${scene.duration_seconds.toFixed(1)}s`:'timed during render'}</span></div><label>Narration<textarea rows={3} value={scene.narration} onChange={e=>onChange({...scene,narration:e.target.value})}/></label><div className="grid three"><label>Characters<select multiple value={scene.characters} onChange={e=>onChange({...scene,characters:Array.from(e.target.selectedOptions).map(o=>o.value)})}>{chars.map(c=><option key={c.name}>{c.name}</option>)}</select></label><label>Location<input value={scene.location} onChange={e=>onChange({...scene,location:e.target.value})}/></label><label>Emotion<input value={scene.emotion} onChange={e=>onChange({...scene,emotion:e.target.value})}/></label></div><label>Image prompt<textarea rows={4} value={scene.image_prompt} onChange={e=>onChange({...scene,image_prompt:e.target.value})}/></label><div className="actions"><button onClick={onSave}>Save Scene</button><button onClick={onRegen}>Regenerate Image</button></div></article>
}
function Stat({name,value,ok}:{name:string,value:string,ok:boolean}){return <div className="stat"><span>{name}</span><b className={ok?'good':'warn'}>{value}</b></div>}
