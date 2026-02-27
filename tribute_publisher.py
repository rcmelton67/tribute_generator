print("RUNNING UPDATED SCRIPT")

import os
import re
import shutil
import json
import html
import urllib.parse
import unicodedata
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image

# ----------------------------
# CONFIG (edit if needed)
# ----------------------------
SITE_DOMAIN = "https://meltonmemorials.com"

# ----------------------------
# PATHS (self-contained)
# ----------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
TRIBUTES_DIR = os.path.join(PROJECT_ROOT, "pet-tributes")
MEMORIALS_DIR = os.path.join(TRIBUTES_DIR, "memorials")

ARCHIVE_INDEX = os.path.join(TRIBUTES_DIR, "index.html")
ARCHIVE_DATA = os.path.join(TRIBUTES_DIR, "data.json")
CARDS_PER_PAGE = 15
MAX_IMAGE_WIDTH = 1200
WEBP_QUALITY = 85

# CSS path used by the generated tribute pages (adjust if your live path differs)
TRIBUTE_CSS_HREF = "/pet-tributes/assets/mm-tribute.css"

# Placeholder source used when no image is uploaded.
PLACEHOLDER_IMAGE_FILE = os.path.join(TRIBUTES_DIR, "assets", "blank_memorial_loving_memory.png")


# ----------------------------
# Helpers
# ----------------------------

def load_template(filename: str) -> str:
    path = os.path.join(TEMPLATES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def normalize_years_input(years_raw: str) -> tuple[str, str, str]:
    """
    Accepts: '2008-2019' or '2008–2019' or '2008 — 2019'
    Returns: (start_year, end_year, pretty_years '2008 – 2019')
    """
    s = (years_raw or "").strip()
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", "", s)
    m = re.fullmatch(r"(\d{4})-(\d{4})", s)
    if not m:
        raise ValueError("Years must be in the format 2008-2019")
    y1, y2 = m.group(1), m.group(2)
    pretty = f"{y1} – {y2}"
    return y1, y2, pretty


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[’'`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # take first sentence-ish chunk
    m = re.search(r"(.+?[.!?])(\s|$)", t)
    if m:
        return m.group(1).strip()
    # else first ~140 chars
    return (t[:140].rstrip() + ("…" if len(t) > 140 else ""))


def summarize_excerpt(text: str, max_chars: int = 220) -> str:
    """Create a readable multi-sentence excerpt for cards/meta."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    # Prefer ending on sentence punctuation before hard cut.
    m = re.search(r"^(.+?[.!?])(?:\s|$)", cut)
    if m and len(m.group(1)) >= 80:
        return m.group(1).strip()
    # Fall back to nearest word boundary.
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:!? ") + "..."


def clean_meta_preview(text: str, max_chars: int = 120) -> str:
    """
    Build a readable preview for meta descriptions:
    - normalize whitespace
    - strip emoji/symbol chars that can cause encoding/display issues
    - prefer sentence boundary cut, else cut on a whole word
    """
    raw = re.sub(r"<[^>]+>", " ", (text or ""))
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""

    # Strip symbols/emojis while keeping letters, numbers, punctuation, and spaces.
    filtered = "".join(
        ch for ch in raw
        if unicodedata.category(ch) not in {"So", "Cs", "Co", "Cn"}
    )
    filtered = re.sub(r"\s+", " ", filtered).strip()
    if not filtered:
        return ""

    if len(filtered) <= max_chars:
        return filtered.rstrip(" ,;:-")

    chunk = filtered[:max_chars]
    sentence_end = max(chunk.rfind(". "), chunk.rfind("! "), chunk.rfind("? "))
    if sentence_end >= int(max_chars * 0.5):
        return chunk[: sentence_end + 1].strip()

    if " " in chunk:
        chunk = chunk.rsplit(" ", 1)[0]
    return chunk.rstrip(" ,;:-")


def parse_safe_markdown(text: str) -> str:
    # Escape all HTML first
    text = html.escape(text or "")

    # Headings
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)

    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

    # Paragraph wrapping
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if line.strip() == "":
            continue
        if line.startswith("<h2>") or line.startswith("<h3>"):
            wrapped.append(line)
        else:
            wrapped.append(f"<p>{line}</p>")

    return "\n".join(wrapped)


def strip_markdown_for_excerpt(text: str) -> str:
    # Escape any HTML first
    text = html.escape(text or "")

    # Remove headings
    text = re.sub(r"^### (.+)$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"\1", text, flags=re.MULTILINE)

    # Remove bold/italic markers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def normalize_dates_text(value: str) -> str:
    """
    Normalize dates text to avoid mojibake like 'â€“' and keep separators consistent.
    """
    s = (value or "").strip()
    s = s.replace("â€“", "-").replace("â€”", "-")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def normalize_published_iso(value: str) -> str:
    """Normalize published date values to full ISO timestamps."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T00:00:00"
    return raw


def safe_mkdir(path: str):
    os.makedirs(path, exist_ok=True)


def get_entry_folder(entry: dict) -> str:
    return (entry.get("folder") or "").strip().strip("/")


def get_entry_web_base(entry: dict) -> str:
    slug = (entry.get("slug") or "").strip()
    folder = get_entry_folder(entry)
    return f"/pet-tributes/{folder}/{slug}/" if folder else f"/pet-tributes/{slug}/"


def find_tribute_folder(slug: str, folder_hint: str = "") -> str:
    slug = (slug or "").strip()
    hint = (folder_hint or "").strip().strip("/")
    if hint:
        hinted = os.path.join(TRIBUTES_DIR, hint, slug)
        if os.path.exists(hinted):
            return hinted
    memorials_path = os.path.join(MEMORIALS_DIR, slug)
    if os.path.exists(memorials_path):
        return memorials_path
    return os.path.join(TRIBUTES_DIR, slug)


def ensure_pillow():
    try:
        return Image is not None
    except Exception:
        return False


def process_placeholder_image(source_png_path: str, output_path: str):
    with Image.open(source_png_path) as img:
        img = img.convert("RGB")

        if img.width > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / img.width
            new_height = int(img.height * ratio)
            img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

        img.save(output_path, "WEBP", quality=WEBP_QUALITY)


def convert_to_webp_normalized(
    src_path: str,
    dest_path: str,
    max_width: int = MAX_IMAGE_WIDTH,
    quality: int = WEBP_QUALITY,
) -> dict:
    """
    Convert an uploaded image to WebP and normalize size:
    - If source width > max_width, downscale to max_width preserving aspect ratio
    - If source width <= max_width, keep original size (no upscaling)
    - Respect EXIF orientation
    Returns info dict for logging/debug.
    """
    from PIL import Image, ImageOps

    with Image.open(src_path) as im:
        # Fix phone rotation issues (EXIF orientation)
        im = ImageOps.exif_transpose(im)

        # Convert to RGB if needed (WebP doesn't like some modes)
        if im.mode in ("RGBA", "P"):
            # Keep alpha if present; Pillow can save WebP with alpha
            pass
        elif im.mode != "RGB":
            im = im.convert("RGB")

        orig_w, orig_h = im.size

        # Downscale only (no upscaling)
        if orig_w > max_width:
            new_h = int((max_width / orig_w) * orig_h)
            im = im.resize((max_width, new_h), Image.LANCZOS)

        # Save WebP
        save_kwargs = {
            "format": "WEBP",
            "quality": quality,
            "method": 6,     # slower but better compression
        }

        # If image has alpha, keep it; otherwise ensure RGB
        # Pillow handles this automatically in most cases.
        im.save(dest_path, **save_kwargs)

        final_w, final_h = im.size
        return {
            "orig": (orig_w, orig_h),
            "final": (final_w, final_h),
            "resized": orig_w > max_width
        }


def load_data() -> list[dict]:
    if not os.path.exists(ARCHIVE_DATA):
        return []
    # Use utf-8-sig so BOM-prefixed JSON files still parse cleanly.
    with open(ARCHIVE_DATA, "r", encoding="utf-8-sig") as f:
        items = json.load(f)
    for item in items:
        item["published_iso"] = normalize_published_iso(
            item.get("published_iso") or item.get("publish_date") or ""
        )
        # Missing or non-true values are treated as not featured.
        item["featured"] = item.get("featured") is True
        # Internal publish-tracking flag (defaults to False).
        item["email_sent"] = item.get("email_sent") is True
    return items


def save_data(items: list[dict]):
    # keep it readable + stable
    with open(ARCHIVE_DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def sort_entries_newest_first(items: list[dict]) -> list[dict]:
    enumerated = list(enumerate(items))
    enumerated.sort(
        key=lambda pair: (
            normalize_published_iso(
                pair[1].get("published_iso") or pair[1].get("publish_date") or ""
            ),
            pair[0],
        ),
        reverse=True,
    )
    entries_sorted = [item for _, item in enumerated]

    featured_entries = [e for e in entries_sorted if e.get("featured") is True]
    if len(featured_entries) > 1:
        # Keep only the newest featured tribute.
        for e in featured_entries[1:]:
            e["featured"] = False

    featured_entry = next((e for e in entries_sorted if e.get("featured") is True), None)
    if featured_entry:
        entries_sorted.remove(featured_entry)
        entries_sorted.insert(0, featured_entry)

    return entries_sorted


def build_card_html(entry: dict) -> str:
    pet_name = entry.get("pet_name", "")
    breed = entry.get("breed", "")
    pet_type = (entry.get("pet_type") or "").strip()
    years_pretty = normalize_dates_text(entry.get("years_pretty", ""))
    excerpt = strip_markdown_for_excerpt(entry.get("excerpt", ""))
    slug = entry.get("slug", "")
    image_filename = entry.get("image_filename", "")
    publish_label = ""
    if entry.get("published_iso"):
        try:
            dt = datetime.fromisoformat(normalize_published_iso(entry.get("published_iso", "")))
            publish_label = dt.strftime("%b %Y")
        except Exception:
            publish_label = ""
    first_name = (entry.get("first_name") or "").strip()
    state = (entry.get("state") or "").strip()
    email = (entry.get("email") or "").strip()
    featured = entry.get("featured") is True

    attribution_html = ""
    if first_name or state:
        parts = [p for p in [first_name, state] if p]
        attribution_html = f'<div class="mm-archive-attribution">{escape_html(", ".join(parts))}</div>'

    subtitle_for_card = ""
    if breed and pet_type:
        subtitle_for_card = f"{breed} - {pet_type}"
    elif breed:
        subtitle_for_card = breed
    elif pet_type:
        subtitle_for_card = pet_type
    title_line = escape_html(pet_name + (f" – {subtitle_for_card}" if subtitle_for_card else ""))

    card_href = get_entry_web_base(entry)
    is_placeholder_card = (
        (not image_filename)
        or image_filename == "blank_memorial_loving_memory.png"
        or image_filename == f"{slug}.png"
        or image_filename.endswith("-memorial-stone.png")
        or image_filename.endswith("-memorial-stone.webp")
    )
    card_img_src = (
        "/pet-tributes/assets/blank_memorial_loving_memory.png"
        if (not image_filename or image_filename == "blank_memorial_loving_memory.png")
        else f"{card_href}{escape_html(image_filename)}"
    )
    card_thumb_class = "mm-archive-thumb mm-placeholder" if is_placeholder_card else "mm-archive-thumb"
    card_more_html = (
        '<div class="mm-archive-more" aria-hidden="true">'
        '<span class="mm-archive-more-label">more</span>'
        '<span class="mm-archive-chevron">&#8250;</span>'
        "</div>"
        if excerpt else ""
    )
    featured_badge_html = '<div class="featured-badge">Featured Tribute</div>' if featured else ""

    return f"""
<article class="mm-archive-card"
  data-name="{escape_html(pet_name)}"
  data-breed="{escape_html(breed)}"
  data-type="{escape_html(pet_type)}"
  data-years="{escape_html(years_pretty)}"
  data-content="{escape_html(excerpt)}"
  data-first-name="{escape_html(first_name)}"
  data-state="{escape_html(state)}"
  data-email="{escape_html(email)}"
>
  <a class="mm-archive-link" href="{card_href}">
    <div class="{card_thumb_class}">
      <span class="mm-date-badge">{escape_html(publish_label)}</span>
      <img src="{card_img_src}" alt="{escape_html(pet_name)} memorial tribute" loading="lazy">
    </div>
    <div class="mm-archive-meta">
      {featured_badge_html}
      <h2 class="mm-archive-title">{title_line}</h2>
      <p class="mm-archive-excerpt">{escape_html(excerpt)}</p>
      {card_more_html}
      <p class="mm-archive-years">{escape_html(years_pretty)}</p>
      {attribution_html}
    </div>
  </a>
</article>
""".strip()


def page_url(page_num: int) -> str:
    return page_url_for_prefix(page_num, "/pet-tributes/")


def page_url_for_prefix(page_num: int, prefix: str) -> str:
    """
    prefix examples:
      "/pet-tributes/"              (main archive)
      "/pet-tributes/dog/"          (pet-type archive root)
    """
    prefix = (prefix or "/").strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix if page_num == 1 else f"{prefix}page-{page_num}/"


def css_href_for_page(page_num: int) -> str:
    # Always use absolute path for live site stability
    return "/pet-tributes/assets/mm-tribute.css"


def build_pagination(current: int, total: int) -> str:
    return build_pagination_for_prefix(current, total, "/pet-tributes/")


def build_pagination_for_prefix(current: int, total: int, prefix: str) -> str:
    if total <= 1:
        return ""

    parts = []

    if current > 1:
        parts.append(f'<a class="mm-page-arrow" href="{page_url_for_prefix(current-1, prefix)}">←</a>')

    for i in range(1, total + 1):
        active = "mm-page-active" if i == current else ""
        parts.append(f'<a class="mm-page-number {active}" href="{page_url_for_prefix(i, prefix)}">{i}</a>')

    if current < total:
        parts.append(f'<a class="mm-page-arrow" href="{page_url_for_prefix(current+1, prefix)}">→</a>')

    return f'<div class="mm-pagination">{" ".join(parts)}</div>'


def build_archive_schema(base_url: str, tributes: list[dict]) -> str:
    item_list = []
    for index, tribute in enumerate(tributes, start=1):
        slug = (tribute.get("slug") or "").strip()
        if not slug:
            continue
        tribute_name = (tribute.get("pet_name") or tribute.get("name") or "").strip()
        item_list.append({
            "@type": "ListItem",
            "position": index,
            "url": f"{base_url}{get_entry_web_base(tribute)}",
            "name": f"{tribute_name} Memorial Tribute".strip(),
        })

    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Pet Memorial Tributes",
        "url": f"{base_url}/pet-tributes/",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": item_list,
        },
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_archive_full_html(cards_html: str, current_page: int, total_pages: int, tribute_entries: list[dict]) -> str:

    title = "Pet Memorial Tributes" if current_page == 1 else f"Pet Memorial Tributes — Page {current_page}"
    canonical = SITE_DOMAIN + page_url(current_page)

    # Load base + archive template
    base = load_template("base.html")
    archive_template = load_template("archive.html")

    # Build head meta
    archive_schema_json = build_archive_schema(SITE_DOMAIN, tribute_entries)
    archive_schema_block = f"""
  <script type="application/ld+json">
{archive_schema_json}
  </script>
""".strip()
    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{canonical}">
  {archive_schema_block}
""".strip()

    # Inject cards + pagination into archive template
    pagination_html = build_pagination(current_page, total_pages)

    content = archive_template.replace("{{CARDS}}", cards_html)
    content = content.replace("{{PAGINATION}}", pagination_html)

    # Load header + footer
    header_template = load_template("header.html")
    header_html = header_template.replace("{{HEADER_CLASSES}}", "site-header")

    footer_html = load_template("footer.html")

    # Assemble final
    final_html = base.replace("{{HEAD_META}}", head_meta)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{CONTENT}}", content)
    final_html = final_html.replace("{{FOOTER}}", footer_html)

    return final_html


def write_archive_page(
    page_entries: list[dict],
    title: str,
    canonical: str,
    output_folder: str,
    current_page: int,
    total_pages: int,
    pagination_prefix: str,
):
    cards_html = "".join(build_card_html(e) for e in page_entries)
    pagination_html = build_pagination_for_prefix(current_page, total_pages, pagination_prefix)

    archive_schema_json = build_archive_schema(SITE_DOMAIN, page_entries)
    archive_schema_block = f"""
  <script type="application/ld+json">
{archive_schema_json}
  </script>
""".strip()

    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{canonical}">
  {archive_schema_block}
""".strip()

    base = load_template("base.html")
    archive_template = load_template("archive.html")

    content = archive_template.replace("{{CARDS}}", cards_html)
    content = content.replace("{{PAGINATION}}", pagination_html)

    header_template = load_template("header.html")
    header_html = header_template.replace("{{HEADER_CLASSES}}", "site-header")
    footer_html = load_template("footer.html")

    final_html = base.replace("{{HEAD_META}}", head_meta)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{CONTENT}}", content)
    final_html = final_html.replace("{{FOOTER}}", footer_html)

    os.makedirs(output_folder, exist_ok=True)
    with open(os.path.join(output_folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(final_html)


def rebuild_archive_pages(entries):
    from math import ceil

    # Featured tributes are pinned first; remaining tributes are newest-first.
    entries = sort_entries_newest_first(entries)

    total_pages = ceil(len(entries) / CARDS_PER_PAGE)

    if total_pages == 0:
        total_pages = 1

    # Remove stale pagination folders so page count shrinks correctly after deletions
    # (e.g. 31 -> 30 entries should remove /page-3/)
    for name in os.listdir(TRIBUTES_DIR):
        folder = os.path.join(TRIBUTES_DIR, name)
        if os.path.isdir(folder) and re.fullmatch(r"page-\d+", name):
            shutil.rmtree(folder, ignore_errors=True)

    for page_num in range(1, total_pages + 1):
        start = (page_num - 1) * CARDS_PER_PAGE
        end = start + CARDS_PER_PAGE
        page_entries = entries[start:end]

        title = "Pet Memorial Tributes" if page_num == 1 else f"Pet Memorial Tributes — Page {page_num}"
        canonical = SITE_DOMAIN + page_url_for_prefix(page_num, "/pet-tributes/")
        pagination_prefix = "/pet-tributes/"

        if page_num == 1:
            output_folder = TRIBUTES_DIR
        else:
            output_folder = os.path.join(TRIBUTES_DIR, f"page-{page_num}")

        write_archive_page(
            page_entries=page_entries,
            title=title,
            canonical=canonical,
            output_folder=output_folder,
            current_page=page_num,
            total_pages=total_pages,
            pagination_prefix=pagination_prefix,
        )


def rebuild_pet_type_archives(entries):
    from math import ceil

    # Normalize and group by pet_type slug
    grouped = {}

    for entry in entries:
        pet_type = (entry.get("pet_type") or "").strip()
        if not pet_type:
            continue

        pet_type_slug = slugify(pet_type)
        if not pet_type_slug:
            continue

        grouped.setdefault(pet_type_slug, []).append(entry)

    # Build each pet type archive
    for pet_type_slug, type_entries in grouped.items():
        type_entries = sort_entries_newest_first(type_entries)

        total_pages = ceil(len(type_entries) / CARDS_PER_PAGE)
        if total_pages == 0:
            total_pages = 1

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * CARDS_PER_PAGE
            end = start + CARDS_PER_PAGE
            page_entries = type_entries[start:end]

            title = f"{pet_type_slug.capitalize()} Memorial Tributes"
            if page_num > 1:
                title = f"{title} — Page {page_num}"
            pagination_prefix = f"/pet-tributes/{pet_type_slug}/"
            canonical = SITE_DOMAIN + page_url_for_prefix(page_num, pagination_prefix)

            if page_num == 1:
                output_folder = os.path.join(TRIBUTES_DIR, pet_type_slug)
            else:
                output_folder = os.path.join(TRIBUTES_DIR, pet_type_slug, f"page-{page_num}")

            write_archive_page(
                page_entries=page_entries,
                title=title,
                canonical=canonical,
                output_folder=output_folder,
                current_page=page_num,
                total_pages=total_pages,
                pagination_prefix=pagination_prefix,
            )


def generate_sitemap(data: list[dict]):
    from math import ceil

    sitemap_path = os.path.join(TRIBUTES_DIR, "sitemap.xml")

    urls = []
    seen_locs = set()

    def add_url(loc: str):
        if not loc or loc in seen_locs:
            return
        seen_locs.add(loc)
        urls.append(
            f"""
  <url>
    <loc>{escape_html(loc)}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>"""
        )

    entries_sorted = sort_entries_newest_first(data)
    main_total_pages = ceil(len(entries_sorted) / CARDS_PER_PAGE)
    if main_total_pages == 0:
        main_total_pages = 1
    for page_num in range(1, main_total_pages + 1):
        add_url(SITE_DOMAIN + page_url_for_prefix(page_num, "/pet-tributes/"))

    grouped = {}
    for entry in entries_sorted:
        pet_type = (entry.get("pet_type") or "").strip()
        if not pet_type:
            continue
        pet_type_slug = slugify(pet_type)
        if not pet_type_slug:
            continue
        grouped.setdefault(pet_type_slug, []).append(entry)

    for pet_type_slug, type_entries in grouped.items():
        type_total_pages = ceil(len(type_entries) / CARDS_PER_PAGE)
        if type_total_pages == 0:
            type_total_pages = 1
        prefix = f"/pet-tributes/{pet_type_slug}/"
        for page_num in range(1, type_total_pages + 1):
            add_url(SITE_DOMAIN + page_url_for_prefix(page_num, prefix))

    for item in data:
        slug = (item.get("slug") or "").strip()
        if not slug:
            continue
        loc = f"{SITE_DOMAIN}{get_entry_web_base(item)}"
        add_url(loc)

    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urls)}
</urlset>
"""

    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write(sitemap_content)



def migrate_existing_folders_to_json():
    entries = []

    for name in os.listdir(TRIBUTES_DIR):
        folder_path = os.path.join(TRIBUTES_DIR, name)

        if not os.path.isdir(folder_path):
            continue

        if name.startswith("assets") or name.startswith("page-"):
            continue

        index_file = os.path.join(folder_path, "index.html")
        if not os.path.exists(index_file):
            continue

        with open(index_file, "r", encoding="utf-8") as f:
            html = f.read()

        # Extract basic fields
        title_match = re.search(r'<h1 class="mm-tribute-name">(.*?)</h1>', html)
        subtitle_match = re.search(r'<p class="mm-tribute-subtitle">(.*?)</p>', html)
        years_match = re.search(r'<p class="mm-years">(.*?)</p>', html)
        excerpt_match = re.search(r'<meta name="description" content="(.*?)"', html)
        origin_match = re.search(r'<p class="mm-tribute-origin">Shared by (.*?)</p>', html)

        pet_name = title_match.group(1).strip() if title_match else name
        breed = ""
        if subtitle_match:
            sub = subtitle_match.group(1)
            breed = sub.replace(" Memorial Tribute", "").strip()

        years_pretty = years_match.group(1).strip() if years_match else ""
        excerpt = excerpt_match.group(1).strip() if excerpt_match else ""

        first_name = ""
        state = ""
        if origin_match:
            parts = origin_match.group(1).split(",")
            if len(parts) > 0:
                first_name = parts[0].strip()
            if len(parts) > 1:
                state = parts[1].strip()

        # find webp image
        image_filename = ""
        for file in os.listdir(folder_path):
            if file.endswith(".webp"):
                image_filename = file
                break

        entries.append({
            "slug": name,
            "pet_name": pet_name,
            "breed": breed,
            "years_pretty": years_pretty,
            "excerpt": excerpt,
            "first_name": first_name,
            "state": state,
            "published_iso": "2026-02-01",
            "image_filename": image_filename,
            "featured": False,
            "email_sent": False,
        })

    save_data(entries)
    rebuild_archive_pages(entries)
    rebuild_pet_type_archives(entries)
    generate_sitemap(entries)


def build_tribute_html(
    pet_name: str,
    first_name: str,
    state: str,
    breed: str,
    pet_type: str,
    years_pretty: str,
    excerpt: str,
    page_url: str,
    tribute_web_path: str,
    og_image_abs: str,
    user_uploaded_image: bool,
    second_image_filename: str,
    publish_date_iso: str,
    tribute_message_html: str,
) -> str:

    # ----- Title / subtitle logic -----
    breed_clean = (breed or "").strip()
    pet_type_clean = (pet_type or "").strip()
    pet_type_title = pet_type_clean if pet_type_clean else "Pet"
    pet_type_lower = pet_type_title.lower()

    if breed_clean:
        subtitle = f"{breed_clean} {pet_type_title} Memorial Tribute"
    else:
        subtitle = f"{pet_type_title} Memorial Tribute"

    title = f"{pet_name} {pet_type_title} Memorial Tribute | Melton Memorials"

    years_pretty = normalize_dates_text(years_pretty)
    plain_message = re.sub(r"<[^>]+>", " ", tribute_message_html or "")
    plain_message = re.sub(r"\s+", " ", plain_message).strip()
    clean_message = re.sub(r"[^\x00-\x7F]+", "", plain_message)
    clean_message = re.sub(r"\s+\.", ".", clean_message)
    clean_message = re.sub(r"\s{2,}", " ", clean_message).strip()
    og_description = excerpt or f"Read the memorial tribute for {pet_name}, a beloved {pet_type_lower}, honored with a handcrafted memorial stone."
    descriptor = f"{breed_clean + ' ' if breed_clean else ''}{pet_type_lower}".strip()
    descriptor = re.sub(r"\s+", " ", descriptor)
    tribute_preview = clean_meta_preview(clean_message or excerpt, max_chars=120)
    meta_description = (
        f"Read the memorial tribute for {pet_name}, "
        f"a beloved {descriptor} "
        f"honored with a handcrafted memorial stone by Melton Memorials."
    )
    if tribute_preview:
        meta_description = f"{meta_description} {tribute_preview}..."
    structured_meta = meta_description
    og_description = structured_meta

    submitter_parts = [p for p in [first_name.strip(), state.strip()] if p]
    submitter_line = ", ".join(submitter_parts)

    breed_line = subtitle
    input_filename = os.path.basename(relative_filename_from_url(og_image_abs))

    # Determine image file/path from provided URL filename. If empty, fall back to shared placeholder.
    if input_filename:
        image_filename = input_filename
        image_path = f"{tribute_web_path}{image_filename}"
        og_image = f"{SITE_DOMAIN}{tribute_web_path}{image_filename}"
    else:
        image_filename = "blank_memorial_loving_memory.png"
        image_path = f"/pet-tributes/assets/{image_filename}"
        og_image = f"{SITE_DOMAIN}/pet-tributes/assets/{image_filename}"

    second_image_filename = (second_image_filename or "").strip()
    if breed_clean:
        image_alt = f"Memorial stone for {pet_name}, beloved {breed_clean} {pet_type_lower}"
    else:
        image_alt = f"Memorial stone for {pet_name}, beloved {pet_type_lower}"
    image_2_block = ""
    if second_image_filename:
        image_2_block = (
            '<div class="mm-tribute-image mm-tribute-image-secondary">'
            f'<img src="{tribute_web_path}{escape_html(second_image_filename)}" alt="{escape_html(image_alt)} 2">'
            "</div>"
        )
    dates_block = f"<p>{escape_html(years_pretty)}</p>" if years_pretty.strip() else ""
    shared_block = f"<p>Shared by {escape_html(submitter_line)}</p>" if submitter_line else ""
    share_description = structured_meta.strip() if (structured_meta or "").strip() else f"Memorial tribute for {pet_name}"
    share_subject = f"{pet_name} Memorial Tribute"
    share_body = f"{share_description}\n\n{page_url}"
    share_body_with_image = share_body + (f"\n\nImage: {og_image}" if og_image else "")
    share_facebook_url = f"https://www.facebook.com/sharer/sharer.php?u={escape_url(page_url)}"
    share_pinterest_url = (
        "https://pinterest.com/pin/create/button/"
        f"?url={escape_url(page_url)}"
        f"&media={escape_url(og_image)}"
        f"&description={escape_url(share_description)}"
    )
    share_email_url = (
        f"mailto:?subject={escape_url(share_subject)}"
        f"&body={escape_url(share_body_with_image)}"
    )

    canonical_url = page_url
    full_image_url = og_image
    publish_date = publish_date_iso
    meta_description = structured_meta
    schema_data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": meta_description,
        "image": full_image_url,
        "author": {
            "@type": "Organization",
            "name": "Melton Memorials",
        },
        "publisher": {
            "@type": "Organization",
            "name": "Melton Memorials",
        },
        "datePublished": publish_date,
        "mainEntityOfPage": canonical_url,
    }
    schema_json = json.dumps(schema_data, ensure_ascii=False)
    breadcrumb_data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": "https://meltonmemorials.com/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Pet Tributes",
                "item": "https://meltonmemorials.com/pet-tributes/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": title,
                "item": canonical_url,
            },
        ],
    }
    breadcrumb_json = json.dumps(breadcrumb_data, ensure_ascii=False)

    # ----- Load base template -----
    base = load_template("base.html")

    # ----- Build head meta -----
    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="description" content="{escape_html(structured_meta)}">
  <link rel="canonical" href="{page_url}">
  <link rel="icon" type="image/x-icon" href="/pet-tributes/assets/favicon.ico">
  <meta name="robots" content="index, follow">
  <meta name="date" content="{publish_date_iso}">
  <meta name="twitter:title" content="{escape_html(title)}">
  <meta name="twitter:description" content="{escape_html(structured_meta)}">
  <meta name="twitter:image" content="{og_image}">
  <script type="application/ld+json">
{schema_json}
  </script>
  <script type="application/ld+json">
{breadcrumb_json}
  </script>
""".strip()

    # ----- Load tribute content template -----
    content = load_template("tribute_content.html")

    content = content.replace("{{PET_NAME}}", escape_html(pet_name))
    content = content.replace("{{BREED_LINE}}", escape_html(breed_line))
    content = content.replace("{{IMAGE_PATH}}", image_path)
    content = content.replace("{{IMAGE_ALT}}", escape_html(image_alt))
    content = content.replace("{{IMAGE_2_BLOCK}}", image_2_block)
    content = content.replace("{{DATES_BLOCK}}", dates_block)
    content = content.replace("{{SHARED_BLOCK}}", shared_block)
    content = content.replace("{{SHARE_FACEBOOK_URL}}", share_facebook_url)
    content = content.replace("{{SHARE_PINTEREST_URL}}", share_pinterest_url)
    content = content.replace("{{SHARE_EMAIL_URL}}", share_email_url)
    content = content.replace("{{TRIBUTE_MESSAGE}}", tribute_message_html)

    # ----- Load header + footer -----
    header_template = load_template("header.html")
    header_html = header_template.replace("{{HEADER_CLASSES}}", "site-header")

    footer_html = load_template("footer.html")

    # ----- Assemble final page -----
    final_html = base.replace("{{HEAD_META}}", head_meta)
    final_html = final_html.replace("{{OG_TITLE}}", escape_html(title))
    final_html = final_html.replace("{{OG_DESCRIPTION}}", escape_html(structured_meta))
    final_html = final_html.replace("{{CANONICAL_URL}}", page_url)
    final_html = final_html.replace("{{OG_IMAGE}}", og_image)
    final_html = final_html.replace("{{PUBLISHED_TIME}}", publish_date_iso)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{CONTENT}}", content)
    final_html = final_html.replace("{{FOOTER}}", footer_html)

    return final_html



def rebuild_single_tribute_page(entry: dict, tribute_message_override: str = ""):
    slug = (entry.get("slug") or "").strip()
    if not slug:
        return

    tribute_folder = find_tribute_folder(slug, entry.get("folder", ""))
    safe_mkdir(tribute_folder)
    index_path = os.path.join(tribute_folder, "index.html")

    # Preserve existing tribute body text when editing metadata/images unless explicit override provided.
    tribute_message_html = ""
    override_text = (tribute_message_override or "").strip()
    if override_text:
        tribute_message_html = parse_safe_markdown(override_text)
    elif os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                existing_html = f.read()
            msg_match = re.search(
                r'<div class="mm-tribute-message(?:\s+mm-tribute-message-centered)?"(?:\s+style="[^"]*")?\s*>\s*(.*?)\s*</div>',
                existing_html,
                flags=re.S,
            )
            if msg_match:
                tribute_message_html = (msg_match.group(1) or "").strip()
        except Exception:
            tribute_message_html = ""

    if not tribute_message_html:
        fallback_excerpt = (entry.get("excerpt") or "").strip()
        tribute_message_html = f"<p>{escape_html(fallback_excerpt)}</p>" if fallback_excerpt else "<p></p>"

    tribute_web_path = get_entry_web_base(entry)
    image_filename = (entry.get("image_filename") or "").strip()
    is_placeholder_image = (
        (not image_filename)
        or image_filename == "blank_memorial_loving_memory.png"
        or image_filename == f"{slug}.png"
        or image_filename.endswith("-memorial-stone.png")
        or image_filename.endswith("-memorial-stone.webp")
    )
    if image_filename and not is_placeholder_image:
        og_image_abs = f"{SITE_DOMAIN}{tribute_web_path}{image_filename}"
    else:
        og_image_abs = f"{SITE_DOMAIN}/pet-tributes/assets/blank_memorial_loving_memory.png"

    page_url = f"{SITE_DOMAIN}{tribute_web_path}"
    tribute_html = build_tribute_html(
        pet_name=entry.get("pet_name", ""),
        first_name=entry.get("first_name", ""),
        state=entry.get("state", ""),
        breed=entry.get("breed", ""),
        pet_type=entry.get("pet_type", ""),
        years_pretty=entry.get("years_pretty", ""),
        excerpt=entry.get("excerpt", ""),
        page_url=page_url,
        tribute_web_path=tribute_web_path,
        og_image_abs=og_image_abs,
        user_uploaded_image=not is_placeholder_image,
        second_image_filename=entry.get("image2_filename", ""),
        publish_date_iso=(entry.get("published_iso") or datetime.now().isoformat(timespec="seconds")),
        tribute_message_html=tribute_message_html,
    )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(tribute_html)


def tribute_message_html_to_text(message_html: str) -> str:
    """Convert stored tribute message HTML back to plain editable text with paragraph spacing."""
    source = message_html or ""
    paragraph_matches = re.findall(r"<p[^>]*>(.*?)</p>", source, flags=re.S | re.I)
    if paragraph_matches:
        parts = []
        for p in paragraph_matches:
            plain = re.sub(r"<[^>]+>", "", p)
            plain = html.unescape(plain).strip()
            if plain:
                parts.append(plain)
        if parts:
            return "\n\n".join(parts)

    fallback = re.sub(r"<[^>]+>", " ", source)
    fallback = html.unescape(fallback)
    fallback = re.sub(r"\s+", " ", fallback).strip()
    return fallback


def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def escape_json(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def escape_url(s: str) -> str:
    # very small helper for pin description
    from urllib.parse import quote
    return quote(s or "")


def relative_filename_from_url(url: str) -> str:
    # If og_image_abs is inside the same folder, we want <filename>.webp
    # If placeholder absolute url, keep it absolute.
    if url.startswith(SITE_DOMAIN + "/pet-tributes/"):
        # last segment
        return url.split("/")[-1]
    return url


# ----------------------------
# GUI App
# ----------------------------
class TributePublisherApp:
    @staticmethod
    def _bind_tab_navigation(current_widget, next_widget, prev_widget):
        def go_next(_event):
            next_widget.focus_set()
            return "break"

        def go_prev(_event):
            prev_widget.focus_set()
            return "break"

        current_widget.bind("<Tab>", go_next)
        current_widget.bind("<Shift-Tab>", go_prev)
        # Some Tk builds (notably on Windows) do not support ISO_Left_Tab.
        try:
            current_widget.bind("<ISO_Left_Tab>", go_prev)
        except Exception:
            pass

    def _apply_create_form_tab_order(self, widgets):
        ordered = [w for w in widgets if w is not None]
        if not ordered:
            return
        for i, widget in enumerate(ordered):
            prev_widget = ordered[i - 1]
            next_widget = ordered[(i + 1) % len(ordered)]
            self._bind_tab_navigation(widget, next_widget, prev_widget)

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Melton Memorials — Tribute Publisher")
        self.root.geometry("1380x920")
        self.root.minsize(1220, 760)
        self.last_tribute_url = ""
        self.last_email = ""
        self.last_first_name = ""

        self.image_path = tk.StringVar(value="")
        self.image2_path = tk.StringVar(value="")

        style = ttk.Style()
        style.configure("TributeNotebook.TNotebook.Tab", padding=(24, 10))

        # notebook + tabs
        notebook = ttk.Notebook(root, style="TributeNotebook.TNotebook")
        notebook.pack(fill="both", expand=True)

        create_frame = ttk.Frame(notebook)
        notebook.add(create_frame, text="Create Tribute")

        manager_frame = ttk.Frame(notebook)
        notebook.add(manager_frame, text="Tribute Manager")

        # create tab layout
        pad = {"padx": 10, "pady": 6}

        tk.Label(create_frame, text="Pet Name *").grid(row=0, column=0, sticky="w", **pad)
        self.pet_name = tk.Entry(create_frame, width=44)
        self.pet_name.grid(row=0, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Pet Type (optional)").grid(row=1, column=0, sticky="w", **pad)
        self.pet_type = tk.Entry(create_frame, width=44)
        self.pet_type.grid(row=1, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="First Name (optional)").grid(row=9, column=0, sticky="w", **pad)
        self.first_name = tk.Entry(create_frame, width=44)
        self.first_name.grid(row=9, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="State (optional)").grid(row=10, column=0, sticky="w", **pad)
        self.state = tk.Entry(create_frame, width=44)
        self.state.grid(row=10, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Email (optional)").grid(row=11, column=0, sticky="w", **pad)
        self.email = tk.Entry(create_frame, width=44)
        self.email.grid(row=11, column=1, sticky="w", **pad)
        self.email_sent_var = tk.BooleanVar(value=False)
        self.email_sent_check = tk.Checkbutton(
            create_frame,
            text="Tribute Published (Email Sent)",
            variable=self.email_sent_var,
            onvalue=True,
            offvalue=False,
        )
        self.email_sent_check.grid(row=12, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Breed (optional)").grid(row=4, column=0, sticky="w", **pad)
        self.breed = tk.Entry(create_frame, width=44)
        self.breed.grid(row=4, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Dates of Life (optional, any format)").grid(row=5, column=0, sticky="w", **pad)
        self.years = tk.Entry(create_frame, width=44)
        self.years.grid(row=5, column=1, sticky="w", **pad)

        self.formatting_guide_text = (
            "Formatting Guide:\n"
            "Use ## Heading Text for section headings.\n"
            "Use ### Heading Text for smaller headings.\n"
            "Use **bold text** for bold.\n"
            "Use *italic text* for italic.\n"
            "Keep formatting minimal for best results."
        )

        tk.Label(create_frame, text="Tribute Message *").grid(row=6, column=0, sticky="nw", **pad)
        message_frame = tk.Frame(create_frame)
        message_frame.grid(row=6, column=1, sticky="w", **pad)
        self.message = tk.Text(message_frame, width=62, height=10)
        self.message.pack(anchor="w")
        self.message_guide = tk.Label(
            create_frame,
            text=self.formatting_guide_text,
            justify="left",
            fg="#666",
            font=("TkDefaultFont", 8),
            wraplength=300,
        )
        self.message_guide.grid(row=6, column=2, sticky="nw", padx=(8, 10), pady=6)

        tk.Label(create_frame, text="Photo 1 (optional, recommended)").grid(row=7, column=0, sticky="w", **pad)

        img_row = tk.Frame(create_frame)
        img_row.grid(row=7, column=1, sticky="w", **pad)

        self.img_label = tk.Label(img_row, textvariable=self.image_path, width=34, anchor="w")
        self.img_label.pack(side="left")

        self.btn_choose_image = tk.Button(img_row, text="Choose…", command=self.choose_image)
        self.btn_choose_image.pack(side="left", padx=6)
        self.btn_clear_image = tk.Button(img_row, text="Clear", command=self.clear_image)
        self.btn_clear_image.pack(side="left")

        tk.Label(create_frame, text="Photo 2 (optional)").grid(row=8, column=0, sticky="w", **pad)

        img2_row = tk.Frame(create_frame)
        img2_row.grid(row=8, column=1, sticky="w", **pad)

        self.img2_label = tk.Label(img2_row, textvariable=self.image2_path, width=34, anchor="w")
        self.img2_label.pack(side="left")
        self.btn_choose_image2 = tk.Button(img2_row, text="Choose…", command=self.choose_image2)
        self.btn_choose_image2.pack(side="left", padx=6)
        self.btn_clear_image2 = tk.Button(img2_row, text="Clear", command=self.clear_image2)
        self.btn_clear_image2.pack(side="left")

        action_row = tk.Frame(create_frame)
        action_row.grid(row=13, column=1, sticky="w", padx=10, pady=14)
        self.btn_generate = tk.Button(
            action_row, text="Generate Tribute Files", command=self.generate, height=2, width=26
        )
        self.btn_generate.pack(side="left")
        self.open_email_btn = tk.Button(
            action_row,
            text="Send Publish Email",
            command=self.send_publish_email,
            width=20,
        )
        self.open_email_btn.pack(side="left", padx=(10, 0))

        tk.Label(
            create_frame,
            text=f"Output: {TRIBUTES_DIR}\nArchive: {ARCHIVE_INDEX}",
            fg="#444"
        ).grid(row=14, column=0, columnspan=2, sticky="w", padx=10, pady=6)

        # Force tab flow to match the visible top-to-bottom form layout.
        self._apply_create_form_tab_order([
            self.pet_name,
            self.pet_type,
            self.breed,
            self.years,
            self.message,
            self.btn_choose_image,
            self.btn_clear_image,
            self.btn_choose_image2,
            self.btn_clear_image2,
            self.first_name,
            self.state,
            self.email,
            self.email_sent_check,
            self.btn_generate,
            self.open_email_btn,
        ])
        self.refresh_email_button_state()

        # manager tab layout
        self.checked_slugs = set()
        columns = ("selected", "slug", "pet_name", "published")
        self.tribute_tree = ttk.Treeview(
            manager_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tribute_tree.heading("selected", text="✓")
        self.tribute_tree.heading("slug", text="Slug")
        self.tribute_tree.heading("pet_name", text="Pet Name")
        self.tribute_tree.heading("published", text="Published")

        self.tribute_tree.column("selected", width=44, anchor="center", stretch=False)
        self.tribute_tree.column("slug", width=300, anchor="w")
        self.tribute_tree.column("pet_name", width=220, anchor="w")
        self.tribute_tree.column("published", width=120, anchor="w")
        self.tribute_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tribute_tree.bind("<Button-1>", self.on_tree_click)

        actions_row = ttk.Frame(manager_frame)
        actions_row.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(actions_row, text="Select All", command=self.select_all_tributes).pack(side="left")
        ttk.Button(actions_row, text="Clear All", command=self.clear_checked_tributes).pack(side="left", padx=(8, 0))
        ttk.Button(actions_row, text="Edit Selected", command=self.edit_selected_tribute).pack(side="left", padx=(8, 0))
        ttk.Button(actions_row, text="Delete Selected Tribute(s)", command=self.delete_selected_tribute).pack(side="right")

        self.refresh_tribute_table()

    def load_tributes(self) -> list[dict]:
        return load_data()

    def on_tree_click(self, event):
        col = self.tribute_tree.identify_column(event.x)
        row = self.tribute_tree.identify_row(event.y)
        if col != "#1" or not row:
            return

        values = self.tribute_tree.item(row, "values")
        if not values or not values[1]:
            return

        slug = values[1]
        if slug in self.checked_slugs:
            self.checked_slugs.remove(slug)
        else:
            self.checked_slugs.add(slug)

        self.refresh_tribute_table()
        return "break"

    def refresh_tribute_table(self):
        for row in self.tribute_tree.get_children():
            self.tribute_tree.delete(row)

        tributes = self.load_tributes()
        valid_slugs = {t.get("slug", "") for t in tributes if t.get("slug")}
        self.checked_slugs = {s for s in self.checked_slugs if s in valid_slugs}
        for tribute in tributes:
            slug = tribute.get("slug", "")
            is_checked = slug in self.checked_slugs
            self.tribute_tree.insert(
                "",
                "end",
                values=(
                    "☑" if is_checked else "☐",
                    slug,
                    tribute.get("pet_name", ""),
                    tribute.get("published_iso", tribute.get("published_date", "")),
                ),
            )

    def select_all_tributes(self):
        tributes = self.load_tributes()
        self.checked_slugs = {t.get("slug", "") for t in tributes if t.get("slug")}
        self.refresh_tribute_table()

    def clear_checked_tributes(self):
        self.checked_slugs.clear()
        self.refresh_tribute_table()

    def edit_selected_tribute(self):
        slugs = sorted(self.checked_slugs)
        if len(slugs) != 1:
            messagebox.showwarning("Select One", "Please check exactly one tribute to edit.")
            return

        slug = slugs[0]
        tributes = self.load_tributes()
        entry = next((t for t in tributes if t.get("slug") == slug), None)
        if not entry:
            messagebox.showerror("Not Found", f'Could not find tribute "{slug}" in data.json.')
            return

        # Load full tribute body text (not just card excerpt) for editing.
        full_tribute_message = ""
        try:
            tribute_folder = find_tribute_folder(slug, entry.get("folder", ""))
            index_path = os.path.join(tribute_folder, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    existing_html = f.read()
                msg_match = re.search(
                    r'<div class="mm-tribute-message(?:\s+mm-tribute-message-centered)?"(?:\s+style="[^"]*")?\s*>\s*(.*?)\s*</div>',
                    existing_html,
                    flags=re.S,
                )
                if msg_match:
                    full_tribute_message = tribute_message_html_to_text((msg_match.group(1) or "").strip())
        except Exception:
            full_tribute_message = ""
        if not full_tribute_message:
            full_tribute_message = (entry.get("excerpt") or "").strip()
        self.last_tribute_url = f"{SITE_DOMAIN}{get_entry_web_base(entry)}"
        self.last_email = (entry.get("email") or "").strip()
        self.last_first_name = (entry.get("first_name") or "").strip()
        self.refresh_email_button_state()

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Tribute — {slug}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("1240x820")
        dialog.minsize(1120, 740)

        pad = {"padx": 10, "pady": 6}
        row = 0

        tk.Label(dialog, text="Slug").grid(row=row, column=0, sticky="w", **pad)
        tk.Label(dialog, text=slug, fg="#444").grid(row=row, column=1, sticky="w", **pad)
        row += 1

        widgets = {}
        selected_uploads = {"image_filename": "", "image2_filename": ""}
        image1_display = tk.StringVar(value=(entry.get("image_filename") or ""))
        image2_display = tk.StringVar(value=(entry.get("image2_filename") or ""))

        def choose_image_for_field(field_key: str):
            path = filedialog.askopenfilename(
                title="Select replacement image",
                filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.heic *.bmp"), ("All files", "*.*")]
            )
            if not path:
                return
            selected_uploads[field_key] = path
            if field_key == "image_filename":
                image1_display.set(os.path.basename(path))
            elif field_key == "image2_filename":
                image2_display.set(os.path.basename(path))

        def clear_image_field(field_key: str):
            selected_uploads[field_key] = ""
            if field_key == "image_filename":
                image1_display.set("")
            elif field_key == "image2_filename":
                image2_display.set("")

        tk.Label(dialog, text="Pet Name *").grid(row=row, column=0, sticky="w", **pad)
        widgets["pet_name"] = tk.Entry(dialog, width=48)
        widgets["pet_name"].insert(0, str(entry.get("pet_name", "") or ""))
        widgets["pet_name"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="Pet Type (optional)").grid(row=row, column=0, sticky="w", **pad)
        widgets["pet_type"] = tk.Entry(dialog, width=48)
        widgets["pet_type"].insert(0, str(entry.get("pet_type", "") or ""))
        widgets["pet_type"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="Breed (optional)").grid(row=row, column=0, sticky="w", **pad)
        widgets["breed"] = tk.Entry(dialog, width=48)
        widgets["breed"].insert(0, str(entry.get("breed", "") or ""))
        widgets["breed"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="Dates of Life (optional, any format)").grid(row=row, column=0, sticky="w", **pad)
        widgets["years_pretty"] = tk.Entry(dialog, width=48)
        widgets["years_pretty"].insert(0, str(entry.get("years_pretty", "") or ""))
        widgets["years_pretty"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="Tribute Message *").grid(row=row, column=0, sticky="nw", **pad)
        text_frame = tk.Frame(dialog)
        text_frame.grid(row=row, column=1, sticky="w", **pad)
        widgets["excerpt"] = tk.Text(text_frame, width=62, height=12, wrap="word")
        widgets["excerpt"].pack(anchor="w")
        widgets["excerpt"].insert("1.0", full_tribute_message)
        tk.Label(
            dialog,
            text=self.formatting_guide_text,
            justify="left",
            fg="#666",
            font=("TkDefaultFont", 8),
            wraplength=300,
        ).grid(row=row, column=2, sticky="nw", padx=(8, 10), pady=6)
        row += 1

        tk.Label(dialog, text="Photo 1 (optional, recommended)").grid(row=row, column=0, sticky="w", **pad)
        img_row = tk.Frame(dialog)
        img_row.grid(row=row, column=1, sticky="w", **pad)
        tk.Label(img_row, textvariable=image1_display, width=34, anchor="w").pack(side="left")
        tk.Button(img_row, text="Choose…", command=lambda: choose_image_for_field("image_filename")).pack(side="left", padx=6)
        tk.Button(img_row, text="Clear", command=lambda: clear_image_field("image_filename")).pack(side="left")
        row += 1

        tk.Label(dialog, text="Photo 2 (optional)").grid(row=row, column=0, sticky="w", **pad)
        img2_row = tk.Frame(dialog)
        img2_row.grid(row=row, column=1, sticky="w", **pad)
        tk.Label(img2_row, textvariable=image2_display, width=34, anchor="w").pack(side="left")
        tk.Button(img2_row, text="Choose…", command=lambda: choose_image_for_field("image2_filename")).pack(side="left", padx=6)
        tk.Button(img2_row, text="Clear", command=lambda: clear_image_field("image2_filename")).pack(side="left")
        row += 1

        tk.Label(dialog, text="First Name (optional)").grid(row=row, column=0, sticky="w", **pad)
        widgets["first_name"] = tk.Entry(dialog, width=48)
        widgets["first_name"].insert(0, str(entry.get("first_name", "") or ""))
        widgets["first_name"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="State (optional)").grid(row=row, column=0, sticky="w", **pad)
        widgets["state"] = tk.Entry(dialog, width=48)
        widgets["state"].insert(0, str(entry.get("state", "") or ""))
        widgets["state"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(dialog, text="Email (optional)").grid(row=row, column=0, sticky="w", **pad)
        widgets["email"] = tk.Entry(dialog, width=48)
        widgets["email"].insert(0, str(entry.get("email", "") or ""))
        widgets["email"].grid(row=row, column=1, sticky="w", **pad)
        row += 1

        edit_email_sent_var = tk.BooleanVar(value=(entry.get("email_sent") is True))
        widgets["email_sent_var"] = edit_email_sent_var
        tk.Checkbutton(
            dialog,
            text="Tribute Published (Email Sent)",
            variable=edit_email_sent_var,
            onvalue=True,
            offvalue=False,
        ).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        def resolve_image_field(field_key: str, output_filename: str, label: str):
            value = image1_display.get().strip() if field_key == "image_filename" else image2_display.get().strip()
            chosen_upload = (selected_uploads.get(field_key) or "").strip()

            # Explicit upload choice always wins for this field.
            # This prevents Image 2 from ever being inferred from Image 1.
            if chosen_upload:
                if not os.path.isfile(chosen_upload):
                    messagebox.showerror("Validation", f"{label} upload not found:\n{chosen_upload}")
                    return None
                if not ensure_pillow():
                    messagebox.showerror(
                        "Pillow not installed",
                        "Image conversion requires Pillow.\n\nRun:\n  py -m pip install pillow"
                    )
                    return None
                tribute_folder = find_tribute_folder(slug, entry.get("folder", ""))
                safe_mkdir(tribute_folder)
                output_path = os.path.join(tribute_folder, output_filename)
                try:
                    info = convert_to_webp_normalized(
                        chosen_upload,
                        output_path,
                        max_width=MAX_IMAGE_WIDTH,
                        quality=WEBP_QUALITY,
                    )
                    print(f"[edit-{field_key}] {info}")
                except Exception as e:
                    messagebox.showerror("Image conversion failed", f"Could not convert {label}:\n{e}")
                    return None
                return output_filename

            if not value:
                return ""

            # If user selected a local file, convert it and store the normalized tribute filename.
            if os.path.isfile(value):
                if not ensure_pillow():
                    messagebox.showerror(
                        "Pillow not installed",
                        "Image conversion requires Pillow.\n\nRun:\n  py -m pip install pillow"
                    )
                    return None

                tribute_folder = find_tribute_folder(slug, entry.get("folder", ""))
                safe_mkdir(tribute_folder)
                output_path = os.path.join(tribute_folder, output_filename)
                try:
                    info = convert_to_webp_normalized(
                        value,
                        output_path,
                        max_width=MAX_IMAGE_WIDTH,
                        quality=WEBP_QUALITY,
                    )
                    print(f"[edit-{field_key}] {info}")
                except Exception as e:
                    messagebox.showerror("Image conversion failed", f"Could not convert {label}:\n{e}")
                    return None
                return output_filename

            looks_like_path = ("/" in value) or ("\\" in value) or bool(re.match(r"^[A-Za-z]:", value))
            if looks_like_path:
                messagebox.showerror("Validation", f"{label} path not found:\n{value}")
                return None

            return value

        def on_save():
            pet_name = widgets["pet_name"].get().strip()
            edited_tribute_message = widgets["excerpt"].get("1.0", "end").strip()
            if not pet_name:
                messagebox.showerror("Validation", "Pet Name is required.")
                return
            if not edited_tribute_message:
                messagebox.showerror("Validation", "Tribute Message is required.")
                return

            entry["pet_name"] = pet_name
            entry["pet_type"] = widgets["pet_type"].get().strip()
            entry["breed"] = widgets["breed"].get().strip()
            entry["years_pretty"] = widgets["years_pretty"].get().strip()
            entry["first_name"] = widgets["first_name"].get().strip()
            entry["state"] = widgets["state"].get().strip()
            entry["email"] = widgets["email"].get().strip()
            entry["email_sent"] = widgets["email_sent_var"].get() is True
            entry["excerpt"] = summarize_excerpt(strip_markdown_for_excerpt(edited_tribute_message))

            image1_filename = resolve_image_field("image_filename", f"{slug}.webp", "Image 1")
            if image1_filename is None:
                return
            if not image1_filename:
                messagebox.showerror("Validation", "Image Filename is required.")
                return

            image2_filename = resolve_image_field("image2_filename", f"{slug}-2.webp", "Image 2")
            if image2_filename is None:
                return

            entry["image_filename"] = image1_filename
            entry["image2_filename"] = image2_filename
            entry["years_pretty"] = normalize_dates_text(entry.get("years_pretty", ""))
            self.last_tribute_url = f"{SITE_DOMAIN}{get_entry_web_base(entry)}"
            self.last_email = entry.get("email", "").strip()
            self.last_first_name = entry.get("first_name", "").strip()
            self.refresh_email_button_state()

            save_data(tributes)
            rebuild_single_tribute_page(entry, tribute_message_override=edited_tribute_message)
            rebuild_archive_pages(tributes)
            rebuild_pet_type_archives(tributes)
            generate_sitemap(tributes)
            self.refresh_tribute_table()
            messagebox.showinfo("Saved", f'Updated tribute "{slug}".')
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.grid(row=row, column=0, columnspan=3, sticky="e", padx=10, pady=(8, 10))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(btn_row, text="Send Publish Email", command=self.send_publish_email).pack(side="right", padx=(0, 8))
        ttk.Button(btn_row, text="Save Changes", command=on_save).pack(side="right", padx=(0, 8))

    def delete_selected_tribute(self):
        slugs = sorted(self.checked_slugs)
        if not slugs:
            messagebox.showwarning("No Selection", "Please check one or more tributes to delete.")
            return

        confirm = simpledialog.askstring(
            "Confirm Delete",
            f'Type DELETE to permanently remove {len(slugs)} tribute(s)'
        )
        if confirm != "DELETE":
            return

        for slug in slugs:
            entry = next((t for t in self.load_tributes() if t.get("slug") == slug), {})
            tribute_folder = find_tribute_folder(slug, entry.get("folder", ""))
            if os.path.exists(tribute_folder):
                shutil.rmtree(tribute_folder, ignore_errors=True)

        tributes = self.load_tributes()
        tributes = [t for t in tributes if t.get("slug") not in slugs]
        save_data(tributes)
        rebuild_archive_pages(tributes)
        rebuild_pet_type_archives(tributes)
        generate_sitemap(tributes)
        self.checked_slugs.clear()
        self.refresh_tribute_table()

        messagebox.showinfo("Deleted", f"Permanently deleted {len(slugs)} tribute(s) and rebuilt archive.")

    def choose_image(self):
        path = filedialog.askopenfilename(
            title="Select tribute photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.heic *.bmp"), ("All files", "*.*")]
        )
        if path:
            self.image_path.set(path)

    def choose_image2(self):
        path = filedialog.askopenfilename(
            title="Select tribute photo (Image 2)",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.heic *.bmp"), ("All files", "*.*")]
        )
        if path:
            self.image2_path.set(path)

    def clear_image(self):
        self.image_path.set("")

    def clear_image2(self):
        self.image2_path.set("")

    def mark_email_sent_true(self):
        tribute_url = (getattr(self, "last_tribute_url", "") or "").strip()
        if not tribute_url:
            return

        entries = load_data()
        updated = False
        for entry in entries:
            candidate_url = f"{SITE_DOMAIN}{get_entry_web_base(entry)}"
            if candidate_url == tribute_url:
                entry["email_sent"] = True
                updated = True
                break

        if updated:
            save_data(entries)
            self.refresh_tribute_table()

    def send_publish_email(self):
        email = (getattr(self, "last_email", "") or "").strip()
        first_name = (getattr(self, "last_first_name", "") or "there").strip()
        tribute_url = (getattr(self, "last_tribute_url", "") or "").strip()

        if not email or not tribute_url:
            messagebox.showwarning("Cannot send email", "Missing customer email or tribute URL.")
            return

        smtp_server = "mail.privateemail.com"
        smtp_port = 465
        sender_email = "rodney@meltonmemorials.com"
        password = os.environ.get("MM_EMAIL_PASS")

        if not password:
            messagebox.showerror("Missing Password", "Environment variable MM_EMAIL_PASS not set.")
            return

        msg = EmailMessage()
        msg["Subject"] = "Your tribute has been published"
        msg["From"] = sender_email
        msg["To"] = email

        msg.set_content(f"""
Hi {first_name},

Your pet’s tribute has now been published.

View the tribute here:
{tribute_url}

With respect,
Melton Memorials
Alma, Arkansas
""")

        msg.add_alternative(f"""
<html>
  <body>
    <p>Hi {first_name},</p>
    <p>Your pet’s tribute has now been published.</p>
    <p><a href="{tribute_url}">Click here to view the tribute</a></p>
    <p>With respect,<br>
    Melton Memorials<br>
    Alma, Arkansas</p>
  </body>
</html>
""", subtype="html")

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                server.login(sender_email, password)
                server.send_message(msg)

            messagebox.showinfo("Success", "Publish email sent successfully.")
            self.mark_email_sent_true()

        except Exception as e:
            messagebox.showerror("Email Failed", str(e))

    def refresh_email_button_state(self):
        email = (getattr(self, "last_email", "") or "").strip()
        tribute_url = (getattr(self, "last_tribute_url", "") or "").strip()
        state = "normal" if (email and tribute_url) else "disabled"
        if hasattr(self, "open_email_btn"):
            self.open_email_btn.config(state=state)

    def generate(self):
        pet_name = self.pet_name.get().strip()
        pet_type = self.pet_type.get().strip()
        first_name = self.first_name.get().strip()
        state = self.state.get().strip()
        email = self.email.get().strip()
        email_sent = self.email_sent_var.get() is True
        breed = self.breed.get().strip()
        years_raw = self.years.get().strip()
        tribute_msg = self.message.get("1.0", "end").strip()

        if not pet_name or not tribute_msg:
            messagebox.showerror("Missing required fields", "Pet Name and Tribute Message are required.")
            return

        years_pretty = normalize_dates_text(years_raw)

        # Slug rules (new tributes only): pet-name + optional type + optional breed.
        # If a slug already exists in data.json, append -2, -3, etc.
        pet_slug = slugify(pet_name)
        type_slug = slugify(pet_type)
        breed_slug = slugify(breed)
        slug_parts = [p for p in [pet_slug, type_slug] if p]
        if breed_slug:
            slug_parts.append(breed_slug)
        base_slug = "-".join(slug_parts).strip("-")
        if not base_slug:
            base_slug = pet_slug

        existing_entries = load_data()
        existing_slugs = {item.get("slug", "") for item in existing_entries if item.get("slug")}
        folder_slug = base_slug
        counter = 2
        while folder_slug in existing_slugs:
            folder_slug = f"{base_slug}-{counter}"
            counter += 1

        tribute_folder = os.path.join(MEMORIALS_DIR, folder_slug)
        safe_mkdir(tribute_folder)
        tribute_web_path = f"/pet-tributes/memorials/{folder_slug}/"

        # Decide image output name (inside folder)
        img_abs_url = ""
        img_filename = None
        img2_filename = ""

        chosen_image = self.image_path.get().strip()
        # Determine if user uploaded image 1
        user_uploaded_image = bool(chosen_image)
        if chosen_image:
            if not ensure_pillow():
                messagebox.showerror(
                    "Pillow not installed",
                    "Image conversion requires Pillow.\n\nRun:\n  py -m pip install pillow"
                )
                return

            img_filename = f"{folder_slug}.webp"
            img_dest = os.path.join(tribute_folder, img_filename)

            try:
                info = convert_to_webp_normalized(
                    chosen_image,
                    img_dest,
                    max_width=MAX_IMAGE_WIDTH,
                    quality=WEBP_QUALITY,
                )
                print(f"[image] {info}")
            except Exception as e:
                messagebox.showerror("Image conversion failed", f"Could not convert image to .webp:\n{e}")
                return

            img_abs_url = f"{SITE_DOMAIN}{tribute_web_path}{img_filename}"
        else:
            # No upload provided for image 1: copy placeholder into tribute folder and name by slug.
            if not os.path.exists(PLACEHOLDER_IMAGE_FILE):
                messagebox.showerror(
                    "Placeholder missing",
                    f"Default image not found:\n{PLACEHOLDER_IMAGE_FILE}"
                )
                return
            img_filename = f"{folder_slug}.webp"
            img_dest = os.path.join(tribute_folder, img_filename)
            try:
                process_placeholder_image(PLACEHOLDER_IMAGE_FILE, img_dest)
            except Exception as e:
                messagebox.showerror("Placeholder processing failed", f"Could not prepare fallback image:\n{e}")
                return
            img_abs_url = f"{SITE_DOMAIN}{tribute_web_path}{img_filename}"

        chosen_image2 = self.image2_path.get().strip()
        if chosen_image2:
            if not ensure_pillow():
                messagebox.showerror(
                    "Pillow not installed",
                    "Image conversion requires Pillow.\n\nRun:\n  py -m pip install pillow"
                )
                return
            img2_filename = f"{folder_slug}-2.webp"
            img2_dest = os.path.join(tribute_folder, img2_filename)
            try:
                info2 = convert_to_webp_normalized(
                    chosen_image2,
                    img2_dest,
                    max_width=MAX_IMAGE_WIDTH,
                    quality=WEBP_QUALITY,
                )
                print(f"[image2] {info2}")
            except Exception as e:
                messagebox.showerror("Image 2 conversion failed", f"Could not convert second image to .webp:\n{e}")
                return

        # Build tribute page values
        publish_date_iso = datetime.now().isoformat(timespec="seconds")
        page_url = f"{SITE_DOMAIN}{tribute_web_path}"
        excerpt = summarize_excerpt(strip_markdown_for_excerpt(tribute_msg))

        # Convert limited markdown into safe HTML.
        tribute_message_html = parse_safe_markdown(tribute_msg)

        tribute_html = build_tribute_html(
            pet_name=pet_name,
            first_name=first_name,
            state=state,
            breed=breed,
            pet_type=pet_type,
            years_pretty=years_pretty,
            excerpt=excerpt,
            page_url=page_url,
            tribute_web_path=tribute_web_path,
            og_image_abs=img_abs_url,
            user_uploaded_image=user_uploaded_image,
            second_image_filename=img2_filename,
            publish_date_iso=publish_date_iso,
            tribute_message_html=tribute_message_html,
        )

        if tribute_html is None:
            raise RuntimeError("build_tribute_html returned None")

        if not isinstance(tribute_html, str):
            raise RuntimeError(f"build_tribute_html returned unexpected type: {type(tribute_html)}")

        index_path = os.path.join(tribute_folder, "index.html")

        try:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(tribute_html)
        except Exception as e:
            raise RuntimeError(f"Failed to write index.html: {e}")

        if not os.path.exists(index_path):
            raise RuntimeError("index.html was not created after write attempt")

        # ---- JSON-backed archive update + rebuild ----
        entries = existing_entries

        published_iso = datetime.now().isoformat(timespec="seconds")

        # if user didn't pick an image, we still create a card, but image_filename must exist for cards
        # (recommend: require image for now, OR set to placeholder filename)
        image_filename = img_filename if img_filename else ""

        entry = {
            "slug": folder_slug,
            "pet_name": pet_name,
            "breed": breed,
            "pet_type": pet_type,
            "folder": "memorials",
            "years_pretty": years_pretty,
            "excerpt": excerpt,
            "first_name": first_name,
            "state": state,
            "email": email,
            "published_iso": published_iso,
            "image_filename": image_filename,
            "image2_filename": img2_filename,
            "featured": False,
            "email_sent": email_sent,
        }

        # prevent duplicates by slug
        entries = [e for e in entries if e.get("slug") != folder_slug]
        entries.append(entry)

        save_data(entries)
        rebuild_archive_pages(entries)
        rebuild_pet_type_archives(entries)
        generate_sitemap(entries)
        self.refresh_tribute_table()

        self.last_tribute_url = page_url
        self.last_email = email
        self.last_first_name = first_name
        self.refresh_email_button_state()
        messagebox.showinfo(
            "Tribute Created Successfully",
            f"Created locally at:\n\n"
            f"{tribute_folder}\n\n"
            f"To publish live:\n"
            f"Upload the contents of:\n"
            f"{TRIBUTES_DIR}\n"
            f"to your server's /pet-tributes/ directory."
        )


def main():
    safe_mkdir(TRIBUTES_DIR)
    root = tk.Tk()
    app = TributePublisherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
