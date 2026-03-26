#!/usr/bin/env python3
import os
import tempfile
from pathlib import Path

import boto3
import mlflow
import torch
from transformers import AutoConfig


def ensure_bucket(endpoint_url: str, key: str, secret: str, bucket: str):
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="us-east-1",
    )
    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)


def main():
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    endpoint = os.getenv("MLFLOW_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    key = os.getenv("AWS_ACCESS_KEY_ID", "minio")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "minio_dev_change_me")

    ensure_bucket(endpoint, key, secret, "mlflow-artifacts")

    os.environ["MLFLOW_S3_ENDPOINT_URL"] = endpoint
    os.environ["AWS_ACCESS_KEY_ID"] = key
    os.environ["AWS_SECRET_ACCESS_KEY"] = secret

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("MultiClaw-MLFlow-baseline")

    x = torch.randn(1024, 4)
    y = (x[:, 0] * 0.7 + x[:, 1] * -0.2 + 0.1).unsqueeze(1)
    model = torch.nn.Sequential(torch.nn.Linear(4, 16), torch.nn.ReLU(), torch.nn.Linear(16, 1))
    optim = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = torch.nn.MSELoss()

    with mlflow.start_run(run_name="torch-baseline"):
        mlflow.log_params({"lr": 0.01, "epochs": 20, "model": "tiny-mlp"})

        for epoch in range(20):
            pred = model(x)
            loss = loss_fn(pred, y)
            optim.zero_grad()
            loss.backward()
            optim.step()
            mlflow.log_metric("train_loss", float(loss.item()), step=epoch)

        config = AutoConfig.from_pretrained("distilbert-base-uncased")
        mlflow.log_param("hf_model_name", "distilbert-base-uncased")
        mlflow.log_param("hf_hidden_size", int(config.hidden_size))

        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "summary.txt"
            artifact.write_text(
                f"final_loss={float(loss.item()):.6f}\n"
                f"hf_model=distilbert-base-uncased\n"
                f"hidden_size={config.hidden_size}\n"
            )
            mlflow.log_artifact(str(artifact), artifact_path="reports")

        mlflow.pytorch.log_model(model, artifact_path="model")

    print("MLflow sample run completed")


if __name__ == "__main__":
    main()
