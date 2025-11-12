import asyncio
import csv
import sqlite3
import argparse
import httpx
import json
import os
import random
from datetime import datetime
from urllib.parse import urlparse

from config import OUTPUT_DIR, DB_PATH, CONCURRENCY_LIMIT
from scraper import scrape_domain, clean_target_url

db_lock = asyncio.Lock()
csv_lock = asyncio.Lock()

def delete_job_data(uid: str):
    try:
        print(f"[*] Initiating deletion sequence for UID: {uid}...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads WHERE uid = ?", (uid,))
        cursor.execute("DELETE FROM runs WHERE uid = ?", (uid,))
        conn.commit()
        conn.close()
        print(f"[+] Successfully purged database records for {uid}")

        csv_path = OUTPUT_DIR / f"{uid}_results.csv"
        if csv_path.exists():
            os.remove(csv_path)
            print(f"[+] Successfully deleted file: {csv_path}")

    except Exception as e:
        print(f"[!] Error deleting data for {uid}: {e}")


async def save_to_db(uid, web_domain, web_email, web_phone, web_address, web_status):
    async with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO leads (uid, web_domain, web_email, web_phone, web_address, web_status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid, web_domain) DO UPDATE SET
                    web_email=excluded.web_email,
                    web_phone=excluded.web_phone,
                    web_address=excluded.web_address,
                    web_status=excluded.web_status,
                    scraped_at=CURRENT_TIMESTAMP
            ''', (uid, web_domain, web_email, web_phone, web_address, web_status))
            conn.commit()
        except Exception as e:
            print(f"[!] DB Error for {web_domain}: {e}")
        finally:
            conn.close()


async def worker(domain, proxies_list, uid, semaphore, csv_path):
    async with semaphore:
        assigned_proxy = random.choice(proxies_list) if proxies_list else None
        proxy_display = "No Proxy" if not assigned_proxy else assigned_proxy.split('@')[-1]

        clean_url = clean_target_url(domain)
        clean_dom_name = urlparse(clean_url).netloc

        print(f"[*] Starting scrape: {clean_dom_name} [Routing via {proxy_display}]")

        try:
            result = await asyncio.wait_for(scrape_domain(clean_url, assigned_proxy), timeout=240.0)
        except asyncio.TimeoutError:
            print(f"[!] CRITICAL TIMEOUT: {clean_dom_name} hung indefinitely. Force terminating.")
            result = {
                "domain": clean_dom_name,
                "emails": [],
                "phones": [],
                "addresses": [],
                "status": "failed: absolute timeout"
            }
        except Exception as e:
            print(f"[!] UNEXPECTED WORKER ERROR: {clean_dom_name} -> {str(e)}")
            result = {
                "domain": clean_dom_name,
                "emails": [],
                "phones": [],
                "addresses": [],
                "status": f"error: {str(e)}"
            }

        emails_str = ", ".join(result.get("emails", []))
        phones_str = ", ".join(result.get("phones", []))
        addresses_str = " | ".join(result.get("addresses", []))
        status = result.get("status", "failed")
        final_domain = result.get("domain", clean_dom_name)
        
        print(f"[+] Finished scrape: {clean_dom_name} | Final Status: {status}")

        await save_to_db(uid, final_domain, emails_str, phones_str, addresses_str, status)

        async with csv_lock:
            with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([final_domain, emails_str, phones_str, addresses_str, status])

        return status


async def worker_csv(domain, proxies_list, uid, semaphore):
    async with semaphore:
        assigned_proxy = random.choice(proxies_list) if proxies_list else None
        proxy_display = "No Proxy" if not assigned_proxy else assigned_proxy.split('@')[-1]

        clean_url = clean_target_url(domain)
        clean_dom_name = urlparse(clean_url).netloc

        print(f"[*] Starting scrape: {clean_dom_name} [Routing via {proxy_display}]")

        try:
            result = await asyncio.wait_for(scrape_domain(clean_url, assigned_proxy), timeout=240.0)
        except asyncio.TimeoutError:
            print(f"[!] CRITICAL TIMEOUT: {clean_dom_name} hung indefinitely. Force terminating.")
            result = {
                "domain": clean_dom_name,
                "emails": [],
                "phones": [],
                "addresses": [],
                "status": "failed: absolute timeout"
            }
        except Exception as e:
            print(f"[!] UNEXPECTED WORKER ERROR: {clean_dom_name} -> {str(e)}")
            result = {
                "domain": clean_dom_name,
                "emails": [],
                "phones": [],
                "addresses": [],
                "status": f"error: {str(e)}"
            }

        emails_str = ", ".join(result.get("emails", []))
        phones_str = ", ".join(result.get("phones", []))
        addresses_str = " | ".join(result.get("addresses", []))
        status = result.get("status", "failed")
        final_domain = result.get("domain", clean_dom_name)
        
        print(f"[+] Finished scrape: {clean_dom_name} | Final Status: {status}")

        await save_to_db(uid, final_domain, emails_str, phones_str, addresses_str, status)

        return {
            "original_domain": domain, 
            "emails": emails_str,
            "phones": phones_str,
            "addresses": addresses_str,
            "status": status
        }


async def update_run_status(uid, total, successful, status):
    async with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO runs (uid, total_domains, successful_domains, status, completed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                successful_domains=excluded.successful_domains,
                status=excluded.status,
                completed_at=excluded.completed_at
        ''', (uid, total, successful, status, datetime.now().isoformat() if status == "completed" else None))
        conn.commit()
        conn.close()


async def call_webhook(webhook_url, uid, total, successful, path_or_url):
    print(f"[*] Firing webhook to {webhook_url} for UID: {uid}...")

    is_url = str(path_or_url).startswith("http")
    
    payload = {
        "uid": uid,
        "status": "completed",
        "download_url" if is_url else "file_location": str(path_or_url),
        "total_domains_processed": total,
        "successful_scrapes": successful,
        "timestamp": datetime.now().isoformat()
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
            if response.status_code in [200, 201]:
                print(f"[+] Webhook delivered successfully! (Status: {response.status_code})")
    except Exception as e:
        print(f"[!] Failed to deliver webhook: {e}")


async def run_orchestrator(uid: str, webhook_url: str, domains: list, proxies: list):
    print(f"\n{'='*50}")
    print(f"🚀 STARTING JSON JOB | UID: {uid} | Target Domains: {len(domains)}")
    print(f"⚙️  Concurrency Limit: {CONCURRENCY_LIMIT} | Active Proxies: {len(proxies)}")
    print(f"{'='*50}\n")

    await update_run_status(uid, len(domains), 0, "running")

    csv_file_path = OUTPUT_DIR / f"{uid}_results.csv"
    with open(csv_file_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["web_domain", "web_email", "web_phone", "web_address", "web_status"])

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    unique_domains = list(set(domains))
    tasks = [worker(domain, proxies, uid, semaphore, csv_file_path) for domain in unique_domains]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful_count = sum(1 for res in results if res == "success")

    await update_run_status(uid, len(unique_domains), successful_count, "completed")
    await call_webhook(webhook_url, uid, len(unique_domains), successful_count, csv_file_path.absolute())


async def run_csv_orchestrator(uid: str, webhook_url: str, input_csv_path: str, domain_col: str, 
                               email_col: str, phone_col: str, address_col: str, status_col: str, 
                               proxies: list, download_base_url: str):
    print(f"\n{'='*50}")
    print(f"🚀 STARTING CSV JOB | UID: {uid}")
    print(f"⚙️  Concurrency Limit: {CONCURRENCY_LIMIT} | Active Proxies: {len(proxies)}")
    print(f"{'='*50}\n")

    rows = []
    with open(input_csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)

    for col in [email_col, phone_col, address_col, status_col]:
        if col and col not in fieldnames:
            fieldnames.append(col)

    def generate_dedup_key(raw_url: str) -> str:
        netloc = urlparse(clean_target_url(raw_url)).netloc.lower()
        return netloc.replace("www.", "").encode('ascii', 'ignore').decode('ascii').strip()

    raw_domains = [row.get(domain_col, "").strip() for row in rows if row.get(domain_col, "").strip()]
    
    unique_target_map = {} 
    for raw in raw_domains:
        d_key = generate_dedup_key(raw)
        if d_key not in unique_target_map:
            unique_target_map[d_key] = raw

    domains_to_scrape = list(unique_target_map.values())

    await update_run_status(uid, len(domains_to_scrape), 0, "running")

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    tasks = [worker_csv(domain, proxies, uid, semaphore) for domain in domains_to_scrape]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)

    results_map = {}
    successful_count = 0
    for res in results:
        if isinstance(res, dict):
            worker_d_key = generate_dedup_key(res["original_domain"])
            results_map[worker_d_key] = res
            if res["status"] == "success":
                successful_count += 1

    for row in rows:
        raw_dom = row.get(domain_col, "").strip()
        if not raw_dom: continue
        
        row_d_key = generate_dedup_key(raw_dom)
        
        if row_d_key in results_map:
            data = results_map[row_d_key]
            if email_col: row[email_col] = data["emails"]
            if phone_col: row[phone_col] = data["phones"]
            if address_col: row[address_col] = data["addresses"]
            if status_col: row[status_col] = data["status"]

    final_csv_path = OUTPUT_DIR / f"{uid}_results.csv"
    with open(final_csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    if os.path.exists(input_csv_path):
        os.remove(input_csv_path)
        print(f"[*] Cleaned up temporary input file: {input_csv_path}")

    await update_run_status(uid, len(domains_to_scrape), successful_count, "completed")
    
    download_url = f"{download_base_url.rstrip('/')}/api/download/{uid}"
    await call_webhook(webhook_url, uid, len(domains_to_scrape), successful_count, download_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Advanced JSON Lead Gen Web Scraper")
    parser.add_argument("--payload", required=False, help="Path to JSON file OR raw JSON string")
    parser.add_argument("--delete", required=False, help="Delete DB entries and CSV file for a given UID")
    args = parser.parse_args()

    if args.delete:
        delete_job_data(args.delete)
        exit(0)

    if not args.payload:
        exit(1)

    try:
        if os.path.isfile(args.payload):
            with open(args.payload, 'r') as f:
                payload_data = json.load(f)
        else:
            payload_data = json.loads(args.payload)
    except Exception as e:
        exit(1)

    uid = payload_data.get("uid")
    webhook_url = payload_data.get("webhook")
    domains_list = payload_data.get("domains", [])
    proxies_list = payload_data.get("proxies", [])

    asyncio.run(run_orchestrator(uid, webhook_url, domains_list, proxies_list))
