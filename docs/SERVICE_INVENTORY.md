# Service Inventory

| Service | Port | Role |
|---------|------|------|
| Gateway | 8000 | Orchestration & Entry |
| Social Module | 8002 | Facebook, Zalo, and Telegram webhook auto-replies |
| Tool Service | 8008 | Read-only infra queries, guarded email, mock provider adapters |
| RAG Service | 8007 | Knowledge Base |
| Guardrail | 8010 | Safety & Security |
| Approval Service | 8011 | In-memory task approval queue |
| AIOps Agent | 8013 | Metric & Log Analysis |
| RCA Agent | 8014 | Cause Analysis |
| Email Agent | 8009 | Stakeholder Comms |
| Monitoring | 8005 | Metrics & Analytics |
| Report Agent | 8012 | Incident summaries |
| DevOps Agent | 8015 | Remediation proposals only |
| Evaluation Service | 8016 | LLM-as-a-judge fixture scoring |
| n8n | 5678 | Legacy workflow automation UI |
