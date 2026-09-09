from __future__ import annotations
from pydantic import BaseModel

class CustomerSummary(BaseModel):
    id: int
    name: str

class CustomerListResponse(BaseModel):
    customers: list[CustomerSummary]