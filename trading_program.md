## Dashboard and Reporting Requirements

### Reporting
Every 12 hours, the system must send a summary message with:
- Paper trading P/L.
- Live trading P/L.
- Current trading account balance.
- Reserved profit balance.
- Current mode status.
- Any active halt or recovery condition.

### Dashboard
The dashboard must display:
- The last 365 days of 1-minute historical market data.
- Paper and live agent performance.
- Current equity, reserved profits, and drawdown.
- Experiment results and acceptance history.

### Notification Constraints
- Notifications must be periodic every 12 hours.
- Notifications must continue in paper mode, live mode, and recovery mode.
- Notifications must not include secrets, private keys, or raw wallet material.

Add to Safety and Ops

## 14. Notification and Observability

### 14.1 12-Hour Status Message
A scheduled reporter sends a compact operational summary every 12 hours.

Message contents:
- Paper bot cumulative P/L.
- Live bot cumulative P/L.
- Current account balance.
- Reserved profit balance.
- Current drawdown.
- Current state: normal, paper-only, live, or recovery.

### 14.2 Delivery Channels
- Slack or Telegram for operational alerts.
- Optional email fallback.
- ArgoCD notifications for deployment lifecycle events.

### 14.3 Failure Handling
If the reporter fails, the failure is logged locally and retried on the next cycle.
Repeated reporting failures trigger an ops alert but do not halt trading.

Add to deployment

## 15. Dashboard Deployment

The dashboard is deployed as a separate containerized service in the openclaw Kubernetes cluster.

### Components
- `dashboard-api`: serves aggregated trading and research data.
- `dashboard-ui`: renders charts and tables.
- `market-ingestor`: stores 1-minute candles locally.
- `status-reporter`: sends 12-hour summary messages.

### GitOps Flow
- Dashboard manifests are version-controlled in Git.
- ArgoCD deploys changes automatically.
- Strategy commits trigger paper-eval pods, but do not directly modify dashboard code.

Add to Data Model

## 16. Persistent Data Model

### Candle Store
Store 1-minute candles for each supported market for at least 365 days.

Suggested table:
- symbol
- interval
- ts
- open
- high
- low
- close
- volume
- source

### Performance Store
Track each bot separately.

Suggested fields:
- bot_type: paper | live
- session_id
- realized_pnl
- unrealized_pnl
- fees_paid
- funding_paid
- balance
- reserved_profit
- max_drawdown
- updated_at
