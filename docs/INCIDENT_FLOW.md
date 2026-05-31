# Incident Response Flow

1. **Detection**: Prometheus alert or manual incident report via `/incident/analyze`.
2. **Analysis**: 
   - `AIOps Agent` queries Prometheus for relevant metrics.
   - `Tool Agent` queries K8s for pod status, logs, and events.
3. **Retrieval**: `RAG Agent` looks up runbooks and architecture docs.
4. **Conclusion**: `RCA Agent` synthesizes all data to find the root cause.
5. **Guardrail Check**: Proposed remediation actions are checked by `Guardrail Agent`.
6. **Approval**: High-risk actions (e.g., `delete pod`) are sent to `Approval Service`.
7. **Reporting**: `Report Agent` creates a summary and `Email Agent` drafts a notification.
