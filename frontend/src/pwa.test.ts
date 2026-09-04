import { beforeEach, expect, it, vi } from 'vitest'

const registerSW = vi.hoisted(() => vi.fn())

vi.mock('virtual:pwa-register', () => ({ registerSW }))

import { registerPlayTrackServiceWorker } from './pwa'

beforeEach(() => {
  registerSW.mockClear()
})

it('checks for a new service worker immediately after registration', async () => {
  const update = vi.fn().mockResolvedValue(undefined)
  registerPlayTrackServiceWorker()

  const options = registerSW.mock.calls[0][0]
  await options.onRegisteredSW?.(
    '/sw.js',
    { update } as unknown as ServiceWorkerRegistration,
  )

  expect(options.immediate).toBe(true)
  expect(update).toHaveBeenCalledOnce()
})
