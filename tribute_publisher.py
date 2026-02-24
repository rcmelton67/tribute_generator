print("RUNNING UPDATED SCRIPT")

import os
import re
import shutil
import json
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

# ----------------------------
# CONFIG (edit if needed)
# ----------------------------
SITE_DOMAIN = "https://meltonmemorials.com"

# ----------------------------
# PATHS (self-contained)
# ----------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
OUTPUT_ROOT = os.path.join(PROJECT_ROOT, "output")
TRIBUTES_DIR = os.path.join(OUTPUT_ROOT, "pet-tributes")

ARCHIVE_INDEX = os.path.join(TRIBUTES_DIR, "index.html")
ARCHIVE_DATA = os.path.join(TRIBUTES_DIR, "data.json")
CARDS_PER_PAGE = 15

# CSS path used by the generated tribute pages (adjust if your live path differs)
TRIBUTE_CSS_HREF = "/pet-tributes/assets/mm-tribute.css"

# If no image is selected, we can fall back to a placeholder image URL (optional).
# Put a real file at this location later if you want:
PLACEHOLDER_IMAGE_URL = f"{SITE_DOMAIN}/pet-tributes/assets/blank-stone.webp"


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


def safe_mkdir(path: str):
    os.makedirs(path, exist_ok=True)


def ensure_pillow():
    try:
        from PIL import Image  # noqa
        return True
    except Exception:
        return False


def convert_to_webp_normalized(src_path: str, dest_path: str, max_width: int = 1200, quality: int = 82) -> dict:
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
    with open(ARCHIVE_DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(items: list[dict]):
    # keep it readable + stable
    with open(ARCHIVE_DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def sort_entries_newest_first(items: list[dict]) -> list[dict]:
    # ISO dates sort lexicographically when consistent
    return sorted(items, key=lambda x: x.get("published_iso", ""), reverse=True)


def build_card_html(entry: dict) -> str:
    pet_name = entry.get("pet_name", "")
    breed = entry.get("breed", "")
    years_pretty = entry.get("years_pretty", "")
    excerpt = entry.get("excerpt", "")
    slug = entry.get("slug", "")
    image_filename = entry.get("image_filename", "")
    publish_label = ""
    if entry.get("published_iso"):
        dt = datetime.strptime(entry["published_iso"], "%Y-%m-%d")
        publish_label = dt.strftime("%b %Y")
    first_name = (entry.get("first_name") or "").strip()
    state = (entry.get("state") or "").strip()

    attribution_html = ""
    if first_name or state:
        parts = [p for p in [first_name, state] if p]
        attribution_html = f'<div class="mm-archive-attribution">{escape_html(", ".join(parts))}</div>'

    title_line = escape_html(pet_name + (f" – {breed}" if breed else ""))

    return f"""
<article class="mm-archive-card"
  data-name="{escape_html(pet_name)}"
  data-breed="{escape_html(breed)}"
  data-years="{escape_html(years_pretty)}"
  data-content="{escape_html(excerpt)}"
>
  <a class="mm-archive-link" href="/pet-tributes/{slug}/">
    <div class="mm-archive-thumb">
      <span class="mm-date-badge">{escape_html(publish_label)}</span>
      <img src="/pet-tributes/{slug}/{escape_html(image_filename)}" alt="{escape_html(pet_name)} memorial tribute" loading="lazy">
    </div>
    <div class="mm-archive-meta">
      <h2 class="mm-archive-title">{title_line}</h2>
      <p class="mm-archive-excerpt">{escape_html(excerpt)}</p>
      <p class="mm-archive-years">{escape_html(years_pretty)}</p>
      {attribution_html}
    </div>
  </a>
</article>
""".strip()


def page_url(page_num: int) -> str:
    return "/pet-tributes/" if page_num == 1 else f"/pet-tributes/page-{page_num}/"


def css_href_for_page(page_num: int) -> str:
    # Always use absolute path for live site stability
    return "/pet-tributes/assets/mm-tribute.css"


def build_pagination(current: int, total: int) -> str:
    if total <= 1:
        return ""

    parts = []

    if current > 1:
        parts.append(f'<a class="mm-page-arrow" href="{page_url(current-1)}">←</a>')

    for i in range(1, total + 1):
        active = "mm-page-active" if i == current else ""
        parts.append(f'<a class="mm-page-number {active}" href="{page_url(i)}">{i}</a>')

    if current < total:
        parts.append(f'<a class="mm-page-arrow" href="{page_url(current+1)}">→</a>')

    return f'<div class="mm-pagination">{" ".join(parts)}</div>'


def build_archive_full_html(cards_html: str, current_page: int, total_pages: int) -> str:
    title = "Pet Memorial Tributes" if current_page == 1 else f"Pet Memorial Tributes — Page {current_page}"
    canonical = SITE_DOMAIN + page_url(current_page)
    prev_link = SITE_DOMAIN + page_url(current_page - 1) if current_page > 1 else ""
    next_link = SITE_DOMAIN + page_url(current_page + 1) if current_page < total_pages else ""

    rel_links = []
    if prev_link:
        rel_links.append(f'<link rel="prev" href="{prev_link}">')
    if next_link:
        rel_links.append(f'<link rel="next" href="{next_link}">')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{escape_html(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{canonical}">
  {"".join(rel_links)}
  <link rel="stylesheet" href="{css_href_for_page(current_page)}">
</head>
<body>

<main class="memorials-hub">
  <div class="container text-center">

    <section class="memorials-hero">
      <div class="hero-header-row">
        <h1>Pet Memorial Tributes</h1>
        <div class="tribute-search-wrapper">
          <input type="text" id="tributeSearch" placeholder="Search tributes..." aria-label="Search tributes">
        </div>
      </div>

      <p>A public archive honoring beloved companions and the memories they leave behind.</p>

      <div class="mm-hero-cta">
        <a href="/submit-a-tribute/" class="mm-btn-primary">Create a Tribute</a>
      </div>
    </section>

    <div class="tribute-grid">
      {cards_html}
    </div>

    {build_pagination(current_page, total_pages)}

    <section class="mm-bottom-cta">
      <h3>Would you like to honor your beloved companion?</h3>
      <div class="mm-cta-buttons">
        <a href="/submit-a-tribute/" class="mm-btn-primary">Create a Tribute</a>
        <a href="/pet-tributes/" class="mm-btn-secondary">View All Memorials</a>
      </div>
    </section>

  </div>
</main>

<script>
document.addEventListener("DOMContentLoaded", function () {{
  const searchInput = document.getElementById("tributeSearch");
  if (!searchInput) return;

  searchInput.addEventListener("input", function () {{
    const query = this.value.toLowerCase().trim();
    const cards = document.querySelectorAll(".mm-archive-card");

    cards.forEach(card => {{
      const searchableText = (
        (card.dataset.name || "") + " " +
        (card.dataset.breed || "") + " " +
        (card.dataset.years || "") + " " +
        (card.dataset.content || "")
      ).toLowerCase();

      card.style.display = searchableText.includes(query) ? "" : "none";
    }});
  }});
}});
</script>

</body>
</html>"""


def rebuild_archive_pages(entries):
    from math import ceil

    CARDS_PER_PAGE = 15

    # Sort newest first
    entries = sorted(entries, key=lambda x: x.get("published_iso", ""), reverse=True)

    total_pages = ceil(len(entries) / CARDS_PER_PAGE)

    for page_num in range(1, total_pages + 1):

        start = (page_num - 1) * CARDS_PER_PAGE
        end = start + CARDS_PER_PAGE
        page_entries = entries[start:end]

        cards_html = ""

        for entry in page_entries:
            publish_label = ""
            if entry.get("published_iso"):
                from datetime import datetime
                dt = datetime.strptime(entry["published_iso"], "%Y-%m-%d")
                publish_label = dt.strftime("%b %Y")

            attribution = ""
            if entry.get("first_name") or entry.get("state"):
                parts = [p for p in [entry.get("first_name"), entry.get("state")] if p]
                attribution = f'<div class="mm-archive-attribution">{", ".join(parts)}</div>'

            cards_html += f"""
<article class="mm-archive-card">
  <a class="mm-archive-link" href="/pet-tributes/{entry["slug"]}/">
    <div class="mm-archive-thumb">
      <span class="mm-date-badge">{publish_label}</span>
      <img src="/pet-tributes/{entry["slug"]}/{entry["image_filename"]}" alt="{entry["pet_name"]} memorial tribute">
    </div>
    <div class="mm-archive-meta">
      <h2 class="mm-archive-title">{entry["pet_name"]} – {entry["breed"]}</h2>
      <p class="mm-archive-excerpt">{entry["excerpt"]}</p>
      <p class="mm-archive-years">{entry["years_pretty"]}</p>
      {attribution}
    </div>
  </a>
</article>
"""

        # Build pagination
        pagination_html = '<div class="mm-pagination">'

        if page_num > 1:
            prev_link = "index.html" if page_num - 1 == 1 else f"page-{page_num-1}/index.html"
            pagination_html += f'<a href="../{prev_link}">←</a>'

        for p in range(1, total_pages + 1):
            if p == page_num:
                pagination_html += f'<a class="active">{p}</a>'
            else:
                link = "index.html" if p == 1 else f"page-{p}/index.html"
                prefix = "" if page_num == 1 else "../"
                pagination_html += f'<a href="{prefix}{link}">{p}</a>'

        if page_num < total_pages:
            next_link = f"page-{page_num+1}/index.html"
            pagination_html += f'<a href="{next_link}">→</a>'

        pagination_html += "</div>"

        # Write page
        if page_num == 1:
            page_path = os.path.join(TRIBUTES_DIR, "index.html")
        else:
            page_folder = os.path.join(TRIBUTES_DIR, f"page-{page_num}")
            os.makedirs(page_folder, exist_ok=True)
            page_path = os.path.join(page_folder, "index.html")

        with open(page_path, "w", encoding="utf-8") as f:
            f.write(build_archive_full_html(cards_html, page_num, total_pages))


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
            "image_filename": image_filename
        })

    save_data(entries)
    rebuild_archive_pages(entries)


def build_tribute_html(
    pet_name: str,
    first_name: str,
    state: str,
    breed: str,
    years_pretty: str,
    excerpt: str,
    page_url: str,
    og_image_abs: str,
    publish_date_iso: str,
    tribute_message_html: str,
) -> str:
    # Title / subtitle logic
    breed_clean = (breed or "").strip()
    if breed_clean:
        title = f"{pet_name} – {breed_clean} Memorial Tribute"
        subtitle = f"{breed_clean} Memorial Tribute"
        og_desc = excerpt or f"Read the memorial tribute honoring {pet_name}."
    else:
        title = f"{pet_name} – Memorial Tribute"
        subtitle = "Memorial Tribute"
        og_desc = excerpt or f"Read the memorial tribute honoring {pet_name}."

    # Keep meta description under ~160-ish when possible
    meta_desc = excerpt if excerpt else f"A memorial tribute honoring {pet_name}."
    if len(meta_desc) > 165:
        meta_desc = meta_desc[:162].rstrip() + "…"

    submitter_parts = [p for p in [first_name.strip(), state.strip()] if p]
    submitter_line = ", ".join(submitter_parts)
    submitter_html = f'<p class="mm-tribute-origin">Shared by {escape_html(submitter_line)}</p>' if submitter_line else ""

    base = load_template("base.html")
    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="description" content="{escape_html(meta_desc)}">
  <link rel="canonical" href="{page_url}">
  <meta name="robots" content="index, follow">
  <meta name="date" content="{publish_date_iso}">

  <!-- Open Graph -->
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Melton Memorials">
  <meta property="og:title" content="{escape_html(title)}">
  <meta property="og:description" content="{escape_html(og_desc)}">
  <meta property="og:url" content="{page_url}">
  <meta property="og:image" content="{og_image_abs}">
  <meta property="article:published_time" content="{publish_date_iso}">

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{escape_html(title)}">
  <meta name="twitter:description" content="{escape_html(og_desc)}">
  <meta name="twitter:image" content="{og_image_abs}">
  <link rel="stylesheet" href="{TRIBUTE_CSS_HREF}">
""".strip()
    content = load_template("tribute_content.html")

    # Inject tribute values
    content = content.replace("{{PET_NAME}}", escape_html(pet_name))
    content = content.replace("{{SUBTITLE}}", escape_html(subtitle))
    content = content.replace("{{IMAGE_SRC}}", relative_filename_from_url(og_image_abs))
    content = content.replace("{{TRIBUTE_MESSAGE}}", tribute_message_html)
    content = content.replace("{{YEARS}}", escape_html(years_pretty))
    content = content.replace("{{SUBMITTER_LINE}}", submitter_html)

    # Placeholder header/footer (future use)
    header_html = ""
    footer_html = ""

    # Assemble final page
    final_html = base.replace("{{HEAD_META}}", head_meta)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{FOOTER}}", footer_html)
    final_html = final_html.replace("{{CONTENT}}", content)

    return final_html
    content = f"""
  <div class="mm-tribute-system">
    <div class="mm-tribute-wrapper">
      <p class="mm-memorial-line">In Loving Memory of</p>

      <h1 class="mm-tribute-name">{escape_html(pet_name)}</h1>

      <p class="mm-tribute-subtitle">{escape_html(subtitle)}</p>

      <div class="mm-tribute-divider"></div>

      <img src="{escape_html(relative_filename_from_url(og_image_abs))}"
           alt="{escape_html(pet_name)} memorial tribute photo"
           style="max-width:100%; height:auto; display:block; margin: 1rem 0; border-radius: 10px;">

      <div class="mm-tribute-body">
        <div class="mm-tribute-message">
          {tribute_message_html}
        </div>
      </div>

      <p class="mm-years">{escape_html(years_pretty)}</p>
      {submitter_html}

      <div class="mm-tribute-share" aria-label="Share this tribute">
        <p class="mm-share-label">Share this memory</p>
        <div class="mm-share-icons">
          <a class="mm-share-icon"
             href="https://www.facebook.com/sharer/sharer.php?u={page_url}"
             target="_blank" rel="noopener" aria-label="Share on Facebook">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M22 12a10 10 0 1 0-11.6 9.9v-7H7.9v-2.9h2.5V9.8c0-2.5 1.5-3.9 3.7-3.9 1.1 0 2.2.2 2.2.2v2.4h-1.2c-1.2 0-1.6.8-1.6 1.5v1.8h2.8l-.4 2.9h-2.4v7A10 10 0 0 0 22 12z"></path>
            </svg>
          </a>

          <a class="mm-share-icon"
             href="https://pinterest.com/pin/create/button/?url={page_url}&media={og_image_abs}&description={escape_url(excerpt or '')}"
             target="_blank" rel="noopener" aria-label="Share on Pinterest">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M12.017 0C5.396 0 .029 5.367.029 11.987c0 5.079 3.158 9.417 7.618 11.162-.105-.949-.199-2.403.041-3.439.219-.937 1.406-5.957 1.406-5.957s-.359-.72-.359-1.781c0-1.663.967-2.911 2.168-2.911 1.024 0 1.518.769 1.518 1.688 0 1.029-.653 2.567-.992 3.992-.285 1.193.6 2.165 1.775 2.165 2.128 0 3.768-2.245 3.768-5.487 0-2.861-2.063-4.869-5.008-4.869-3.646 0-5.781 2.731-5.781 5.551 0 1.096.422 2.28 1.081 2.979.12.126.137.237.1.424-.13.522-.419 1.694-.476 1.929-.076.317-.253.385-.584.233-2.172-1.008-3.525-4.197-3.525-6.76 0-5.506 4.01-10.58 11.564-10.58 6.071 0 10.785 4.323 10.785 10.111 0 6.033-3.8 10.89-9.073 10.89-1.776 0-3.447-.92-4.018-2.012 0 0-.961 3.657-1.192 4.543-.432 1.66-1.597 3.743-2.378 5.011 1.791.529 3.693.817 5.655.817 6.619 0 11.988-5.367 11.988-11.987C24.005 5.367 18.636 0 12.017 0z"></path>
            </svg>
          </a>

          <a class="mm-share-icon"
             href="mailto:?subject=Memorial Tribute&body={page_url}"
             aria-label="Share by Email">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4-8 5L4 8V6l8 5 8-5v2z"></path>
            </svg>
          </a>
        </div>
      </div>

      <div class="mm-tribute-cta">
        <a href="{SITE_DOMAIN}/shop/" class="mm-btn">Explore Memorial Stones →</a>
      </div>
    </div>
  </div>

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "mainEntityOfPage": {{
      "@type": "WebPage",
      "@id": "{page_url}"
    }},
    "headline": "{escape_json(title)}",
    "image": ["{og_image_abs}"],
    "datePublished": "{publish_date_iso}",
    "dateModified": "{publish_date_iso}",
    "author": {{
      "@type": "Organization",
      "name": "Melton Memorials"
    }},
    "publisher": {{
      "@type": "Organization",
      "name": "Melton Memorials"
    }},
    "description": "{escape_json(meta_desc)}"
  }}
  </script>
</div>
""".strip()

    # Placeholder header/footer for future injection
    header_html = ""
    footer_html = ""

    final_html = base.replace("{{HEAD_META}}", head_meta)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{FOOTER}}", footer_html)
    final_html = final_html.replace("{{CONTENT}}", content)

    return final_html


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
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Melton Memorials — Tribute Publisher")

        self.image_path = tk.StringVar(value="")

        # layout
        pad = {"padx": 10, "pady": 6}

        tk.Label(root, text="Pet Name *").grid(row=0, column=0, sticky="w", **pad)
        self.pet_name = tk.Entry(root, width=44)
        self.pet_name.grid(row=0, column=1, sticky="w", **pad)

        tk.Label(root, text="First Name (optional)").grid(row=1, column=0, sticky="w", **pad)
        self.first_name = tk.Entry(root, width=44)
        self.first_name.grid(row=1, column=1, sticky="w", **pad)

        tk.Label(root, text="State (optional)").grid(row=2, column=0, sticky="w", **pad)
        self.state = tk.Entry(root, width=44)
        self.state.grid(row=2, column=1, sticky="w", **pad)

        tk.Label(root, text="Breed (optional)").grid(row=3, column=0, sticky="w", **pad)
        self.breed = tk.Entry(root, width=44)
        self.breed.grid(row=3, column=1, sticky="w", **pad)

        tk.Label(root, text="Dates of Life (optional, any format)").grid(row=4, column=0, sticky="w", **pad)
        self.years = tk.Entry(root, width=44)
        self.years.grid(row=4, column=1, sticky="w", **pad)

        tk.Label(root, text="Tribute Message *").grid(row=5, column=0, sticky="nw", **pad)
        self.message = tk.Text(root, width=44, height=8)
        self.message.grid(row=5, column=1, sticky="w", **pad)

        tk.Label(root, text="Photo (optional, recommended)").grid(row=6, column=0, sticky="w", **pad)

        img_row = tk.Frame(root)
        img_row.grid(row=6, column=1, sticky="w", **pad)

        self.img_label = tk.Label(img_row, textvariable=self.image_path, width=34, anchor="w")
        self.img_label.pack(side="left")

        tk.Button(img_row, text="Choose…", command=self.choose_image).pack(side="left", padx=6)
        tk.Button(img_row, text="Clear", command=self.clear_image).pack(side="left")

        tk.Button(root, text="Generate Tribute Files", command=self.generate, height=2, width=26)\
            .grid(row=7, column=1, sticky="w", padx=10, pady=14)

        tk.Label(
            root,
            text=f"Output: {TRIBUTES_DIR}\nArchive: {ARCHIVE_INDEX}",
            fg="#444"
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=10, pady=6)

    def choose_image(self):
        path = filedialog.askopenfilename(
            title="Select tribute photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.heic *.bmp"), ("All files", "*.*")]
        )
        if path:
            self.image_path.set(path)

    def clear_image(self):
        self.image_path.set("")

    def generate(self):
        pet_name = self.pet_name.get().strip()
        first_name = self.first_name.get().strip()
        state = self.state.get().strip()
        breed = self.breed.get().strip()
        years_raw = self.years.get().strip()
        tribute_msg = self.message.get("1.0", "end").strip()

        if not pet_name or not tribute_msg:
            messagebox.showerror("Missing required fields", "Pet Name and Tribute Message are required.")
            return

        years_pretty = years_raw.strip()

        # folder slug rules: pet-name + optional breed + optional extracted years
        base_parts = [slugify(pet_name)]
        if breed:
            base_parts.append(slugify(breed))

        # Try extracting 4-digit years for slug, but don't require them
        year_matches = re.findall(r"\d{4}", years_pretty)
        if len(year_matches) >= 2:
            base_parts.append(f"{year_matches[0]}-{year_matches[1]}")

        folder_slug = "-".join([p for p in base_parts if p])

        tribute_folder = os.path.join(TRIBUTES_DIR, folder_slug)
        safe_mkdir(tribute_folder)

        # Decide image output name (inside folder)
        img_abs_url = PLACEHOLDER_IMAGE_URL
        img_filename = None

        chosen_image = self.image_path.get().strip()
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
                info = convert_to_webp_normalized(chosen_image, img_dest, max_width=1200, quality=82)
                print(f"[image] {info}")
            except Exception as e:
                messagebox.showerror("Image conversion failed", f"Could not convert image to .webp:\n{e}")
                return

            img_abs_url = f"{SITE_DOMAIN}/pet-tributes/{folder_slug}/{img_filename}"

        # Build tribute page values
        publish_date_iso = datetime.now().strftime("%Y-%m-%d")
        page_url = f"{SITE_DOMAIN}/pet-tributes/{folder_slug}/"
        excerpt = first_sentence(tribute_msg)

        # Convert tribute message into HTML paragraphs
        tribute_message_html = "\n".join(
            f"<p>{escape_html(p.strip())}</p>"
            for p in re.split(r"\n\s*\n", tribute_msg)
            if p.strip()
        )

        tribute_html = build_tribute_html(
            pet_name=pet_name,
            first_name=first_name,
            state=state,
            breed=breed,
            years_pretty=years_pretty,
            excerpt=excerpt,
            page_url=page_url,
            og_image_abs=img_abs_url,
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
        entries = load_data()

        published_iso = datetime.now().strftime("%Y-%m-%d")

        # if user didn't pick an image, we still create a card, but image_filename must exist for cards
        # (recommend: require image for now, OR set to placeholder filename)
        image_filename = img_filename if img_filename else "blank-stone.webp"

        entry = {
            "slug": folder_slug,
            "pet_name": pet_name,
            "breed": breed,
            "years_pretty": years_pretty,
            "excerpt": excerpt,
            "first_name": first_name,
            "state": state,
            "published_iso": published_iso,
            "image_filename": image_filename,
        }

        # prevent duplicates by slug
        entries = [e for e in entries if e.get("slug") != folder_slug]
        entries.append(entry)

        save_data(entries)
        rebuild_archive_pages(entries)

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