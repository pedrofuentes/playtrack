document.documentElement.classList.add('js')

const toggle = document.querySelector('.nav-toggle')
const navigation = document.querySelector('#site-nav')

toggle?.addEventListener('click', () => {
  const open = toggle.getAttribute('aria-expanded') !== 'true'
  toggle.setAttribute('aria-expanded', String(open))
  navigation?.classList.toggle('is-open', open)
})

navigation?.addEventListener('click', (event) => {
  if (!(event.target instanceof HTMLAnchorElement)) return
  toggle?.setAttribute('aria-expanded', 'false')
  navigation.classList.remove('is-open')
})

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const reveals = document.querySelectorAll('.reveal')

if (reducedMotion || !('IntersectionObserver' in window)) {
  reveals.forEach((element) => element.classList.add('is-visible'))
} else {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return
      entry.target.classList.add('is-visible')
      observer.unobserve(entry.target)
    })
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 })
  reveals.forEach((element) => observer.observe(element))
}

const selectPrompt = (button, code) => {
  const range = document.createRange()
  range.selectNodeContents(code)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
  button.textContent = 'Press ⌘C / Ctrl+C'
}

document.querySelectorAll('.copy-button').forEach((button) => {
  button.addEventListener('click', () => {
    const code = button.closest('.code-card')?.querySelector('pre code')
    if (!code) return
    const text = code.textContent ?? ''

    if (!navigator.clipboard?.writeText) {
      selectPrompt(button, code)
      return
    }

    navigator.clipboard.writeText(text).then(() => {
      button.textContent = 'Copied'
      setTimeout(() => {
        button.textContent = 'Copy prompt'
      }, 2000)
    }).catch(() => selectPrompt(button, code))
  })
})
