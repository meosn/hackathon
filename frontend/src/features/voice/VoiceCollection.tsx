import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Check, Star, Trash2, RotateCcw, Lock, Plus, LoaderCircle, Volume2 } from 'lucide-react'
import { api, queryClient, useApi } from '../../api/client'
import type { Preferences } from '../../api/types'
import { SpeakerAvatar } from '../../components/SpeakerAvatar'
import { ErrorNote } from '../../components/UI'
import { useVoicePreview } from './useVoicePreview'
import { PremiumNotice } from './PremiumNotice'

export type LibraryVoice = {id:string;name:string;description:string;custom:boolean;favorite:boolean;hidden:boolean;selected:boolean;locked:boolean}
export function VoiceCollection({mode='settings',prefs,onSelected}:{mode?:'home'|'settings';prefs?:Preferences;onSelected?:(prefs:Preferences)=>void}) {
  const library=useApi<LibraryVoice[]>('/voice-library')
  const preview=useVoicePreview()
  const [premium,setPremium]=useState(false)
  const [deleting,setDeleting]=useState<LibraryVoice|null>(null)
  const rows=Array.isArray(library.data)?library.data:[]
  const change=useMutation({
    mutationFn:async({voice,action}:{voice:LibraryVoice;action:'select'|'favorite'|'remove'|'restore'})=>{
      const path='/voice-library/'+encodeURIComponent(voice.id)
      if(action==='select') {
        const result = prefs?.voice_engine === 'openai'
          ? (await api<Preferences>('/users/me/preferences','PATCH',{voice_engine:'openai',voice_profile_id:voice.id}), await api<LibraryVoice[]>('/voice-library'))
          : await api<LibraryVoice[]>(path+'/select','POST')
        const updated=await api<Preferences>('/users/me/preferences')
        queryClient.setQueryData(['/users/me/preferences'],updated)
        onSelected?.(updated)
        return result
      }
      if(action==='remove') {
        await api(path,'DELETE')
        return api<LibraryVoice[]>('/voice-library')
      }
      return api<LibraryVoice[]>(path,'PATCH',action==='favorite'?{favorite:!voice.favorite}:{hidden:false})
    },
    onSuccess:data=>{
      queryClient.setQueryData(['/voice-library'],data)
      setDeleting(null)
      void queryClient.invalidateQueries({queryKey:['/users/me/custom-voice']})
      void queryClient.invalidateQueries({queryKey:['/users/me/preferences']})
      void queryClient.invalidateQueries({queryKey:['prepared-editions']})
    },
  })
  function select(voice:LibraryVoice) {
    if(voice.locked) {setPremium(true);return}
    preview.play(voice.id,voice.custom||voice.id==='energetic'?'elevenlabs':prefs?.voice_engine||'openai',prefs?.language||'en')
    change.mutate({voice,action:'select'})
  }
  const openai = prefs?.voice_engine !== 'elevenlabs'
  const openaiNames: Record<string, string> = {professional:'Marin',jarvis:'Cedar',cyberpunk:'Echo'}
  const providerRows = openai ? rows.filter(v=>v.id in openaiNames).map(v=>({...v,name:openaiNames[v.id],description:'OpenAI voice',hidden:false,locked:false})) : rows
  const visible=providerRows.filter(v=>!v.hidden)
  return <div className={'voice-collection '+mode}>
    {premium&&<PremiumNotice onClose={()=>setPremium(false)}/>}
    <div className={mode==='home'?'music-hosts':'voice-collection-list'}>
      {visible.map(voice=><div key={voice.id} className="voice-library-row">
        <button type="button" className={mode==='home'?'music-host':'voice-library-select'} aria-pressed={voice.selected}
          title={'Preview and select '+voice.name} disabled={change.isPending} onClick={()=>select(voice)}>
          <span className={mode==='home'?'portrait-wrap':'voice-library-avatar'}>
            {voice.custom||openai?<span className="speaker-avatar custom-voice-icon">{voice.name.slice(0,1).toUpperCase()}</span>:<SpeakerAvatar id={voice.id}/>}
            {voice.selected&&<span className="voice-check"><Check size={13}/></span>}
            {voice.locked&&<span className="voice-lock"><Lock size={16}/></span>}
            {preview.id===voice.id&&<span className="voice-preview-indicator active">{preview.loading?<LoaderCircle size={18} className="spin"/>:<Volume2 size={18}/>}</span>}
          </span>
          <span><strong>{voice.name}</strong>{mode==='settings'&&<small>{voice.custom?'Your custom voice':voice.description}</small>}</span>
        </button>
        {mode==='settings'&&!openai&&<div className="voice-library-actions">
          <button type="button" className="icon" aria-label={(voice.favorite?'Remove ':'Add ')+voice.name+(voice.favorite?' from favorites':' to favorites')} aria-pressed={voice.favorite} onClick={()=>change.mutate({voice,action:'favorite'})} disabled={change.isPending}><Star size={18} fill={voice.favorite?'currentColor':'none'}/></button>
          <button type="button" className="icon" aria-label={'Delete '+voice.name} onClick={()=>setDeleting(voice)} disabled={change.isPending}><Trash2 size={17}/></button>
        </div>}
      </div>)}
      {mode==='home'&&<Link to="/settings?section=audio" className="music-host"><span className="portrait-wrap"><span className="speaker-avatar custom-voice-icon"><Plus size={28}/></span></span><span>Manage voices</span></Link>}
    </div>
    {mode==='home'&&visible.length===0&&<p className="preference-hint">Add a voice in Settings to keep it here.</p>}
    {mode==='settings'&&!openai&&<>
      <p className="preference-hint">Manage your characters and favorite voices. Changes save automatically.</p>
      {rows.some(v=>v.hidden)&&<details className="voice-restore"><summary>Add from collection</summary>{rows.filter(v=>v.hidden).map(voice=><button type="button" key={voice.id} onClick={()=>change.mutate({voice,action:'restore'})}><RotateCcw size={14}/>{voice.name}</button>)}</details>}
      {deleting&&<div className="voice-delete-confirm" role="group" aria-label="Delete voice confirmation"><p>{deleting.custom?'Remove “'+deleting.name+'” from your account? Saved episodes will remain.':'Remove “'+deleting.name+'” from your collection? You can add it again later.'}</p><button type="button" className="btn quiet" onClick={()=>setDeleting(null)}>Keep voice</button><button type="button" className="btn outline" disabled={change.isPending} onClick={()=>change.mutate({voice:deleting,action:'remove'})}>Remove voice</button></div>}
    </>}
    <Link className="btn outline agent-catalog-link" to="/agent-catalogs">
      Agent Catalogs <ArrowRight size={16} aria-hidden="true" />
    </Link>
    <ErrorNote error={library.error||change.error||preview.error}/>
  </div>
}
