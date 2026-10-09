<script lang="ts" setup>
import type { ActivePlanVersion } from '../../../types/plan';
import type { PlanBindingForm, RiderResult } from '../../../types/rider';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';

import { getActivePlanVersionsApi } from '../../../api/plan';
import { createRiderBindingsBatchApi } from '../../../api/rider';
import { parseBatchRowErrors } from '../../adjustment/batch-errors';
import {
  batchBindingBody,
  batchRiderSummary,
  selectedRiderIds,
} from '../batch-ops';
import { bindingFormSchema } from '../data';

const riders = ref<RiderResult[]>([]);
const versions = ref<ActivePlanVersion[]>([]);
const rowErrors = ref<string[]>([]);

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: bindingFormSchema,
  showDefaultActions: false,
});

const [Drawer, drawerApi] = useVbenDrawer({
  class: 'w-[520px]',
  confirmText: '确认绑定',
  destroyOnClose: true,
  async onConfirm() {
    const ids = selectedRiderIds(riders.value);
    if (ids.length === 0) {
      message.warning('请先勾选骑手');
      return;
    }
    if (versions.value.length === 0) {
      message.warning('暂无启用中的方案版本');
      return;
    }
    const { valid } = await formApi.validate();
    if (!valid) return;
    const values = await formApi.getValues<PlanBindingForm>();
    if (values.binding_type === 'override' && !values.end_date) {
      message.warning('区间覆盖绑定必须填写开始和结束日期');
      return;
    }
    rowErrors.value = [];
    drawerApi.lock();
    try {
      const result = await createRiderBindingsBatchApi(
        batchBindingBody(ids, values),
      );
      message.success(
        `已为 ${result?.count ?? ids.length} 名骑手绑定方案，相关日期已标记需重算`,
      );
      drawerApi.getData<{ onSuccess?: () => void }>()?.onSuccess?.();
      await drawerApi.close();
    } catch (error: unknown) {
      rowErrors.value = parseBatchRowErrors(error).map(
        (item) => `第 ${item.row} 名：${item.reason}`,
      );
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    rowErrors.value = [];
    riders.value = drawerApi.getData<{ riders?: RiderResult[] }>()?.riders ?? [];
    formApi.resetForm();
    versions.value = (await getActivePlanVersionsApi()) ?? [];
    const options = versions.value.map((item) => ({
      label: `${item.plan_name} · ${item.short_name} v${item.version_no}`,
      value: item.id,
    }));
    formApi.updateSchema([
      {
        componentProps: {
          notFoundContent: '暂无启用版本',
          options,
          placeholder: options.length ? '请选择启用版本' : '暂无启用版本',
        },
        fieldName: 'plan_version_id',
      },
    ]);
  },
});
</script>

<template>
  <Drawer title="批量绑定方案">
    <div class="flex flex-col gap-3">
      <a-alert
        show-icon
        type="info"
        :message="`将为 ${riders.length} 名骑手绑定同一方案：${batchRiderSummary(riders) || '未选择'}。每人单独校验锁账并标记需重算。任一失败则全部不生效。`"
      />
      <div
        v-if="rowErrors.length > 0"
        class="flex max-h-40 flex-col gap-2 overflow-auto"
      >
        <a-alert
          v-for="(line, index) in rowErrors"
          :key="index"
          show-icon
          type="error"
          :message="line"
        />
      </div>
      <Form />
    </div>
  </Drawer>
</template>
