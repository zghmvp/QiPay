<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { RiderForm, RiderResult } from '../../types/rider';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useVbenDrawer, VbenButton } from '@vben/common-ui';
import { MaterialSymbolsAdd } from '@vben/icons';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { useVbenVxeGrid } from '#/adapter/vxe-table';

import {
  createRiderApi,
  deleteRiderApi,
  disableRiderAccountApi,
  enableRiderAccountApi,
  getRiderApi,
  getRiderListApi,
  leaveRiderApi,
  openRiderAccountApi,
  resetRiderPasswordApi,
  updateRiderApi,
} from '../../api/rider';
import { useReasonModal } from '../../components/use-reason-modal';
import PageContainer from '../_shared/PageContainer.vue';
import { querySchema, riderFormSchema, useColumns } from './data';

const router = useRouter();
const route = useRoute();
const { ReasonModal, prompt } = useReasonModal();

function queryStr(key: string) {
  const raw = route.query[key];
  const v = Array.isArray(raw) ? raw[0] : raw;
  return typeof v === 'string' && v ? v : undefined;
}

function queryNum(key: string) {
  const n = Number(queryStr(key));
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const initialStatus = queryStr('status');
const initialSiteId = queryNum('site_id');
const fromNoPlan = queryStr('from') === 'no_plan';

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: querySchema.map((item) => {
    if (item.fieldName === 'status' && initialStatus) {
      return { ...item, defaultValue: initialStatus };
    }
    if (item.fieldName === 'site_id' && initialSiteId) {
      return { ...item, defaultValue: initialSiteId };
    }
    return item;
  }),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<RiderResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        return await getRiderListApi({
          page: page.currentPage,
          size: page.pageSize,
          ...formValues,
        });
      },
    },
  },
  rowConfig: { keyField: 'id' },
  toolbarConfig: {
    custom: true,
    refresh: true,
    refreshOptions: { code: 'query' },
  },
};

const [Grid, gridApi] = useVbenVxeGrid({ formOptions, gridOptions });

function onRefresh() {
  gridApi.query();
}

async function onActionClick({ code, row }: OnActionClickParams<RiderResult>) {
  switch (code) {
    case 'profile': {
      router.push(`/rider-salary/rider/${row.id}`);
      break;
    }
    case 'binding': {
      router.push(`/rider-salary/rider/${row.id}?tab=binding`);
      break;
    }
    case 'delete': {
      await deleteRiderApi(row.id);
      message.success(`已删除骑手 ${row.name}`);
      onRefresh();
      break;
    }
    case 'disable-account': {
      const { reason } = await prompt({ title: '停用账号原因' });
      await disableRiderAccountApi(row.id, { reason });
      message.success('已停用账号');
      onRefresh();
      break;
    }
    case 'edit': {
      drawerApi.setData(row).open();
      break;
    }
    case 'employ': {
      router.push(`/rider-salary/rider/${row.id}?tab=employ`);
      break;
    }
    case 'enable-account': {
      const { reason } = await prompt({
        reasonRequired: false,
        title: '启用账号',
      });
      await enableRiderAccountApi(row.id, { reason });
      message.success('已启用账号');
      onRefresh();
      break;
    }
    case 'leave': {
      leaveTarget.value = row;
      leaveDrawerApi.open();
      break;
    }
    case 'open-account': {
      const { password, reason } = await prompt({
        extraHint: row.phone
          ? `将开通账号，用户名为工号 ${row.job_no}，初始密码默认为手机号后 6 位。`
          : '该骑手无手机号，请指定初始密码。',
        password: !row.phone,
        passwordRequired: !row.phone,
        title: '开通骑手账号',
      });
      await openRiderAccountApi(row.id, { password, reason });
      message.success(
        `已开通账号，用户名为工号 ${row.job_no}，初始密码为手机号后 6 位，请提示骑手首次登录后修改密码。`,
      );
      onRefresh();
      break;
    }
    case 'reset-password': {
      const { password, reason } = await prompt({
        password: true,
        reasonRequired: false,
        title: '重置骑手密码',
      });
      await resetRiderPasswordApi(row.id, { password, reason });
      message.success('已重置密码');
      onRefresh();
      break;
    }
  }
}

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: riderFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number; site_id?: number }>();
const drawerTitle = computed(() => (formData.value?.id ? '编辑骑手' : '新增骑手'));

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[520px]',
  destroyOnClose: true,
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<RiderForm>();
    let reason: string | undefined;
    if (
      formData.value?.id &&
      formData.value.site_id &&
      values.site_id !== formData.value.site_id
    ) {
      const result = await prompt({
        extraHint: '更换站点不会改写历史订单。请检查方案绑定与进行中的预支。',
        title: '更换站点原因',
      });
      reason = result.reason;
    }
    drawerApi.lock();
    try {
      if (formData.value?.id) {
        await updateRiderApi(formData.value.id, { ...values, reason });
      } else {
        await createRiderApi(values);
      }
      message.success('操作成功');
      await drawerApi.close();
      onRefresh();
    } finally {
      drawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<RiderResult>();
    formApi.resetForm();
    if (data?.id) {
      formData.value = { id: data.id, site_id: data.site_id };
      formApi.setValues(data);
    } else {
      formData.value = undefined;
    }
  },
});

const leaveTarget = ref<RiderResult>();
const [LeaveForm, leaveFormApi] = useVbenForm({
  layout: 'vertical',
  schema: [
    {
      component: 'DatePicker',
      componentProps: {
        format: 'YYYY-MM-DD',
        style: { width: '100%' },
        valueFormat: 'YYYY-MM-DD',
      },
      fieldName: 'leave_date',
      label: '离职日期',
      rules: 'required',
    },
  ],
  showDefaultActions: false,
});

const [LeaveDrawer, leaveDrawerApi] = useVbenDrawer({
  class: 'w-[420px]',
  confirmText: '确认离职',
  destroyOnClose: true,
  async onConfirm() {
    const pk = leaveTarget.value?.id;
    if (!pk) return;
    const { valid } = await leaveFormApi.validate();
    if (!valid) return;
    const values = await leaveFormApi.getValues<{ leave_date: string }>();
    const { reason } = await prompt({ title: '离职原因' });
    leaveDrawerApi.lock();
    try {
      await leaveRiderApi(pk, { leave_date: values.leave_date, reason });
      message.success('已办理离职');
      await leaveDrawerApi.close();
      onRefresh();
    } finally {
      leaveDrawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    leaveFormApi.resetForm();
  },
});

onMounted(() => {
  const riderId = Number(route.query.rider_id);
  if (Number.isFinite(riderId) && riderId > 0) {
    const tab = typeof route.query.tab === 'string' ? route.query.tab : undefined;
    const month = queryStr('month');
    router.replace({
      path: `/rider-salary/rider/${riderId}`,
      query: {
        ...(tab ? { tab } : {}),
        ...(month ? { month } : {}),
      },
    });
    return;
  }
  const values: Record<string, unknown> = {};
  if (initialStatus) values.status = initialStatus;
  if (initialSiteId) values.site_id = initialSiteId;
  if (Object.keys(values).length) {
    void gridApi.formApi.setValues(values);
  }
  const editId = Number(route.query.edit_id);
  if (Number.isFinite(editId) && editId > 0) {
    void getRiderApi(editId).then((row) => {
      if (row) drawerApi.setData(row).open();
    });
  }
});
</script>

<template>
  <PageContainer>
    <a-alert
      v-if="fromNoPlan"
      class="mb-2"
      data-testid="rider-list-no-plan-scope"
      show-icon
      type="info"
      message="无方案日待办：请点「方案绑定」进入该骑手绑定时间轴，不要只打开日历。"
    />
    <a-alert
      v-if="initialStatus === 'on_job'"
      class="mb-2"
      data-testid="rider-list-status-scope"
      show-icon
      type="info"
      message="已按工作台跳转筛选：在职骑手"
    />
    <a-alert
      v-if="initialStatus === 'resigned'"
      class="mb-2"
      data-testid="rider-list-resigned-scope"
      show-icon
      type="info"
      message="已按工作台跳转筛选：离职骑手"
    />
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:rider:add'"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          新增骑手
        </VbenButton>
      </template>
      <template #plan="{ row }">
        <span v-if="row.plan_short_name" class="inline-flex items-center gap-1">
          <span
            class="inline-block size-2 rounded-full"
            :style="{ background: row.plan_color || '#1677ff' }"
          ></span>
          {{ row.plan_short_name }}
        </span>
        <span v-else class="text-muted-foreground">未绑定</span>
      </template>
    </Grid>
    <Drawer :title="drawerTitle">
      <Form />
    </Drawer>
    <LeaveDrawer title="骑手离职">
      <LeaveForm />
    </LeaveDrawer>
    <ReasonModal />
  </PageContainer>
</template>
