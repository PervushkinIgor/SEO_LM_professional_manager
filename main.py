import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import json
import re
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright


class AdvancedSEOCrawler:
    def __init__(self, start_url, max_pages=30):
        self.start_url = start_url
        self.domain = urlparse(start_url).netloc
        self.max_pages = max_pages
        self.to_crawl = [start_url]
        self.crawled = set()
        self.results = []
        # Headers for quick link checking via requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36 Smart-SEO-Bot/4.0'
        }

    def is_internal(self, url):
        return urlparse(url).netloc == self.domain

    def clean_url(self, url):
        return url.split('#')[0]

    def evaluate_risk_zone(self, row):
        """Page rating: from critical issues to ideal."""
        status = row.get("Status Code")

        # 1. Red Zone (Critical)
        if isinstance(status, str) and "Error" in status:
            return "1. RED (Site unavailable/Network error)"
        if isinstance(status, int) and status >= 400:
            return "1. RED (Server Error/Point of Death)"
        if status == 200 and row["H1 Count"] == 0:
            return "1. RED (There is no main H1 heading)"
        if row["Broken Links"] != "Нет":
            return "1. RED (Broken links found)"
        if row["Load Time (sec)"] > 3.0:
            return "1. RED (Slow loading > 3 sec)"
        if "ВЫСОКИЙ" in row["AI Sludge Risk"]:
            return "1. RED (Suspected AI Junk/Text Sheet)"

        # 2. Yellow Zone (Minor issues and growth points)
        if row["Title"] == "Absent" or row["Description"] == "Absent":
            return "2. YELLOW (Missing Title or Description)"
        if row["H1 Count"] > 1:
            return "2. YELLOW (H1 duplication)"
        if row["Images Without Alt"] > 0:
            return "2. YELLOW (Pictures without alt text)"
        if row["Open Graph"] == "❌ Нет":
            return "2. YELLOW (No social media markup OG)"
        if row["JSON-LD Entities"] == 0:
            return "2. YELLOW (No JSON-LD markup for AI search)"

        # 3. Green Zone
        return "3. GREEN (No problems found)"

    def crawl(self):
        print(f"=== Launch Smart SEO-Crawler (Playwright Edition) for: {self.start_url} ===")

        # Launch the browser once for all pages to save resources
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            while self.to_crawl and len(self.crawled) < self.max_pages:
                current_url = self.to_crawl.pop(0)
                current_url = self.clean_url(current_url)

                if current_url in self.crawled:
                    continue

                print(f"[{len(self.crawled) + 1}/{self.max_pages}] Analyzing: {current_url}")
                self.crawled.add(current_url)

                row = {
                    "URL": current_url, "Status Code": None, "Load Time (sec)": 0.0,
                    "Title": "Absent", "Description": "Absent",
                    "H1 Count": 0, "Images Without Alt": 0, "Broken Links": "No",
                    "Open Graph": "❌ No", "JSON-LD Entities": 0,
                    "Text/HTML Ratio (%)": 0, "AI Sludge Risk": "Short",
                    "Risk Zone": "Not defined"
                }

                page = browser.new_page()
                try:
                    start_time = time.perf_counter()
                    # networkidle waits until all background JS requests finish (solves Shadow DOM/React/Vue issues)
                    response = page.goto(current_url, wait_until="networkidle", timeout=15000)
                    end_time = time.perf_counter()

                    row["Status Code"] = response.status if response else 500
                    row["Load Time (sec)"] = round(end_time - start_time, 2)

                    if row["Status Code"] == 200:
                        # Get the rendered DOM
                        html = page.content()
                        soup = BeautifulSoup(html, 'html.parser')

                        # --- BASIC SEO ---
                        if soup.title and soup.title.string:
                            row["Title"] = soup.title.string.strip()

                        desc_tag = soup.find('meta', attrs={'name': 'description'})
                        if desc_tag and desc_tag.get('content'):
                            row["Description"] = desc_tag['content'].strip()

                        row["H1 Count"] = len(soup.find_all('h1'))
                        row["Images Without Alt"] = sum(1 for img in soup.find_all('img') if not img.get('alt'))

                        og_tags = soup.find_all('meta', attrs={'property': re.compile(r'^og:')})
                        if len(og_tags) >= 3:
                            row["Open Graph"] = "✅ Full"
                        elif len(og_tags) > 0:
                            row["Open Graph"] = "⚠️ Partial"

                        # --- ADVANCED: GEO & JSON-LD ---
                        json_ld_scripts = soup.find_all('script', type='application/ld+json')
                        entities_count = 0
                        for script in json_ld_scripts:
                            if script.string:
                                try:
                                    json.loads(script.string)
                                    entities_count += 1
                                except json.JSONDecodeError:
                                    pass
                        row["JSON-LD Entities"] = entities_count

                        # --- ADVANCED: AI SLUDGE & TEXT RATIO ---
                        clean_soup = BeautifulSoup(html, 'html.parser')
                        for tag in clean_soup(["script", "style", "noscript", "svg"]):
                            tag.extract()

                        clean_text = clean_soup.get_text(separator=' ', strip=True)
                        word_count = len(re.findall(r'\b\w+\b', clean_text, re.UNICODE))

                        if len(html) > 0:
                            ratio = (len(clean_text) / len(html)) * 100
                            row["Text/HTML Ratio (%)"] = round(ratio, 2)

                        paragraphs = len(soup.find_all('p'))
                        lists = len(soup.find_all(['ul', 'ol']))

                        if word_count > 1500 and lists == 0 and paragraphs > 15:
                            row["AI Sludge Risk"] = "HIGH (Long text without structure)"
                        elif row["Text/HTML Ratio (%)"] < 5 and word_count > 300:
                            row["AI Sludge Risk"] = "HIGH (Lots of code, little meaning)"

                        # --- BROKEN LINKS AND CRAWL QUEUE ---
                        links = soup.find_all('a', href=True)
                        broken_list = []

                        for link in links:
                            full_url = urljoin(current_url, link['href'])
                            full_url = self.clean_url(full_url)

                            if self.is_internal(
                                    full_url) and full_url not in self.crawled and full_url not in self.to_crawl:
                                self.to_crawl.append(full_url)

                            # Lightweight link checking via requests (to avoid slowing down the browser)
                            if self.is_internal(full_url) and full_url.startswith('http'):
                                try:
                                    check = requests.head(full_url, headers=self.headers, timeout=2,
                                                          allow_redirects=True)
                                    if check.status_code == 404:
                                        broken_list.append(full_url)
                                except:
                                    pass  # Ignore timeouts

                        if broken_list:
                            row["Broken Links"] = ", ".join(set(broken_list))

                except Exception as e:
                    row["Status Code"] = f"Timeout error/JS"

                finally:
                    # Always close the page to prevent memory leaks
                    page.close()

                row["Risk Zone"] = self.evaluate_risk_zone(row)
                self.results.append(row)

                # A short pause to be polite to the server
                time.sleep(0.5)

            browser.close()
            self.save_to_excel()

    def save_to_excel(self):
        df = pd.DataFrame(self.results)
        df = df.sort_values(by="Risk Zone", ascending=True)
        output_file = "smart_seo_audit_report.xlsx"
        df.to_excel(output_file, index=False)
        print(f"\n[Success] Smart audit completed! Sorted report saved in: {output_file}")


# --- EXECUTION ---
if __name__ == "__main__":
    crawler = AdvancedSEOCrawler(start_url="https://example.com", max_pages=15)
    crawler.crawl()