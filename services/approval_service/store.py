import json
import os
from typing import Dict, Optional, List
from .models import ApprovalRequest


class ApprovalStore:
    def __init__(self, persist_path: str = "data/approvals.json"):
        self.persist_path = persist_path
        self.approvals: Dict[str, ApprovalRequest] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self.approvals[k] = ApprovalRequest.model_validate(v)
            except Exception as e:
                print(f"Failed to load approvals: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        try:
            with open(self.persist_path, "w") as f:
                data = {k: v.model_dump(mode="json") for k, v in self.approvals.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save approvals: {e}")

    def add(self, approval: ApprovalRequest):
        self.approvals[approval.id] = approval
        self._save()

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        return self.approvals.get(approval_id)

    def list_all(self) -> List[ApprovalRequest]:
        return list(self.approvals.values())

    def update(self, approval: ApprovalRequest):
        self.approvals[approval.id] = approval
        self._save()


_store = ApprovalStore()


def get_store() -> ApprovalStore:
    return _store
