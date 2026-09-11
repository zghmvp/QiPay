import type { ReasonPromptOptions, ReasonResult } from './reason-types';

import { useVbenModal } from '@vben/common-ui';

import ReasonModal from './ReasonModal.vue';

export function useReasonModal() {
  const [Modal, modalApi] = useVbenModal({
    connectedComponent: ReasonModal,
  });

  function prompt(options: ReasonPromptOptions = {}): Promise<ReasonResult> {
    return new Promise((resolve, reject) => {
      modalApi.setData({ ...options, reject, resolve }).open();
    });
  }

  return { ReasonModal: Modal, prompt };
}
