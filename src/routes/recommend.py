import os
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
import pandas as pd
import requests
from functools import lru_cache
from dotenv import load_dotenv
import joblib
from .utils import clean_text

# Load environment variables
load_dotenv()

recommend_bp = Blueprint("recommend", __name__, url_prefix="/recommend")

# ── TMDB configuration from .env ─────────────────────────────────────────────────
TMDB_API_KEY    = os.getenv("TMDB_API_KEY", "")
TMDB_BASE_URL   = os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3")
TMDB_IMAGE_BASE = os.getenv("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p/w500")

# Model file paths (from .env or defaults)
EMOTION_MODEL_PATH       = os.getenv("EMOTION_MODEL_PATH",       "emotion_classifier.joblib")
CONTENT_SIM_PATH         = os.getenv("CONTENT_SIM_PATH",         "content_similarity.joblib")
COLLABORATIVE_MODEL_PATH = os.getenv("COLLABORATIVE_MODEL_PATH", "collaborative_filtering.joblib")
MOVIE_METADATA_CSV_PATH  = os.getenv("MOVIE_METADATA_CSV_PATH",  "movie_metadata.csv")

# Emotion ↔ Genre mapping (used for labeling only)
EMOTION_GENRE_MAP = {
    "joy": ["Comedy", "Musical", "Family", "Animation"],
    "sadness": ["Drama", "Romance", "Music"],
    "anger": ["Action", "Thriller", "Crime", "War"],
    "anticipation": ["Adventure", "Sci-Fi", "Mystery", "Fantasy"],
    "surprise": ["Thriller", "Mystery", "Fantasy", "Horror"],
    "disgust": ["Horror", "Thriller", "Crime"],
    "fear": ["Horror", "Mystery", "Thriller"],
    "trust": ["Drama", "Romance", "Family", "History"]
}

# ── Globals (loaded once) ────────────────────────────────────────────────────────
emotion_model  = None
content_sim    = None
svd_model      = None
movies_df      = None
title_to_index = None
tmdb_session   = None

def load_models():
    """
    Load or reuse all models and movie metadata. Uses memory-mapping for content_similarity.
    """
    global emotion_model, content_sim, svd_model, movies_df, title_to_index, tmdb_session

    if emotion_model is None:
        emotion_model = joblib.load(EMOTION_MODEL_PATH)

    if content_sim is None:
        # memory-map the float32 similarity array
        content_sim = joblib.load(CONTENT_SIM_PATH, mmap_mode="r")

    if svd_model is None:
        svd_model = joblib.load(COLLABORATIVE_MODEL_PATH)

    if movies_df is None:
        movies_df = pd.read_csv(MOVIE_METADATA_CSV_PATH)
        movies_df["title_lower"] = movies_df["title"].str.lower()
        title_to_index = pd.Series(movies_df.index.values, index=movies_df["title_lower"]).to_dict()
        tmdb_session = requests.Session()

    return

@lru_cache(maxsize=1024)
def get_movie_details_from_tmdb(tmdb_id: int) -> dict:
    """
    Fetch full details from TMDB for a given movie ID.
    Caches up to 1024 unique IDs to avoid repeated HTTP calls.
    """
    try:
        resp = tmdb_session.get(
            f"{TMDB_BASE_URL}/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY}
        )
        resp.raise_for_status()
        data = resp.json()
        poster = data.get("poster_path") or ""
        if poster and not poster.startswith("/"):
            poster = "/" + poster
        return {
            "id": data.get("id"),
            "title": data.get("title", ""),
            "poster_path": TMDB_IMAGE_BASE + poster if poster else "",
            "vote_average": data.get("vote_average", 0.0),
            "release_date": data.get("release_date", "") or "",
            "genres": [g["name"] for g in data.get("genres", [])],
            "overview": data.get("overview", "") or ""
        }
    except Exception:
        return None

def enhance_movie_data(movie: dict) -> dict:
    """
    Merge stored metadata with TMDB-fetched details if possible.
    If TMDB fails, fallback to minimal stored info (title + ID).
    """
    tmdb_id = movie.get("id")
    if tmdb_id:
        tmdb_info = get_movie_details_from_tmdb(tmdb_id)
        if tmdb_info:
            return tmdb_info
    return {
        "id": movie.get("id"),
        "title": movie.get("title", ""),
        "poster_path": "",
        "vote_average": 0.0,
        "release_date": "",
        "genres": [],
        "overview": ""
    }

def get_content_recommendations(movie_title: str, n: int = 5) -> list:
    """
    Look up movie_title → index. Use memory-mapped content_sim to pick top-n similar.
    If title not found, return random sample of n.
    """
    load_models()
    idx = title_to_index.get(movie_title.lower())
    if idx is None:
        return movies_df.sample(n).to_dict("records")

    sim_scores = content_sim[idx]  # memory-mapped float32 array
    top_indices = (-sim_scores).argsort()[1 : n+1]
    return movies_df.iloc[top_indices].to_dict("records")

def get_emotion_recommendations(user_input: str, n: int = 5) -> tuple[str, list]:
    """
    Predict emotion from user_input. Then sample n random movies (genre filtering unsupported without 'genres' column).
    Returns (detected_emotion, [movie_dicts]).
    """
    load_models()
    cleaned = clean_text(user_input)
    detected_emotion = emotion_model.predict([cleaned])[0]
    recommendations = movies_df.sample(n).to_dict("records")
    return detected_emotion, recommendations

def get_top_collaborative_recommendations(user_id, n: int = 5) -> list:
    """
    Predict ratings for all movies in movies_df using the memory-loaded SVD, return top-n.
    """
    load_models()
    try:
        uid = int(user_id)
    except:
        uid = abs(hash(user_id)) % 100_000

    preds = []
    for idx, row in movies_df.iterrows():
        mid = row["id"]
        est = svd_model.predict(uid, mid).est
        preds.append((idx, est))

    top_indices = sorted(preds, key=lambda x: x[1], reverse=True)[:n]
    indices = [i for i, _ in top_indices]
    return movies_df.iloc[indices].to_dict("records")

@recommend_bp.route("/search_suggestions", methods=["GET"])
def search_suggestions():
    """
    Return up to 10 title suggestions matching query substring (case-insensitive).
    """
    load_models()
    query = request.args.get("q", "").strip().lower()
    suggestions = []
    if query:
        mask = movies_df["title_lower"].str.contains(query, na=False)
        filtered = movies_df.loc[mask, ["id", "title"]].head(10)
        suggestions = filtered.to_dict("records")
    return jsonify(suggestions)

@recommend_bp.route("/", methods=["GET"])
@login_required
def recommendations():
    """
    Renders the recommendations page. Two sections:
    1) "results" block if mood/query-based (rec_type != "Only For You")
    2) Always show "Only For You" personalized recommendations below.
    """
    load_models()

    # 1) Personalized "Only For You" from collaborative filtering
    personalized_raw = get_top_collaborative_recommendations(current_user.id, n=10)
    personalized_recs = [enhance_movie_data(m) for m in personalized_raw]
    # Filter out any with missing poster_path
    personalized_recs = [m for m in personalized_recs if m.get("poster_path")]

    # 2) Determine if mood-based or query-based
    main_recs = []
    rec_type = "Only For You"
    detected_emotion = None
    search_query = request.args.get("query", "").strip()
    user_input = request.args.get("user_input", "").strip()

    if user_input:
        detected_emotion, emo_movies = get_emotion_recommendations(user_input, n=10)
        emo_recs = [enhance_movie_data(m) for m in emo_movies]
        main_recs = [m for m in emo_recs if m.get("poster_path")]
        rec_type = f"{detected_emotion.capitalize()} Recommendations"
    elif search_query:
        content_movies = get_content_recommendations(search_query, n=10)
        content_recs = [enhance_movie_data(m) for m in content_movies]
        main_recs = [m for m in content_recs if m.get("poster_path")]
        rec_type = f"Similar to '{search_query}'"

    return render_template(
        "home/recommendations.html",
        recs=main_recs,
        personalized_recs=personalized_recs,
        rec_type=rec_type,
        emotion=detected_emotion,
        search_query=search_query,
        user_input=user_input
    )
