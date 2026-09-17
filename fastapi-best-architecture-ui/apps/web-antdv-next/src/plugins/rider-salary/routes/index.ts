import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'mdi:moped-outline',
      title: '骑手薪资',
    },
    name: 'RiderSalary',
    path: '/rider-salary',
    redirect: '/rider-salary/dashboard',
    children: [
      {
        component: () => import('../views/dashboard/index.vue'),
        meta: { icon: 'lucide:layout-dashboard', title: '工作台' },
        name: 'RiderSalaryDashboard',
        path: '/rider-salary/dashboard',
      },
      {
        component: () => import('../views/site/index.vue'),
        meta: { icon: 'lucide:building-2', title: '站点管理' },
        name: 'RiderSalarySite',
        path: '/rider-salary/site',
      },
      {
        component: () => import('../views/rider/index.vue'),
        meta: { icon: 'lucide:users', title: '骑手管理' },
        name: 'RiderSalaryRider',
        path: '/rider-salary/rider',
      },
      {
        component: () => import('../views/rider/detail.vue'),
        meta: {
          hideInMenu: true,
          icon: 'lucide:user-round',
          title: '骑手档案',
        },
        name: 'RiderSalaryRiderDetail',
        path: '/rider-salary/rider/:id',
      },
      {
        component: () => import('../views/subject/index.vue'),
        meta: { icon: 'lucide:list', title: '科目管理' },
        name: 'RiderSalarySubject',
        path: '/rider-salary/subject',
      },
      {
        component: () => import('../views/plan/index.vue'),
        meta: { icon: 'lucide:file-spreadsheet', title: '薪资方案' },
        name: 'RiderSalaryPlan',
        path: '/rider-salary/plan',
      },
      {
        component: () => import('../views/plan/editor.vue'),
        meta: {
          hideInMenu: true,
          icon: 'lucide:pencil-ruler',
          title: '方案编辑器',
        },
        name: 'RiderSalaryPlanEditor',
        path: '/rider-salary/plan/editor/:versionId',
      },
      {
        component: () => import('../views/order/index.vue'),
        meta: { icon: 'lucide:clipboard-list', title: '订单明细' },
        name: 'RiderSalaryOrder',
        path: '/rider-salary/order',
      },
      {
        component: () => import('../views/adjustment/index.vue'),
        meta: { icon: 'lucide:plus-minus', title: '奖惩录入' },
        name: 'RiderSalaryAdjustment',
        path: '/rider-salary/adjustment',
      },
      {
        component: () => import('../views/period/index.vue'),
        meta: { icon: 'lucide:calendar-range', title: '结算周期' },
        name: 'RiderSalaryPeriod',
        path: '/rider-salary/period',
      },
      {
        component: () => import('../views/period/calculate.vue'),
        meta: {
          hideInMenu: true,
          icon: 'lucide:calculator',
          title: '周期算薪',
        },
        name: 'RiderSalaryPeriodCalculate',
        path: '/rider-salary/period/:id/calculate',
      },
      {
        component: () => import('../views/payroll/index.vue'),
        meta: { icon: 'lucide:wallet', title: '薪资结果' },
        name: 'RiderSalaryPayroll',
        path: '/rider-salary/payroll',
      },
      {
        component: () => import('../views/payroll/detail.vue'),
        meta: {
          hideInMenu: true,
          icon: 'lucide:file-text',
          title: '薪资明细',
        },
        name: 'RiderSalaryPayrollDetail',
        path: '/rider-salary/payroll/:id',
      },
      {
        component: () => import('../views/calendar/index.vue'),
        meta: { icon: 'lucide:calendar', title: '薪资日历' },
        name: 'RiderSalaryCalendar',
        path: '/rider-salary/calendar',
      },
      {
        component: () => import('../views/advance/index.vue'),
        meta: { icon: 'lucide:hand-coins', title: '预支审核' },
        name: 'RiderSalaryAdvance',
        path: '/rider-salary/advance',
      },
      {
        component: () => import('../views/audit/index.vue'),
        meta: { icon: 'lucide:scroll-text', title: '操作日志' },
        name: 'RiderSalaryAudit',
        path: '/rider-salary/audit',
      },
    ],
  },
];

export default routes;
