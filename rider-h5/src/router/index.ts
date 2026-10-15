import { createRouter, createWebHistory } from 'vue-router'
import { showToast } from 'vant'
import { getToken } from '@/utils/storage'
import { useMenuStore } from '@/stores/menu'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      redirect: '/home',
    },
    {
      path: '/home',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { tab: 'home', feature: 'home', title: '首页' },
    },
    {
      path: '/day/:date',
      name: 'day',
      component: () => import('@/views/DayView.vue'),
      meta: { feature: 'home', title: '当日明细' },
    },
    {
      path: '/adjustments',
      name: 'adjustments',
      component: () => import('@/views/AdjustmentsView.vue'),
      meta: { tab: 'adjustments', feature: 'adjustments', title: '奖惩' },
    },
    {
      path: '/plan',
      name: 'plan',
      component: () => import('@/views/PlanView.vue'),
      meta: { feature: 'plan', title: '当前方案' },
    },
    {
      path: '/advance',
      name: 'advance',
      component: () => import('@/views/AdvanceView.vue'),
      meta: { tab: 'advance', feature: 'advance', title: '预支' },
    },
    {
      path: '/notices',
      name: 'notices',
      component: () => import('@/views/NoticesView.vue'),
      meta: { tab: 'notices', feature: 'notices', title: '公告' },
    },
    {
      path: '/me',
      name: 'me',
      component: () => import('@/views/MeView.vue'),
      meta: { tab: 'me', title: '我的' },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/home',
    },
  ],
})

router.beforeEach(async (to) => {
  const token = getToken()
  if (!to.meta.public && !token) {
    return { path: '/login', replace: true }
  }
  const menus = useMenuStore()
  if (token && !menus.loaded && (to.path === '/login' || to.meta.feature)) {
    try {
      await menus.load()
    } catch {
      menus.loaded = true
    }
  }
  if (to.path === '/login' && token) {
    return { path: menus.landingPath(), replace: true }
  }
  const feature = typeof to.meta.feature === 'string' ? to.meta.feature : ''
  if (!feature || !token) return true
  if (!menus.isOpen(feature)) {
    const target = feature === 'home' || !menus.isOpen('home') ? '/me' : '/home'
    if (to.path === target) return true
    showToast('该功能暂未开放')
    return { path: target, replace: true }
  }
  return true
})

export default router
