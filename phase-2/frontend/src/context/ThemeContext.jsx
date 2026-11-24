import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const ThemeContext = createContext(null)

// Bumped from 'cpa.theme' to drop preferences saved under the old behaviour.
// That matters: the effect below persists whatever initialTheme() returned, so
// anyone who opened the app on a dark-mode OS had 'dark' written to storage and
// would keep seeing dark however the default changed. The suffix resets that
// once; the toggle still works normally afterwards.
const STORAGE_KEY = 'cpa.theme.v2'

//: Light is the product default. The OS preference is deliberately not
//: consulted: this is a content tool whose output is reviewed against white
//: social and web surfaces, so the editing surface should match. Users who
//: want dark have the toggle in the header, and that choice is remembered.
const DEFAULT_THEME = 'light'

function initialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    /* localStorage can throw in private browsing; fall through to the default */
  }
  return DEFAULT_THEME
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(initialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  const value = useMemo(
    () => ({ theme, isDark: theme === 'dark', setTheme, toggle }),
    [theme, toggle],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside a ThemeProvider')
  return context
}
