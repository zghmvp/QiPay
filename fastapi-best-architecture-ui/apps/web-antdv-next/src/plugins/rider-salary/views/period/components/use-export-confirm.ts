import type { ExportConfirmOptions, ExportConfirmResult } from './export-confirm-types';

import { useVbenModal } from '@vben/common-ui';

import ExportConfirmModal from './ExportConfirmModal.vue';

export function useExportConfirm() {
  const [Modal, modalApi] = useVbenModal({
    connectedComponent: ExportConfirmModal,
  });

  function prompt(options: ExportConfirmOptions): Promise<ExportConfirmResult> {
    return new Promise((resolve, reject) => {
      modalApi.setData({ ...options, reject, resolve }).open();
    });
  }

  return { ExportConfirmModal: Modal, prompt };
}
