import { useEffect } from 'react'

interface WorkspaceShortcutActions {
  togglePlayback: () => void
  stepFrames: (delta: number) => void
  primaryAction: () => void
  openLibrary: () => void
  closeSurface: () => void
}

export function useWorkspaceShortcuts(actions: WorkspaceShortcutActions): void {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return

      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === 'k') {
        event.preventDefault()
        actions.openLibrary()
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return

      if (event.key === ' ') {
        event.preventDefault()
        actions.togglePlayback()
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        actions.stepFrames(-1)
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        actions.stepFrames(1)
      } else if (event.key === 'Enter') {
        event.preventDefault()
        actions.primaryAction()
      } else if (event.key === 'Escape') {
        actions.closeSurface()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [actions])
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('input, textarea, select, button, a')) return true
  return target.closest('[contenteditable="true"]') !== null
}
