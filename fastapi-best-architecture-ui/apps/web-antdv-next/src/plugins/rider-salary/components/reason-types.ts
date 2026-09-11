export interface ReasonPromptOptions {
  extraHint?: string;
  password?: boolean;
  passwordRequired?: boolean;
  reasonRequired?: boolean;
  title?: string;
}

export interface ReasonResult {
  password?: string;
  reason: string;
}
