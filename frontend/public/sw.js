/* No private API/audio caching. This worker only receives edition notifications. */
self.addEventListener('install',()=>self.skipWaiting())
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()))
self.addEventListener('push',event=>{
 let data={}
 try {data=event.data?.json()||{}}catch{}
 const target=typeof data.url==='string'&&data.url.startsWith('/briefings/')?data.url:'/'
 event.waitUntil(self.registration.showNotification(data.title||'Your news is ready',{
  body:data.body||'Your briefing is ready. Tap to listen.',icon:'/icon-192.png',badge:'/icon-192.png',tag:data.tag||'sourcera-news',data:{url:target}
 }))
})
self.addEventListener('notificationclick',event=>{
 event.notification.close()
 const target=new URL(event.notification.data?.url||'/',self.location.origin)
 if(target.origin!==self.location.origin)return
 event.waitUntil((async()=>{
  const clients=await self.clients.matchAll({type:'window',includeUncontrolled:true})
  const existing=clients.find(c=>new URL(c.url).origin===self.location.origin)
  if(existing){await existing.navigate(target.href);return existing.focus()}
  return self.clients.openWindow(target.href)
 })())
})
