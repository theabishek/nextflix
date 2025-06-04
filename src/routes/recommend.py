from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
import pickle
import pandas as pd
import requests
from .utils import clean_text

recommend_bp = Blueprint("recommend", __name__, url_prefix="/recommend")

# TMDB configuration
TMDB_API_KEY = "1a483b7f5ffd41254a97bd00fa4ee773"
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Emotion-to-genre mapping
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

# Global variables for models and CSV data
emotion_model = None
content_sim = None
svd_model = None
movies_df = None

def load_models():
    global emotion_model, content_sim, svd_model, movies_df
    if emotion_model is None:
        with open("models/emotion_classifier.pkl", "rb") as f:
            emotion_model = pickle.load(f)
    if content_sim is None:
        with open("models/content_similarity.pkl", "rb") as f:
            content_sim = pickle.load(f)
    if svd_model is None:
        with open("models/collaborative_filtering.pkl", "rb") as f:
            svd_model = pickle.load(f)
    if movies_df is None:
        movies_df = pd.read_csv("models/movie_metadata.csv")
        required_columns = ['id', 'title', 'poster_path', 'vote_average', 'release_date', 'genres']
        for col in required_columns:
            if col not in movies_df.columns:
                movies_df[col] = None
        # We ignore the CSV poster_path (force it to an empty string) so we always use TMDB id.
        movies_df['poster_path'] = ""
    return

def get_poster_by_tmdb_id(tmdb_id):
    """Fetch the poster path from TMDB given the movie’s TMDB id."""
    try:
        response = requests.get(
            f"{TMDB_BASE_URL}/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY}
        )
        if response.status_code == 200:
            data = response.json()
            poster_path = data.get("poster_path", "")
            if poster_path and not poster_path.startswith("/"):
                poster_path = "/" + poster_path
            return poster_path
    except Exception as e:
        print(f"Error fetching poster for TMDB id {tmdb_id}: {e}")
    return ""

def get_movie_details_from_tmdb(tmdb_id):
    """Fetch complete movie details from TMDB using the movie's id."""
    try:
        response = requests.get(
            f"{TMDB_BASE_URL}/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY}
        )
        if response.status_code == 200:
            data = response.json()
            poster_path = data.get("poster_path", "")
            if poster_path and not poster_path.startswith("/"):
                poster_path = "/" + poster_path
            return {
                "id": data.get("id"),
                "title": data.get("title"),
                "poster_path": poster_path,
                "vote_average": data.get("vote_average", 0),
                "release_date": data.get("release_date", ""),
                "genres": [g["name"] for g in data.get("genres", [])],
                "overview": data.get("overview", "")
            }
    except Exception as e:
        print(f"Error fetching details for TMDB id {tmdb_id}: {e}")
    return None

def enhance_movie_data(movie):
    """
    Enhance the movie dictionary by overriding the poster_path with the TMDB API value.
    Also updates genres, vote_average, and release_date if missing.
    """
    tmdb_id = movie.get("id")
    if tmdb_id:
        poster = get_poster_by_tmdb_id(tmdb_id)
        movie["poster_path"] = poster
        if not movie.get("genres") or not movie.get("release_date"):
            tmdb_data = get_movie_details_from_tmdb(tmdb_id)
            if tmdb_data:
                movie["genres"] = tmdb_data.get("genres")
                movie["vote_average"] = tmdb_data.get("vote_average")
                movie["release_date"] = tmdb_data.get("release_date")
    return movie

def get_content_recommendations(movie_title, n=5):
    load_models()
    try:
        idx = movies_df[movies_df["title"].str.lower() == movie_title.lower()].index[0]
        sim_scores = list(enumerate(content_sim[idx]))
        sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
        recommended_idxs = [i[0] for i in sim_scores[1:n+1]]
        return movies_df.iloc[recommended_idxs].to_dict("records")
    except Exception as e:
        print(f"Content recommendation error: {e}")
        return movies_df.sample(n).to_dict("records")

def get_emotion_recommendations(user_input, n=5):
    load_models()
    cleaned_input = clean_text(user_input)
    detected_emotion = emotion_model.predict([cleaned_input])[0]
    recommended_genres = EMOTION_GENRE_MAP.get(detected_emotion, ["Popular"])
    if 'genres' in movies_df.columns:
        genre_filtered = movies_df[movies_df["genres"].apply(
            lambda x: any(genre in x for genre in recommended_genres) if isinstance(x, str) else False
        )]
    else:
        genre_filtered = movies_df
    if len(genre_filtered) < n:
        genre_filtered = movies_df
    return genre_filtered.sample(n).to_dict("records")

def get_top_collaborative_recommendations(user_id, n=5):
    load_models()
    try:
        if not isinstance(user_id, int):
            user_id = hash(user_id) % 10000
        movies_df["predicted_rating"] = movies_df["id"].apply(
            lambda mid: svd_model.predict(user_id, mid).est
        )
        top_movies = movies_df.sort_values("predicted_rating", ascending=False).head(n)
        recs = top_movies.to_dict("records")
        return recs
    except Exception as e:
        print(f"Collaborative filtering error: {e}")
        return movies_df.sample(n).to_dict("records")
    finally:
        if "predicted_rating" in movies_df.columns:
            movies_df.drop("predicted_rating", axis=1, inplace=True)

# NEW: Endpoint for search suggestions.
@recommend_bp.route("/search_suggestions", methods=["GET"])
def search_suggestions():
    load_models()
    query = request.args.get("q", "")
    suggestions = []
    if query:
        filtered = movies_df[movies_df["title"].str.contains(query, case=False, na=False)]
        for _, row in filtered.head(10).iterrows():
            suggestions.append({"id": row["id"], "title": row["title"]})
    return jsonify(suggestions)

@recommend_bp.route("/", methods=["GET"])
@login_required
def recommendations():
    load_models()
    personalized_raw = get_top_collaborative_recommendations(current_user.id, n=10)
    personalized_recs = [enhance_movie_data(m) for m in personalized_raw]

    main_recs = []
    rec_type = "Only For You"
    emotion = None
    genres = []

    search_query = request.args.get("query")
    user_input = request.args.get("user_input")
    if user_input:
        cleaned_input = clean_text(user_input)
        emotion = emotion_model.predict([cleaned_input])[0]
        genres = EMOTION_GENRE_MAP.get(emotion, ["Popular"])
        main_raw = get_emotion_recommendations(cleaned_input, n=10)
        main_recs = [enhance_movie_data(m) for m in main_raw]
        # Append the genre names in brackets to the heading.
        rec_type = f"{emotion.capitalize()} Recommendations ({', '.join(genres)})"
    elif search_query:
        main_raw = get_content_recommendations(search_query, n=10)
        main_recs = [enhance_movie_data(m) for m in main_raw]
        rec_type = f"Similar to '{search_query}'"
    return render_template(
        "home/recommendations.html",
        recs=main_recs,
        personalized_recs=personalized_recs,
        rec_type=rec_type,
        emotion=emotion,
        genres=genres,
        search_query=search_query or "",
        user_input=user_input or ""
    )
