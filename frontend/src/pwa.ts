import { registerSW } from 'virtual:pwa-register'

export function registerPlayTrackServiceWorker(): void {
  registerSW({
    immediate: true,
    onRegisteredSW: (_workerUrl, registration) => {
      if (registration) void registration.update().catch(() => {})
    },
  })
}
