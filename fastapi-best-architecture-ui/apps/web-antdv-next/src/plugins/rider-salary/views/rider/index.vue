<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { RiderForm, RiderLeaveCheck, RiderResult } from '../../types/rider';

import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { confirm, useVbenDrawer, VbenButton } from '@vben/common-ui';
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
  getRiderLeaveCheckApi,
  getRiderListApi,
  leaveRiderApi,
  openRiderAccountApi,
  resetRiderPasswordApi,
  updateRiderApi,
} from '../../api/rider';
import MoneyText from '../../components/MoneyText.vue';
import { useReasonModal } from '../../components/use-reason-modal';
import { toDateString } from '../../utils/date';
import PageContainer from '../_shared/PageContainer.vue';
import { querySchema, riderFormSchema, useColumns } from './data';

const router = useRouter();
const route = useRoute();
const { ReasonModal, prompt } = useReasonModal();

const formOptions: VbenFormProps = {
  collapsed: false,
  schema: querySchema,
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
  wrapperClass: 'grid-cols-1 md:grid-cols-2 xl:grid-cols-4',
};

const gridOptions: VxeTableGridOptions<RiderResult> = {
  columns: useColumns(onActionClick),
  height: 'auto',
  proxyConfig: {
    ajax: {
      query: async ({ page }, formValues) => {
        const { hire_range, ...rest } = formValues as Record<string, unknown> & {
          hire_range?: [string, string];
        };
        return await getRiderListApi({
          hire_date_from: toDateString(hire_range?.[0]),
          hire_date_to: toDateString(hire_range?.[1]),
          page: page.currentPage,
          size: page.pageSize,
          ...rest,
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
    let transferDate: string | undefined;
    if (
      formData.value?.id &&
      formData.value.site_id &&
      values.site_id !== formData.value.site_id
    ) {
      const result = await prompt({
        dateLabel: '调岗生效日期',
        extraHint:
          '生效日期当天起归属新站点，此前的订单仍归旧站点。请检查方案绑定与进行中的预支。',
        title: '更换站点',
        withDate: true,
      });
      reason = result.reason;
      transferDate = result.date;
    }
    drawerApi.lock();
    try {
      if (formData.value?.id) {
        await updateRiderApi(formData.value.id, {
          ...values,
          reason,
          transfer_date: transferDate,
        });
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
const leaveCheck = ref<RiderLeaveCheck>();
const leaveBlocked = computed(() => (leaveCheck.value?.in_flight_count ?? 0) > 0);
const leaveOutstanding = computed(
  () => Number(leaveCheck.value?.undeducted_amount ?? 0) + Number(leaveCheck.value?.debt_amount ?? 0) > 0,
);
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
    if (leaveBlocked.value) {
      message.warning('请先驳回或发放该骑手的在途预支，再办理离职');
      return;
    }
    const { valid } = await leaveFormApi.validate();
    if (!valid) return;
    const values = await leaveFormApi.getValues<{ leave_date: string }>();
    if (leaveOutstanding.value) {
      await confirm({
        content: `该骑手尚有未扣回预支 ${leaveCheck.value?.undeducted_amount} 元、欠款 ${leaveCheck.value?.debt_amount} 元。离职结算时从最后一期工资中扣回，不足部分需线下追回。确认继续办理离职？`,
        icon: 'warning',
      });
    }
    const { reason } = await prompt({ title: '离职原因' });
    leaveDrawerApi.lock();
    try {
      await leaveRiderApi(pk, {
        confirm_outstanding: leaveOutstanding.value,
        leave_date: values.leave_date,
        reason,
      });
      message.success('已办理离职');
      await leaveDrawerApi.close();
      onRefresh();
    } finally {
      leaveDrawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    leaveFormApi.resetForm();
    leaveCheck.value = undefined;
    const pk = leaveTarget.value?.id;
    if (pk) leaveCheck.value = await getRiderLeaveCheckApi(pk);
  },
});

onMounted(() => {
  const riderId = Number(route.query.rider_id);
  if (Number.isFinite(riderId) && riderId > 0) {
    const tab = typeof route.query.tab === 'string' ? route.query.tab : undefined;
    router.replace({
      path: `/rider-salary/rider/${riderId}`,
      query: tab ? { tab } : {},
    });
    return;
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
      <a-alert
        v-if="leaveBlocked"
        class="mb-4"
        show-icon
        type="error"
        :message="`该骑手有 ${leaveCheck?.in_flight_count} 笔待审核或待发放的预支，请先驳回或发放后再办理离职`"
      />
      <a-alert v-else-if="leaveOutstanding" class="mb-4" show-icon type="warning">
        <template #message>
          尚有未扣回预支 <MoneyText :value="leaveCheck?.undeducted_amount" /> 元、欠款
          <MoneyText :value="leaveCheck?.debt_amount" /> 元，将在离职结算时从最后一期工资中扣回
        </template>
      </a-alert>
      <LeaveForm />
    </LeaveDrawer>
    <ReasonModal />
  </PageContainer>
</template>
