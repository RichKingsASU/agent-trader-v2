# Ops-only Ingress (optional)

These manifests are **not applied** by the default `kubectl apply -f k8s/` (it is non-recursive).

If you have an ingress controller (example: nginx), you can enable internal-only access to a
small set of ops endpoints:

```bash
kubectl apply -f k8s/ingress/
```

Review and adjust:
- ingress class (`spec.ingressClassName`)
- allowlist ranges (`nginx.ingress.kubernetes.io/whitelist-source-range`)
- internal LB annotations (cloud-specific)

## vNEXT: repo-wide non-invasive confirmation

A repo-wide scan shows **no vNEXT-labeled runtime code** (outside vendored dependencies), so vNEXT introduces:
- no imports from live-trading execution code
- no side effects
- no background threads
- no network calls

