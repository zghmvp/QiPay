export function openAccountHint(jobNo: string): string {
  return `将开通账号，用户名为工号 ${jobNo}。不填密码则生成随机密码，仅展示一次，骑手首次登录必须修改。`;
}

export function resetPasswordHint(): string {
  return '不填密码则生成随机密码，仅展示一次。重置后旧登录失效，骑手须重新登录，首次登录必须修改。';
}

export function specifiedPasswordMessage(action: string): string {
  return `已${action}，使用的是您填写的密码。骑手首次登录必须修改。`;
}

export function batchOpenAccountHint(count: number): string {
  return `将为 ${count} 名骑手分别开通账号，用户名为各自工号。每人生成独立的随机密码，仅展示一次，首次登录必须修改。不会使用统一口令。`;
}

export function batchResetPasswordHint(count: number): string {
  return `将为 ${count} 名骑手分别生成新的随机密码，仅展示一次。重置后旧登录失效，每人首次登录必须修改。不会使用统一口令。`;
}
