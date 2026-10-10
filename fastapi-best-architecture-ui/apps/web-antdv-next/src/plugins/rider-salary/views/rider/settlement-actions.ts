/** 离职结算向导里，按周期状态决定下一步按钮。 */

export function settlementActions(status: string) {
  const open = status === 'open' || status === 'reopened';
  return {
    calculate: open,
    lock: open,
    markPaid: status === 'locked',
    paid: status === 'paid',
  };
}
