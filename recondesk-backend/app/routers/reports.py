from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from supabase import Client

from app.auth import get_current_active_user
from app.database import supabase_client
from app.services.report_service import generate_reconciliation_pdf

router = APIRouter()


@router.get("/reconciliation/{job_id}/pdf")
async def download_reconciliation_pdf(
    job_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    """Generate and stream a PDF report for a completed reconciliation job."""
    job_result = (
        db.table("reconciliation_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("user_id", str(current_user["id"]))
        .single()
        .execute()
    )
    if not job_result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    job = job_result.data
    summary = {
        "total": job.get("total_rows", 0),
        "matched": job.get("matched_rows", 0),
        "partial": 0,
        "unmatched": job.get("unmatched_rows", 0),
    }

    rows_result = db.table("reconciliation_rows").select("*").eq("job_id", job_id).execute()
    rows = rows_result.data or []

    pdf_bytes = generate_reconciliation_pdf(
        job_name=job["name"],
        summary=summary,
        rows=rows,
        generated_by=current_user.get("email", "ReconDesk"),
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="recondesk-{job_id[:8]}.pdf"'},
    )
