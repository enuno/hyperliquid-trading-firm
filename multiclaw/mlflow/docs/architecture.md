# MLFlow Lab Architecture

## Goals
1. Reproducible experiments (code + params + data lineage)
2. Deterministic model promotion (staging -> production)
3. Shared observability patterns with MultiClaw/Quant lanes
4. Low-cost, open-source-first deployment on VPS

## Components
- **MLflow Tracking Server**: experiment tracking and registry API
- **Postgres**: MLflow backend metadata
- **MinIO**: model artifacts, checkpoints, plots, evaluation files
- **Training Workers**: PyTorch/HF jobs (local, container, or scheduled)
- **Evaluation Gate**: metric thresholds + regression checks before promotion

## Data/Model Path
1. Dataset prep job produces versioned data refs
2. Training run logs params/metrics/artifacts to MLflow
3. Model candidate registered in MLflow Model Registry
4. Evaluation policy decides promotion to staging/production
5. Inference service consumes promoted model

## Optional GraphQL
GraphQL is optional here. If needed, expose read-side metadata from Postgres via Hasura for dashboards. Keep writes through MLflow APIs to avoid consistency drift.

## Security Notes
- Use non-default secrets in `.env`
- Restrict tracking UI to private network / Tailscale
- Separate read/write credentials for automation agents
