# Training Service Notes

Current baseline script:
- `sample_mlflow_hf_torch_run.py`

It demonstrates:
- bucket bootstrap (MinIO)
- MLflow experiment/run creation
- PyTorch training loop metric logging
- Hugging Face config parameter logging
- artifact upload + model logging

Next enhancements:
- dataset loaders and split tracking
- eval harness + threshold checks
- standardized model-card output
