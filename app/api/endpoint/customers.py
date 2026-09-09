from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.schemas.customers import CustomerListResponse, CustomerSummary
from app.dependencies.db import get_db

router = APIRouter(prefix="/customers", tags=["customers"])

@router.get("", response_model=CustomerListResponse)
def list_customers(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, name FROM customers ORDER BY name")).mappings().all()
    return CustomerListResponse(customers=[CustomerSummary(**dict(r)) for r in rows])