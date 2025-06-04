from flask_login import UserMixin
from bson import ObjectId
from datetime import datetime
from flask import current_app
from extensions import bcrypt, login_manager


class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.email = user_data["email"]
        self.username = user_data.get("username", "")
        self.name = user_data.get("name", "Unknown")  # Default to "Unknown" if name is missing
        self.created_at = user_data.get("created_at", datetime.utcnow())
        self.profile_pic = user_data.get("profile_pic", None)

    @staticmethod
    def create_user(email, password, **kwargs):
        """
        Create a new user and save to the database.
        """
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        user_data = {
            "email": email,
            "password": hashed_pw,
            "created_at": datetime.utcnow(),
            **kwargs
        }
        db = current_app.config["db"]
        try:
            result = db.users.insert_one(user_data)
            return result.inserted_id  # Return the newly created user ID
        except Exception as e:
            print(f"Error creating user: {e}")
            return None

    @staticmethod
    def find_by_email(email):
        """
        Find a user by their email.
        """
        db = current_app.config["db"]
        try:
            return db.users.find_one({"email": email})
        except Exception as e:
            print(f"Error finding user by email: {e}")
            return None

    @staticmethod
    def find_by_username(username):
        """
        Find a user by their username.
        """
        db = current_app.config["db"]
        try:
            return db.users.find_one({"username": username})
        except Exception as e:
            print(f"Error finding user by username: {e}")
            return None

    @staticmethod
    def find_by_phone(phone):
        """
        Find a user by their phone number.
        """
        db = current_app.config["db"]
        try:
            return db.users.find_one({"phone": phone})
        except Exception as e:
            print(f"Error finding user by phone: {e}")
            return None

    @staticmethod
    def check_password(hashed_password, plain_password):
        """
        Check if a plain password matches a hashed password.
        """
        return bcrypt.check_password_hash(hashed_password, plain_password)

    @staticmethod
    def update_user(user_id, updates):
        """
        Update user information based on user_id.
        """
        db = current_app.config["db"]
        try:
            result = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
            return result.modified_count > 0  # Returns True if an update occurred
        except Exception as e:
            print(f"Error updating user: {e}")
            return False

    @staticmethod
    def delete_user(user_id):
        """
        Delete a user from the database based on user_id.
        """
        db = current_app.config["db"]
        try:
            result = db.users.delete_one({"_id": ObjectId(user_id)})
            return result.deleted_count > 0  # Returns True if a deletion occurred
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False


@login_manager.user_loader
def load_user(user_id):
    """
    Flask-Login: Load a user instance from the user ID.
    """
    db = current_app.config["db"]
    try:
        user_data = db.users.find_one({"_id": ObjectId(user_id)})
        if user_data:
            return User(user_data)
        return None
    except Exception as e:
        print(f"Error loading user: {e}")
        return None
