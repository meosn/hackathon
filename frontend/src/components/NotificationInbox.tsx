import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api, queryClient } from '../api/client'
type Notice={id:string;title:string;url:string;read:boolean;created_at:string}
export function NotificationInbox(){
 const [open,setOpen]=useState(false)
 const inbox=useQuery({queryKey:['/notifications'],queryFn:()=>api<Notice[]>('/notifications'),refetchInterval:60000})
 const rows=Array.isArray(inbox.data)?inbox.data:[]
 const count=rows.filter(n=>!n.read).length
 return <div className="notification-inbox"><button type="button" className="icon notification-bell" aria-label={count?'Notifications, '+count+' unread':'Notifications'} aria-expanded={open} onClick={()=>setOpen(!open)}><Bell size={18}/>{count>0&&<i/>}</button>{open&&<section className="notification-popover" aria-label="Your notifications"><div><strong>Your news</strong><button type="button" className="icon" aria-label="Close notifications" onClick={()=>setOpen(false)}>×</button></div>{rows.length?rows.slice(0,8).map(n=><Link key={n.id} to={n.url} className={n.read?'':'unread'} onClick={()=>{setOpen(false);void api('/notifications/'+n.id+'/read','POST').then(()=>queryClient.invalidateQueries({queryKey:['/notifications']}))}}><span>{n.title}</span><small>{new Date(n.created_at).toLocaleString()}</small></Link>):<p>Your scheduled briefings will appear here when they’re ready.</p>}<Link to="/settings?section=routine" onClick={()=>setOpen(false)}>Notification settings</Link></section>}</div>
}
