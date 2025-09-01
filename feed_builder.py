#!/usr/bin/env python3
import os
import re
import time
import hashlib
import requests
from bs4 import BeautifulSoup
import trafilatura
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin
from datetime import datetime, timezone
from dateutil import parser as dateparser
import html

BASE_LIST = "https://www.aboutamazon.it/notizie"
BASE_URL  = "https://www.aboutamazon.it"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AboutAmazonIT-RSS/1.0)"
}

# Remove characters invalid for XML 1.0
_XML_INVALID_RE = re.compile(r"[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD]")

def sanitize_xml(text: str) -> str:
    """Sanitize text for XML compatibility"""
    if not text:
        return ""
    # First decode any HTML entities
    text = html.unescape(text)
    # Remove XML invalid characters
    text = _XML_INVALID_RE.sub("", text)
    # Normalize whitespace
    text = ' '.join(text.split())
    return text

def fetch(url: str) -> str:
    """Fetch URL with proper error handling and encoding"""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    # Ensure proper encoding
    r.encoding = r.apparent_encoding or 'utf-8'
    return r.text

def list_articles():
    """Extract article URLs from the main page"""
    html = fetch(BASE_LIST)
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    
    # Look for article links more specifically
    for a in soup.select('a[href*="/notizie/"]'):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(BASE_URL, href)
        
        # Filter out unwanted URLs
        if any(pattern in full for pattern in ["/tag/", "/search", "/categoria/", BASE_LIST]):
            continue
            
        # Only include URLs that look like actual articles
        if re.search(r'/notizie/[^/]+/[^/]+$', full):
            urls.add(full)
    
    return sorted(urls)

def extract_article(url: str):
    """Extract article content with better error handling"""
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    
    # Extract content using trafilatura with better options
    extracted = trafilatura.extract(
        html, 
        url=url,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        favor_precision=True,
        deduplicate=True
    )

    # Title extraction with multiple fallbacks
    title = None
    
    # Try h1 first
    h1 = soup.find("h1")
    if h1:
        title = sanitize_xml(h1.get_text(strip=True))
    
    # Try meta tags
    if not title:
        for meta_prop in ["og:title", "twitter:title"]:
            meta = soup.find("meta", property=meta_prop) or soup.find("meta", {"name": meta_prop})
            if meta and meta.get("content"):
                title = sanitize_xml(meta["content"].strip())
                break
    
    # Try title tag
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = sanitize_xml(title_tag.get_text(strip=True))
    
    # Last resort
    if not title:
        title = "Articolo da About Amazon Italia"
    
    # Content processing
    if extracted:
        content = sanitize_xml(extracted.strip())
    else:
        # Fallback: try to extract from article or main content
        content_elem = soup.find("article") or soup.find("main") or soup.find("div", class_="content")
        if content_elem:
            # Remove navigation, footer, sidebar elements
            for unwanted in content_elem.find_all(["nav", "footer", "aside", "header"]):
                unwanted.decompose()
            content = sanitize_xml(content_elem.get_text(strip=True))
        else:
            content = "Contenuto non disponibile"

    # Date extraction with better handling
    pub_dt = None
    
    # Try various date selectors
    date_selectors = [
        ('meta', {"property": "article:published_time"}),
        ('meta', {"name": "article:published_time"}),
        ('meta', {"property": "article:published"}),
        ('meta', {"name": "pubdate"}),
        ('meta', {"name": "date"}),
        ('time', {"datetime": True}),
        ('time', {}),
    ]
    
    for selector in date_selectors:
        tag = soup.find(*selector)
        if tag:
            raw_date = None
            if tag.name == "time":
                raw_date = tag.get("datetime") or tag.get_text(strip=True)
            else:
                raw_date = tag.get("content")
            
            if raw_date:
                try:
                    pub_dt = dateparser.parse(raw_date)
                    if pub_dt:
                        break
                except Exception:
                    continue

    # Ensure timezone-aware datetime
    if pub_dt:
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        else:
            pub_dt = pub_dt.astimezone(timezone.utc)
    else:
        pub_dt = datetime.now(timezone.utc)

    return {
        "title": title,
        "link": url,
        "content": content,
        "pub_dt": pub_dt,
    }

def build_feed(items, out_path="docs/feed.xml"):
    """Build RSS feed with proper encoding"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fg = FeedGenerator()
    fg.id("https://simplemal.github.io/aboutamazon-it-rss/feed.xml")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo degli articoli da About Amazon Italia (aboutamazon.it).")
    
    # Self link to the feed
    fg.link(href="https://simplemal.github.io/aboutamazon-it-rss/feed.xml", rel="self")
    # Website link
    fg.link(href=BASE_LIST)
    
    fg.language("it")
    fg.lastBuildDate(datetime.now(timezone.utc))
    fg.ttl(60)
    fg.docs("http://www.rssboard.org/rss-specification")
    fg.generator("python-feedgen")

    for item in items:
        fe = fg.add_entry()
        
        # Use a hash of the URL as GUID to avoid issues
        guid_hash = hashlib.sha1(item["link"].encode('utf-8')).hexdigest()
        fe.guid(guid_hash, permalink=False)
        
        fe.title(item["title"])
        fe.link(href=item["link"])
        
        # Use the full content in description
        description = item.get("content", "")
        if len(description) > 50000:  # Reasonable limit
            description = description[:50000] + "..."
        
        fe.description(f'<p>{html.escape(description)}</p>')
        
        if item.get("pub_dt"):
            fe.pubDate(item["pub_dt"])

    # Write with explicit UTF-8 encoding
    rss_str = fg.rss_str(pretty=True)
    with open(out_path, 'wb') as f:
        f.write(rss_str)

def main():
    """Main execution function"""
    print("Fetching article URLs...")
    urls = list_articles()
    
    # Limit to avoid overwhelming the server
    urls = urls[:30]
    print(f"Found {len(urls)} articles to process")
    
    items = []
    for i, url in enumerate(urls, 1):
        try:
            print(f"Processing {i}/{len(urls)}: {url}")
            article = extract_article(url)
            items.append(article)
            time.sleep(1.0)  # Be respectful to the server
        except Exception as e:
            print(f"Error processing {url}: {e}")
            continue
    
    # Sort by publication date (newest first)
    items.sort(key=lambda x: x["pub_dt"], reverse=True)
    
    print(f"Building feed with {len(items)} articles...")
    build_feed(items)
    print("Feed generated successfully!")

if __name__ == "__main__":
    main()
