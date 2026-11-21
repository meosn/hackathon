import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { queryClient } from '../../api/client'
import { NotificationsSettings } from './NotificationsSettings'
const previous=Object.getOwnPropertyDescriptor(navigator,'serviceWorker')
afterEach(()=>{cleanup();queryClient.clear();vi.restoreAllMocks();vi.unstubAllGlobals();if(previous)Object.defineProperty(navigator,'serviceWorker',previous);else delete (navigator as unknown as Record<string,unknown>).serviceWorker})
function show(){render(<QueryClientProvider client={queryClient}><NotificationsSettings/></QueryClientProvider>)}
it('explains Home Screen installation when push is unsupported',()=>{
 vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({available:true,public_key:'test'})))
 show()
 expect(screen.getByText(/Home Screen/)).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'Enable on this device'})).not.toBeInTheDocument()
})
it('asks permission only on the enable click and never subscribes after a denial',async()=>{
 const permission=vi.fn().mockResolvedValue('denied')
 vi.stubGlobal('Notification',{requestPermission:permission})
 vi.stubGlobal('PushManager',function(){})
 const reg={pushManager:{getSubscription:vi.fn().mockResolvedValue(null),subscribe:vi.fn()}}
 Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:{register:vi.fn().mockResolvedValue(reg),ready:Promise.resolve(reg)}})
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response(JSON.stringify({available:true,public_key:'test'}),{headers:{'Content-Type':'application/json'}}))
 show()
 const enable=screen.getByRole('button',{name:'Enable on this device'})
 await waitFor(()=>expect(enable).toBeEnabled())
 expect(permission).not.toHaveBeenCalled()
 fireEvent.click(enable)
 await screen.findByText(/Notifications are blocked/)
 expect(permission).toHaveBeenCalledOnce()
 expect(reg.pushManager.subscribe).not.toHaveBeenCalled()
 expect(fetcher.mock.calls.every(([path])=>!String(path).endsWith('/subscriptions'))).toBe(true)
})
