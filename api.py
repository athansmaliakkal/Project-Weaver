import sqlite3
import os
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Security, File, UploadFile, Form, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

from config import DB_PATH, OUTPUT_DIR
from main import run_orchestrator, run_csv_orchestrator, delete_job_data
from init_db import initialize_database

API_KEY = os.getenv("API_SECRET_KEY", "abc123321cba")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return api_key

app = FastAPI(title="Lead Gen Scraper API", version="2.0")

@app.on_event("startup")
async def startup_event():
    print("[*] Server starting up. Verifying database integrity...")
    initialize_database()

class ScrapePayload(BaseModel):
    uid: str
    webhook: str
    domains: List[str]
    proxies: Optional[List[str]] = []

@app.post("/api/scrape", dependencies=[Depends(verify_api_key)], status_code=202)
async def start_scrape_job(payload: ScrapePayload, background_tasks: BackgroundTasks):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM runs WHERE uid = ?", (payload.uid,))
    existing_job = cursor.fetchone()
    conn.close()

    if existing_job:
        raise HTTPException(status_code=400, detail=f"Job with UID {payload.uid} already exists.")

    background_tasks.add_task(
        run_orchestrator,
        uid=payload.uid,
        webhook_url=payload.webhook,
        domains=payload.domains,
        proxies=payload.proxies
    )

    return {"message": "JSON Job accepted and running in the background", "uid": payload.uid}


@app.post("/api/scrape/csv", dependencies=[Depends(verify_api_key)], status_code=202)
async def start_scrape_job_csv(
    request: Request,
    background_tasks: BackgroundTasks,
    uid: str = Form(...),
    webhook: str = Form(...),
    domain_column: str = Form(...),
    email_column: str = Form("scraped_email"),
    phone_column: str = Form("scraped_phone"),
    address_column: str = Form("scraped_address"),
    status_column: str = Form("scraped_status"),
    proxies: str = Form("[]"), 
    file: UploadFile = File(...)
):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM runs WHERE uid = ?", (uid,))
    existing_job = cursor.fetchone()
    conn.close()

    if existing_job:
        raise HTTPException(status_code=400, detail=f"Job with UID {uid} already exists.")

    try:
        proxies_list = json.loads(proxies)
        if not isinstance(proxies_list, list):
            proxies_list = []
    except json.JSONDecodeError:
        proxies_list = []

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are allowed.")

    temp_input_path = OUTPUT_DIR / f"temp_input_{uid}.csv"
    with open(temp_input_path, "wb") as buffer:
        buffer.write(await file.read())

    download_base_url = str(request.base_url)

    background_tasks.add_task(
        run_csv_orchestrator,
        uid=uid,
        webhook_url=webhook,
        input_csv_path=str(temp_input_path),
        domain_col=domain_column,
        email_col=email_column,
        phone_col=phone_column,
        address_col=address_column,
        status_col=status_column,
        proxies=proxies_list,
        download_base_url=download_base_url
    )

    return {"message": "CSV Job accepted and running in the background", "uid": uid}


@app.get("/api/download/{uid}", dependencies=[Depends(verify_api_key)])
async def download_results_csv(uid: str):
    file_path = OUTPUT_DIR / f"{uid}_results.csv"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found. Job might still be running or was deleted.")

    return FileResponse(
        path=file_path,
        filename=f"{uid}_results.csv",
        media_type='text/csv'
    )


@app.get("/api/status/{uid}", dependencies=[Depends(verify_api_key)])
async def get_job_status(uid: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT total_domains, successful_domains, status, started_at, completed_at FROM runs WHERE uid = ?", (uid,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "uid": uid,
        "total_domains": row[0],
        "successful_domains": row[1],
        "status": row[2],
        "started_at": row[3],
        "completed_at": row[4]
    }


@app.get("/api/results/{uid}", dependencies=[Depends(verify_api_key)])
async def get_job_results(uid: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT web_domain, web_email, web_phone, web_address, web_status FROM leads WHERE uid = ?", (uid,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No results found for this UID")

    results = [dict(row) for row in rows]
    return {"uid": uid, "total_leads": len(results), "data": results}


@app.delete("/api/job/{uid}", dependencies=[Depends(verify_api_key)])
async def delete_job(uid: str):
    delete_job_data(uid)
    return {"message": f"Successfully deleted all data associated with UID: {uid}"}
