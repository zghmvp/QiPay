import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getMenus } from '@/api/me'
import type { H5Menus } from '@/types'

const OPEN: H5Menus = {
  show_adjustments: true,
  show_advance: true,
  show_notices: true,
  show_plan: true,
  show_home: true,
  show_home_pay: true,
  show_day_amount: true,
  show_estimate_net: true,
  show_advance_inflight: true,
}

function normalize(data: Partial<H5Menus> | null | undefined): H5Menus {
  const source = data ?? {}
  return {
    show_adjustments: source.show_adjustments !== false,
    show_advance: source.show_advance !== false,
    show_notices: source.show_notices !== false,
    show_plan: source.show_plan !== false,
    show_home: source.show_home !== false,
    show_home_pay: source.show_home_pay !== false,
    show_day_amount: source.show_day_amount !== false,
    show_estimate_net: source.show_estimate_net !== false,
    show_advance_inflight: source.show_advance_inflight !== false,
  }
}

export const useMenuStore = defineStore('h5-menu', () => {
  const flags = ref<H5Menus>({ ...OPEN })
  const loaded = ref(false)

  async function load() {
    flags.value = normalize(await getMenus())
    loaded.value = true
    return flags.value
  }

  function isOpen(feature: string) {
    if (feature === 'adjustments') return flags.value.show_adjustments
    if (feature === 'advance') return flags.value.show_advance
    if (feature === 'notices') return flags.value.show_notices
    if (feature === 'plan') return flags.value.show_plan
    if (feature === 'home' || feature === 'day' || feature === 'calendar' || feature === 'payroll') {
      return flags.value.show_home
    }
    return true
  }

  function landingPath() {
    return flags.value.show_home ? '/home' : '/me'
  }

  function reset() {
    flags.value = { ...OPEN }
    loaded.value = false
  }

  return { flags, loaded, load, isOpen, landingPath, reset }
})
