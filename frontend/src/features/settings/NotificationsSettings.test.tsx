import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { queryClient } from '../../api/client'
import { NotificationsSettings } from './NotificationsSettings'
const previous=Object.getOwnPropertyDescriptor(navigator,'serviceWorker')
afterEach(()=>{cleanup();queryClient.clear();vi.restoreAllMocks();vi.unstubAllGlobals();if(previous)Object.defineProperty(navigator,'serviceWorker',previous);else delete (navigator as unknown as Record<string,unknown>).serviceWorker})
function show(){render(<QueryClientProvider client={queryClient}><NotificationsSettings/></QueryClientProvider>)}
function setup(permission='default'){
 const reg={pushManager:{getSubscription:vi.fn().mockResolvedValue(null),subscribe:vi.fn()}}
 vi.stubGlobal('Notification',{permission,requestPermission:vi.fn()})
 vi.stubGlobal('PushManager',function(){})
 Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:{register:vi.fn().mockResolvedValue(reg),ready:Promise.resolve(reg)}})
 vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify({available:true,public_key:'AQID',enabled:true}),{headers:{'Content-Type':'application/json'}}))
 return reg
}
it('explains unsupported browser capability without asking permission',()=>{
 vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({available:true,public_key:'AQID'}))
 show()
 expect(screen.getByText(/does not support push/)).toBeInTheDocument()
})
it('never subscribes when browser permission is already denied',async()=>{
 const reg=setup('denied');show()
 await waitFor(()=>expect(screen.getByRole('button',{name:'Enable on this device'})).toBeEnabled())
 fireEvent.click(screen.getByRole('button',{name:'Enable on this device'}))
 await screen.findByText(/Notifications are blocked/)
 expect(reg.pushManager.subscribe).not.toHaveBeenCalled()
})
it('subscribes synchronously inside the click, then saves the endpoint',async()=>{
 const reg=setup();let inClick=false
 reg.pushManager.subscribe.mockImplementation(()=>{
  expect(inClick).toBe(true)
  return Promise.resolve({toJSON:()=>({endpoint:'https://web.push.apple.com/test',keys:{p256dh:'key',auth:'auth'}})})
 })
 show()
 await waitFor(()=>expect(screen.getByRole('button',{name:'Enable on this device'})).toBeEnabled())
 expect(reg.pushManager.subscribe).not.toHaveBeenCalled()
 inClick=true;fireEvent.click(screen.getByRole('button',{name:'Enable on this device'}));inClick=false
 expect(reg.pushManager.subscribe).toHaveBeenCalledOnce()
 await screen.findByRole('button',{name:'Send test'})
 expect(Notification.requestPermission).not.toHaveBeenCalled()
 expect(vi.mocked(fetch).mock.calls.some(([path])=>String(path).endsWith('/subscriptions'))).toBe(true)
})
