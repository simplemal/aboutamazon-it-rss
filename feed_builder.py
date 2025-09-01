#!/usr/bin/env python3
import os
import time
import hashlib
import requests
from bs4 import BeautifulSoup
import trafilatura
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin

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
    downloaded = trafilatura.fetch_url(url, no_ssl=True)  # fallback a rete diretta di trafilatura
    text = trafilatura.extract(downloaded) if downloaded else None

    soup = BeautifulSoup(html, "html.parser")
    # Titolo
    title = None
    el = soup.find("h1")
    if el:
        title = el.get_text(strip=True)
    if not title:
        # fallback a meta og:title
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        title = url

    # Descrizione/HTML: usa trafilatura per testo pieno, altrimenti fallback a paragrafo iniziale
    content_html = None
    if text:
        # Wrappa in <p> preservando righe
        paras = [f"<p>{p.strip()}</p>" for p in text.split("\n") if p.strip()]
        content_html = "\n".join(paras)
    else:
        # fallback molto conservativo
        first_p = soup.find("p")
        content_html = f"<p>{first_p.get_text(strip=True) if first_p else ''}</p>"

    # Data: prova meta tag
    pub_date = None
    for sel in [
        ('meta', {"property": "article:published_time"}),
        ('meta', {"name": "article:published_time"}),
        ('meta', {"name": "pubdate"}),
        ('time', {}),
    ]:
        tag = soup.find(*sel)
        if tag:
            if tag.name == "time":
                pub_date = tag.get("datetime") or tag.get_text(strip=True)
            else:
                pub_date = tag.get("content")
            break

    return {
        "title": title,
        "link": url,
        "content_html": content_html,
        "pub_date": pub_date,
    }

def build_feed(items, out_path="docs/feed.xml"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fg = FeedGenerator()
    fg.id("aboutamazon-it-news")
    fg.title("About Amazon Italia — Notizie (feed non ufficiale)")
    fg.description("Feed non ufficiale con contenuto completo degli articoli da About Amazon Italia (aboutamazon.it).")
    self_url = os.getenv("SELF_FEED_URL", "https://example.invalid/feed.xml")
    fg.link(href=self_url, rel="self")
    fg.link(href=BASE_LIST, rel="alternate")
    fg.link(href="https://example.invalid", rel="self")  # aggiornato dal workflow se vuoi
    fg.language("it")

    for it in items:
        fe = fg.add_entry()
        fe.id(hashlib.sha1(it["link"].encode("utf-8")).hexdigest())
        fe.title(it["title"])
        fe.link(href=it["link"])
        if it["pub_date"]:
            try:
                fe.pubDate(it["pub_date"])
            except Exception:
                pass
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
