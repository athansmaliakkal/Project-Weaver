import os
import asyncio
import re
import stat
import random
import httpx
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, parse_qs
from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox
import phonenumbers

os.environ["MOZ_DISABLE_GLXTEST"] = "1"
os.environ["MOZ_HEADLESS"] = "1"
os.environ["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
os.environ["MOZ_DISABLE_GMP_SANDBOX"] = "1"
os.environ["DISABLE_WAYLAND"] = "1"
os.environ["MOZ_WEBRENDER"] = "0"
os.environ["MOZ_SOFTWARE_WEBRENDER"] = "1"
if "WAYLAND_DISPLAY" in os.environ:
    del os.environ["WAYLAND_DISPLAY"]

try:
    _camoufox_cache = Path.home() / ".cache" / "camoufox"
    _glx_test_file = _camoufox_cache / "glxtest"
    if _camoufox_cache.exists() and not _glx_test_file.exists():
        _glx_test_file.write_text("#!/bin/sh\nexit 0\n")
        _glx_test_file.chmod(_glx_test_file.stat().st_mode | stat.S_IEXEC)
except Exception:
    pass

TARGET_LINK_KEYWORDS = [
    'contact', 'about', 'team', 'support', 'location', 'us', 
    'reach', 'help', 'directory', 'staff', 'office', 'connect', 
    'info', 'profile', 'impressum', 'corporate', 'headquarters', 
    'management', 'board', 'investors', 'service',
    'privacy', 'policy', 'terms', 'legal', 'conditions'
]

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

JUNK_PREFIXES = {'noreply', 'no-reply', 'daemon', 'postmaster', 'sentry', 'mailer', 'abuse', 'example'}
JUNK_DOMAINS = {'sentry.io', 'wixpress.com', 'example.com', 'domain.com', 'name.com'}
FILE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.js', '.css', '.woff', '.ttf']


def clean_target_url(raw_url: str, force_http: bool = False) -> str:
    raw_url = unquote(raw_url.strip())
    
    if "google.com/url" in raw_url or "google.com.au/url" in raw_url:
        parsed = urlparse(raw_url)
        qs = parse_qs(parsed.query)
        if 'q' in qs:
            raw_url = qs['q'][0]
        elif 'url' in qs:
            raw_url = qs['url'][0]
            
    if not raw_url.startswith("http"):
        raw_url = ("http://" if force_http else "https://") + raw_url
        
    return raw_url

async def block_unnecessary_resources(route, request):
    excluded_types = ['image', 'stylesheet', 'media', 'font', 'other']
    if request.resource_type in excluded_types or ".css" in request.url or ".jpg" in request.url:
        await route.abort()
    else:
        await route.continue_()

def is_valid_email(email: str) -> bool:
    email = email.lower()
    
    if any(email.endswith(ext) for ext in FILE_EXTENSIONS):
        return False
        
    try:
        prefix, domain = email.split('@')
        if prefix in JUNK_PREFIXES or domain in JUNK_DOMAINS:
            return False
        if len(prefix) > 25:
            return False
        return True
    except ValueError:
        return False

def deobfuscate_text(text: str) -> str:
    text = re.sub(r'\s*(?:\[at\]|\(at\)|\{at\}| @ )\s*', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*(?:\[dot\]|\(dot\)|\{dot\}| \. )\s*', '.', text, flags=re.IGNORECASE)
    return text

def extract_data_from_html(html_content, current_data):
    soup = BeautifulSoup(html_content, 'lxml')
    
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip().lower()
        if href.startswith('mailto:'):
            raw_email = href.replace('mailto:', '').split('?')[0].strip()
            if EMAIL_REGEX.match(raw_email) and is_valid_email(raw_email):
                current_data["emails"].add(raw_email)
        elif href.startswith('tel:'):
            raw_phone = href.replace('tel:', '').strip()
            current_data["phones"].add(raw_phone)

    for script_or_style in soup(['script', 'style', 'noscript']):
        script_or_style.decompose()

    text_content = soup.get_text(separator=' ', strip=True)
    
    clean_text = deobfuscate_text(text_content)

    found_emails = EMAIL_REGEX.findall(clean_text)
    for email in found_emails:
        if is_valid_email(email):
            current_data["emails"].add(email.lower())

    for match in phonenumbers.PhoneNumberMatcher(clean_text, "US"): 
        current_data["phones"].add(match.raw_string.strip())

    address_tags = soup.find_all('address')
    for tag in address_tags:
        current_data["addresses"].add(tag.get_text(separator=', ', strip=True))

def find_target_links_in_dom(html_content, base_url):
    soup = BeautifulSoup(html_content, 'lxml')
    links_to_visit = set()
    
    base_domain = urlparse(base_url).netloc.replace("www.", "")

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        target_domain = urlparse(full_url).netloc.replace("www.", "")
        
        if target_domain == base_domain:
            url_lower, text_lower = full_url.lower(), a_tag.get_text(strip=True).lower()
            if any(kw in url_lower or kw in text_lower for kw in TARGET_LINK_KEYWORDS):
                links_to_visit.add(full_url)
                
    return links_to_visit

def prioritize_links(links: set) -> list:
    def score(link):
        link_l = link.lower()
        pts = 0
        if '/contact' in link_l: pts += 10
        if '/about' in link_l: pts += 5
        if '/team' in link_l: pts += 3
        if 'privacy' in link_l or 'policy' in link_l or 'terms' in link_l: pts += 2 
        return pts
        
    sorted_links = sorted(list(links), key=score, reverse=True)
    return sorted_links[:6]


async def scrape_domain(domain: str, proxy_server: str = None, is_retry: bool = False, force_http: bool = False) -> dict:
    url = clean_target_url(domain, force_http=force_http)
    domain_netloc = urlparse(url).netloc

    lead_data = {"domain": domain_netloc, "emails": set(), "phones": set(), "addresses": set(), "status": "failed"}
    
    proxy_config = None
    if proxy_server:
        parsed_proxy = urlparse(proxy_server)
        if parsed_proxy.username and parsed_proxy.password:
            proxy_config = {
                "server": f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}",
                "username": parsed_proxy.username,
                "password": parsed_proxy.password
            }
        else:
            proxy_config = {"server": proxy_server}

    try:
        async with AsyncCamoufox(headless=True, proxy=proxy_config, geoip=True) as browser:
            page = await browser.new_page()

            print(f"[{domain_netloc}] Icebreaker Phase: Loading Homepage...")
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            await page.wait_for_timeout(4500) 
            
            for frame in page.frames:
                try:
                    frame_html = await frame.content()
                    extract_data_from_html(frame_html, lead_data)
                except Exception:
                    pass

            sub_links = set()
            print(f"[{domain_netloc}] Hunting for XML Sitemap...")
            
            sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml", "/page-sitemap.xml"]
            
            try:
                context_cookies = await page.context.cookies()
                httpx_cookies = {c['name']: c['value'] for c in context_cookies}
                
                async with httpx.AsyncClient(verify=False, proxy=proxy_server) as client:
                    for path in sitemap_paths:
                        sitemap_resp = await client.get(f"{url.rstrip('/')}{path}", cookies=httpx_cookies, timeout=7)
                        
                        if sitemap_resp.status_code == 200 and "xml" in sitemap_resp.headers.get("Content-Type", "").lower():
                            soup = BeautifulSoup(sitemap_resp.text, 'xml')
                            for loc in soup.find_all('loc'):
                                loc_url = loc.text.strip()
                                if any(kw in loc_url.lower() for kw in TARGET_LINK_KEYWORDS):
                                    sub_links.add(loc_url)
                            if sub_links:
                                break 
            except Exception:
                pass 

            if not sub_links:
                print(f"[{domain_netloc}] Sitemaps missed. Falling back to DOM <a> tags...")
                home_html = await page.content()
                sub_links = find_target_links_in_dom(home_html, url)

            if not sub_links:
                print(f"[{domain_netloc}] 0 sub-pages found. Initiating extended blind brute-force...")
                sub_links.add(f"{url.rstrip('/')}/contact")
                sub_links.add(f"{url.rstrip('/')}/contact-us")
                sub_links.add(f"{url.rstrip('/')}/about")
                sub_links.add(f"{url.rstrip('/')}/about-us")
                sub_links.add(f"{url.rstrip('/')}/impressum")
                sub_links.add(f"{url.rstrip('/')}/privacy-policy")

            sub_links = prioritize_links(sub_links)

            print(f"[{domain_netloc}] Speed Run Phase: Intercepting Assets. Scraping {len(sub_links)} sub-pages.")
            await page.route("**/*", block_unnecessary_resources)

            for link in sub_links:
                try:
                    await page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    
                    for frame in page.frames:
                        try:
                            frame_html = await frame.content()
                            extract_data_from_html(frame_html, lead_data)
                        except Exception:
                            pass
                except Exception:
                    pass 

            lead_data["status"] = "success"

    except Exception as e:
        error_msg = str(e)
        
        if not is_retry:
            fallback_domain = None
            is_http_fallback = False
            
            if domain_netloc.startswith("www."):
                fallback_domain = domain_netloc.replace("www.", "", 1)
            elif "ERR_CERT" in error_msg or "timeout" in error_msg.lower():
                fallback_domain = domain
                is_http_fallback = True

            if fallback_domain:
                print(f"[!] {domain_netloc} failed. Activating Fallback Retry...")
                return await scrape_domain(fallback_domain, proxy_server, is_retry=True, force_http=is_http_fallback)
            
        print(f"[!] Error scraping {domain_netloc}: {error_msg}")
        lead_data["status"] = f"error: {error_msg}"
        
    return {
        "domain": lead_data["domain"],
        "emails": list(lead_data["emails"]),
        "phones": list(lead_data["phones"]),
        "addresses": list(lead_data["addresses"]),
        "status": lead_data["status"]
    }
