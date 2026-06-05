# High CPU Troubleshooting Runbook

## Overview

This runbook covers steps to diagnose and resolve high CPU alerts for services
running in Kubernetes production clusters.

## Symptoms

- CPU usage above 80% for more than 5 minutes.
- Alert: `HighCPUUsage` from Prometheus Alertmanager.
- Service may become unresponsive or experience increased latency.

## Step 1: Verify the alert

1. Open Grafana and check the CPU panel for the affected service.
2. Run the following Prometheus query to confirm:

```promql
sum(rate(container_cpu_usage_seconds_total{namespace="production"}[5m])) by (pod)
```

3. Identify which pod(s) are affected.

## Step 2: Check for memory leaks

1. Check memory usage:

```bash
kubectl top pods -n production --sort-by=memory
```

2. If memory is also high, the service may be experiencing a GC (Garbage Collection) loop.

### Sub-step 2.1: Examine JVM heap (Java services)

```bash
kubectl exec -it <pod-name> -n production -- jcmd 1 VM.native_memory
```

## Step 3: Check recent deployments

1. Review recent deployments that may have introduced the issue:

```bash
kubectl rollout history deployment/payment-service -n production
```

2. If a recent deployment is suspected, consider a rollback:

```bash
kubectl rollout undo deployment/payment-service -n production
```

**IMPORTANT**: Rolling back requires approval from the on-call engineer.

## Step 4: Remediation options

Choose based on severity:

| Severity | Action | Approval Required |
|---|---|---|
| Warning | Monitor for 15 min | No |
| Critical (pod unresponsive) | Restart pod | Yes |
| Critical (all pods) | Scale up replicas | Yes |
| Prolonged (>1 hr) | Rollback deployment | Yes |

### Restart a specific pod

```bash
kubectl delete pod <pod-name> -n production
```

### Scale up the deployment

```bash
kubectl scale deployment payment-service --replicas=4 -n production
```

## Step 5: Post-incident

1. File an incident report within 24 hours.
2. Update this runbook if new patterns are found.
3. Create a JIRA ticket for the root cause fix.

## Related runbooks

- [Memory OOM Runbook](./memory-oom.md)
- [Pod Crash Loop Runbook](./pod-crash-loop.md)
- [Deployment Rollback Runbook](./deployment-rollback.md)
