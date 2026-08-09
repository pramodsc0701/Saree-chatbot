# Saree Catalog Site

A simple product catalog web app with a folder-based backend.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000.

## Add products

Drop images into the catalog folder like this:

```
catalog/<category>/<subcategory>/<price>/<image>.jpg
```

Example:

```
catalog/wedding-saree/banarasi-silk/1500/banarasi-red.jpg
```

The UI will automatically show the category, subcategory, and price.

## Deploy to Render

1. Push this folder to a new GitHub repo.
2. Create a new free Web Service on Render and connect the repo.
3. Add the `CLOUDINARY_URL` environment variable (optional; if not set, images are served from the `catalog/` folder).
4. Render will build from `render.yaml` and give you a live URL.
