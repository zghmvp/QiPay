<script lang="ts" setup>
import type { OrderForm, OrderResult } from '../../../types/order';

import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';

import { createOrderApi, updateOrderApi } from '../../../api/order';
import { getPeriodForDateApi } from '../../../api/period';
import { useReasonModal } from '../../../components/use-reason-modal';
import { toDateString } from '../../../utils/date';
import { orderFormSchema } from '../data';
import {
  type OrderWriteKind,
  type OrderWriteLanding,
  orderWriteSuccessMessage,
  resolveOrderWriteLanding,
} from '../stale-after-write';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const router = useRouter();
const { ReasonModal, prompt } = useReasonModal();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: orderFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const existingOrder = ref<OrderResult>();
const writeResult = ref<{
  kind: OrderWriteKind;
  landing: OrderWriteLanding;
  message: string;
}>();

const drawerTitle = computed(() => {
  if (writeResult.value) return '需重算，尚未出账';
  return formData.value?.id ? '纠错订单' : '补录订单';
});

function bizDateOf(values: OrderForm): string | undefined {
  return (
    toDateString(existingOrder.value?.biz_date) ||
    toDateString(values.order_time) ||
    toDateString(values.deliver_time)
  );
}

async function resolveLanding(values: OrderForm): Promise<OrderWriteLanding> {
  const siteId = Number(values.site_id);
  const riderId = Number(values.rider_id);
  const bizDate = bizDateOf(values);
  if (Number.isFinite(siteId) && siteId > 0 && bizDate) {
    try {
      const covering = await getPeriodForDateApi({
        date: bizDate,
        rider_id: Number.isFinite(riderId) && riderId > 0 ? riderId : undefined,
        site_id: siteId,
      });
      return resolveOrderWriteLanding({
        bizDate,
        periodId: covering.period?.id,
        periodStatus: covering.period?.status,
        siteId,
      });
    } catch {
      return resolveOrderWriteLanding({ bizDate, siteId });
    }
  }
  return resolveOrderWriteLanding({
    bizDate,
    siteId: Number.isFinite(siteId) ? siteId : undefined,
  });
}

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[520px]',
  destroyOnClose: true,
  async onConfirm() {
    if (writeResult.value) {
      const { landing } = writeResult.value;
      await drawerApi.close();
      await router.push({ path: landing.path, query: landing.query });
      return;
    }
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<OrderForm>();
    let reason: string | undefined;
    if (formData.value?.id) {
      try {
        ({ reason } = await prompt({ title: '纠错原因' }));
      } catch (error: unknown) {
        if (isUserCancelled(error)) return;
        throw error;
      }
    }
    drawerApi.lock();
    try {
      const kind: OrderWriteKind =
        formData.value?.id && reason ? 'fix' : 'backfill';
      if (formData.value?.id && reason) {
        await updateOrderApi(formData.value.id, { ...values, reason });
      } else {
        await createOrderApi(values);
      }
      const landing = await resolveLanding(values);
      const text = orderWriteSuccessMessage(kind);
      writeResult.value = { kind, landing, message: text };
      message.success(text);
      drawerApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
    } finally {
      drawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) {
      writeResult.value = undefined;
      existingOrder.value = undefined;
      return;
    }
    const data = drawerApi.getData<OrderResult & { onSuccess?: () => void }>();
    formApi.resetForm();
    writeResult.value = undefined;
    if (data?.id) {
      formData.value = { id: data.id };
      existingOrder.value = data;
      formApi.setValues(data);
    } else {
      formData.value = undefined;
      existingOrder.value = undefined;
    }
  },
});

function goLanding() {
  const landing = writeResult.value?.landing;
  if (!landing) return;
  void drawerApi.close();
  void router.push({ path: landing.path, query: landing.query });
}
</script>

<template>
  <Drawer :title="drawerTitle">
    <a-alert
      v-if="writeResult"
      show-icon
      type="warning"
      data-testid="ops-order-fix-shows-stale"
      :message="writeResult.message"
    >
      <template #description>
        写订单不是薪资已更新。请到覆盖该日的该期算薪页重算。
      </template>
      <template #action>
        <a-button
          type="primary"
          data-testid="ops-order-fix-goto-calc"
          @click="goLanding"
        >
          {{ writeResult.landing.ctaLabel }}
        </a-button>
      </template>
    </a-alert>
    <Form v-show="!writeResult" />
    <ReasonModal />
  </Drawer>
</template>
