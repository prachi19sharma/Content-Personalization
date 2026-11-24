import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  brandsApi,
  catalogApi,
  conversationsApi,
  errorMessage,
  profileApi,
} from '../services/api'
import { useToast } from '../context/ToastContext'

/**
 * Shared app-shell data for the single-domain build: the five marketing agents
 * with this user's per-agent status, the brand profile they all share, and the
 * conversation list in the sidebar. Lives in the layout so the sidebar and
 * pages stay in sync after a chat, a setup, a rename or a delete.
 */
export function useAppData() {
  const toast = useToast()
  const [agents, setAgents] = useState([])
  const [brand, setBrand] = useState(null)
  const [brandProfile, setBrandProfile] = useState(null)
  const [brands, setBrands] = useState([])
  const [activeBrandId, setActiveBrandId] = useState(null)
  const [switchingBrand, setSwitchingBrand] = useState(false)
  const [conversations, setConversations] = useState([])
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [catalogError, setCatalogError] = useState(null)

  const loadCatalog = useCallback(async () => {
    setCatalogError(null)
    try {
      const [agentList, brandCard, savedBrand, brandList] = await Promise.all([
        catalogApi.agents(),
        catalogApi.brand(),
        profileApi.getBrand(),
        brandsApi.list(),
      ])
      setAgents(agentList)
      setBrand(brandCard)
      setBrandProfile(savedBrand)
      setBrands(brandList.brands || [])
      setActiveBrandId(brandList.active_id ?? null)
    } catch (error) {
      setCatalogError(errorMessage(error, 'Could not load the agents'))
    } finally {
      setLoadingCatalog(false)
    }
  }, [])

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await conversationsApi.list({ limit: 60 }))
    } catch (error) {
      console.warn('conversation load failed:', errorMessage(error))
    } finally {
      setLoadingConversations(false)
    }
  }, [])

  useEffect(() => {
    loadCatalog()
    loadConversations()
  }, [loadCatalog, loadConversations])

  /** agent key -> agent summary, for O(1) lookups in message lists. */
  const agentsByKey = useMemo(
    () => Object.fromEntries(agents.map((agent) => [agent.key, agent])),
    [agents],
  )

  const visualAgents = useMemo(
    () => agents.filter((agent) => agent.output_kind !== 'text'),
    [agents],
  )

  const brandConfigured = Boolean(brandProfile?.is_configured)

  const activeBrand = useMemo(
    () => brands.find((item) => item.id === activeBrandId) ?? null,
    [brands, activeBrandId],
  )

  /**
   * Switch brand, then reload everything that is brand-scoped.
   *
   * Agent "Personalized" badges, the conversation sidebar and the memory
   * counts all describe one brand, so leaving any of them stale after a switch
   * would show one client's state under another client's name.
   */
  const switchBrand = useCallback(
    async (brandId) => {
      if (!brandId || brandId === activeBrandId) return
      setSwitchingBrand(true)
      try {
        const next = await brandsApi.activate(brandId)
        setActiveBrandId(next.id)
        await Promise.all([loadCatalog(), loadConversations()])
        toast.success(`Switched to ${next.label}`)
      } catch (error) {
        toast.error(errorMessage(error, 'Could not switch brand'))
      } finally {
        setSwitchingBrand(false)
      }
    },
    [activeBrandId, loadCatalog, loadConversations, toast],
  )

  const createBrand = useCallback(
    async (label) => {
      const created = await brandsApi.create(label)
      setActiveBrandId(created.id)
      await Promise.all([loadCatalog(), loadConversations()])
      toast.success(`${created.label} created — set it up below`)
      return created
    },
    [loadCatalog, loadConversations, toast],
  )

  const renameBrand = useCallback(
    async (brandId, label) => {
      const updated = await brandsApi.rename(brandId, label)
      setBrands((current) =>
        current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
      )
      return updated
    },
    [],
  )

  const deleteBrand = useCallback(
    async (brandId) => {
      await brandsApi.remove(brandId)
      await Promise.all([loadCatalog(), loadConversations()])
    },
    [loadCatalog, loadConversations],
  )

  const renameConversation = useCallback(
    async (conversation, title) => {
      try {
        const updated = await conversationsApi.update(conversation.id, { title })
        setConversations((current) =>
          current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)),
        )
        toast.success('Conversation renamed')
      } catch (error) {
        toast.error(errorMessage(error, 'Rename failed'))
      }
    },
    [toast],
  )

  const deleteConversation = useCallback(
    async (conversationId) => {
      await conversationsApi.remove(conversationId)
      setConversations((current) => current.filter((item) => item.id !== conversationId))
      loadCatalog()
    },
    [loadCatalog],
  )

  return {
    agents,
    agentsByKey,
    visualAgents,
    brand,
    brandProfile,
    brandConfigured,
    brands,
    activeBrand,
    activeBrandId,
    switchingBrand,
    switchBrand,
    createBrand,
    renameBrand,
    deleteBrand,
    conversations,
    loadingCatalog,
    loadingConversations,
    catalogError,
    reloadCatalog: loadCatalog,
    reloadConversations: loadConversations,
    setConversations,
    renameConversation,
    deleteConversation,
  }
}
