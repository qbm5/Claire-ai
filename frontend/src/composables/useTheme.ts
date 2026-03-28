import { ref } from 'vue'

type Theme = 'dark' | 'light'

const stored = localStorage.getItem('theme') as Theme | null
const theme = ref<Theme>(stored === 'light' ? 'light' : 'dark')

function applyClass() {
  if (theme.value === 'light') {
    document.documentElement.classList.add('light')
  } else {
    document.documentElement.classList.remove('light')
  }
}

applyClass()

function toggle() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('theme', theme.value)
  applyClass()
}

function setTheme(t: Theme) {
  theme.value = t
  localStorage.setItem('theme', t)
  applyClass()
}

export function useTheme() {
  return { theme, toggle, setTheme }
}
