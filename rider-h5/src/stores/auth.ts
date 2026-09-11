import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getProfile } from '@/api/me'
import { logout as logoutApi } from '@/api/auth'
import { clearToken, getToken, setToken } from '@/utils/storage'
import type { MeProfile } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const profile = ref<MeProfile | null>(null)

  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => profile.value?.name || '')
  const siteName = computed(() => profile.value?.site_name || '')

  function saveToken(value: string) {
    token.value = value
    setToken(value)
  }

  async function loadProfile() {
    profile.value = await getProfile()
    return profile.value
  }

  async function logout() {
    try {
      await logoutApi()
    } catch {
      /* 退出失败仍清理本地会话 */
    }
    token.value = ''
    profile.value = null
    clearToken()
  }

  return {
    token,
    profile,
    isLoggedIn,
    displayName,
    siteName,
    saveToken,
    loadProfile,
    logout,
  }
})
