<script lang="ts" setup>
import type { RollbackPreviewResult } from '../../../types/plan';

import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

import {
  getRollbackPreviewApi,
  rollbackPlanVersionApi,
} from '../../../api/plan';
import {
  ROLLBACK_CONFIRM_TEXT,
  canSubmitRollback,
  rollbackSuccessText,
} from './rollback-contract';

const loading = ref(false);
const preview = ref<RollbackPreviewResult>();
const reason = ref('');
const confirmText = ref('');

const [Modal, modalApi] = useVbenModal({
  class: 'w-[640px]',
  confirmText: '执行回退',
  destroyOnClose: true,
  async onConfirm() {
    const pk = versionId.value;
    if (!pk) return;
    if (!reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    if (preview.value?.has_paid && confirmText.value !== ROLLBACK_CONFIRM_TEXT) {
      message.warning('请输入确认文字「确认回退」');
      return;
    }
    modalApi.lock();
    try {
      const copied = await rollbackPlanVersionApi(pk, {
        confirm_text: confirmText.value,
        reason: reason.value.trim(),
      });
      const newId = copied?.id;
      const versionNo = copied?.version_no;
      message.success(
        typeof versionNo === 'number'
          ? rollbackSuccessText(versionNo)
          : '回退完成，已复制草稿，请修改后重新试算启用',
      );
      modalApi.getData<{ onSuccess?: (id?: number) => void }>()?.onSuccess?.(newId);
      await modalApi.close();
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    reason.value = '';
    confirmText.value = '';
    preview.value = undefined;
    const pk = versionId.value;
    if (!pk) return;
    loading.value = true;
    try {
      preview.value = await getRollbackPreviewApi(pk);
    } finally {
      loading.value = false;
    }
  },
});

const versionId = computed(
  () => modalApi.getData<{ versionId?: number }>()?.versionId,
);

const canSubmit = computed(() =>
  canSubmitRollback({
    confirmText: confirmText.value,
    hasPaid: Boolean(preview.value?.has_paid),
    previewReady: Boolean(preview.value),
    reason: reason.value,
  }),
);
</script>

<template>
  <Modal title="确认回退方案版本">
    <a-spin :spinning="loading">
      <div class="flex flex-col gap-3">
        <a-alert
          v-if="preview?.has_paid"
          type="error"
          show-icon
          message="该方案已执行发薪操作，回退将产生财务影响"
        />
        <div class="text-sm leading-6">
          该操作不可撤销，将产生以下后果：
          <ol class="mt-2 list-decimal pl-5">
            <li>
              方案版本「{{ preview?.version_label }}」将作废；
            </li>
            <li>将解除 {{ preview?.binding_count ?? 0 }} 条骑手绑定；</li>
            <li>
              将作废 {{ preview?.payrolls_draft ?? 0 }} 条草稿薪资结果，下次算薪将新建草稿；
            </li>
            <li v-if="(preview?.reversal_count ?? 0) > 0">
              此外将生成 {{ preview?.reversal_count ?? 0 }} 条反冲单（已发薪
              {{ preview?.payrolls_paid ?? 0 }} 条、已定稿
              {{ preview?.payrolls_finalized ?? 0 }}
              条），所属周期进入「补发中」。同一周期内未使用该版本的已定稿、已发薪单也会一并反冲，避免重算后原单与补发双发。导出将出现原单 / 反冲 / 补发三行。
            </li>
            <li>系统将自动复制一份新草稿版本供修改后重新试算启用。</li>
          </ol>
        </div>
        <div v-if="preview?.riders?.length">
          <div class="mb-1 text-sm font-medium">将被解绑的骑手</div>
          <a-table
            :data-source="preview.riders"
            :pagination="false"
            row-key="rider_id"
            size="small"
          >
            <a-table-column data-index="job_no" title="工号" />
            <a-table-column data-index="name" title="姓名" />
            <a-table-column data-index="start_date" title="开始" />
            <a-table-column data-index="end_date" title="结束" />
          </a-table>
        </div>
        <a-textarea
          v-model:value="reason"
          :rows="3"
          placeholder="请说明回退原因"
        />
        <div v-if="preview?.has_paid">
          <div class="mb-1 text-sm">请输入「确认回退」</div>
          <a-input v-model:value="confirmText" placeholder="确认回退" />
        </div>
        <div class="text-muted-foreground text-xs">
          {{
            preview?.has_paid
              ? '已发薪结果需要输入确认文字。'
              : '填写回退原因后即可执行。'
          }}当前{{ canSubmit ? '可提交' : '不可提交' }}。
        </div>
      </div>
    </a-spin>
  </Modal>
</template>
