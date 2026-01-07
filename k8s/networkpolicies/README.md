# NetworkPolicies (optional)

These manifests are **disabled by default** because enabling default-deny policies can be disruptive,
especially if your cluster/CNI has special requirements for kubelet health checks or DNS.

To enable:

```bash
kubectl apply -f k8s/networkpolicies/
```

To remove:

```bash
kubectl delete -f k8s/networkpolicies/
```

