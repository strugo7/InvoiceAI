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

## Gmail account connection (OAuth)

Account connection no longer needs any files on disk. It uses an **OAuth Web
flow** (`/api/auth/login` → Google → `/api/auth/callback`) and stores the
**encrypted** tokens in Supabase (`gmail_accounts` table). To make it work:

- Provide `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`,
  `SESSION_SECRET`, `TOKEN_ENC_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` via the
  Secret (created from `backend/.env`, see Deploy step 1).
- `OAUTH_REDIRECT_URI` must point at how you actually reach the service (e.g. the
  `port-forward`/Ingress URL + `/api/auth/callback`) and be listed as an Authorized
  redirect URI on the Google **Web application** OAuth client.
- Run `backend/sql/gmail_accounts.sql` against the Supabase project once.

## Known limitations (next steps)

- **Ephemeral storage.** `reports/` (and the legacy `invoices.json` backup) live in
  the container filesystem and reset on restart. Invoices and Gmail credentials
  persist in Supabase; add a PVC only if you need generated PDFs to survive.
- **Single replica only** — see the scheduler note in `deployment.yaml`. The signed
  session used for the OAuth `state` is keyed by `SESSION_SECRET`; multiple replicas
  are fine for that as long as they share the same `SESSION_SECRET`.
