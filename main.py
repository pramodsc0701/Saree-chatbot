import json
import os
import threading
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
if CLOUDINARY_URL and not CLOUDINARY_URL.startswith("cloudinary://"):
    CLOUDINARY_URL = ""

if CLOUDINARY_URL:
    import cloudinary
    import cloudinary.uploader
    from urllib.parse import urlparse

    parsed = urlparse(CLOUDINARY_URL)
    cloudinary.config(
        cloud_name=parsed.hostname,
        api_key=parsed.username,
        api_secret=parsed.password,
        secure=True,
    )

STATIC_DIR = os.path.join(BASE_DIR, "static")


def _catalog_dir() -> str:
    for name in ("catalog", "Catalog"):
        p = os.path.join(BASE_DIR, name)
        if os.path.isdir(p):
            return p
    return os.path.join(BASE_DIR, "catalog")


CATALOG_DIR = _catalog_dir()

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(CATALOG_DIR, exist_ok=True)

app = FastAPI(title="Saree Catalog")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/catalog", StaticFiles(directory=CATALOG_DIR), name="catalog")


# ---------------------------------------------------------------------------
# Catalog (folder-based product backend)
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif")

MATERIALS = {
    "silk": ["silk", "banarasi", "kanjeevaram", "kanjivaram", "patola"],
    "cotton": ["cotton", "handloom", "khadi", "bandhani", "gharchola"],
    "chiffon": ["chiffon"],
    "georgette": ["georgette"],
}

OCCASIONS = {
    "wedding": ["wedding", "bridal", "marriage"],
    "festival": ["festival", "festive"],
    "party": ["party"],
    "daily": ["daily", "casual", "office", "work"],
}


def detect_material(text: str) -> Optional[str]:
    text = text.lower()
    for material, keywords in MATERIALS.items():
        if any(k in text for k in keywords):
            return material
    return None


def detect_occasion(text: str) -> Optional[str]:
    text = text.lower()
    for occasion, keywords in OCCASIONS.items():
        if any(k in text for k in keywords):
            return occasion
    return None


def _title_name(filename: str) -> str:
    name = filename.rsplit(".", 1)[0]
    return name.replace("-", " ").replace("_", " ").title()


CLOUDINARY_CACHE_FILE = os.path.join(BASE_DIR, "cloudinary_cache.json")
_cloudinary_cache: Dict[str, str] = {}
_cloudinary_lock = threading.Lock()


def _load_cloudinary_cache() -> None:
    global _cloudinary_cache
    if os.path.exists(CLOUDINARY_CACHE_FILE):
        try:
            with open(CLOUDINARY_CACHE_FILE) as f:
                _cloudinary_cache = json.load(f)
        except json.JSONDecodeError:
            _cloudinary_cache = {}


def _save_cloudinary_cache() -> None:
    with open(CLOUDINARY_CACHE_FILE, "w") as f:
        json.dump(_cloudinary_cache, f)


def _cloudinary_url_for(file_path: str, file_rel: str) -> str:
    if not CLOUDINARY_URL:
        return f"/catalog/{file_rel}"
    key = file_rel
    with _cloudinary_lock:
        url = _cloudinary_cache.get(key)
    if url:
        return url
    try:
        public_id = file_rel.replace("/", "_").rsplit(".", 1)[0]
        response = cloudinary.uploader.upload(
            file_path,
            folder="saree-catalog-site",
            public_id=public_id,
            overwrite=False,
        )
        url = response.get("secure_url")
    except Exception:
        return f"/catalog/{file_rel}"
    if url:
        with _cloudinary_lock:
            _cloudinary_cache[key] = url
            _save_cloudinary_cache()
    return url or f"/catalog/{file_rel}"


def scan_catalog_sync(catalog_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    catalog_dir = catalog_dir or CATALOG_DIR
    products: List[Dict[str, Any]] = []

    for root, _dirs, files in os.walk(catalog_dir):
        rel = os.path.relpath(root, catalog_dir)
        if rel == ".":
            continue

        parts = rel.split(os.sep)
        category = parts[0] if len(parts) > 0 else ""
        subcategory = parts[1] if len(parts) > 1 else ""
        price = 0
        if len(parts) > 2:
            try:
                price = int(parts[2])
            except ValueError:
                price = 0

        for f in files:
            if f.lower().endswith(IMAGE_EXTENSIONS):
                file_rel = os.path.join(rel, f).replace(os.sep, "/")
                file_path = os.path.join(root, f)
                combined = f"{subcategory} {f}"
                material = detect_material(combined) or detect_material(category) or "silk"
                occasion = detect_occasion(combined) or detect_occasion(category) or "wedding"
                products.append(
                    {
                        "id": f"cat-{file_rel}",
                        "name": _title_name(f),
                        "material": material,
                        "occasion": occasion,
                        "price": price,
                        "image_url": _cloudinary_url_for(file_path, file_rel),
                        "category": _title_name(category),
                        "subcategory": _title_name(subcategory),
                    }
                )

    return products


def scan_catalog_metadata_sync(catalog_dir: Optional[str] = None) -> Dict[str, Any]:
    catalog_dir = catalog_dir or CATALOG_DIR
    tree: Dict[str, Any] = {}

    for root, _dirs, files in os.walk(catalog_dir):
        rel = os.path.relpath(root, catalog_dir)
        if rel == ".":
            continue
        parts = rel.split(os.sep)
        if len(parts) < 3:
            continue
        category, subcategory, price_raw = parts[0], parts[1], parts[2]
        try:
            price = int(price_raw)
        except ValueError:
            continue
        image_count = sum(1 for f in files if f.lower().endswith(IMAGE_EXTENSIONS))
        if image_count == 0:
            continue
        cat = tree.setdefault(
            category, {"slug": category, "name": _title_name(category), "subcategories": {}}
        )
        sub = cat["subcategories"].setdefault(
            subcategory,
            {"slug": subcategory, "name": _title_name(subcategory), "prices": set(), "count": 0},
        )
        sub["prices"].add(price)
        sub["count"] += image_count

    categories = []
    for cat_slug in sorted(tree):
        cat_data = tree[cat_slug]
        sub_list = []
        for sub_slug in sorted(cat_data["subcategories"]):
            sub_data = cat_data["subcategories"][sub_slug]
            sub_list.append(
                {
                    "slug": sub_data["slug"],
                    "name": sub_data["name"],
                    "prices": sorted(sub_data["prices"]),
                    "count": sub_data["count"],
                }
            )
        categories.append(
            {"slug": cat_data["slug"], "name": cat_data["name"], "subcategories": sub_list}
        )

    return {"categories": categories}


def _normalize_text(s: str) -> str:
    return s.lower().replace("-", " ").replace("_", " ").strip()


def _match_product(product: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    if filters.get("material") and product.get("material") != filters["material"].lower():
        return False
    if filters.get("occasion") and product.get("occasion") != filters["occasion"].lower():
        return False
    if filters.get("min_price") and product.get("price", 0) < filters["min_price"]:
        return False
    if filters.get("max_price") and product.get("price", 0) > filters["max_price"]:
        return False
    if filters.get("category") and _normalize_text(product.get("category", "")) != _normalize_text(filters["category"]):
        return False
    if filters.get("subcategory") and _normalize_text(product.get("subcategory", "")) != _normalize_text(filters["subcategory"]):
        return False
    if filters.get("keywords"):
        kw = _normalize_text(filters["keywords"])
        searchable = " ".join(
            _normalize_text(product.get(field, "")) for field in ("name", "material", "occasion", "category", "subcategory")
        )
        if kw not in searchable:
            return False
    return True


def search_products_sync(
    material: Optional[str] = None,
    occasion: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    keywords: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if material:
        filters["material"] = material.lower()
    if occasion:
        filters["occasion"] = occasion.lower()
    if min_price:
        filters["min_price"] = min_price
    if max_price:
        filters["max_price"] = max_price
    if category:
        filters["category"] = category
    if subcategory:
        filters["subcategory"] = subcategory
    if keywords:
        filters["keywords"] = keywords

    all_products = scan_catalog_sync()

    if filters:
        return [p for p in all_products if _match_product(p, filters)]
    return all_products


_load_cloudinary_cache()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/products")
async def list_products(
    material: Optional[str] = Query(None),
    occasion: Optional[str] = Query(None),
    min_price: Optional[int] = Query(None),
    max_price: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    subcategory: Optional[str] = Query(None),
    keywords: Optional[str] = Query(None),
):
    return await run_in_threadpool(
        search_products_sync,
        material,
        occasion,
        min_price,
        max_price,
        category,
        subcategory,
        keywords,
    )


@app.get("/api/categories")
async def list_categories():
    return await run_in_threadpool(scan_catalog_metadata_sync)


@app.get("/api/catalog")
async def list_catalog():
    return await run_in_threadpool(scan_catalog_sync)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
