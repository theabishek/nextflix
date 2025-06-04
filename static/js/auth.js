document.addEventListener("DOMContentLoaded", async function () {
    try {
        const TMDB_API_KEY = "YOUR_TMDB_API_KEY";
        const response = await fetch(`https://api.themoviedb.org/3/movie/popular?api_key=${TMDB_API_KEY}`);
        const data = await response.json();
        if (data.results.length > 0) {
            const randomMovie = data.results[Math.floor(Math.random() * data.results.length)];
            const backdropUrl = `https://image.tmdb.org/t/p/original${randomMovie.backdrop_path}`;
            document.querySelector(".auth-background").style.backgroundImage = `url(${backdropUrl})`;
        }
    } catch (error) {
        console.error("Error fetching TMDB backgrounds:", error);
    }
});
