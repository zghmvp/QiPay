import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/utils/storage'

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
      meta: { tab: 'home', title: '首页' },
    },
    {
      path: '/day/:date',
      name: 'day',
      component: () => import('@/views/DayView.vue'),
      meta: { title: '当日明细' },
    },
    {
      path: '/adjustments',
      name: 'adjustments',
      component: () => import('@/views/AdjustmentsView.vue'),
      meta: { tab: 'adjustments', title: '奖惩' },
    },
    {
      path: '/plan',
      name: 'plan',
      component: () => import('@/views/PlanView.vue'),
      meta: { title: '当前方案' },
    },
    {
      path: '/advance',
      name: 'advance',
      component: () => import('@/views/AdvanceView.vue'),
      meta: { tab: 'advance', title: '预支' },
    },
    {
      path: '/notices',
      name: 'notices',
      component: () => import('@/views/NoticesView.vue'),
      meta: { tab: 'notices', title: '公告' },
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

router.beforeEach((to) => {
  const token = getToken()
  if (!to.meta.public && !token) {
    return { path: '/login', replace: true }
  }
  if (to.path === '/login' && token) {
    return { path: '/home', replace: true }
  }
  return true
})

export default router
