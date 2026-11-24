import { useEffect, useRef, useState } from 'react'
import { Building2, Check, ChevronDown, Plus, Spline } from 'lucide-react'
import { useAppShell } from '../layouts/AppLayout'
import { useToast } from '../context/ToastContext'
import { errorMessage } from '../services/api'
import { Spinner } from './ui'

/**
 * Switch which brand (client) the five agents are working for.
 *
 * Each brand keeps its own brand answers, its own per-agent configuration, its
 * own chat history and its own memories. Switching re-points all five agents at
 * that brand, so the same agent can serve any number of clients without the
 * user overwriting the previous one's setup.
 */
export default function BrandSwitcher() {
  const {
    brands,
    activeBrand,
    activeBrandId,
    switchBrand,
    createBrand,
    switchingBrand,
  } = useAppShell()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const wrapRef = useRef(null)
  const inputRef = useRef(null)

  // Close on an outside click or Escape, as a menu should.
  useEffect(() => {
    if (!open) return undefined
    const onClick = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) {
        setOpen(false)
        setCreating(false)
      }
    }
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
        setCreating(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (creating) inputRef.current?.focus()
  }, [creating])

  const submitNew = async (event) => {
    event.preventDefault()
    const label = draft.trim()
    if (!label) return
    setBusy(true)
    try {
      await createBrand(label)
      setDraft('')
      setCreating(false)
      setOpen(false)
    } catch (error) {
      toast.error(errorMessage(error, 'Could not create the brand'))
    } finally {
      setBusy(false)
    }
  }

  const label = activeBrand?.label || 'No brand yet'

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left text-sm transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
          {switchingBrand ? (
            <Spinner className="h-3.5 w-3.5" />
          ) : (
            <Building2 className="h-4 w-4" aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{label}</span>
          <span className="block text-[0.7rem] text-slate-500 dark:text-slate-400">
            {brands.length > 1 ? `${brands.length} brands` : 'Brand'}
          </span>
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div
          className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
          role="listbox"
        >
          <ul className="max-h-64 overflow-y-auto py-1">
            {brands.map((item) => {
              const active = item.id === activeBrandId
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    disabled={switchingBrand}
                    onClick={() => {
                      setOpen(false)
                      switchBrand(item.id)
                    }}
                    className={`flex w-full items-center gap-2 px-2.5 py-2 text-left text-sm transition-colors disabled:opacity-60 ${
                      active
                        ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-200'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800'
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{item.label}</span>
                      <span className="block text-[0.7rem] text-slate-500 dark:text-slate-400">
                        {item.is_configured ? 'Set up' : 'Needs setup'}
                      </span>
                    </span>
                    {active && (
                      <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>

          <div className="border-t divider p-1.5">
            {creating ? (
              <form onSubmit={submitNew} className="flex items-center gap-1.5">
                <input
                  ref={inputRef}
                  className="input h-8 py-1 text-sm"
                  value={draft}
                  maxLength={160}
                  placeholder="Client or brand name"
                  onChange={(event) => setDraft(event.target.value)}
                />
                <button
                  type="submit"
                  className="btn-primary h-8 shrink-0 px-2 py-1 text-xs"
                  disabled={busy || !draft.trim()}
                >
                  {busy ? <Spinner className="h-3 w-3" /> : 'Add'}
                </button>
              </form>
            ) : (
              <button
                type="button"
                className="btn-ghost w-full justify-start px-2 py-1.5 text-xs"
                onClick={() => setCreating(true)}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                New brand
              </button>
            )}
            <p className="mt-1 flex items-start gap-1.5 px-1.5 pb-0.5 text-[0.68rem] leading-snug text-slate-500 dark:text-slate-400">
              <Spline className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
              Each brand keeps its own agent setup, chats and memories.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
