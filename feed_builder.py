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

BASE_LIST = "https://www.aboutamazon.it/notizie"
BASE_URL  = "https://www.aboutamazon.it"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AboutAmazonIT-RSS/1.0)"
}

# Remove characters invalid for XML 1.0
_XML_INVALID_RE = re.compile(r"[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD]")

def sanitize_xml(text: str) -> str:
    if not text:
        return ""
    return _XML_INVALID_RE.sub("", text)

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def list_articles():
    html = fetch(BASE_LIST)
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.select('a[href*="/notizie/"]'):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(BASE_URL, href)
        if "/tag/" in full or "/search" in full:
            continue
        urls.add(full)
    return sorted(urls)

def extract_article(url: str):
    html = fetch(url)
    text = trafilatura.extract(html, url=url)
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        title = url
    title = sanitize_xml(title)

    # Content
    if text:
        text_plain = sanitize_xml(text.strip())
    else:
        first_p = soup.find("p")
        text_plain = sanitize_xml(first_p.get_text(strip=True) if first_p else "")

    # Date
    pub_dt = None
    for sel in [
        ('meta', {"property": "article:published_time"}),
        ('meta', {"name": "article:published_time"}),
        ('meta', {"name": "pubdate"}),
        ('time', {}),
    ]:
        tag = soup.find(*sel)
        if tag:
            raw = tag.get("datetime") if tag.name == "time" else tag.get("content")
            raw = (raw or tag.get_text(strip=True) or "").strip()
            try:
                pub_dt = dateparser.parse(raw)
            except Exception:
                pub_dt = None
            break

    pub_dt_aware = (pub_dt.astimezone(timezone.utc) if (pub_dt and pub_dt.tzinfo)
                    else (pub_dt.replace(tzinfo=timezone.utc) if pub_dt else datetime.now(timezone.utc)))

    return {
        "title": title,
        "link": url,
        "text_plain": text_plain,
        "pub_dt": pub_dt_aware,
    }

def build_feed(items, out_path="docs/feed.xml"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fg = FeedGenerator()
    fg.id("aboutamazon-it-news")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo (testo) degli articoli da About Amazon Italia (aboutamazon.it).")

    # Required channel <link> for RSS 2.0 must point to the website, not to the feed
    fg.link(href=BASE_LIST)

    fg.language("it")
    fg.lastBuildDate(datetime.now(timezone.utc))
    fg.ttl(60)
    fg.docs("https://www.rssboard.org/rss-specification")
    fg.generator("python-feedgen")

    for it in items:
        fe = fg.add_entry()

        # GUID as permalink URL (validator-friendly)
        fe.guid(it["link"], permalink=True)

        fe.title(it["title"])
        fe.link(href=it["link"])

        # Put full text (plain) into <description> — valid RSS 2.0
        # Limit to a large but safe size
        desc = it.get("text_plain") or it["title"]
        fe.description(desc[:100000])

        if it.get("pub_dt"):
            fe.pubDate(it["pub_dt"])

    fg.rss_file(out_path, pretty=True)

def main():
    urls = list_articles()[:30]
    items = []
    for u in urls:
        try:
            items.append(extract_article(u))
            time.sleep(1.0)
        except Exception:
            continue
    items.sort(key=lambda x: x["pub_dt"], reverse=True)
    build_feed(items)

if __name__ == "__main__":
    main()
