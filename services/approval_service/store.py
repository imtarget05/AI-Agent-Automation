from typing import Dict, Optional
from .models import ApprovalRequest

class ApprovalStore:
    def __init__(self):
        self.approvals: Dict[str, ApprovalRequest] = {}

    def add(self, approval: ApprovalRequest):
        self.approvals[approval.id] = approval

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        return self.approvals.get(approval_id)

    def list_all(self):
        return list(self.approvals.values())

    def update(self, approval: ApprovalRequest):
        self.approvals[approval.id] = approval

_store = ApprovalStore()

def get_store() -> ApprovalStore:
    return _store
