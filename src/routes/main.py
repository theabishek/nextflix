# main.py (Blueprint for “main”)
from flask import Blueprint, render_template, request, flash, jsonify
from flask_login import current_user
import requests
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

# Load environment variables
load_dotenv()

main_bp = Blueprint('main', __name__, template_folder='templates/home')

TMDB_API_KEY = os.getenv('TMDB_API_KEY')
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Create a single session for keep-alive / connection pooling
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
session.mount("https://", adapter)
session.headers.update({"Accept": "application/json"})

def fetch_tmdb_json(url):
    """
    Fetch JSON from TMDB via a persistent session, with error handling.
    Returns the parsed JSON or an empty dict on failure.
    """
    try:
        resp = session.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Error fetching from TMDB: {e}")
        return {}

@lru_cache(maxsize=128)
def cached_search_results(query: str):
    """
    Cached call to TMDB /search/multi?query={query}. Returns a tuple of results list.
    """
    url = (
        f"{TMDB_BASE_URL}/search/multi"
        f"?api_key={TMDB_API_KEY}&query={requests.utils.requote_uri(query)}&include_adult=false"
    )
    data = fetch_tmdb_json(url)
    return tuple(data.get("results", []))

@lru_cache(maxsize=128)
def cached_autocomplete_results(prefix: str):
    """
    Cached call to TMDB /search/multi for autocomplete. Returns a tuple of results list.
    """
    # Reuse cached_search_results under the hood for the same prefix
    return cached_search_results(prefix)

@main_bp.route("/")
def index():
    # TRENDING (India, week) for movies + TV
    movie_url = f"{TMDB_BASE_URL}/trending/movie/week?api_key={TMDB_API_KEY}&region=IN"
    tv_url = f"{TMDB_BASE_URL}/trending/tv/week?api_key={TMDB_API_KEY}&region=IN"

    try:
        # Fetch both endpoints in parallel to minimize latency
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_movie = executor.submit(fetch_tmdb_json, movie_url)
            future_tv = executor.submit(fetch_tmdb_json, tv_url)

            tm = future_movie.result().get("results", []) or []
            tv = future_tv.result().get("results", []) or []

        combined = tm + tv
        # Sort by popularity descending
        combined.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        top_trending = combined[:20]
    except Exception as e:
        print(f"Error fetching trending content: {e}")
        top_trending = []
        flash("Failed to fetch trending content. Please try again later.", "error")

    return render_template(
        "home/index.html",
        trending_items=top_trending,
        is_authenticated=current_user.is_authenticated
    )

@main_bp.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return render_template(
            "home/search.html",
            search_results=[],
            query="",
            is_authenticated=current_user.is_authenticated,
            page_name="Search"
        )

    try:
        raw_results = cached_search_results(query)
        processed_results = []
        seen = set()
        for item in raw_results:
            mtype = item.get("media_type")
            if mtype not in ("movie", "tv"):
                continue
            mid = item.get("id")
            key = (mtype, mid)
            if key in seen:
                continue
            seen.add(key)
            processed_results.append({
                "id": mid,
                "media_type": mtype,
                "title": item.get("title") or item.get("name"),
                "poster_path": item.get("poster_path"),
                "release_date": item.get("release_date") or item.get("first_air_date", ""),
                "vote_average": item.get("vote_average", 0),
                "overview": item.get("overview")
            })
    except Exception as e:
        print(f"Search error: {e}")
        processed_results = []
        flash("Failed to complete search. Please try again later.", "error")

    return render_template(
        "home/search.html",
        search_results=processed_results,
        query=query,
        is_authenticated=current_user.is_authenticated,
        page_name="Search Results"
    )

@main_bp.route("/autocomplete")
def autocomplete():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": []})

    try:
        raw = cached_autocomplete_results(query)
        suggestions = []
        count = 0
        for item in raw:
            if count >= 8:
                break
            mtype = item.get("media_type")
            if mtype not in ("movie", "tv"):
                continue
            title = item.get("title") or item.get("name")
            year = (item.get("release_date") or item.get("first_air_date", ""))[:4]
            poster = item.get("poster_path")
            suggestions.append({
                "title": title,
                "year": year or "",
                "poster": f"https://image.tmdb.org/t/p/w92{poster}" if poster else "",
                "id": item.get("id"),
                "media_type": mtype
            })
            count += 1
    except Exception as e:
        print(f"Autocomplete error: {e}")
        suggestions = []

    return jsonify({"results": suggestions})
