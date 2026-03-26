# MultiClaw-MLFlow 🧪🦞

[![MLflow Quality Gate](https://github.com/AIML-Solutions/MultiClaw-MLFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/AIML-Solutions/MultiClaw-MLFlow/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e.svg)](LICENSE)

**MultiClaw-MLFlow** is AIML Solutions’ model lifecycle and experiment governance lane.

It gives MultiClaw teams a reproducible system for training, evaluating, registering, and auditing models across quant and agentic workflows.

## What this repo does

- Runs MLflow tracking + model registry
- Stores metadata in Postgres and artifacts in MinIO (S3-compatible)
- Provides baseline PyTorch + HF tracked experiment flow
- Defines architecture and runbook standards for expansion

## Verified status

- `mlflow-db`, `mlflow-minio`, `mlflow-tracking` stack validated
- Tracking UI available at `http://localhost:5000`
- Artifact bucket `mlflow-artifacts` verified
- Sample training run completed with logged metrics + artifacts

## Core docs

- [docs/architecture.md](docs/architecture.md)
- [docs/runbook.md](docs/runbook.md)
- [docs/EXPERIMENT_STANDARD.md](docs/EXPERIMENT_STANDARD.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)

## Quick start

```bash
cd infra
cp .env.example .env
docker compose up -d

MLFLOW_TRACKING_URI=http://127.0.0.1:5000 \
MLFLOW_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
AWS_ACCESS_KEY_ID=minio \
AWS_SECRET_ACCESS_KEY=minio_dev_change_me \
python3 services/training/sample_mlflow_hf_torch_run.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
