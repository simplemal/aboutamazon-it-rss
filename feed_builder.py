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
import json

BASE_LIST = "https://www.aboutamazon.it/notizie"
BASE_URL  = "https://www.aboutamazon.it"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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

def list_articles_from_categories():
    """Get articles from specific category pages that load content directly"""
    urls = set()
    
    # Known category URLs that should have direct HTML content
    categories = [
        "https://www.aboutamazon.it/notizie/company-news",
        "https://www.aboutamazon.it/notizie/piccole-e-medie-imprese", 
        "https://www.aboutamazon.it/notizie/lavorare-ad-amazon",
        "https://www.aboutamazon.it/notizie/sostenibilita",
        "https://www.aboutamazon.it/notizie/dispositivi-amazon",
        "https://www.aboutamazon.it/notizie/nella-comunita",
        "https://www.aboutamazon.it/notizie/public-policy"
    ]
    
    for category_url in categories:
        try:
            print(f"Fetching category: {category_url}")
            html = fetch(category_url)
            soup = BeautifulSoup(html, "html.parser")
            
            # Look for article links in various possible structures
            selectors = [
                'a[href*="/notizie/"]',
                '.article-title a',
                '.news-item a',
                'h2 a',
                'h3 a',
                '.post-title a'
            ]
            
            found_in_category = 0
            for selector in selectors:
                links = soup.select(selector)
                for link in links:
                    href = link.get('href', '').strip()
                    if not href or href.startswith('#'):
                        continue
                    
                    full_url = urljoin(BASE_URL, href)
                    
                    # Skip unwanted URLs
                    skip_patterns = ['/tag/', '/search', '/categoria/', '/page/', category_url, BASE_LIST]
                    if any(pattern in full_url for pattern in skip_patterns):
                        continue
                    
                    # Must be an actual article URL
                    if '/notizie/' in full_url and len(full_url.split('/')) >= 5:
                        urls.add(full_url)
                        found_in_category += 1
            
            print(f"Found {found_in_category} articles in {category_url}")
            time.sleep(0.5)  # Be nice to the server
            
        except Exception as e:
            print(f"Error fetching category {category_url}: {e}")
            continue
    
    print(f"Total unique articles found: {len(urls)}")
    return list(urls)

def get_known_articles():
    """Fallback list of known recent articles"""
    return [
        "https://www.aboutamazon.it/notizie/company-news/amazon-compie-15-anni-italia-tre-giorni-offerte-esclusive",
        "https://www.aboutamazon.it/notizie/sostenibilita/amazon-lancia-per-la-prima-volta-i-second-chance-deal-days",
        "https://www.aboutamazon.it/notizie/sostenibilita/amazon-consegne-in-giornata-veicoli-elettrici-prima-volta-europa",
        "https://www.aboutamazon.it/notizie/dispositivi-amazon/amazon-amplia-la-famiglia-kindle-colorsoft-con-un-modello-da-16-gb",
        "https://www.aboutamazon.it/notizie/public-policy/amazon-e-tra-i-50-maggiori-contribuenti-fiscali-in-italia",
        "https://www.aboutamazon.it/notizie/nella-comunita/talento-e-passione-stem-vincitrici-amazon-women-in-innovation-2025",
        "https://www.aboutamazon.it/notizie/sostenibilita/il-primo-raccolto-nella-piantagione-di-alghe-marine-nel-mare-del-nord-finanziata-da-amazon"
    ]

def extract_article(url: str):
    """Extract article content with better error handling and image extraction"""
    try:
        html = fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract content using trafilatura
        extracted = trafilatura.extract(
            html, 
            url=url,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=True,
            deduplicate=True,
            include_images=True  # Enable image extraction
        )

        # Title extraction
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
                # Clean up title (remove site name)
                if " — " in title:
                    title = title.split(" — ")[0]
        
        if not title:
            title = "Articolo da About Amazon Italia"

        # Enhanced image extraction - check multiple sources
        images = []
        
        # 1. Try Open Graph image first (most reliable) - multiple ways to find it
        og_image_url = None
        
        # Method 1: Standard property search
        og_tag = soup.find("meta", property="og:image")
        if og_tag and og_tag.get("content"):
            og_image_url = og_tag["content"].strip()
        
        # Method 2: Case-insensitive search
        if not og_image_url:
            og_tag = soup.find("meta", {"property": re.compile(r"og:image", re.I)})
            if og_tag and og_tag.get("content"):
                og_image_url = og_tag["content"].strip()
        
        # Method 3: Search all meta tags manually
        if not og_image_url:
            all_metas = soup.find_all("meta")
            for meta in all_metas:
                prop = meta.get("property", "").lower()
                if prop == "og:image" and meta.get("content"):
                    og_image_url = meta["content"].strip()
                    break
        
        if og_image_url:
            # Make sure it's a complete URL
            if not og_image_url.startswith("http"):
                og_image_url = urljoin(url, og_image_url)
            images.append({"url": og_image_url, "alt": "Immagine articolo"})

        # 2. Try other OG image variants
        if not images:
            for prop in ["og:image:url", "og:image:secure_url"]:
                og_tag = soup.find("meta", property=prop)
                if og_tag and og_tag.get("content"):
                    img_url = og_tag["content"].strip()
                    if img_url:
                        if not img_url.startswith("http"):
                            img_url = urljoin(url, img_url)
                        images.append({"url": img_url, "alt": "Immagine articolo"})
                        break

        # 3. Try Twitter Card image
        if not images:
            for prop in ["twitter:image", "twitter:image:src"]:
                twitter_tag = soup.find("meta", {"name": prop}) or soup.find("meta", property=prop)
                if twitter_tag and twitter_tag.get("content"):
                    img_url = twitter_tag["content"].strip()
                    if img_url:
                        if not img_url.startswith("http"):
                            img_url = urljoin(url, img_url)
                        images.append({"url": img_url, "alt": "Immagine articolo"})
                        break

        # 4. Look for images in JSON-LD structured data
        if not images:
            json_scripts = soup.find_all("script", type="application/ld+json")
            for script in json_scripts:
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and "image" in data:
                        img_data = data["image"]
                        img_url = None
                        
                        if isinstance(img_data, str):
                            img_url = img_data
                        elif isinstance(img_data, dict) and "url" in img_data:
                            img_url = img_data["url"]
                        elif isinstance(img_data, list) and len(img_data) > 0:
                            first_img = img_data[0]
                            if isinstance(first_img, str):
                                img_url = first_img
                            elif isinstance(first_img, dict) and "url" in first_img:
                                img_url = first_img["url"]
                        
                        if img_url:
                            if not img_url.startswith("http"):
                                img_url = urljoin(url, img_url)
                            images.append({"url": img_url, "alt": "Immagine articolo"})
                            break
                except:
                    continue

        # 5. Look for images in the article content (fallback)
        if not images:
            article_elem = soup.find("article") or soup.find("main") or soup.find("div", class_="content")
            if article_elem:
                img_tags = article_elem.find_all("img")
                for img in img_tags[:2]:  # Limit to first 2 images
                    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                    if src:
                        img_url = urljoin(url, src)
                        alt_text = img.get("alt", "Immagine")
                        images.append({"url": img_url, "alt": alt_text})

        # Enhanced content processing
        content = ""
        if extracted:
            content = sanitize_xml(extracted.strip())
        else:
            # Fallback: look for article content
            article_elem = soup.find("article") or soup.find("main") or soup.find("div", class_="content")
            if article_elem:
                # Remove unwanted elements but keep images info
                for unwanted in article_elem.find_all(["nav", "footer", "aside", "header", "script", "style"]):
                    unwanted.decompose()
                content = sanitize_xml(article_elem.get_text(strip=True))

        # Add main image to content if found + debug info
        debug_info = f"[DEBUG: Found {len(images)} images for {url}] "
        if images:
            main_img = images[0]  # Use the first (most important) image
            img_html = f'<img src="{html.escape(main_img["url"])}" alt="{html.escape(main_img["alt"])}" style="max-width:100%;height:auto;margin-bottom:15px;"><br>'
            debug_info += f"Main image: {main_img['url'][:100]}... "
            content = img_html + debug_info + content
        else:
            content = debug_info + content

        if not content:
            content = f"Leggi l'articolo completo su: {url}"

        # Date extraction
        pub_dt = None
        
        date_selectors = [
            ('meta', {"property": "article:published_time"}),
            ('meta', {"name": "article:published_time"}),
            ('meta', {"property": "article:published"}),
            ('time', {"datetime": True}),
        ]
        
        for selector in date_selectors:
            tag = soup.find(*selector)
            if tag:
                raw_date = tag.get("datetime") if tag.name == "time" else tag.get("content")
                if raw_date:
                    try:
                        pub_dt = dateparser.parse(raw_date)
                        if pub_dt:
                            break
                    except Exception:
                        continue

        # Default to current time if no date found
        if not pub_dt:
            pub_dt = datetime.now(timezone.utc)
        elif pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        else:
            pub_dt = pub_dt.astimezone(timezone.utc)

        return {
            "title": title,
            "link": url,
            "content": content,
            "pub_dt": pub_dt,
            "images": images
        }
        
    except Exception as e:
        print(f"Error extracting article {url}: {e}")
        return None

def build_feed(items, out_path="docs/feed.xml"):
    """Build RSS feed with proper encoding and Feedly-compatible format"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fg = FeedGenerator()
    fg.id("https://simplemal.github.io/aboutamazon-it-rss/feed.xml")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo degli articoli da About Amazon Italia (aboutamazon.it).")
    
    # Self link to the feed (required for Feedly)
    fg.link(href="https://simplemal.github.io/aboutamazon-it-rss/feed.xml", rel="self")
    # Website link (required)
    fg.link(href=BASE_LIST)
    
    fg.language("it")
    fg.lastBuildDate(datetime.now(timezone.utc))
    fg.ttl(60)
    fg.docs("http://www.rssboard.org/rss-specification")
    fg.generator("python-feedgen")

    # Add required elements for better compatibility
    fg.managingEditor("noreply@aboutamazon.it (About Amazon Italia)")
    fg.webMaster("noreply@aboutamazon.it (About Amazon Italia)")

    for item in items:
        fe = fg.add_entry()
        
        # Use the URL itself as GUID (permalink=True is better for Feedly)
        fe.guid(item["link"], permalink=True)
        
        fe.title(item["title"])
        fe.link(href=item["link"])
        
        # Format content with HTML for images
        description = item.get("content", "")
        if len(description) > 50000:
            description = description[:50000] + "..."
        
        # If content already contains HTML (images), keep it as HTML
        # Otherwise wrap in paragraph tags
        if '<img' in description or '<br>' in description:
            # Content already has HTML from images - use as is
            fe.description(description)
        else:
            # Plain text content - wrap in paragraph
            fe.description(f'<p>{html.escape(description)}</p>')
        
        fe.pubDate(item["pub_dt"])
        
        # Add author if possible
        fe.author(email="noreply@aboutamazon.it", name="About Amazon Italia")
        
        # Add enclosure for first image if available
        if item.get("images") and len(item["images"]) > 0:
            first_img = item["images"][0]
            try:
                # Try to get image info for enclosure
                img_response = requests.head(first_img["url"], timeout=5)
                if img_response.status_code == 200:
                    content_type = img_response.headers.get('content-type', 'image/jpeg')
                    content_length = img_response.headers.get('content-length', '0')
                    fe.enclosure(first_img["url"], content_length, content_type)
            except:
                # Skip enclosure if can't get image info
                pass

    # Generate RSS and add custom elements for better compatibility
    rss_str = fg.rss_str(pretty=True)
    
    # Decode to string to modify it
    rss_content = rss_str.decode('utf-8')
    
    # Ensure proper RSS 2.0 declaration and add missing elements
    if '<?xml version' not in rss_content:
        rss_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + rss_content
    
    # Write with explicit UTF-8 encoding
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(rss_content)

def main():
    """Main execution function"""
    print("Fetching articles from category pages...")
    
    # First try to get articles from category pages
    urls = list_articles_from_categories()
    
    # If that fails, use known articles
    if not urls:
        print("No articles found from categories, using known articles...")
        urls = get_known_articles()
    
    # Limit to reasonable number
    if len(urls) > 30:
        urls = urls[:30]
    
    print(f"Processing {len(urls)} articles...")
    
    items = []
    for i, url in enumerate(urls, 1):
        print(f"Processing {i}/{len(urls)}: {url}")
        
        article = extract_article(url)
        if article and article.get("title") and article.get("content"):
            items.append(article)
            print(f"✓ {article['title'][:60]}...")
        else:
            print(f"✗ Failed to extract content")
        
        time.sleep(1.0)  # Be respectful
    
    if not items:
        print("No articles successfully processed!")
        return
    
    # Sort by date (newest first)
    items.sort(key=lambda x: x["pub_dt"], reverse=True)
    
    print(f"Building feed with {len(items)} articles...")
    build_feed(items)
    print(f"Feed generated successfully with {len(items)} items!")

if __name__ == "__main__":
    main()
