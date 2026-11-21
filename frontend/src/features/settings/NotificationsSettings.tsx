import { useEffect, useState } from 'react'
import { Bell, BellOff } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { api, useApi } from '../../api/client'
import { ErrorNote } from '../../components/UI'

type Config={available:boolean;public_key:string|null}
function publicKey(value:string) {return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0))}
async function bounded<T>(promise:Promise<T>,milliseconds:number):Promise<T>{
 let timer:ReturnType<typeof setTimeout>|undefined
 try{return await Promise.race([promise,new Promise<T>((_,reject)=>{timer=setTimeout(()=>reject(Error('The browser’s push service did not respond. Please try again.')),milliseconds)})])}
 finally{if(timer)clearTimeout(timer)}
}
export function NotificationsSettings() {
 const config=useApi<Config>('/notifications/settings')
 const [active,setActive]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('')
 const [registration,setRegistration]=useState<ServiceWorkerRegistration|null>(null)
 const [attempt,setAttempt]=useState(0)
 const iphone=/iPhone/i.test(navigator.userAgent)
 const installed=window.matchMedia?.('(display-mode: standalone)').matches||(navigator as Navigator&{standalone?:boolean}).standalone===true
 const installRequired=iphone&&!installed
 const supported='Notification' in window&&'serviceWorker' in navigator&&'PushManager' in window
 useEffect(()=>{
  if(!supported||installRequired)return
  let live=true
  setError('')
  void (async()=>{
   await navigator.serviceWorker.register(import.meta.env.BASE_URL + 'sw.js')
   const reg=await bounded(navigator.serviceWorker.ready,10000)
   if(!live)return
   setRegistration(reg)
   const sub=await reg.pushManager.getSubscription()
   if(!sub)return
   const state=await api<{enabled:boolean}>('/notifications/subscriptions/status','POST',{endpoint:sub.endpoint})
   if(live)setActive(state.enabled&&Notification.permission==='granted')
  })().catch(()=>{if(live)setError('Could not prepare browser notifications. Please retry. If private browsing is enabled, open a regular window.')})
  return()=>{live=false}
 },[supported,installRequired,attempt])
 const toggle=useMutation({mutationFn:async(subscription:Promise<PushSubscription>|null)=>{
  if(!registration)return
  if(active){
   const existing=await registration.pushManager.getSubscription()
   if(existing){await api('/notifications/subscriptions','DELETE',{endpoint:existing.endpoint});await existing.unsubscribe()}
   setActive(false);return
  }
  const sub=await bounded(subscription!,20000)
  await api('/notifications/subscriptions','POST',sub.toJSON())
  setActive(true);setMessage('Notifications are enabled on this device. Send a test to check delivery.')
 },onError:failure=>{
  setError(failure instanceof DOMException&&failure.name==='NotAllowedError'
   ?'Notifications were not allowed. Enable them for this site in your browser and system notification settings, then try again.'
   :failure instanceof Error?failure.message:'Could not enable notifications. Please try again.')
 }})
 function change(){
  setError('');setMessage('')
  if(active){toggle.mutate(null);return}
  if(Notification.permission==='denied'){setError('Notifications are blocked. Allow this site in your browser and system notification settings.');return}
  if(!registration||!config.data?.public_key)return
  // Safari requires subscribe itself to run directly in the tap/click handler.
  // Preparing the worker or requesting permission first loses that gesture.
  try{const subscription=registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:publicKey(config.data.public_key)});toggle.mutate(subscription)}
  catch(failure){setError(failure instanceof Error?failure.message:'Could not request notification permission.')}
 }
 const test=useMutation({mutationFn:()=>api('/notifications/test','POST'),onSuccess:()=>setMessage('Test queued. A system notification should appear shortly; check your device’s notification center.')})
 return <section className="preference-block notification-settings">
  <div className="preference-label"><h3>News notifications</h3>{active?<Bell size={19}/>:<BellOff size={19}/>}</div>
  <p className="preference-hint">Get a notification when your scheduled edition is ready. Open it to listen.</p>
  {installRequired?<div className="preference-hint"><strong>First, add Sourcera to your Home Screen.</strong><ol><li>Open Safari’s Share menu and choose “Add to Home Screen”.</li><li>Open Sourcera using that new icon and sign in.</li><li>Return here and enable notifications.</li></ol><p>An ordinary Safari tab on iPhone cannot receive these notifications.</p></div>
   :!supported?<p className="preference-hint">This browser does not support push notifications here. Try a supported browser in a regular window.</p>
   :<><button type="button" className={'btn '+(active?'outline':'primary')} disabled={toggle.isPending||!registration||!config.data?.available} onClick={change}>{toggle.isPending?'Updating…':active?'Turn off on this device':!registration?'Preparing notifications…':'Enable on this device'}</button>
    {active&&<button type="button" className="btn quiet" disabled={test.isPending} onClick={()=>test.mutate()}>Send test</button>}
    {error&&<button type="button" className="btn quiet" onClick={()=>setAttempt(n=>n+1)}>Retry setup</button>}</>}
  {message&&<p className="preference-hint" role="status">{message}</p>}
  <ErrorNote error={error||test.error||config.error}/>
 </section>
}
