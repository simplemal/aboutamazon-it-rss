#!/usr/bin/env python3
import os
import time
import hashlib
import requests
from bs4 import BeautifulSoup
import trafilatura
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin
from datetime import datetime
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

    # Selettori generici per card/articoli in lista
    for a in soup.select('a[href*="/notizie/"]'):
        href = a.get("href", "").strip()
        if not href:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(BASE_URL, href)
        # escludi tag, ricerche, ecc.
        if "/tag/" in full or "/search" in full:
            continue
        urls.add(full)

    # Ordine deterministico
    return sorted(urls)

def extract_article(url):
    html = fetch(url)
    downloaded = trafilatura.fetch_url(url, no_ssl=True)
    text = trafilatura.extract(downloaded) if downloaded else None

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

    return {
        "title": title,
        "link": url,
        "content_html": content_html,
        "text_plain": text_plain,
        "pub_dt": pub_dt or datetime.utcnow(),
    }

def build_feed(items, out_path="docs/feed.xml"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fg = FeedGenerator()
    fg.id("aboutamazon-it-news")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo degli articoli da About Amazon Italia (aboutamazon.it).")
    fg.link(href=BASE_LIST, rel="alternate")
    
    self_url = os.getenv("SELF_FEED_URL", "https://example.invalid/feed.xml")
    fg.link(href=self_url, rel="self")
    fg.language("it")
    fg.lastBuildDate(datetime.utcnow())
    fg.ttl(60)

    for it in items:
        fe = fg.add_entry()
        fe.id(hashlib.sha1(it["link"].encode("utf-8")).hexdigest())
        fe.guid(hashlib.sha1(it["link"].encode("utf-8")).hexdigest(), permalink=False)
        fe.title(it["title"])
        fe.link(href=it["link"])
    
        # descrizione breve (prima riga del testo)
        summary = ""
        if it.get("text_plain"):
            summary = it["text_plain"].split("\n", 1)[0][:300]
        fe.description(summary or it["title"])
    
        if it.get("pub_dt"):
            fe.pubDate(it["pub_dt"])
    
        fe.content(it["content_html"], type="CDATA")

    fg.rss_str(pretty=True)
    fg.rss_file(out_path, pretty=True)

def main():
    urls = list_articles()
    # Limita a 20–30 articoli per performance
    urls = urls[:30]

    items = []
    for u in urls:
        try:
            items.append(extract_article(u))
            time.sleep(1.0)  # cortesia
        except Exception:
            continue

    build_feed(items)

if __name__ == "__main__":
    main()
