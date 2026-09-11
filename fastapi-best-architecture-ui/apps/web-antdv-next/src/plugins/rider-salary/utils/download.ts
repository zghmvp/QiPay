import { downloadFileFromBlob } from '@vben/utils';

import { requestClient } from '#/api/request';

function headerValue(headers: unknown, name: string): string | undefined {
  if (!headers || typeof headers !== 'object') return undefined;
  const rec = headers as Record<string, unknown> & {
    get?: (key: string) => null | string | undefined;
  };
  if (typeof rec.get === 'function') {
    return rec.get(name) || rec.get(name.toLowerCase()) || undefined;
  }
  const raw =
    rec[name] ?? rec[name.toLowerCase()] ?? rec['Content-Disposition'];
  return typeof raw === 'string' ? raw : undefined;
}

/** 解析 RFC 5987 `filename*=UTF-8''...`，回退 `filename=` */
export function parseContentDisposition(
  header?: null | string,
): string | undefined {
  if (!header) return undefined;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replaceAll(/['"]/g, ''));
    } catch {
      return star[1].trim();
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim();
}

export async function downloadNamedBlob(
  url: string,
  fallbackName: string,
  config?: { params?: Record<string, unknown> },
) {
  const res = await requestClient.download<{
    data: Blob;
    headers: unknown;
  }>(url, {
    params: config?.params,
    responseReturn: 'raw',
  });
  const fileName =
    parseContentDisposition(
      headerValue(res.headers, 'content-disposition'),
    ) || fallbackName;
  downloadFileFromBlob({ fileName, source: res.data });
}
