from flask import Blueprint, abort, session, current_app, make_response
from extensions import supabase_admin
from functools import wraps
import requests
import os
from flask_caching import Cache

STORAGE_LINK = os.getenv("STORAGE_LINK")

images_bp = Blueprint("images", __name__, url_prefix="/images")

cache = Cache(config={"CACHE_TYPE": "SimpleCache"})

def init_cache(app):
    cache.init_app(app)

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            abort(401)
        try:
            user_id = session["user_id"]
            user = supabase_admin.auth.admin.get_user_by_id(user_id).user
            if not user:
                session.clear()
                abort(401)
        except Exception:
            current_app.logger.exception("session validation failed")
            session.clear()
            abort(401)
        return f(user.user_metadata, *args, **kwargs)
    return wrapped

@images_bp.route("/<path:path>")
@login_required
def proxy_image(user, path):
    url = f"{STORAGE_LINK}/{path}"
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        abort(resp.status_code)

    content = resp.content
    content_type = resp.headers.get("Content-Type", "application/octet-stream")

    response = make_response(content)
    response.headers["Content-Type"] = content_type

    # Allow browsers to cache for 10 minutes
    response.headers["Cache-Control"] = "public, max-age=600, immutable"

    # Optional CDN hints (Vercel may still skip because of cookies)
    response.headers["CDN-Cache-Control"] = "public, max-age=600"
    response.headers["Vercel-CDN-Cache-Control"] = "public, max-age=600"

    return response