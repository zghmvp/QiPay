<script lang="ts" setup>
import type { ReasonPromptOptions, ReasonResult } from './reason-types';

import { ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { message } from 'antdv-next';

const reason = ref('');
const password = ref('');
const title = ref('请填写操作原因');
const extraHint = ref('');
const extraHintTestId = ref<string>();
const needPassword = ref(false);
const passwordRequired = ref(false);
const reasonRequired = ref(true);
const confirmed = ref(false);

const [Modal, modalApi] = useVbenModal({
  class: 'w-[480px]',
  confirmText: '确定',
  destroyOnClose: true,
  async onConfirm() {
    if (reasonRequired.value && !reason.value.trim()) {
      message.warning('请填写操作原因');
      return;
    }
    if (needPassword.value && passwordRequired.value && !password.value) {
      message.warning('请填写密码');
      return;
    }
    const data = modalApi.getData<{
      reject?: (err?: unknown) => void;
      resolve?: (value: ReasonResult) => void;
    }>();
    confirmed.value = true;
    data?.resolve?.({
      password: needPassword.value ? password.value || undefined : undefined,
      reason: reason.value.trim(),
    });
    await modalApi.close();
  },
  onOpenChange(isOpen) {
    if (!isOpen) {
      if (!confirmed.value) {
        modalApi.getData<{ reject?: (err?: unknown) => void }>()?.reject?.(
          new Error('cancelled'),
        );
      }
      return;
    }
    const data = modalApi.getData<
      ReasonPromptOptions & {
        reject?: (err?: unknown) => void;
        resolve?: (value: ReasonResult) => void;
      }
    >();
    confirmed.value = false;
    reason.value = '';
    password.value = '';
    title.value = data?.title || '请填写操作原因';
    extraHint.value = data?.extraHint || '';
    extraHintTestId.value = data?.extraHintTestId;
    needPassword.value = Boolean(data?.password);
    passwordRequired.value = Boolean(data?.passwordRequired);
    reasonRequired.value = data?.reasonRequired !== false;
  },
});
</script>

<template>
  <Modal :title="title">
    <div class="flex flex-col gap-3">
      <a-alert
        v-if="extraHint"
        type="info"
        show-icon
        :data-testid="extraHintTestId"
        :message="extraHint"
      />
      <a-textarea
        v-model:value="reason"
        :placeholder="reasonRequired ? '请填写操作原因' : '操作原因（可选）'"
        :rows="4"
      />
      <a-input-password
        v-if="needPassword"
        v-model:value="password"
        :placeholder="passwordRequired ? '请输入密码' : '密码（可选，不填则按规则生成）'"
      />
    </div>
  </Modal>
</template>
