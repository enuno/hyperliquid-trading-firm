// types/prompt-policy.ts
export interface PromptPolicy {
  role: AgentRole;
  version: number;
  baseTemplate: string;        // instruction block
  hyperparams: PromptHyperparams;
  lastUpdatedAt: number;
}

export interface PromptHistoryEntry {
  role: AgentRole;
  policyVersion: number;
  windowStart: number;
  windowEnd: number;
  score: number;               // 0..100 ATLAS-style
  summary: string;             // what happened in this window
}
