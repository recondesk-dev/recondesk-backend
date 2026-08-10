"""GSTR-9 & GSTR-9C Annual Return FastAPI Router.

Endpoints for GSTR-9 auto-computation, CA audit cell overrides, GSTR-9C reconciliation,
and official GSTN portal JSON exports.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services import gstr9_computation as g9_svc
from app.services import gstr9c_computation as g9c_svc
from app.services.reconciliation_import_wizard.wizard_service import assert_client_access

logger = logging.getLogger(__name__)

router = APIRouter()


class AuditOverrideItem(BaseModel):
    table_key: str = Field(..., description="Table identifier, e.g. table4")
    cell_key: str = Field(..., description="Cell identifier, e.g. 4B_b2b")
    override_value: float = Field(..., description="CA override value")
    notes: Optional[str] = Field(None, description="Optional audit observation note")


class SaveAuditOverridesRequest(BaseModel):
    client_id: str = Field(..., description="UUID of client GSTIN")
    financial_year: str = Field(..., description="Financial year in YYYY-YY format, e.g. 2025-26")
    overrides: list[AuditOverrideItem] = Field(..., description="List of CA cell overrides")


def _assert_client(sb: Any, client_id: str, user_id: str) -> None:
    try:
        assert_client_access(sb, client_id, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this client GSTIN",
        ) from exc


@router.get("/clients/{client_id}/computation")
async def get_gstr9_computation(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch system-computed Form GSTR-9 Figures (Tables 4 to 9) with CA overrides."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        comp = g9_svc.compute_gstr9(sb, client_id, fy)
        return comp
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to compute GSTR-9: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute GSTR-9: {exc}",
        ) from exc


@router.patch("/clients/{client_id}/overrides")
async def save_gstr9_audit_overrides(
    client_id: str,
    body: SaveAuditOverridesRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Save CA audit cell overrides for Form GSTR-9."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    fy = body.financial_year.strip()
    updater_uuid = user_id if (user_id and len(user_id) == 36) else None

    try:
        try:
            for item in body.overrides:
                row = {
                    "client_gstin_id": client_id,
                    "financial_year": fy,
                    "table_key": item.table_key.strip(),
                    "cell_key": item.cell_key.strip(),
                    "override_value": item.override_value,
                    "notes": item.notes,
                }
                if updater_uuid:
                    row["updated_by"] = updater_uuid

                sb.table("gstr9_audit_overrides").upsert(
                    row, on_conflict="client_gstin_id,financial_year,table_key,cell_key"
                ).execute()
        except Exception as postgrest_exc:
            logger.warning("Supabase PostgREST upsert failed, executing via direct SQL fallback: %s", postgrest_exc)
            from app.config import get_settings
            import sqlalchemy as sa
            s = get_settings()
            db_url = s.SUPABASE_DATABASE_URL or s.DATABASE_URL
            if db_url:
                eng = sa.create_engine(db_url)
                with eng.connect() as conn:
                    # Self-healing DDL: ensure table exists before insert
                    conn.execute(
                        sa.text(
                            """
                            CREATE TABLE IF NOT EXISTS public.gstr9_audit_overrides (
                                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                                client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                                financial_year TEXT NOT NULL,
                                table_key TEXT NOT NULL,
                                cell_key TEXT NOT NULL,
                                system_value NUMERIC(15, 2) DEFAULT 0.00,
                                override_value NUMERIC(15, 2) NOT NULL,
                                notes TEXT,
                                updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                                CONSTRAINT uq_gstr9_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
                            );
                            """
                        )
                    )
                    conn.commit()

                    for item in body.overrides:
                        conn.execute(
                            sa.text(
                                """
                                INSERT INTO public.gstr9_audit_overrides
                                (client_gstin_id, financial_year, table_key, cell_key, override_value, notes, updated_by)
                                VALUES (:cid, :fy, :tk, :ck, :ov, :notes, :ub)
                                ON CONFLICT (client_gstin_id, financial_year, table_key, cell_key)
                                DO UPDATE SET override_value = EXCLUDED.override_value, notes = EXCLUDED.notes, updated_at = NOW();
                                """
                            ),
                            {
                                "cid": client_id,
                                "fy": fy,
                                "tk": item.table_key.strip(),
                                "ck": item.cell_key.strip(),
                                "ov": item.override_value,
                                "notes": item.notes,
                                "ub": updater_uuid,
                            },
                        )
                    # Notify PostgREST to reload schema
                    conn.execute(sa.text("NOTIFY pgrst, 'reload schema';"))
                    conn.commit()
                eng.dispose()

        comp = g9_svc.compute_gstr9(sb, client_id, fy)
        return comp
    except Exception as exc:
        logger.exception("Failed to save GSTR-9 overrides for client %s fy %s: %s", client_id, fy, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save audit overrides: {exc}",
        ) from exc


@router.get("/clients/{client_id}/gstr9c/reconciliation")
async def get_gstr9c_reconciliation(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    audited_turnover: float = Query(0.0, description="Audited Gross Turnover"),
    audited_itc: float = Query(0.0, description="Audited Net ITC"),
    audited_tax: float = Query(0.0, description="Audited Tax Payable"),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch GSTR-9C Reconciliation Statement figures & turnover/ITC variances."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        comp = g9c_svc.compute_gstr9c(
            sb,
            client_id,
            fy,
            audited_turnover=audited_turnover,
            audited_itc=audited_itc,
            audited_tax=audited_tax,
        )
        return comp
    except Exception as exc:
        logger.exception("Failed to compute GSTR-9C reconciliation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute GSTR-9C",
        ) from exc


@router.get("/clients/{client_id}/export/json")
async def export_gstr9_portal_json(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    current_user: dict = Depends(get_current_active_user),
):
    """Download official GSTN Portal compliant GSTR-9 JSON for upload."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        payload = g9_svc.build_gstr9_portal_json(sb, client_id, fy)
        json_bytes = json.dumps(payload, indent=2).encode("utf-8")
        filename = f"gstr9_{comp_gstin(payload)}_{fy.replace('-', '')}.json"

        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.exception("Failed to export GSTR-9 JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate GSTR-9 JSON",
        ) from exc


@router.get("/clients/{client_id}/gstr9c/export/json")
async def export_gstr9c_portal_json(
    client_id: str,
    fy: str = Query("2025-26", description="Financial year YYYY-YY"),
    audited_turnover: float = Query(0.0, description="Audited Gross Turnover"),
    audited_itc: float = Query(0.0, description="Audited Net ITC"),
    audited_tax: float = Query(0.0, description="Audited Tax Payable"),
    current_user: dict = Depends(get_current_active_user),
):
    """Download official GSTR-9C JSON payload for Auditor DSC signing."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        payload = g9c_svc.build_gstr9c_portal_json(
            sb, client_id, fy, audited_turnover, audited_itc, audited_tax
        )
        json_bytes = json.dumps(payload, indent=2).encode("utf-8")
        filename = f"gstr9c_{comp_gstin(payload)}_{fy.replace('-', '')}.json"

        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.exception("Failed to export GSTR-9C JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate GSTR-9C JSON",
        ) from exc


def comp_gstin(payload: dict) -> str:
    return payload.get("gstin", "GSTIN")
