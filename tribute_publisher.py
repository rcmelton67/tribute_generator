print("RUNNING UPDATED SCRIPT")

import os
import re
import shutil
import json
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

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

# CSS path used by the generated tribute pages (adjust if your live path differs)
TRIBUTE_CSS_HREF = "/pet-tributes/assets/mm-tribute.css"

# Placeholder source used when no image is uploaded.
PLACEHOLDER_IMAGE_FILE = os.path.join(TRIBUTES_DIR, "assets", "blank_pet_memorial.png")


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
    # Use utf-8-sig so BOM-prefixed JSON files still parse cleanly.
    with open(ARCHIVE_DATA, "r", encoding="utf-8-sig") as f:
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
    pet_type = (entry.get("pet_type") or "").strip()
    years_pretty = normalize_dates_text(entry.get("years_pretty", ""))
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

    subtitle_for_card = breed if breed else pet_type
    title_line = escape_html(pet_name + (f" – {subtitle_for_card}" if subtitle_for_card else ""))

    card_href = get_entry_web_base(entry)
    is_placeholder_card = (
        (not image_filename)
        or image_filename == "blank_pet_memorial.png"
        or image_filename == f"{slug}.png"
    )
    card_img_src = (
        "/pet-tributes/assets/blank_pet_memorial.png"
        if (not image_filename or image_filename == "blank_pet_memorial.png")
        else f"{card_href}{escape_html(image_filename)}"
    )
    card_thumb_class = "mm-archive-thumb mm-placeholder" if is_placeholder_card else "mm-archive-thumb"
    card_overlay_html = (
        f'<div class="mm-stone-name mm-stone-name-card">{escape_html(pet_name)}</div>'
        if is_placeholder_card else ""
    )

    return f"""
<article class="mm-archive-card"
  data-name="{escape_html(pet_name)}"
  data-breed="{escape_html(breed)}"
  data-years="{escape_html(years_pretty)}"
  data-content="{escape_html(excerpt)}"
>
  <a class="mm-archive-link" href="{card_href}">
    <div class="{card_thumb_class}">
      <span class="mm-date-badge">{escape_html(publish_label)}</span>
      <img src="{card_img_src}" alt="{escape_html(pet_name)} memorial tribute" loading="lazy">
      {card_overlay_html}
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

    # Load base + archive template
    base = load_template("base.html")
    archive_template = load_template("archive.html")

    # Build head meta
    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{canonical}">
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

def rebuild_archive_pages(entries):
    from math import ceil

    # Sort newest first
    entries = sorted(entries, key=lambda x: x.get("published_iso", ""), reverse=True)

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

        cards_html = ""
        for entry in page_entries:
            cards_html += build_card_html(entry)

        # Build full archive page via template system
        final_html = build_archive_full_html(cards_html, page_num, total_pages)

        # Determine path
        if page_num == 1:
            page_path = os.path.join(TRIBUTES_DIR, "index.html")
        else:
            page_folder = os.path.join(TRIBUTES_DIR, f"page-{page_num}")
            os.makedirs(page_folder, exist_ok=True)
            page_path = os.path.join(page_folder, "index.html")

        with open(page_path, "w", encoding="utf-8") as f:
            f.write(final_html)



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
    pet_type: str,
    years_pretty: str,
    excerpt: str,
    page_url: str,
    tribute_web_path: str,
    og_image_abs: str,
    is_placeholder_image: bool,
    second_image_filename: str,
    publish_date_iso: str,
    tribute_message_html: str,
) -> str:

    # ----- Title / subtitle logic -----
    breed_clean = (breed or "").strip()
    pet_type_clean = (pet_type or "").strip()
    if breed_clean:
        subtitle = f"{breed_clean} Memorial Tribute"
        title = f"{pet_name} – {subtitle} | Melton Memorials"
        og_desc = excerpt or f"Read the memorial tribute honoring {pet_name}."
    elif pet_type_clean:
        subtitle = f"{pet_type_clean} Memorial Tribute"
        title = f"{pet_name} – {subtitle} | Melton Memorials"
        og_desc = excerpt or f"Read the memorial tribute honoring {pet_name}."
    else:
        subtitle = "Pet Memorial Tribute"
        title = f"{pet_name} – Pet Memorial Tribute | Melton Memorials"
        og_desc = excerpt or f"Read the memorial tribute honoring {pet_name}."

    years_pretty = normalize_dates_text(years_pretty)
    plain_message = re.sub(r"<[^>]+>", " ", tribute_message_html or "")
    plain_message = re.sub(r"\s+", " ", plain_message).strip()
    og_description = plain_message[:160] if plain_message else (excerpt or f"A memorial tribute honoring {pet_name}.")
    meta_desc = og_description

    submitter_parts = [p for p in [first_name.strip(), state.strip()] if p]
    submitter_line = ", ".join(submitter_parts)

    breed_line = subtitle
    input_filename = os.path.basename(relative_filename_from_url(og_image_abs))
    is_placeholder = bool(is_placeholder_image) or (input_filename == "blank_pet_memorial.png")

    # Determine image file/path from provided URL filename. If empty, fall back to shared placeholder.
    if input_filename:
        image_filename = input_filename
        image_path = f"{tribute_web_path}{image_filename}"
        og_image = f"{SITE_DOMAIN}{tribute_web_path}{image_filename}"
    else:
        image_filename = "blank_pet_memorial.png"
        image_path = f"/pet-tributes/assets/{image_filename}"
        og_image = f"{SITE_DOMAIN}/pet-tributes/assets/{image_filename}"

    image_class = "mm-placeholder" if is_placeholder else ""
    second_image_filename = (second_image_filename or "").strip()
    image_alt = f"{pet_name} {pet_type_clean} memorial portrait".strip() if pet_type_clean else f"{pet_name} memorial portrait"
    image_2_block = ""
    if second_image_filename:
        image_2_block = (
            '<div class="mm-tribute-image mm-tribute-image-secondary">'
            f'<img src="{tribute_web_path}{escape_html(second_image_filename)}" alt="{escape_html(image_alt)} 2">'
            "</div>"
        )
    dates_block = f"<p>{escape_html(years_pretty)}</p>" if years_pretty.strip() else ""
    shared_block = f"<p>Shared by {escape_html(submitter_line)}</p>" if submitter_line else ""
    share_description = og_description.strip() if (og_description or "").strip() else f"Memorial tribute for {pet_name}"
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

    # ----- Load base template -----
    base = load_template("base.html")

    # ----- Build head meta -----
    head_meta = f"""
  <title>{escape_html(title)}</title>
  <meta name="description" content="{escape_html(meta_desc)}">
  <link rel="canonical" href="{page_url}">
  <meta name="robots" content="index, follow">
  <meta name="date" content="{publish_date_iso}">
  <meta name="twitter:title" content="{escape_html(title)}">
  <meta name="twitter:description" content="{escape_html(og_description)}">
  <meta name="twitter:image" content="{og_image}">
""".strip()

    # ----- Load tribute content template -----
    content = load_template("tribute_content.html")

    content = content.replace("{{PET_NAME}}", escape_html(pet_name))
    content = content.replace("{{BREED_LINE}}", escape_html(breed_line))
    content = content.replace("{{IMAGE_PATH}}", image_path)
    content = content.replace("{{IMAGE_ALT}}", escape_html(image_alt))
    content = content.replace("{{IMAGE_CLASS}}", image_class)
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
    final_html = final_html.replace("{{OG_DESCRIPTION}}", escape_html(og_description))
    final_html = final_html.replace("{{CANONICAL_URL}}", page_url)
    final_html = final_html.replace("{{OG_IMAGE}}", og_image)
    final_html = final_html.replace("{{PUBLISHED_TIME}}", publish_date_iso)
    final_html = final_html.replace("{{HEADER}}", header_html)
    final_html = final_html.replace("{{CONTENT}}", content)
    final_html = final_html.replace("{{FOOTER}}", footer_html)

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

        tk.Label(create_frame, text="Breed (optional)").grid(row=4, column=0, sticky="w", **pad)
        self.breed = tk.Entry(create_frame, width=44)
        self.breed.grid(row=4, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Dates of Life (optional, any format)").grid(row=5, column=0, sticky="w", **pad)
        self.years = tk.Entry(create_frame, width=44)
        self.years.grid(row=5, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Tribute Message *").grid(row=6, column=0, sticky="nw", **pad)
        self.message = tk.Text(create_frame, width=44, height=8)
        self.message.grid(row=6, column=1, sticky="w", **pad)

        tk.Label(create_frame, text="Photo 1 (optional, recommended)").grid(row=7, column=0, sticky="w", **pad)

        img_row = tk.Frame(create_frame)
        img_row.grid(row=7, column=1, sticky="w", **pad)

        self.img_label = tk.Label(img_row, textvariable=self.image_path, width=34, anchor="w")
        self.img_label.pack(side="left")

        tk.Button(img_row, text="Choose…", command=self.choose_image).pack(side="left", padx=6)
        tk.Button(img_row, text="Clear", command=self.clear_image).pack(side="left")

        tk.Label(create_frame, text="Photo 2 (optional)").grid(row=8, column=0, sticky="w", **pad)

        img2_row = tk.Frame(create_frame)
        img2_row.grid(row=8, column=1, sticky="w", **pad)

        self.img2_label = tk.Label(img2_row, textvariable=self.image2_path, width=34, anchor="w")
        self.img2_label.pack(side="left")
        tk.Button(img2_row, text="Choose…", command=self.choose_image2).pack(side="left", padx=6)
        tk.Button(img2_row, text="Clear", command=self.clear_image2).pack(side="left")

        tk.Button(create_frame, text="Generate Tribute Files", command=self.generate, height=2, width=26)\
            .grid(row=11, column=1, sticky="w", padx=10, pady=14)

        tk.Label(
            create_frame,
            text=f"Output: {TRIBUTES_DIR}\nArchive: {ARCHIVE_INDEX}",
            fg="#444"
        ).grid(row=12, column=0, columnspan=2, sticky="w", padx=10, pady=6)

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

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Tribute — {slug}")
        dialog.transient(self.root)
        dialog.grab_set()

        pad = {"padx": 10, "pady": 6}
        row = 0

        tk.Label(dialog, text="Slug").grid(row=row, column=0, sticky="w", **pad)
        tk.Label(dialog, text=slug, fg="#444").grid(row=row, column=1, sticky="w", **pad)
        row += 1

        fields = [
            ("Pet Name *", "pet_name"),
            ("Pet Type", "pet_type"),
            ("Breed", "breed"),
            ("Dates of Life", "years_pretty"),
            ("Excerpt", "excerpt"),
            ("Published (YYYY-MM-DD)", "published_iso"),
            ("Image Filename", "image_filename"),
            ("Image 2 Filename", "image2_filename"),
            ("First Name", "first_name"),
            ("State", "state"),
        ]
        widgets = {}

        for label, key in fields:
            tk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", **pad)
            widget = tk.Entry(dialog, width=48)
            widget.insert(0, str(entry.get(key, "") or ""))
            widget.grid(row=row, column=1, sticky="w", **pad)
            widgets[key] = widget
            row += 1

        def on_save():
            pet_name = widgets["pet_name"].get().strip()
            published_iso = widgets["published_iso"].get().strip()
            if not pet_name:
                messagebox.showerror("Validation", "Pet Name is required.")
                return
            if published_iso:
                try:
                    datetime.strptime(published_iso, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("Validation", "Published date must be YYYY-MM-DD.")
                    return

            for _, key in fields:
                entry[key] = widgets[key].get().strip()
            entry["years_pretty"] = normalize_dates_text(entry.get("years_pretty", ""))

            save_data(tributes)
            rebuild_archive_pages(tributes)
            self.refresh_tribute_table()
            messagebox.showinfo("Saved", f'Updated tribute "{slug}".')
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.grid(row=row, column=0, columnspan=2, sticky="e", padx=10, pady=(8, 10))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right")
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

    def generate(self):
        pet_name = self.pet_name.get().strip()
        pet_type = self.pet_type.get().strip()
        first_name = self.first_name.get().strip()
        state = self.state.get().strip()
        breed = self.breed.get().strip()
        years_raw = self.years.get().strip()
        tribute_msg = self.message.get("1.0", "end").strip()

        if not pet_name or not tribute_msg:
            messagebox.showerror("Missing required fields", "Pet Name and Tribute Message are required.")
            return

        years_pretty = normalize_dates_text(years_raw)

        # folder slug rules: pet-name + optional breed + optional extracted years
        base_parts = [slugify(pet_name)]
        if breed:
            base_parts.append(slugify(breed))

        # Try extracting 4-digit years for slug, but don't require them
        year_matches = re.findall(r"\d{4}", years_pretty)
        if len(year_matches) >= 2:
            base_parts.append(f"{year_matches[0]}-{year_matches[1]}")

        folder_slug = "-".join([p for p in base_parts if p])

        tribute_folder = os.path.join(MEMORIALS_DIR, folder_slug)
        safe_mkdir(tribute_folder)
        tribute_web_path = f"/pet-tributes/memorials/{folder_slug}/"

        # Decide image output name (inside folder)
        img_abs_url = ""
        img_filename = None
        img2_filename = ""
        is_placeholder_image = False

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

            img_abs_url = f"{SITE_DOMAIN}{tribute_web_path}{img_filename}"
        else:
            # No upload provided for image 1: copy placeholder into tribute folder and name by slug.
            if not os.path.exists(PLACEHOLDER_IMAGE_FILE):
                messagebox.showerror(
                    "Placeholder missing",
                    f"Default image not found:\n{PLACEHOLDER_IMAGE_FILE}"
                )
                return
            img_filename = f"{folder_slug}.png"
            img_dest = os.path.join(tribute_folder, img_filename)
            try:
                shutil.copy2(PLACEHOLDER_IMAGE_FILE, img_dest)
            except Exception as e:
                messagebox.showerror("Placeholder copy failed", f"Could not prepare fallback image:\n{e}")
                return
            img_abs_url = f"{SITE_DOMAIN}{tribute_web_path}{img_filename}"
            is_placeholder_image = True

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
                info2 = convert_to_webp_normalized(chosen_image2, img2_dest, max_width=1200, quality=82)
                print(f"[image2] {info2}")
            except Exception as e:
                messagebox.showerror("Image 2 conversion failed", f"Could not convert second image to .webp:\n{e}")
                return

        # Build tribute page values
        publish_date_iso = datetime.now().strftime("%Y-%m-%d")
        page_url = f"{SITE_DOMAIN}{tribute_web_path}"
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
            pet_type=pet_type,
            years_pretty=years_pretty,
            excerpt=excerpt,
            page_url=page_url,
            tribute_web_path=tribute_web_path,
            og_image_abs=img_abs_url,
            is_placeholder_image=is_placeholder_image,
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
        entries = load_data()

        published_iso = datetime.now().strftime("%Y-%m-%d")

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
            "published_iso": published_iso,
            "image_filename": image_filename,
            "image2_filename": img2_filename,
        }

        # prevent duplicates by slug
        entries = [e for e in entries if e.get("slug") != folder_slug]
        entries.append(entry)

        save_data(entries)
        rebuild_archive_pages(entries)
        self.refresh_tribute_table()

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