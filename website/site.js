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
