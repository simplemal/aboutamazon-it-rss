#!/usr/bin/env python3
import os
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
BASE_URL = "https://www.aboutamazon.it"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AboutAmazonIT-RSS/1.0)"
}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def list_articles():
    html = fetch(BASE_LIST)
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.select('a[href*="/notizie/"]'):
        href = a.get("href", "").strip()
        if not href:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(BASE_URL, href)
        if "/tag/" in full or "/search" in full:
            continue
        urls.add(full)
    return sorted(urls)

def extract_article(url):
    html = fetch(url)
    text = trafilatura.extract(html, url=url)
    soup = BeautifulSoup(html, "html.parser")

    title = None
    el = soup.find("h1")
    if el:
        title = el.get_text(strip=True)
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        title = url

    content_html = None
    text_plain = None
    if text:
        text_plain = text.strip()
        paras = [f"<p>{p.strip()}</p>" for p in text_plain.split("\n") if p.strip()]
        content_html = "\n".join(paras)
    else:
        first_p = soup.find("p")
        txt = first_p.get_text(strip=True) if first_p else ""
        text_plain = txt
        content_html = f"<p>{txt}</p>"

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
            raw = raw or tag.get_text(strip=True)
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
        "content_html": content_html,
        "text_plain": text_plain,
        "pub_dt": pub_dt_aware,
    }

def build_feed(items, out_path="docs/feed.xml"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fg = FeedGenerator()
    fg.id("aboutamazon-it-news")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo degli articoli da About Amazon Italia (aboutamazon.it).")

    # Channel <link> (obbligatorio in RSS 2.0) + atom:link self
    fg.link(href=BASE_LIST)
    self_url = os.getenv("SELF_FEED_URL", "https://example.invalid/feed.xml")
    fg.link(href=self_url, rel="self")

    fg.language("it")
    fg.lastBuildDate(datetime.now(timezone.utc))
    fg.ttl(60)

    for it in items:
        fe = fg.add_entry()
        guid = hashlib.sha1(it["link"].encode("utf-8")).hexdigest()
        fe.id(guid)
        fe.guid(guid, permalink=False)
        fe.title(it["title"])
        fe.link(href=it["link"])

        # Usa <description> con l'HTML completo (compatibile con RSS 2.0)
        fe.description(it["content_html"] or it["title"])

        if it.get("pub_dt"):
            fe.pubDate(it["pub_dt"])

    fg.rss_str(pretty=True)
    fg.rss_file(out_path, pretty=True)

def main():
    urls = list_articles()
    urls = urls[:30]
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
