from flask import Flask
from dotenv import load_dotenv
import os, sys
from extensions import login_manager, bcrypt
from pymongo import MongoClient

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")

# Initialize extensions
login_manager.init_app(app)
bcrypt.init_app(app)
login_manager.login_view = "auth.login"

# Initialize MongoDB connection (using Atlas connection string)
client = MongoClient(os.getenv("MONGO_URI"))
db = client['movie_recommendation']
app.config["db"] = db

# Register blueprints for modular routes
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.routes.auth import auth_bp
from src.routes.main import main_bp
from src.routes.movie import movie_bp
from src.routes.recommend import recommend_bp
app.register_blueprint(recommend_bp)

app.register_blueprint(movie_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

