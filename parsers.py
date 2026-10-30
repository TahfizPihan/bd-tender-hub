"""Source parsers. Each returns a list of raw dicts:
title, link, summary, published, (optional) organization, deadline."""
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString

TENDER_WORDS = re.compile(
    r"(tender|bid|eoi|expression\s+of\s+interest|rfp|rfq|procurement|quotation|"
    r"দরপত্র|টেন্ডার|দরপ্রস্তাব|আগ্রহ|ক্রয়|সরবরাহ)", re.I)

JUNK_TEXT = re.compile(r"^(home|read more|more|click here|details|view all|next|previous|login)$", re.I)


def _strip_html(s):
    if not s:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(s, "html.parser").get_text(" ")).strip()


def _tag(el):
    return el.tag.split("}")[-1].lower()


def _iso(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def parse_rss(xml_text, source=None):
    """Parse RSS 2.0 or Atom into raw items."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        d = {}
        for child in el:
            t = _tag(child)
            if t == "title":
                d["title"] = _strip_html(child.text)
            elif t == "link":
                d["link"] = (child.get("href") or child.text or "").strip()
            elif t in ("description", "summary", "content", "encoded"):
                d["summary"] = _strip_html(child.text)
            elif t in ("pubdate", "published", "updated", "date"):
                d["published"] = _iso(child.text)
        if d.get("title") and d.get("link"):
            items.append(d)
    return items


def parse_html_links(html, base_url, source=None):
    """Heuristic collector for notice pages: any link that looks like a tender
    (keyword in text/URL, or a PDF/DOC attachment with a long-enough label)."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        href = a["href"].strip()
        if not text or len(text) < 12 or JUNK_TEXT.match(text):
            continue
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        is_doc = bool(re.search(r"\.(pdf|docx?|xlsx?)($|\?)", url, re.I))
        if not (TENDER_WORDS.search(text) or TENDER_WORDS.search(url) or (is_doc and len(text) > 25)):
            continue
        if url in seen:
            continue
        seen.add(url)
        ctx = a.find_parent(["tr", "li", "p", "div"])
        ctx_text = re.sub(r"\s+", " ", ctx.get_text(" ")).strip()[:500] if ctx else text
        items.append({"title": text[:300], "link": url, "summary": ctx_text, "published": None})
    return items


def html_to_text_with_links(html, base_url, max_chars=30000):
    """Plain text of a page where every link is written as `text <absolute-url>` and
    table rows stay on one line (`cell | cell | cell`). This keeps 'Click Here' links
    next to the title and deadline of their row for the AI to read."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "svg", "form"]):
        t.decompose()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = re.sub(r"\s+", " ", a.get_text(" ")).strip() or "link"
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            a.replace_with(NavigableString(label))
        else:
            a.replace_with(NavigableString(f"{label} <{urljoin(base_url, href)}>"))
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ")).strip() for c in tr.find_all(["td", "th"])]
        tr.replace_with(NavigableString(" | ".join(c for c in cells if c) + "\n"))
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:max_chars]
