from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from bson import ObjectId
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Define the Movie Blueprint
movie_bp = Blueprint('movie', __name__, url_prefix='/movie')

# Get API key from environment
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Function to safely extract filename from URL
def get_filename_from_url(url):
    return os.path.basename(url) if url else None

def get_with_retry(url, retries=3, backoff_factor=0.5):
    """
    Fetches a URL with retry logic.

    Args:
        url (str): The URL to fetch.
        retries (int): The maximum number of retries.
        backoff_factor (float): The backoff factor for the retry delay.

    Returns:
        requests.Response: The response object, or None if all retries fail.
    """
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 503, 504),  # Retry on these status codes
    )
    adapter = HTTPAdapter(max_retries=retry)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    try:
        response = http.get(url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return response
    except requests.exceptions.RequestException as e:
        print(f"Request failed after multiple retries: {e}")
        return None

# Movie Details Route
@movie_bp.route('/details/<int:movie_id>', methods=['GET'])
def movie_details(movie_id):
    movie_url = f"{TMDB_BASE_URL}/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=videos,credits"
    recommendations_url = f"{TMDB_BASE_URL}/movie/{movie_id}/recommendations?api_key={TMDB_API_KEY}&language=en-US"

    movie = {}
    recommendations = []
    try:
        movie_response = requests.get(movie_url)
        movie_response.raise_for_status()
        movie = movie_response.json()

        # Process genres
        movie['genres'] = [g['name'] for g in movie.get('genres', [])]

        # Process director(s)
        directors = []
        for person in movie.get('credits', {}).get('crew', []):
            if person.get('job') == 'Director':
                directors.append(person['name'])
        movie['director'] = ", ".join(directors) if directors else 'N/A'

        # Process cast (first 5 actors) - Fixed formatting
        cast = []
        for actor in movie.get('credits', {}).get('cast', [])[:5]:
            if isinstance(actor, dict) and 'name' in actor:
                cast.append(actor['name'])
        movie['cast'] = cast  # Store as list, not string

        # Process trailer (YouTube)
        movie['trailer_key'] = None
        for video in movie.get('videos', {}).get('results', []):
            if video['type'] == 'Trailer' and video['site'] == 'YouTube':
                movie['trailer_key'] = video['key']
                break

        recommendations_response = get_with_retry(recommendations_url) or requests.get(recommendations_url)
        recommendations_response.raise_for_status()
        recommendations = recommendations_response.json().get('results', [])

    except requests.exceptions.RequestException as e:
        flash(f"Failed to fetch movie details due to a network error: {str(e)}", 'error')

    # User-specific data
    movie_in_watchlist = False
    movie_in_favorites = False
    user_like = False
    user_dislike = False
    reviews = []

    if current_user.is_authenticated:
        db = current_app.config["db"]
        user = db.users.find_one({"_id": ObjectId(current_user.get_id())})
        if user:
            # Check watchlist
            movie_in_watchlist = any(str(movie_id) == m["id"] for m in user.get("watchlist", []))
            # Check favorites
            movie_in_favorites = any(str(movie_id) == m["id"] for m in user.get("favorites", []))

        # Check likes/dislikes
        reaction = db.likes.find_one({
            "user_id": str(current_user.get_id()),
            "movie_id": str(movie_id)
        })
        if reaction:
            user_like = reaction.get("type") == "like"
            user_dislike = reaction.get("type") == "dislike"
        
        # Fetch reviews
        reviews = list(db.reviews.find({"movie_id": str(movie_id)}).sort("timestamp", -1))

    return render_template(
        "home/details.html",
        movie=movie,
        movie_id=movie_id,
        recommendations=recommendations,
        is_authenticated=current_user.is_authenticated,
        movie_in_watchlist=movie_in_watchlist,
        movie_in_favorites=movie_in_favorites,
        user_like=user_like,
        user_dislike=user_dislike,
        reviews=reviews
    )

# Watchlist Route
@movie_bp.route('/watchlist')
@login_required
def watchlist():
    db = current_app.config["db"]
    user = db.users.find_one({"_id": ObjectId(current_user.get_id())})
    watchlist_ids = [movie["id"] for movie in user.get("watchlist", [])]

    # Fetch full movie details for each watchlist item
    watchlist_movies = []
    for movie_id in watchlist_ids:
        try:
            movie_url = f"{TMDB_BASE_URL}/movie/{movie_id}?api_key={TMDB_API_KEY}"
            movie_response = get_with_retry(movie_url) or requests.get(movie_url)
            movie_response.raise_for_status()
            movie_data = movie_response.json()

            movie = {
                "id": str(movie_data.get("id")),
                "title": movie_data.get("title", "N/A"),
                "poster_path": movie_data.get("poster_path", ""),
                "vote_average": movie_data.get("vote_average", 0.0),
                "release_date": movie_data.get("release_date", "N/A")
            }
            watchlist_movies.append(movie)
        except requests.exceptions.RequestException as e:
            flash(f"Failed to fetch watchlist movie details due to a network error: {str(e)}", 'error')
            print(f"Error fetching movie {movie_id}: {e}")
            continue

    return render_template("home/watchlist.html", cards=watchlist_movies)

# Favorites Route
@movie_bp.route('/favorites')
@login_required
def favorites():
    db = current_app.config["db"]
    user = db.users.find_one({"_id": ObjectId(current_user.get_id())})
    favorites_ids = [movie["id"] for movie in user.get("favorites", [])]

    # Fetch full movie details for each favorite item
    favorites_movies = []
    for movie_id in favorites_ids:
        try:
            movie_url = f"{TMDB_BASE_URL}/movie/{movie_id}?api_key={TMDB_API_KEY}"
            movie_response = get_with_retry(movie_url) or requests.get(movie_url)
            movie_response.raise_for_status()
            movie_data = movie_response.json()

            movie = {
                "id": str(movie_data.get("id")),
                "title": movie_data.get("title", "N/A"),
                "poster_path": movie_data.get("poster_path", ""),
                "vote_average": movie_data.get("vote_average", 0.0),
                "release_date": movie_data.get("release_date", "N/A")
            }
            favorites_movies.append(movie)
        except requests.exceptions.RequestException as e:
            flash(f"Failed to fetch favorite movie details due to a network error: {str(e)}", 'error')
            print(f"Error fetching movie {movie_id}: {e}")
            continue

    return render_template("home/favorites.html", cards=favorites_movies)

# Toggle Watchlist
@movie_bp.route('/toggle-watchlist/<int:movie_id>', methods=['POST'])
@login_required
def toggle_watchlist(movie_id):
    db = current_app.config["db"]
    user = db.users.find_one({"_id": ObjectId(current_user.get_id())})

    watchlist = user.get("watchlist", [])
    if any(movie["id"] == str(movie_id) for movie in watchlist):
        watchlist = [m for m in watchlist if m["id"] != str(movie_id)]
        flash("Removed from watchlist", "info")
    else:
        watchlist.append({"id": str(movie_id)})
        flash("Added to watchlist", "success")

    db.users.update_one({"_id": ObjectId(current_user.get_id())}, {"$set": {"watchlist": watchlist}})
    return redirect(url_for("movie.movie_details", movie_id=movie_id))

# Toggle Favorites
@movie_bp.route('/toggle-favorite/<int:movie_id>', methods=['POST'])
@login_required
def toggle_favorite(movie_id):
    db = current_app.config["db"]
    user = db.users.find_one({"_id": ObjectId(current_user.get_id())})

    favorites = user.get("favorites", [])
    if any(movie["id"] == str(movie_id) for movie in favorites):
        favorites = [m for m in favorites if m["id"] != str(movie_id)]
        flash("Removed from favorites", "info")
    else:
        favorites.append({"id": str(movie_id)})
        flash("Added to favorites", "success")

    db.users.update_one({"_id": ObjectId(current_user.get_id())}, {"$set": {"favorites": favorites}})
    return redirect(url_for("movie.movie_details", movie_id=movie_id))

# Like & Dislike
@movie_bp.route('/like-movie/<int:movie_id>', methods=['POST'])
@login_required
def like_movie(movie_id):
    db = current_app.config["db"]
    db.likes.update_one(
        {"user_id": str(current_user.get_id()), "movie_id": str(movie_id)},
        {"$set": {"type": "like"}},
        upsert=True
    )
    flash("Liked movie!", "success")
    return redirect(url_for("movie.movie_details", movie_id=movie_id))

@movie_bp.route('/dislike-movie/<int:movie_id>', methods=['POST'])
@login_required
def dislike_movie(movie_id):
    db = current_app.config["db"]
    db.likes.update_one(
        {"user_id": str(current_user.get_id()), "movie_id": str(movie_id)},
        {"$set": {"type": "dislike"}},
        upsert=True
    )
    flash("Disliked movie!", "info")
    return redirect(url_for("movie.movie_details", movie_id=movie_id))

@movie_bp.route('/submit-review/<int:movie_id>', methods=['POST'])
@login_required
def submit_review(movie_id):
    db = current_app.config["db"]
    review_text = request.form.get("review")
    rating = request.form.get("rating")

    # Validate rating
    if not rating or not rating.isdigit() or int(rating) < 1 or int(rating) > 5:
        flash("Please select a valid rating between 1-5 stars", "danger")
        return redirect(url_for("movie.movie_details", movie_id=movie_id))

    # Create new review document
    review_data = {
        "user_id": str(current_user.get_id()),
        "movie_id": str(movie_id),
        "review": review_text.strip(),
        "rating": int(rating),
        "timestamp": datetime.utcnow(),
        "user": {
            "name": current_user.name,
            "profile_pic": get_filename_from_url(current_user.profile_pic)
        }
    }

    # Insert new review
    db.reviews.insert_one(review_data)

    flash("Review submitted successfully!", "success")
    return redirect(url_for("movie.movie_details", movie_id=movie_id))

# Delete Review
@movie_bp.route('/delete-review/<review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    db = current_app.config["db"]
    review = db.reviews.find_one({"_id": ObjectId(review_id)})

    if review and review["user_id"] == str(current_user.get_id()):
        movie_id = int(review["movie_id"])
        db.reviews.delete_one({"_id": ObjectId(review_id)})
        flash("Review deleted!", "success")
        return redirect(url_for("movie.movie_details", movie_id=movie_id))
    else:
        flash("You can only delete your own reviews!", "danger")
        return redirect(url_for("main.home"))