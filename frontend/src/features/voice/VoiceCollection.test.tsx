import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { queryClient } from '../../api/client'
import type { Preferences } from '../../api/types'
import { VoiceCollection, type LibraryVoice } from './VoiceCollection'
vi.mock('./useVoicePreview',()=>({useVoicePreview:()=>({play:vi.fn(),stop:vi.fn(),id:'',error:''})}))
let rows:LibraryVoice[]
beforeEach(()=>{
 queryClient.clear()
 rows=[{id:'professional',name:'The Anchor',description:'News',custom:false,favorite:true,hidden:false,selected:true,locked:false},{id:'jarvis',name:'Studio Assistant',description:'Clear',custom:false,favorite:false,hidden:false,selected:false,locked:false},{id:'custom:private',name:'My own voice',description:'Private',custom:true,favorite:true,hidden:false,selected:false,locked:false}]
 vi.spyOn(globalThis,'fetch').mockImplementation(async(path,options)=>{
  if(options?.method==='PATCH'){
   const key=decodeURIComponent(String(path).split('/').pop()!)
   rows=rows.map(v=>v.id===key?{...v,...JSON.parse(String(options.body))}:v)
  }
  return new Response(JSON.stringify(rows),{status:200,headers:{'Content-Type':'application/json'}})
 })
})
afterEach(()=>{cleanup();queryClient.clear();vi.restoreAllMocks()})
function show(mode:'home'|'settings', engine='elevenlabs') {render(<QueryClientProvider client={queryClient}><MemoryRouter><VoiceCollection mode={mode} prefs={{voice_engine:engine} as Preferences}/></MemoryRouter></QueryClientProvider>)}
it('shows only favorite ElevenLabs characters on home, including private voices',async()=>{
 show('home')
 await screen.findByText('My own voice')
 expect(screen.getByText('The Anchor')).toBeInTheDocument()
 expect(screen.queryByText('Studio Assistant')).not.toBeInTheDocument()
 expect(screen.getByRole('link',{name:'Manage voices'})).toBeInTheDocument()
})
it('lists the private voice in settings and persists favorite changes',async()=>{
 show('settings')
 await screen.findByText('My own voice')
 fireEvent.click(screen.getByRole('button',{name:'Add Studio Assistant to favorites'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'Remove Studio Assistant from favorites'})).toHaveAttribute('aria-pressed','true'))
 const request=vi.mocked(fetch).mock.calls.find(([,opts])=>opts?.method==='PATCH')
 expect(JSON.parse(String(request?.[1]?.body))).toEqual({favorite:true})
 fireEvent.click(screen.getByRole('button',{name:'Delete My own voice'}))
 expect(screen.getByRole('group',{name:'Delete voice confirmation'})).toBeInTheDocument()
 expect(vi.mocked(fetch).mock.calls.some(([,opts])=>opts?.method==='DELETE')).toBe(false)
})

it('shows OpenAI voices with favorite controls and without ElevenLabs characters',async()=>{
 show('settings','openai')
 await screen.findByText('Marin')
 expect(screen.getByText('Cedar')).toBeInTheDocument()
 expect(screen.queryByText('My own voice')).not.toBeInTheDocument()
 expect(screen.queryByText('The Anchor')).not.toBeInTheDocument()
 expect(screen.queryByRole('button',{name:/Delete/})).not.toBeInTheDocument()
})

it('shows only favorite OpenAI voices on home',async()=>{
 show('home','openai')
 await screen.findByText('Marin')
 expect(screen.queryByText('Cedar')).not.toBeInTheDocument()
})
it('lets OpenAI voices be marked as favorites in settings',async()=>{
 show('settings','openai')
 fireEvent.click(await screen.findByRole('button',{name:'Add Cedar to favorites'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'Remove Cedar from favorites'})).toHaveAttribute('aria-pressed','true'))
})
it('shows an explanation when no visible voices are favorites',async()=>{
 rows=rows.map(v=>({...v,favorite:false}))
 show('home')
 expect(await screen.findByText('Mark voices as favorites in Settings to show them here.')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:/Preview and select/})).not.toBeInTheDocument()
})
it('keeps hidden favorites off home even when selected',async()=>{
 rows=rows.map(v=>({...v,hidden:v.favorite}))
 show('home')
 await screen.findByText('Mark voices as favorites in Settings to show them here.')
 expect(screen.queryByText('The Anchor')).not.toBeInTheDocument()
})
