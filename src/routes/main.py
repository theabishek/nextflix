from flask import Blueprint, render_template, request, flash, jsonify
import requests
from flask_login import current_user

main_bp = Blueprint('main', __name__, template_folder='templates/home')

@main_bp.route("/")
def index():
    TMDB_API_KEY = "1a483b7f5ffd41254a97bd00fa4ee773"

    # Get trending movies
    trending_url = f"https://api.themoviedb.org/3/trending/movie/week?api_key={TMDB_API_KEY}"
    trending_movies = []
    try:
        trending_response = requests.get(trending_url, timeout=5)
        trending_response.raise_for_status()
        trending_data = trending_response.json()
        trending_movies = trending_data.get("results", [])
    except requests.RequestException as e:
        print(f"Error fetching trending movies: {e}")
        trending_movies = []
        flash(f"Failed to fetch trending movies due to a network error: {str(e)}", 'error')

    return render_template(
        "home/index.html",
        trending_movies=trending_movies,
        is_authenticated=current_user.is_authenticated
    )

@main_bp.route("/search")
def search():
    query = request.args.get("q")
    TMDB_API_KEY = "1a483b7f5ffd41254a97bd00fa4ee773"
    search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
    search_results = []
    try:
        search_response = requests.get(search_url, timeout=5)
        search_response.raise_for_status()
        search_data = search_response.json()
        search_results = search_data.get("results", [])
    except requests.RequestException as e:
        print(f"Error fetching search movies: {e}")
        search_results = []
        flash(f"Failed to fetch search movies due to a network error: {str(e)}", 'error')

    return render_template(
        "home/search.html",
        search_results=search_results,
        query=query,
        is_authenticated=current_user.is_authenticated,
        page_name="Search Results"  # Add the page name here
    )

@main_bp.route("/autocomplete")
def autocomplete():
    TMDB_API_KEY = "1a483b7f5ffd41254a97bd00fa4ee773"
    query = request.args.get("q", "")
    suggestions = []
    if query:
        search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
        try:
            response = requests.get(search_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            for movie in data.get("results", [])[:8]:
                suggestions.append({
                    "title": movie.get("title"),
                    "year": movie.get("release_date", "")[:4],
                    "poster": f"https://image.tmdb.org/t/p/w92{movie.get('poster_path')}" if movie.get("poster_path") else "",
                    "id": movie.get("id"),
                })
        except requests.RequestException as e:
            print(f"Error in autocomplete: {e}")
    return jsonify({"results": suggestions})

