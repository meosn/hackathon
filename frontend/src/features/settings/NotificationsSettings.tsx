import { useEffect, useState } from 'react'
import { Bell, BellOff } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { api, useApi } from '../../api/client'
import { ErrorNote } from '../../components/UI'

type Config={available:boolean;public_key:string|null}
function publicKey(value:string) {return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0))}
export function NotificationsSettings() {
  const config=useApi<Config>('/notifications/settings')
  const [active,setActive]=useState(false)
  const [message,setMessage]=useState('')
  const supported=typeof window!=='undefined'&&'Notification' in window&&'serviceWorker' in navigator&&'PushManager' in window
  useEffect(()=>{
    if(!supported)return
    let live=true
    void navigator.serviceWorker.register('/sw.js').then(async reg=>{
      const sub=await reg.pushManager.getSubscription()
      if(!sub)return
      const state=await api<{enabled:boolean}>('/notifications/subscriptions/status','POST',{endpoint:sub.endpoint})
      if(live)setActive(state.enabled)
    }).catch(()=>{})
    return()=>{live=false}
  },[supported])
  const toggle=useMutation({mutationFn:async(permission:Promise<NotificationPermission>|null)=>{
    setMessage('')
    const reg=await navigator.serviceWorker.ready
    const existing=await reg.pushManager.getSubscription()
    if(active) {
      if(existing){await api('/notifications/subscriptions','DELETE',{endpoint:existing.endpoint});await existing.unsubscribe()}
      setActive(false);return
    }
    if(await permission!=='granted')throw Error('Notifications are blocked. Allow them in your browser’s site settings.')
    if(!config.data?.public_key)throw Error('Notifications are temporarily unavailable.')
    const sub=existing||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:publicKey(config.data.public_key)})
    await api('/notifications/subscriptions','POST',sub.toJSON())
    setActive(true);setMessage('You’ll be notified when a scheduled briefing is ready.')
  }})
  const test=useMutation({mutationFn:()=>api('/notifications/test','POST'),onSuccess:()=>setMessage('Test notification queued for this account’s enabled devices.')})
  return <section className="preference-block notification-settings">
    <div className="preference-label"><h3>News notifications</h3>{active?<Bell size={19}/>:<BellOff size={19}/>}</div>
    <p className="preference-hint">Get a notification when your scheduled edition is ready. Open it to listen.</p>
    {!supported?<p className="preference-hint">On iPhone or iPad, add Sourcera to your Home Screen from Safari’s Share menu, open it there, then enable notifications. On a computer, use a browser that supports push notifications.</p>:<>
      <button type="button" className={'btn '+(active?'outline':'primary')} disabled={toggle.isPending||!config.data?.available}
        onClick={()=>{const permission=active?null:Notification.requestPermission();toggle.mutate(permission)}}>{toggle.isPending?'Updating…':active?'Turn off on this device':'Enable on this device'}</button>
      {active&&<button type="button" className="btn quiet" disabled={test.isPending} onClick={()=>test.mutate()}>Send test</button>}
    </>}
    {message&&<p className="preference-hint" role="status">{message}</p>}
    <ErrorNote error={toggle.error||test.error||config.error}/>
  </section>
}
