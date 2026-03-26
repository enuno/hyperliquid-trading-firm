# Experiment Tracking Standard

## Naming convention
- Experiment: `<department>-<domain>-<objective>`
- Run name: `<model>-<dataset>-<variant>-<timestamp>`

## Mandatory logged metadata
- model family + version
- dataset identifier/version
- hyperparameters
- training/eval metrics
- artifact URI
- operator/agent role

## Promotion criteria
- quality metrics above threshold
- no regression against baseline
- reproducibility checks passed
- governance fields complete

## Artifact expectations
- summary report
- model package
- requirements/environment capture
- reproducibility notes
