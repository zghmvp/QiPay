<script lang="ts" setup>
import type { MoneyValue } from '../../../types/common';

import { computed, ref } from 'vue';

import { VbenButton } from '@vben/common-ui';

import { message } from 'antdv-next';

import { createLeaveSettlementApi } from '../../../api/rider';
import {
  calculatePeriodApi,
  getCalcJobApi,
  getPeriodApi,
  lockPeriodWithExpectedStatusApi,
  markPaidPeriodWithExpectedStatusApi,
} from '../../../api/period';
import { describeCalcJob, waitForCalcJob } from '../../period/calc-progress';
import { enumLabel, PERIOD_STATUS_OPTIONS } from '../../../constants/enums';
import { formatMoney } from '../../../utils/money';
import { settlementActions } from '../settlement-actions';

const props = defineProps<{
  hints: string[];
  leaveDate: string;
  riderId: number;
}>();

const busy = ref(false);
const reason = ref('');
const periodId = ref<number>();
const status = ref('');
const startDate = ref('');
const endDate = ref('');
const hint = ref('');
const netTotal = ref<MoneyValue>();
const warnings = ref<string[]>([]);

const actions = computed(() => settlementActions(status.value));
const statusLabel = computed(() =>
  status.value ? enumLabel(PERIOD_STATUS_OPTIONS, status.value) : '',
);

async function refreshPeriod(id: number) {
  const detail = await getPeriodApi(id);
  status.value = detail.status;
  startDate.value = detail.start_date;
  endDate.value = detail.end_date;
  netTotal.value = detail.net_total;
}

async function generate() {
  busy.value = true;
  try {
    const result = await createLeaveSettlementApi(props.riderId);
    periodId.value = result.period_id;
    status.value = result.status;
    startDate.value = result.start_date;
    endDate.value = result.end_date;
    hint.value = result.hint;
    message.success(result.created ? '已生成离职结算周期' : '已沿用已有结算周期');
    await refreshPeriod(result.period_id);
  } finally {
    busy.value = false;
  }
}

async function preview() {
  const id = periodId.value;
  if (!id) return;
  busy.value = true;
  try {
    const result = await calculatePeriodApi(id);
    if (result.queued && result.job_id) {
      const job = await waitForCalcJob(result.job_id, getCalcJobApi);
      warnings.value = job.warnings ?? [];
      await refreshPeriod(id);
      const outcome = describeCalcJob(job);
      message[outcome.level](outcome.text);
    } else {
      warnings.value = result.warnings ?? [];
      await refreshPeriod(id);
      message.success(
        result.queued ? '已转入后台算薪' : `已算薪 ${result.calculated} 人`,
      );
    }
  } finally {
    busy.value = false;
  }
}

async function lock() {
  const id = periodId.value;
  if (!id) return;
  if (!reason.value.trim()) {
    message.warning('请填写操作原因');
    return;
  }
  busy.value = true;
  try {
    await lockPeriodWithExpectedStatusApi(id, reason.value.trim(), status.value);
    await refreshPeriod(id);
    message.success('已锁账');
  } finally {
    busy.value = false;
  }
}

async function markPaid() {
  const id = periodId.value;
  if (!id) return;
  busy.value = true;
  try {
    await markPaidPeriodWithExpectedStatusApi(
      id,
      reason.value.trim() || undefined,
      status.value,
    );
    await refreshPeriod(id);
    message.success('已标记发薪');
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <a-alert
      show-icon
      type="info"
      message="计薪截至离职日。结算周期会盖住离职日所在的站点周期；若这样才能整段覆盖已有站点级周期，结束日可能晚于离职日。锁账仍校验当前状态，重复锁账会提示状态已变化。"
    />
    <a-alert
      v-for="(item, index) in hints"
      :key="index"
      show-icon
      type="warning"
      :message="item"
    />
    <p>离职日期：{{ leaveDate }}</p>
    <VbenButton
      v-access:code="'rs:period:generate'"
      :disabled="busy"
      @click="generate"
    >
      {{ periodId ? '刷新结算周期' : '生成离职结算周期' }}
    </VbenButton>
    <template v-if="periodId">
      <a-alert show-icon type="success" :message="hint || '已有离职结算周期'" />
      <p>
        周期 {{ startDate }} 至 {{ endDate }}，状态 {{ statusLabel }}
        <template v-if="netTotal !== undefined">
          ，实发 {{ formatMoney(netTotal) }} 元
        </template>
      </p>
      <a-alert
        v-for="(item, index) in warnings"
        :key="`warn-${index}`"
        show-icon
        type="warning"
        :message="item"
      />
      <VbenButton
        v-if="actions.calculate"
        v-access:code="'rs:period:calculate'"
        :disabled="busy"
        @click="preview"
      >
        算薪预览
      </VbenButton>
      <a-textarea
        v-if="actions.lock || actions.markPaid"
        v-model:value="reason"
        :maxlength="200"
        placeholder="锁账或标记发薪原因"
        :rows="2"
      />
      <VbenButton
        v-if="actions.lock"
        v-access:code="'rs:period:lock'"
        :disabled="busy"
        @click="lock"
      >
        锁账
      </VbenButton>
      <VbenButton
        v-if="actions.markPaid"
        v-access:code="'rs:period:mark-paid'"
        :disabled="busy"
        @click="markPaid"
      >
        标记发薪
      </VbenButton>
      <a-alert
        v-if="actions.paid"
        show-icon
        type="success"
        message="该离职结算周期已标记发薪。"
      />
    </template>
  </div>
</template>
