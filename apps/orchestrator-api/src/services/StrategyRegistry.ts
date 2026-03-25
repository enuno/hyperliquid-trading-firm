// apps/orchestrator-api/src/services/StrategyRegistry.ts

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  parametersSchema: any;
}

export class StrategyRegistry {
  list(): StrategyMeta[] {
    // Static for now; later read from config/strategies/*
    return [
      { id: "grid_bot", name: "Grid Bot", description: "...", parametersSchema: {/*...*/} },
      { id: "dca_bot", name: "DCA", description: "...", parametersSchema: {/*...*/} },
      { id: "rsi_reversion", name: "RSI Reversion", description: "...", parametersSchema: {/*...*/} },
      { id: "hyperliquid_perps_meta", name: "HyperLiquid Meta", description: "LLM/TradingAgents-driven", parametersSchema: {/*...*/} },
    ];
  }
}
