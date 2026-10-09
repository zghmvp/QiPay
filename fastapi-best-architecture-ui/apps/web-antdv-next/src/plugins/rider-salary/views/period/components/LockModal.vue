<script lang="ts" setup>
import type { LockCheckResult, PeriodResult } from '../../../types/period';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  calculatePeriodApi,
  getCalcJobApi,
  carryForwardPeriodApi,
  lockCheckPeriodApi,
  lockPeriodApi,
} from '../../../api/period';
import {
  describeCalcJob,
  waitForCalcJob,
} from '../calc-progress';
import { canConfirmPeriodLock, supplementRiderIds } from '../lock-guard';
import { supplementCalculateParam } from '../rider-search';

const reason = ref('');
const carryReason = ref('');
const loading = ref(false);
const carrying = ref(false);
const recalculating = ref(false);
const loadError = ref('');
const check = ref<LockCheckResult | null>(null);

const missingSupplement = computed(
  () => check.value?.missing_supplement ?? [],
);

const supplementIds = computed(() => supplementRiderIds(check.value));

const canLock = computed(() =>
  canConfirmPeriodLock({
    canLock: check.value?.can_lock,
    carrying: carrying.value,
    loadError: Boolean(loadError.value),
    loading: loading.value,
    needsRecalcCount: check.value?.needs_recalc?.length ?? 0,
    recalculating: recalculating.value,
    uncalculatedCount: check.value?.uncalculated?.length ?? 0,
  }),
);

const [Modal, modalApi] = useVbenModal({
  class: 'w-[560px]',
  confirmDisabled: true,
  confirmText: '确认锁账',
  destroyOnClose: true,
  async onConfirm() {
    if (!canLock.value) return;
    if (!reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    const period = modalApi.getData<PeriodResult & { onSuccess?: () => void }>();
    if (!period?.id) return;
    modalApi.lock();
    try {
      await lockPeriodApi(period.id, reason.value.trim());
      message.success('已锁账');
      period.onSuccess?.();
      await modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    reason.value = '';
    carryReason.value = '';
    recalculating.value = false;
    check.value = null;
    loadError.value = '';
    modalApi.setState({ confirmDisabled: true });
    const period = modalApi.getData<PeriodResult>();
    if (!period?.id) {
      loadError.value = '未找到结算周期';
      return;
    }
    await reloadCheck(period.id);
  },
});

function syncConfirm() {
  modalApi.setState({ confirmDisabled: !canLock.value });
}

async function reloadCheck(periodId: number) {
  loading.value = true;
  loadError.value = '';
  try {
    check.value = await lockCheckPeriodApi(periodId);
  } catch {
    loadError.value = '锁账预检失败，请关闭后重试';
    check.value = null;
  } finally {
    loading.value = false;
    syncConfirm();
  }
}

async function recalculateListed() {
  const period = modalApi.getData<PeriodResult>();
  const ids = supplementIds.value;
  if (!period?.id || !ids.length || recalculating.value) return;
  recalculating.value = true;
  syncConfirm();
  try {
    const res = await calculatePeriodApi(
      period.id,
      supplementCalculateParam(ids),
    );
    if (res.queued && res.job_id) {
      const job = await waitForCalcJob(res.job_id, getCalcJobApi);
      const outcome = describeCalcJob(job);
      message[outcome.level](outcome.text);
      if (job.warnings?.length) {
        message.warning(job.warnings.join('；'));
      }
    } else if (res.queued) {
      message.info('算薪已转入后台处理，请稍后重新打开锁账预检');
    } else {
      message.success(`已计算 ${res.calculated} 名骑手`);
      if (res.warnings?.length) {
        message.warning(res.warnings.join('；'));
      }
    }
    await reloadCheck(period.id);
  } finally {
    recalculating.value = false;
    syncConfirm();
  }
}

async function carryForward(riderIds?: number[]) {
  const period = modalApi.getData<PeriodResult>();
  if (!period?.id || carrying.value) return;
  carrying.value = true;
  syncConfirm();
  try {
    const result = await carryForwardPeriodApi(period.id, {
      reason: carryReason.value.trim() || undefined,
      rider_ids: riderIds,
    });
    message.success(`已沿用原单 ${result.created_count} 人`);
    await reloadCheck(period.id);
  } finally {
    carrying.value = false;
    syncConfirm();
  }
}
</script>

<template>
  <Modal title="锁账">
    <a-spin :spinning="loading">
      <div class="flex flex-col gap-3">
        <a-alert
          v-if="loadError"
          show-icon
          type="error"
          :message="loadError"
        />
        <a-alert
          v-else-if="check && !check.can_lock"
          show-icon
          type="error"
          :message="check.message || '当前不能锁账'"
        />
        <a-alert
          v-else-if="check?.empty"
          show-icon
          type="info"
          message="本期没有应算骑手，可以锁账。标记发薪时会提示本期没有薪资单。"
        />
        <a-alert
          v-else-if="check"
          show-icon
          type="info"
          message="确认后将冻结本周期订单、奖惩与薪资结果。"
        />

        <div
          v-if="supplementIds.length"
          class="flex items-center justify-between gap-3"
        >
          <span class="text-xs text-gray-500">
            可先补算下列未算薪和需重算的骑手，完成后再锁账。
          </span>
          <a-button
            v-access:code="'rs:period:calculate'"
            size="small"
            type="primary"
            :disabled="carrying"
            :loading="recalculating"
            @click="recalculateListed"
          >
            补算这些骑手
          </a-button>
        </div>

        <div v-if="missingSupplement.length">
          <div class="mb-1 font-medium">缺补发单</div>
          <p class="mb-2 text-xs text-gray-500">
            这些骑手的原单已反冲，还没有可用的补发单。金额不需要变化时，沿用原单会生成一张金额相同的补发草稿。
          </p>
          <a-textarea
            v-model:value="carryReason"
            placeholder="沿用原因，可留空"
            :rows="2"
          />
          <div class="mb-2 mt-2 flex justify-end">
            <a-button
              size="small"
              type="primary"
              :loading="carrying"
              @click="carryForward()"
            >
              全部沿用原单
            </a-button>
          </div>
          <div class="mb-1 flex gap-3 px-3 text-xs text-gray-500">
            <span class="w-24">工号</span>
            <span class="flex-1">姓名</span>
            <span class="w-20 text-right">操作</span>
          </div>
          <ul class="max-h-40 overflow-auto rounded border border-border px-3 py-2">
            <li
              v-for="item in missingSupplement"
              :key="item.rider_id"
              class="flex items-center gap-3 leading-6"
            >
              <span class="w-24 shrink-0">{{ item.job_no }}</span>
              <span class="flex-1">{{ item.rider_name || '—' }}</span>
              <a-button
                class="w-20 px-0"
                type="link"
                size="small"
                :disabled="carrying"
                @click="carryForward([item.rider_id])"
              >
                沿用原单
              </a-button>
            </li>
          </ul>
        </div>

        <div v-if="check?.uncalculated.length">
          <div class="mb-1 font-medium">未算薪</div>
          <div class="mb-1 flex gap-3 px-3 text-xs text-gray-500">
            <span class="w-24">工号</span>
            <span>姓名</span>
          </div>
          <ul class="max-h-40 overflow-auto rounded border border-border px-3 py-2">
            <li
              v-for="item in check.uncalculated"
              :key="item.rider_id"
              class="flex gap-3 leading-6"
            >
              <span class="w-24 shrink-0">{{ item.job_no }}</span>
              <span>{{ item.rider_name || '—' }}</span>
            </li>
          </ul>
        </div>

        <div v-if="check?.needs_recalc.length">
          <div class="mb-1 font-medium">需重算</div>
          <div class="mb-1 flex gap-3 px-3 text-xs text-gray-500">
            <span class="w-24">工号</span>
            <span>姓名</span>
          </div>
          <ul class="max-h-40 overflow-auto rounded border border-border px-3 py-2">
            <li
              v-for="item in check.needs_recalc"
              :key="item.rider_id"
              class="flex gap-3 leading-6"
            >
              <span class="w-24 shrink-0">{{ item.job_no }}</span>
              <span>{{ item.rider_name || '—' }}</span>
            </li>
          </ul>
        </div>

        <a-textarea
          v-if="canLock"
          v-model:value="reason"
          placeholder="请填写锁账原因"
          :rows="3"
        />
      </div>
    </a-spin>
  </Modal>
</template>
