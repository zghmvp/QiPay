const cache = new Map<number, number>();

export function getCachedManagerCount(siteId: number) {
  return cache.has(siteId) ? (cache.get(siteId) ?? 0) : null;
}

export function setCachedManagerCount(siteId: number, count: number) {
  cache.set(siteId, count);
}

export function invalidateManagerCount(siteId?: number) {
  if (typeof siteId === 'number') {
    cache.delete(siteId);
    return;
  }
  cache.clear();
}
