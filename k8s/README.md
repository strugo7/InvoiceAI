# Kubernetes deployment (Rancher Desktop / k3s)

Manifests to run the InvoiceAI backend on a local k3s cluster.

| File | Role |
|------|------|
| `deployment.yaml` | Runs the backend Pod (1 replica, probes, non-root hardening) |
| `service.yaml` | `ClusterIP` exposing port 8000 inside the cluster |
| `secret.example.yaml` | Template documenting the Secret keys (no real values) |
| `kustomization.yaml` | Bundles deployment + service for `kubectl apply -k` |

## Prerequisites

1. **Rancher Desktop is running and Kubernetes is enabled.** Verify:
   ```bash
   kubectl config use-context rancher-desktop
   kubectl get nodes        # node must be Ready
   ```
2. **The image is in k3s's image store.** k3s uses containerd, which is separate
   from Docker. Build so k3s can see it:
   ```bash
   # If Rancher's container engine is containerd (default):
   nerdctl --namespace k8s.io build -t invoiceai-backend:latest .

   # If it's dockerd (moby), build then side-load into k3s:
   docker build -t invoiceai-backend:latest .
   docker save invoiceai-backend:latest | nerdctl --namespace k8s.io load
   ```

## Deploy

```bash
# 1. Create the Secret from your local .env (gitignored, never committed)
kubectl create secret generic invoiceai-secrets --from-env-file=backend/.env

# 2. Apply the manifests
kubectl apply -k k8s/

# 3. Watch it come up
kubectl rollout status deployment/invoiceai-backend
kubectl get pods -l app.kubernetes.io/name=invoiceai-backend
```

## Access

```bash
kubectl port-forward svc/invoiceai-backend 8000:8000
# open http://localhost:8000
```

## Update after a code change

```bash
nerdctl --namespace k8s.io build -t invoiceai-backend:latest .
kubectl rollout restart deployment/invoiceai-backend
```

## Known limitations (next steps)

- **Gmail scanning won't work yet.** The app reads `token_*.json` and
  `credentials.json` from disk (`backend/agent.py`); those are `.dockerignore`d
  and not in the image. They must be mounted (Secret volume + a writable copy,
  or a PVC, since the app rewrites refreshed tokens). The dashboard and the
  cached `invoices.json` still render.
- **Ephemeral storage.** `invoices.json` and `reports/` live in the container
  filesystem and reset on restart. Add a PVC if you need them to persist.
- **Single replica only** — see the scheduler note in `deployment.yaml`.
