"""
Convierte el XML de Facebook Shopping de VTEX (Sporting) al CSV de ChatGPT Ads (OpenAI).
Lo ejecuta GitHub Actions cada 6 horas y lo publica en GitHub Pages como sporting.csv.
"""
import csv
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://www.sporting.com.ar/XMLData/facebook-shopping.xml"
OUT = sys.argv[1] if len(sys.argv) > 1 else "public/sporting.csv"
SELLER_NAME = "Sporting"
SELLER_URL = "https://www.sporting.com.ar"
RETURN_POLICY_URL = ""  # opcional
CURRENCY = "ARS"
ONLY_IN_STOCK = True
MAX_DESC = 1000

NS = {"a": "http://www.w3.org/2005/Atom", "g": "http://base.google.com/ns/1.0"}

HEADERS = [
    "item_id", "group_id", "listing_has_variations", "variant_dict",
    "title", "description", "url", "brand", "seller_name", "seller_url",
    "image_url", "price", "sale_price", "availability", "condition",
    "gender", "age_group", "color", "size", "product_category", "gtin", "mpn",
    "return_policy", "is_eligible_search", "is_eligible_checkout", "is_ads_eligible",
]


def get(e, name):
    for tag in (f"g:{name}", f"a:{name}", name):
        c = e.find(tag, NS)
        if c is not None:
            if c.text and c.text.strip():
                return c.text.strip()
            if c.get("href"):
                return c.get("href").strip()
            return ""
    return ""


def money(v):
    if not v:
        return ""
    s = re.sub(r"[A-Za-z]{3}|\$|\s", "", v)
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        n = float(s)
    except ValueError:
        return ""
    return f"{n:.2f} {CURRENCY}" if n > 0 else ""


def disponibilidad(v):
    s = re.sub(r"[\s-]", "_", (v or "").lower())
    return {"in_stock": "in_stock", "out_of_stock": "out_of_stock", "preorder": "pre_order",
            "pre_order": "pre_order", "backorder": "backorder"}.get(s, "unknown")


def gtin_valido(v):
    s = re.sub(r"\D", "", v or "")
    if len(s) not in (8, 12, 13, 14) or re.fullmatch(r"(\d)\1+", s):
        return ""
    d = [int(x) for x in s]
    check = d.pop()
    total = sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d)))
    return s if (10 - total % 10) % 10 == check else ""


def limpiar(t):
    t = re.sub(r"</?(br|li|p|div)[^>]*>", " ", t or "", flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", t).strip()


def title_case(t):
    return re.sub(r"(^|\s|-)(\S)", lambda m: m.group(1) + m.group(2).upper(), (t or "").lower())


def convertir(e):
    item_id = get(e, "id")
    raw_title = get(e, "title")
    link = get(e, "link")
    image = get(e, "image_link")
    price = money(get(e, "price"))
    if not (item_id and raw_title and link and image and price):
        return None

    m_color = re.search(r"Color:\s*([^-]+?)(?:\s+-|$)", raw_title, re.I)
    m_talle = re.search(r"Talle:\s*(.+)$", raw_title, re.I)
    base_title = re.sub(r"\s+-\s+(Color|Talle):.*$", "", raw_title, flags=re.I).strip()

    color = limpiar(get(e, "color") or (m_color.group(1) if m_color else ""))
    size = limpiar(get(e, "size") or (m_talle.group(1) if m_talle else ""))
    if re.fullmatch(r"[uú]nico", size, re.I):
        size = ""
    size = size.upper()

    title = base_title + (f" - Talle {size}" if size else "")

    sale = money(get(e, "sale_price"))
    if sale and float(sale.split()[0]) >= float(price.split()[0]):
        sale = ""

    low = base_title.lower()
    gender = ("unisex" if re.search(r"\bunisex\b", low) else
              "female" if re.search(r"\bmujer(es)?\b", low) else
              "male" if re.search(r"\bhombre(s)?\b", low) else "")
    age = ("kids" if re.search(r"\b(niñ[oa]s?|kids|infantil|junior)\b", low) else
           "infant" if re.search(r"\b(bebés?|baby)\b", low) else "")
    cond = get(e, "condition")
    cat = get(e, "product_type")

    return {
        "_group": link.split("?")[0],
        "item_id": item_id,
        "title": title[:150],
        "description": (limpiar(get(e, "description")) or base_title)[:MAX_DESC],
        "url": link,
        "brand": title_case(get(e, "brand") or SELLER_NAME)[:70],
        "seller_name": SELLER_NAME,
        "seller_url": SELLER_URL,
        "image_url": image,
        "price": price,
        "sale_price": sale,
        "availability": disponibilidad(get(e, "availability")),
        "condition": cond if cond in ("new", "used", "refurbished") else "new",
        "gender": gender,
        "age_group": age,
        "color": color,
        "size": size,
        "product_category": title_case(cat) if cat else "",
        "gtin": gtin_valido(get(e, "gtin")),
        "mpn": get(e, "mpn"),
        "return_policy": RETURN_POLICY_URL,
        "is_eligible_search": "true",
        "is_eligible_checkout": "false",
        "is_ads_eligible": "true",
    }


def main():
    src = os.environ.get("FEED_FILE")
    if src:
        data = open(src, "rb").read()
    else:
        req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 feed-sporting"})
        data = urllib.request.urlopen(req, timeout=300).read()

    root = ET.fromstring(data)
    entries = root.findall("a:entry", NS) or root.findall("./channel/item")

    items, seen, groups, descartados = [], set(), {}, 0
    for e in entries:
        it = convertir(e)
        if not it:
            descartados += 1
            continue
        if ONLY_IN_STOCK and it["availability"] != "in_stock":
            continue
        if it["item_id"] in seen:
            continue
        seen.add(it["item_id"])
        groups[it["_group"]] = groups.get(it["_group"], 0) + 1
        items.append(it)

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for it in items:
            variant = {k: it[k] for k in ("color", "size") if it[k]}
            if groups[it["_group"]] > 1 and variant:
                it["group_id"] = it["_group"]
                it["listing_has_variations"] = "true"
                it["variant_dict"] = json.dumps(variant, ensure_ascii=False)
            w.writerow([it.get(h, "") for h in HEADERS])

    print(f"Entradas en el XML: {len(entries)} | Filas en el feed: {len(items)} | Descartadas: {descartados}")
    if not items:
        sys.exit("El feed quedó vacío: no se publica.")


if __name__ == "__main__":
    main()
