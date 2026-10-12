<script lang="ts" setup>
import type { VbenFormProps } from '@vben/common-ui';

import type { AdvanceResult } from '../../types/advance';
import type { MoneyValue } from '../../types/common';
import type {
  BatchIssuedPassword,
  RiderForm,
  RiderResult,
} from '../../types/rider';

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

import { getAdvanceListApi } from '../../api/advance';
import {
  createRiderApi,
  deleteRiderApi,
  disableRiderAccountApi,
  enableRiderAccountApi,
  getRiderApi,
  getRiderListApi,
  leaveRiderApi,
  openRiderAccountApi,
  openRiderAccountsBatchApi,
  resetRiderPasswordApi,
  resetRiderPasswordsBatchApi,
  updateRiderApi,
} from '../../api/rider';
import { useReasonModal } from '../../components/use-reason-modal';
import { LIST_OPEN_CODES } from '../../constants/access';
import { formatMoney } from '../../utils/money';
import { parseBatchRowErrors } from '../adjustment/batch-errors';
import { statusFromQuery, withStatusDefault } from './list-query';
import {
  batchOpenAccountHint,
  batchResetPasswordHint,
  openAccountHint,
  resetPasswordHint,
  specifiedPasswordMessage,
} from './password-hint';
import PageContainer from '../_shared/PageContainer.vue';
import { batchAccountBody, formatIssuedPasswords, selectedRiderIds } from './batch-ops';
import BatchBindingDrawer from './components/BatchBindingDrawer.vue';
import LeaveSettlementPanel from './components/LeaveSettlementPanel.vue';
import {
  querySchema,
  riderEditFormSchema,
  riderFormSchema,
  useColumns,
} from './data';

const router = useRouter();
const route = useRoute();
const initialStatus = statusFromQuery(route.query.status);
const { ReasonModal, prompt } = useReasonModal();
const issuedOpen = ref(false);
const issuedJobNo = ref('');
const issuedPassword = ref('');
const batchIssuedOpen = ref(false);
const batchIssued = ref<BatchIssuedPassword[]>([]);
const batchErrorOpen = ref(false);
const batchErrors = ref<string[]>([]);

function showIssuedPassword(
  jobNo: string,
  password: null | string | undefined,
  action: string,
) {
  if (password) {
    issuedJobNo.value = jobNo;
    issuedPassword.value = password;
    issuedOpen.value = true;
    return;
  }
  message.success(specifiedPasswordMessage(action));
}

async function copyIssuedPassword() {
  try {
    await navigator.clipboard.writeText(issuedPassword.value);
    message.success('已复制初始密码');
  } catch {
    message.warning('复制失败，请手动选择密码复制');
    return Promise.reject(new Error('复制失败'));
  }
}

const formOptions: VbenFormProps = {
  collapsed: true,
  schema: withStatusDefault(querySchema, initialStatus),
  showCollapseButton: true,
  submitButtonOptions: { content: '查询' },
};

const gridOptions: VxeTableGridOptions<RiderResult> = {
  checkboxConfig: { highlight: true },
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
const [BatchBindDrawer, batchBindApi] = useVbenDrawer({
  connectedComponent: BatchBindingDrawer,
});

function onRefresh() {
  gridApi.query();
}

function currentRiders(): RiderResult[] {
  const grid = gridApi.grid;
  if (!grid) return [];
  return grid.getCheckboxRecords(true) as RiderResult[];
}

function openBatchBind() {
  const riders = currentRiders();
  if (selectedRiderIds(riders).length === 0) {
    message.warning('请先勾选骑手');
    return;
  }
  batchBindApi.setData({ onSuccess: onRefresh, riders }).open();
}

function showBatchPasswords(items: BatchIssuedPassword[]) {
  batchIssued.value = items;
  batchIssuedOpen.value = true;
}

async function copyBatchPasswords() {
  try {
    await navigator.clipboard.writeText(formatIssuedPasswords(batchIssued.value));
    message.success('已复制全部初始密码');
  } catch {
    message.warning('复制失败，请手动选择密码复制');
    return Promise.reject(new Error('复制失败'));
  }
}

async function runBatchAccount(kind: 'open' | 'reset') {
  const ids = selectedRiderIds(currentRiders());
  if (ids.length === 0) {
    message.warning('请先勾选骑手');
    return;
  }
  const opening = kind === 'open';
  const { reason } = await prompt({
    extraHint: opening
      ? batchOpenAccountHint(ids.length)
      : batchResetPasswordHint(ids.length),
    reasonRequired: opening,
    title: opening ? '批量开通账号' : '批量重置密码',
  });
  try {
    const issued = opening
      ? await openRiderAccountsBatchApi(batchAccountBody(ids, reason))
      : await resetRiderPasswordsBatchApi(batchAccountBody(ids, reason));
    showBatchPasswords(issued?.items ?? []);
    onRefresh();
  } catch (error: unknown) {
    const parsed = parseBatchRowErrors(error);
    if (parsed.length > 0) {
      batchErrors.value = parsed.map((item) => `第 ${item.row} 名：${item.reason}`);
      batchErrorOpen.value = true;
    }
  }
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
      leavePhase.value = 'form';
      leaveDate.value = '';
      leaveTarget.value = row;
      leaveDrawerApi.setState({ confirmText: '确认离职' });
      leaveDrawerApi.open();
      break;
    }
    case 'leave-settlement': {
      leavePhase.value = 'settle';
      leaveDate.value = row.leave_date ?? '';
      leaveTarget.value = row;
      leaveDrawerApi.setState({ confirmText: '完成' });
      leaveDrawerApi.open();
      break;
    }
    case 'open-account': {
      const { password, reason } = await prompt({
        extraHint: openAccountHint(row.job_no),
        password: true,
        passwordRequired: false,
        title: '开通骑手账号',
      });
      const issued = await openRiderAccountApi(row.id, { password, reason });
      showIssuedPassword(row.job_no, issued?.initial_password, '开通账号');
      onRefresh();
      break;
    }
    case 'reset-password': {
      const { password, reason } = await prompt({
        extraHint: resetPasswordHint(),
        password: true,
        passwordRequired: false,
        reasonRequired: false,
        title: '重置骑手密码',
      });
      const issued = await resetRiderPasswordApi(row.id, { password, reason });
      showIssuedPassword(row.job_no, issued?.initial_password, '重置密码');
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
        await updateRiderApi(formData.value.id, {
          advance_limit: values.advance_limit,
          hire_date: values.hire_date,
          job_no: values.job_no,
          name: values.name,
          phone: values.phone,
          reason,
          remark: values.remark,
          settle_cycle_override: values.settle_cycle_override,
          site_id: values.site_id,
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
    const editing = Boolean(data?.id);
    formApi.setState({
      schema: editing ? riderEditFormSchema : riderFormSchema,
    });
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
const leavePreview = ref<string[]>([]);
const leavePhase = ref<'form' | 'settle'>('form');
const leaveDate = ref('');

function moneyNumber(value: MoneyValue): number {
  const amount = Number(value ?? 0);
  return Number.isFinite(amount) ? amount : 0;
}

function buildLeavePreview(items: AdvanceResult[]): string[] {
  const hints: string[] = [];
  const pending = items.filter((item) => item.status === 'pending').length;
  const toPay = items.filter((item) => item.status === 'to_pay').length;
  const outstanding = items
    .filter((item) => item.status === 'paid')
    .reduce(
      (total, item) => total + Math.max(moneyNumber(item.remaining_amount), 0),
      0,
    );
  if (pending > 0) {
    hints.push('待审核的预支将在确认离职后自动驳回。');
  }
  if (toPay > 0) {
    hints.push('该骑手有待发放的预支，离职后请取消，不要标记发放。');
  }
  if (outstanding > 0) {
    hints.push(
      `该骑手尚有预支待抵扣 ${formatMoney(outstanding)} 元，离职后将在未锁账周期继续抵扣。`,
    );
  }
  return hints;
}

async function loadLeavePreview(riderId: number) {
  leavePreview.value = [];
  try {
    const page = await getAdvanceListApi({
      page: 1,
      rider_id: riderId,
      size: 100,
    });
    leavePreview.value = buildLeavePreview(page.items ?? []);
  } catch {
    leavePreview.value = [];
  }
}

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
  class: 'w-[480px]',
  confirmText: '确认离职',
  destroyOnClose: true,
  async onConfirm() {
    if (leavePhase.value === 'settle') {
      await leaveDrawerApi.close();
      onRefresh();
      return;
    }
    const pk = leaveTarget.value?.id;
    if (!pk) return;
    const { valid } = await leaveFormApi.validate();
    if (!valid) return;
    const values = await leaveFormApi.getValues<{ leave_date: string }>();
    const { reason } = await prompt({ title: '离职原因' });
    leaveDrawerApi.lock();
    try {
      const result = await leaveRiderApi(pk, {
        leave_date: values.leave_date,
        reason,
      });
      message.success('已办理离职');
      for (const hint of result?.hints ?? []) {
        message.warning(hint);
      }
      leaveDate.value = values.leave_date;
      leavePhase.value = 'settle';
      leaveDrawerApi.setState({ confirmText: '完成' });
      onRefresh();
    } finally {
      leaveDrawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) {
      leavePreview.value = [];
      leavePhase.value = 'form';
      leaveDate.value = '';
      leaveDrawerApi.setState({ confirmText: '确认离职' });
      return;
    }
    if (leavePhase.value === 'form') {
      leaveFormApi.resetForm();
    }
    const riderId = leaveTarget.value?.id;
    if (riderId) {
      void loadLeavePreview(riderId);
    }
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
  if (initialStatus) {
    void gridApi.formApi.setValues({ status: initialStatus });
  }
});
</script>

<template>
  <PageContainer v-access:code="LIST_OPEN_CODES.rider">
    <Grid>
      <template #toolbar-actions>
        <VbenButton
          v-access:code="'rs:rider:add'"
          @click="() => drawerApi.setData(null).open()"
        >
          <MaterialSymbolsAdd class="size-5" />
          新增骑手
        </VbenButton>
        <VbenButton
          v-access:code="'rs:rider:binding'"
          class="ml-2"
          @click="openBatchBind"
        >
          批量绑定方案
        </VbenButton>
        <VbenButton
          v-access:code="'rs:rider:account'"
          class="ml-2"
          @click="runBatchAccount('open')"
        >
          批量开通账号
        </VbenButton>
        <VbenButton
          v-access:code="'rs:rider:account'"
          class="ml-2"
          @click="runBatchAccount('reset')"
        >
          批量重置密码
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
    <LeaveDrawer :title="leavePhase === 'settle' ? '离职结算' : '骑手离职'">
      <LeaveSettlementPanel
        v-if="leavePhase === 'settle' && leaveTarget?.id && leaveDate"
        :hints="leavePreview"
        :leave-date="leaveDate"
        :rider-id="leaveTarget.id"
      />
      <div v-else class="flex flex-col gap-3">
        <a-alert
          show-icon
          type="info"
          message="离职日当天仍计薪。若该日所在周期已锁账，将拒绝离职，请先走反冲补发。待审核预支会自动驳回；待发放预支不会自动取消。确认后可继续生成离职结算周期，单独算薪、锁账和标记发薪。"
        />
        <a-alert
          v-for="(hint, index) in leavePreview"
          :key="index"
          show-icon
          type="warning"
          :message="hint"
        />
        <LeaveForm />
      </div>
    </LeaveDrawer>
    <BatchBindDrawer />
    <ReasonModal />
    <a-modal
      v-model:open="batchIssuedOpen"
      title="初始密码仅展示一次"
      width="720px"
      ok-text="复制全部密码"
      cancel-text="关闭"
      @ok="copyBatchPasswords"
    >
      <div class="flex flex-col gap-3">
        <p>
          共 {{ batchIssued.length }} 人。请立即复制并告知骑手。关闭后无法再次查看。每人首次登录必须修改密码。
        </p>
        <a-table
          :data-source="batchIssued"
          :pagination="false"
          row-key="rider_id"
          size="small"
        >
          <a-table-column data-index="username" title="工号" />
          <a-table-column data-index="name" title="姓名" />
          <a-table-column data-index="initial_password" title="初始密码" />
        </a-table>
      </div>
    </a-modal>
    <a-modal
      v-model:open="batchErrorOpen"
      title="批量操作未完成"
      :footer="null"
    >
      <div class="flex max-h-80 flex-col gap-2 overflow-auto">
        <a-alert
          v-for="(line, index) in batchErrors"
          :key="index"
          show-icon
          type="error"
          :message="line"
        />
      </div>
    </a-modal>
    <a-modal
      v-model:open="issuedOpen"
      title="初始密码仅展示一次"
      ok-text="复制密码"
      cancel-text="关闭"
      @ok="copyIssuedPassword"
    >
      <div class="flex flex-col gap-3">
        <p>用户名：{{ issuedJobNo }}</p>
        <a-input :value="issuedPassword" readonly />
        <p>请立即复制并告知骑手。关闭后无法再次查看。首次登录必须修改密码。</p>
      </div>
    </a-modal>
  </PageContainer>
</template>
