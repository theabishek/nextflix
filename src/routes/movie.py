import os
from datetime import datetime
from bson import ObjectId
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from dotenv import load_dotenv

# -----------------------------------------
# LOAD ENVIRONMENT & CONFIGURE SESSION
# -----------------------------------------
load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Create a persistent Requests session for TMDB
session = requests.Session()
session.headers.update({"Accept": "application/json"})


# -----------------------------------------
# TMDB FETCH FUNCTIONS & HELPERS
# -----------------------------------------

def fetch_tmdb_item(item_id: int, item_type: str = "movie", include_details: bool = True):
    """
    Fetch a TMDB item (movie or tv). If include_details=True, append videos, credits, recommendations.
    Returns the JSON dict or None on error (and flashes error).
    """
    if item_type not in ("movie", "tv"):
        flash(f"Invalid type '{item_type}' requested.", "error")
        return None

    url = f"{TMDB_BASE_URL}/{item_type}/{item_id}?api_key={TMDB_API_KEY}"
    if include_details:
        url += "&append_to_response=videos,credits,recommendations"

    try:
        resp = session.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        flash(f"Failed to fetch {item_type} details: {e}", "error")
        return None


@lru_cache(maxsize=256)
def fetch_tmdb_item_cached(item_type: str, item_id: int, include_details: bool = False):
    """
    LRU-cached wrapper around fetch_tmdb_item(...).
    Caches by (item_type, item_id, include_details).
    """
    return fetch_tmdb_item(item_id, item_type=item_type, include_details=include_details)


def fetch_items_concurrently(item_list: list):
    """
    Given a list of dicts: [{"id": "123", "type": "movie"}, {"id": "456", "type": "tv"}, ...],
    fetch minimal data (no append_to_response). Return a dict mapping (type, id) -> basic fields.
    Defaults missing 'type' to 'movie'.
    """
    def fetch_one(pair):
        _id_str = pair.get("id")
        _type = pair.get("type", "movie")

        if not _id_str:
            return None

        try:
            raw_data = fetch_tmdb_item_cached(_type, int(_id_str), False)
        except Exception:
            raw_data = None

        if not raw_data:
            return None

        return {
            "id": str(raw_data.get("id")),
            "type": _type,
            "title": raw_data.get("title") or raw_data.get("name") or "N/A",
            "poster_path": raw_data.get("poster_path") or "",
            "vote_average": raw_data.get("vote_average", 0.0) or 0.0,
            "release_date": raw_data.get("release_date") or raw_data.get("first_air_date") or "",
        }

    fetched = {}
    max_workers = min(len(item_list), 5) if item_list else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, pair): pair for pair in item_list}
        for fut in as_completed(futures):
            pair = futures[fut]
            try:
                result = fut.result()
                if result:
                    key = (result["type"], result["id"])
                    fetched[key] = result
            except Exception as e:
                print(f"Error fetching for pair={pair}: {e}")
    return fetched


def process_base_fields(raw: dict, item_type: str):
    """
    Normalize common fields for movie or tv:
    - id, type, title, original_title, release_date/first_air_date,
      poster_path, backdrop_path, overview, tagline, vote_average, status, genres,
      runtime (movie) or episode_run_time (tv), seasons/episodes for tv.
    """
    if not raw:
        return None

    base = {
        "id": raw.get("id"),
        "type": item_type,
        "poster_path": raw.get("poster_path") or "",
        "backdrop_path": raw.get("backdrop_path") or "",
        "overview": raw.get("overview") or "",
        "tagline": raw.get("tagline") or "",
        "vote_average": raw.get("vote_average", 0.0) or 0.0,
        "status": raw.get("status") or "",
        "genres": [g["name"] for g in raw.get("genres", [])],
    }

    if item_type == "movie":
        base["title"] = raw.get("title") or "N/A"
        base["original_title"] = raw.get("original_title") or base["title"]
        base["release_date"] = raw.get("release_date") or ""
        base["runtime"] = raw.get("runtime") or 0

        # Fill TV-specific keys as empty
        base["first_air_date"] = ""
        base["episode_run_time"] = []
        base["seasons"] = []
        base["number_of_seasons"] = 0
        base["number_of_episodes"] = 0
    else:  # tv
        base["title"] = raw.get("name") or "N/A"
        base["original_title"] = raw.get("original_name") or base["title"]
        base["release_date"] = ""
        base["first_air_date"] = raw.get("first_air_date") or ""
        base["episode_run_time"] = raw.get("episode_run_time", [])
        base["runtime"] = raw.get("episode_run_time", [0])[0] if raw.get("episode_run_time") else 0
        base["seasons"] = raw.get("seasons", [])
        base["number_of_seasons"] = raw.get("number_of_seasons", 0)
        base["number_of_episodes"] = raw.get("number_of_episodes", 0)

    return base


def process_crew_and_cast(raw: dict, item_type: str):
    """
    Extract director (for movie) or creators (for tv), plus first five cast members.
    """
    result = {
        "director": "N/A",
        "creators": [],
        "cast": [],
    }

    credits = raw.get("credits", {})
    crew = credits.get("crew", [])
    cast_list = credits.get("cast", [])

    if item_type == "movie":
        directors = [p["name"] for p in crew if p.get("job") == "Director"]
        result["director"] = ", ".join(directors) if directors else "N/A"
    else:  # tv
        created_by = raw.get("created_by", [])
        result["creators"] = [c.get("name") for c in created_by if c.get("name")]
        if not result["creators"]:
            # fallback to crew with job="Creator"
            tv_creators = [p["name"] for p in crew if p.get("job") == "Creator"]
            result["creators"] = tv_creators
        result["director"] = None

    # First 5 cast names
    result["cast"] = [actor["name"] for actor in cast_list[:5] if actor.get("name")]
    return result


def process_trailer(raw: dict):
    """
    Find the first YouTube trailer key in raw["videos"]["results"].
    """
    for video in raw.get("videos", {}).get("results", []):
        if video.get("type") == "Trailer" and video.get("site") == "YouTube":
            return video.get("key")
    return None


def process_recommendations(raw: dict):
    """
    Return raw["recommendations"]["results"] or empty list.
    """
    return raw.get("recommendations", {}).get("results", [])


def fetch_user_data(user_id: str, item_id: int = None, item_type: str = "movie"):
    """
    Fetch user-specific flags: whether item is in watchlist/favorites,
    whether user liked/disliked, and reviews for this item.
    """
    db = current_app.config["db"]
    user = db.users.find_one(
        {"_id": ObjectId(user_id)},
        {"watchlist": 1, "favorites": 1}
    )

    user_data = {
        "item_in_watchlist": False,
        "item_in_favorites": False,
        "user_like": False,
        "user_dislike": False,
        "reviews": []
    }

    if user and item_id is not None:
        id_str = str(item_id)
        watchlist = user.get("watchlist", [])
        favorites = user.get("favorites", [])

        user_data["item_in_watchlist"] = any(
            (m.get("id") == id_str and m.get("type") == item_type)
            for m in watchlist
        )
        user_data["item_in_favorites"] = any(
            (m.get("id") == id_str and m.get("type") == item_type)
            for m in favorites
        )

        reaction = db.likes.find_one({
            "user_id": user_id,
            "item_id": id_str,
            "item_type": item_type
        })
        if reaction:
            user_data["user_like"] = reaction.get("type") == "like"
            user_data["user_dislike"] = reaction.get("type") == "dislike"

        user_data["reviews"] = list(db.reviews.find(
            {"item_id": id_str, "item_type": item_type},
            {"review": 1, "rating": 1, "timestamp": 1, "user": 1, "_id": 1}
        ).sort("timestamp", -1))

    return user_data


# -----------------------------------------
# DEFINE BLUEPRINT & ROUTES
# -----------------------------------------
movie_bp = Blueprint('movie', __name__, url_prefix='/movie')


@movie_bp.route('/details/<string:item_type>/<int:item_id>', methods=['GET'])
def movie_details(item_type, item_id):
    """
    Unified details route for both movies and TV shows:
    /movie/details/movie/550
    /movie/details/tv/1399
    """
    raw = fetch_tmdb_item(item_id, item_type=item_type, include_details=True)
    if not raw:
        return redirect(url_for('main.index'))

    base = process_base_fields(raw, item_type)
    if not base:
        flash("Error processing basic fields.", "error")
        return redirect(url_for('main.index'))

    crew_cast = process_crew_and_cast(raw, item_type)
    trailer_key = process_trailer(raw)
    recommendations = process_recommendations(raw)

    user_data = {}
    if current_user.is_authenticated:
        user_data = fetch_user_data(current_user.get_id(), item_id, item_type)

    return render_template(
        "home/details.html",
        item=base,
        crew_cast=crew_cast,
        trailer_key=trailer_key,
        recommendations=recommendations,
        is_authenticated=current_user.is_authenticated,
        **user_data
    )


@movie_bp.route('/watchlist')
@login_required
def watchlist():
    db = current_app.config["db"]
    user = db.users.find_one(
        {"_id": ObjectId(current_user.get_id())},
        {"watchlist": 1}
    )
    watchlist = user.get("watchlist", [])
    fetched = fetch_items_concurrently(watchlist)

    cards = []
    for pair in watchlist:
        key = (pair.get("type", "movie"), str(pair.get("id")))
        if key in fetched:
            cards.append(fetched[key])

    return render_template("home/watchlist.html", cards=cards)


@movie_bp.route('/favorites')
@login_required
def favorites():
    db = current_app.config["db"]
    user = db.users.find_one(
        {"_id": ObjectId(current_user.get_id())},
        {"favorites": 1}
    )
    favorites = user.get("favorites", [])
    fetched = fetch_items_concurrently(favorites)

    cards = []
    for pair in favorites:
        key = (pair.get("type", "movie"), str(pair.get("id")))
        if key in fetched:
            cards.append(fetched[key])

    return render_template("home/favorites.html", cards=cards)


@movie_bp.route('/toggle-watchlist/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def toggle_watchlist(item_type, item_id):
    db = current_app.config["db"]
    user_id = current_user.get_id()
    obj_id = ObjectId(user_id)

    user = db.users.find_one({"_id": obj_id})
    if not user:
        flash("User not found", "error")
        return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))

    current_watchlist = user.get("watchlist", [])
    entry = {"id": str(item_id), "type": item_type}

    if entry in current_watchlist:
        updated_watchlist = [i for i in current_watchlist if i != entry]
        flash("Removed from watchlist", "info")
    else:
        updated_watchlist = current_watchlist + [entry]
        flash("Added to watchlist", "success")

    db.users.update_one(
        {"_id": obj_id},
        {"$set": {"watchlist": updated_watchlist}}
    )

    return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))

@movie_bp.route('/toggle-favorite/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def toggle_favorite(item_type, item_id):
    db = current_app.config["db"]
    user_id = current_user.get_id()
    obj_id = ObjectId(user_id)

    user = db.users.find_one({"_id": obj_id})
    if not user:
        flash("User not found", "error")
        return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))

    current_favorites = user.get("favorites", [])
    entry = {"id": str(item_id), "type": item_type}

    if entry in current_favorites:
        updated_favorites = [i for i in current_favorites if i != entry]
        flash("Removed from favorites", "info")
    else:
        updated_favorites = current_favorites + [entry]
        flash("Added to favorites", "success")

    db.users.update_one(
        {"_id": obj_id},
        {"$set": {"favorites": updated_favorites}}
    )

    return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))


@movie_bp.route('/like-item/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def like_item(item_type, item_id):
    db = current_app.config["db"]
    user_id = current_user.get_id()

    db.likes.update_one(
        {"user_id": user_id, "item_id": str(item_id), "item_type": item_type},
        {"$set": {"type": "like"}},
        upsert=True
    )
    flash("You liked this item!", "success")
    return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))


@movie_bp.route('/dislike-item/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def dislike_item(item_type, item_id):
    db = current_app.config["db"]
    user_id = current_user.get_id()

    db.likes.update_one(
        {"user_id": user_id, "item_id": str(item_id), "item_type": item_type},
        {"$set": {"type": "dislike"}},
        upsert=True
    )
    flash("You disliked this item!", "info")
    return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))


@movie_bp.route('/submit-review/<string:item_type>/<int:item_id>', methods=['POST'])
@login_required
def submit_review(item_type, item_id):
    db = current_app.config["db"]
    review_text = request.form.get("review", "").strip()
    rating = request.form.get("rating", "").strip()

    if not rating.isdigit() or int(rating) < 1 or int(rating) > 5:
        flash("Please select a valid rating between 1-5 stars", "danger")
        return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))

    review_data = {
        "user_id": current_user.get_id(),
        "item_id": str(item_id),
        "item_type": item_type,
        "review": review_text,
        "rating": int(rating),
        "timestamp": datetime.utcnow(),
        "user": {
            "name": current_user.name,
            "profile_pic": os.path.basename(current_user.profile_pic) if current_user.profile_pic else None
        }
    }

    try:
        db.reviews.insert_one(review_data)
        flash("Review submitted successfully!", "success")
    except Exception as e:
        flash(f"Failed to submit review: {e}", "error")

    return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))


@movie_bp.route('/delete-review/<string:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    db = current_app.config["db"]
    review = db.reviews.find_one({"_id": ObjectId(review_id)})

    if review and review.get("user_id") == current_user.get_id():
        item_type = review.get("item_type", "movie")
        item_id = int(review.get("item_id"))
        db.reviews.delete_one({"_id": ObjectId(review_id)})
        flash("Review deleted!", "success")
        return redirect(url_for("movie.movie_details", item_type=item_type, item_id=item_id))

    flash("You can only delete your own reviews!", "danger")
    return redirect(url_for("main.index"))
