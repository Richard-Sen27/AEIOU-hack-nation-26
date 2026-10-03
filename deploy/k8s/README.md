# Kubernetes

Secrets are never committed. Create them by hand in the target namespace, e.g.:

```sh
kubectl create secret generic atlas-backend \
  --namespace ionvo-develop \
  --from-literal=DATABASE_URL='postgresql+psycopg://...'
```
