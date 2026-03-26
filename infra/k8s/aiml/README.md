# Kubernetes manifests

Apply with:

```bash
kubectl apply -f namespace.yaml
# Add more manifests (deployments, services) as needed.
```

Validate locally (no cluster):

```bash
kubectl apply --dry-run=client -f .
```
