# 🕸️ Project Weaver

Project Weaver is an asynchronous, headless **Web Scraper API** built mainly for high-yield lead generation and data enrichment.

It is designed to plug directly into automation tools like **n8n**, **Make**, or custom backend systems. The service accepts large lists of company domains, routes them through residential proxies using stealth browsers, and extracts useful contact information such as **emails, phone numbers, and addresses** from the website DOM.

The goal of the project is to act more like a small **data-processing microservice** rather than a simple scraping script.

---

# 🚀 Core Engine Features

### Native CSV Pipeline
A `multipart/form-data` endpoint accepts CSV uploads directly. The system processes each domain and injects the scraped results back into the **same file**, preserving the original row order.

### Smart Deduplication
Different versions of the same site (for example `http://domain.com`, `https://www.domain.com`, or `www.domain.com/`) are mathematically normalized to a single key.

The scraper only processes the domain once to save proxy bandwidth, then maps the results back to all matching rows.

### The “Deadman's Switch”
Each Playwright worker runs inside a strict `asyncio` timeout. If a proxy crashes or a website freezes indefinitely, the worker is forcefully terminated after **4 minutes** to prevent memory leaks and stalled jobs.

### Legal Page Discovery
If emails are hidden behind contact forms, the scraper automatically searches **Privacy Policy**, **Terms of Service**, and **Impressum** pages where contact information is often legally required to appear.

### IFrame Deep Scanning
Instead of only scraping the main page DOM, Weaver recursively scans **embedded iframes** (HubSpot widgets, Zendesk forms, etc.) to discover additional contact information.

### Anti-Bot De-obfuscation
Regex preprocessing converts protected text like:

```
info [at] domain [dot] com
```

back into a standard machine-readable email format before extraction.

---

# 🐳 Quickstart (Docker Deployment)

Project Weaver is fully containerized. The Docker environment installs:

- Ubuntu dependencies
- Python virtual environment
- Playwright
- Camoufox stealth browser binaries

Everything runs automatically when the container starts.

---

## 1. Clone & Configure

```bash
git clone https://github.com/athansmaliakkal/Project-Weaver.git
cd Project-Weaver
```

Open the `.env` file in the project root and update the values:

```env
API_SECRET_KEY=your_secure_api_key
CONCURRENCY_LIMIT=3
```

The repository already includes a `.env` file with placeholder values.  
Simply replace them with your own configuration before starting the service.

## 2. Start the Service

```bash
docker compose up -d --build
```

This builds the container and exposes the API on:

```
http://localhost:8000
```

Generated files and job state will be stored locally in:

```
./output
./db
```

---

# 📖 API Reference

## Authentication

All API requests require authentication using a custom header.

```
Header Key: X-API-Key
Header Value: <your API key from .env>
```

---

# 1. Create a CSV Job (Recommended)

Uploads a CSV file and enriches it with scraped data in the background.

### Endpoint

```
POST /api/scrape/csv
```

### Content Type

```
multipart/form-data
```

### Form Fields

| Field | Type | Required | Description |
|------|------|------|------|
| uid | string | yes | Unique identifier for the job |
| webhook | string | yes | URL to receive completion webhook |
| domain_column | string | yes | Name of the column containing domains |
| file | file | yes | CSV file |
| proxies | string | no | JSON array of proxy URLs |
| email_column | string | no | Custom output column name |
| phone_column | string | no | Custom output column name |
| address_column | string | no | Custom output column name |
| status_column | string | no | Custom output column name |

### Success Response

```json
{
  "message": "CSV Job accepted and running in the background",
  "uid": "job_12345"
}
```

---

# 2. Create a JSON Job

Instead of uploading a CSV, you can submit domains directly as JSON.

### Endpoint

```
POST /api/scrape
```

### Example Request

```json
{
  "uid": "job_12345",
  "webhook": "https://your-domain.com/webhook",
  "domains": [
    "example.com",
    "test.com"
  ],
  "proxies": [
    "http://user:pass@proxy.com:80"
  ]
}
```

---

# 3. Check Job Status

Retrieve real-time job progress.

### Endpoint

```
GET /api/status/{uid}
```

### Example Response

```json
{
  "uid": "job_12345",
  "total_domains": 100,
  "successful_domains": 85,
  "status": "running",
  "started_at": "2026-03-13T10:00:00",
  "completed_at": null
}
```

---

# 4. Download Finished CSV

Download the enriched CSV file once the job is finished.

### Endpoint

```
GET /api/download/{uid}
```

### Response

```
text/csv
```

Returns `404 Not Found` if the job failed or was already deleted.

---

# 5. Get Results as JSON

Fetch raw results directly from the database.

### Endpoint

```
GET /api/results/{uid}
```

---

# 6. Delete / Cleanup Job (Important)

Output files and database rows are **not automatically deleted**.

After your system downloads the data, you should clean up the job manually.

### Endpoint

```
DELETE /api/job/{uid}
```

This removes:

- the CSV output file
- associated database entries

---

# 🔗 Webhook Mechanics

Project Weaver runs completely **asynchronously**.

When the background job finishes processing all domains, it automatically sends a webhook.

### Method

```
POST
```

### Payload Example

```json
{
  "uid": "job_12345",
  "status": "completed",
  "download_url": "http://<your-server-ip>:8000/api/download/job_12345",
  "total_domains_processed": 50,
  "successful_scrapes": 48,
  "timestamp": "2026-03-13T10:05:00.123456"
}
```

If the **JSON job method** was used instead of CSV, the payload may contain:

```
file_location
```

instead of a `download_url`.

---

# 📊 Output CSV Structure

When you upload a CSV, the original data is **never modified or reordered**.

### Row Order Preservation

Even though domains are processed concurrently, the final CSV maintains the exact order of your original upload.

### Additional Columns Added

The system appends four new columns to the right side of the CSV.

| Column | Description |
|------|------|
| scraped_email | Comma-separated list of discovered emails |
| scraped_phone | Comma-separated list of phone numbers |
| scraped_address | Pipe-separated list of physical addresses |
| scraped_status | Result of scraping process |

Example values:

```
success
failed: absolute timeout
error: SSL_ERROR
```

---

# 👨‍💻 Author Notes

This project was built mainly as an experiment in pushing the limits of **headless browser concurrency and intelligent DOM parsing**.

By combining **Camoufox stealth browsing**, **Playwright automation**, and **asyncio concurrency controls**, the goal was to create something that behaves more like a small **scraping microservice** than a simple script.

It’s not meant to be perfect, but it’s been a fun way to explore building scalable scraping systems and API-driven automation tools.