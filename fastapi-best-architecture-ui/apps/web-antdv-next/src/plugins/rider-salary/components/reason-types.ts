export interface ReasonPromptOptions {
  dateLabel?: string;
  extraHint?: string;
  password?: boolean;
  passwordRequired?: boolean;
  reasonRequired?: boolean;
  title?: string;
  withDate?: boolean;
}

export interface ReasonResult {
  date?: string;
  password?: string;
  reason: string;
}
