# MLFlow Lab Runbook

## 1) Start Infra
```bash
cd ~/.openclaw/workspace/projects/mlflow-lab/infra
cp .env.example .env
docker compose up -d
```

## 2) Validate Services
- MLflow UI/API: `http://localhost:5000`
- MinIO Console: `http://localhost:9001`
- Postgres: `localhost:5433`

## 3) Client Setup
```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

## 4) First Experiment (PyTorch/HF)
- Run a baseline script in `services/training/`.
- Log params, metrics, and model artifacts.

## 5) Promotion Policy
- Register model version after successful run.
- Move to `Staging` only if evaluation thresholds pass.
- Move to `Production` after manual approval.

## 6) Backups
- Snapshot Postgres metadata
- Snapshot MinIO bucket (artifacts)
