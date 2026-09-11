<script lang="ts" setup>
import type { OrderForm, OrderResult } from '../../../types/order';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';

import { createOrderApi, updateOrderApi } from '../../../api/order';
import { useReasonModal } from '../../../components/use-reason-modal';
import { orderFormSchema } from '../data';

function isUserCancelled(error: unknown) {
  const msg = (error as Error)?.message;
  return msg === 'cancelled' || msg === 'dialog cancelled';
}

const { ReasonModal, prompt } = useReasonModal();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: orderFormSchema,
  showDefaultActions: false,
});

const formData = ref<{ id?: number }>();
const drawerTitle = computed(() => (formData.value?.id ? '纠错订单' : '补录订单'));

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[520px]',
  destroyOnClose: true,
  async onConfirm() {
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
      if (formData.value?.id && reason) {
        await updateOrderApi(formData.value.id, { ...values, reason });
        message.success('已纠错订单');
      } else {
        await createOrderApi(values);
        message.success('已补录订单');
      }
      drawerApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
      await drawerApi.close();
    } finally {
      drawerApi.unlock();
    }
  },
  onOpenChange(isOpen) {
    if (!isOpen) return;
    const data = drawerApi.getData<OrderResult & { onSuccess?: () => void }>();
    formApi.resetForm();
    if (data?.id) {
      formData.value = { id: data.id };
      formApi.setValues(data);
    } else {
      formData.value = undefined;
    }
  },
});
</script>

<template>
  <Drawer :title="drawerTitle">
    <Form />
    <ReasonModal />
  </Drawer>
</template>
