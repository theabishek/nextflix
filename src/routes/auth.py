import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, current_user, login_required
from bson import ObjectId
from flask_bcrypt import Bcrypt
from src.models.user_model import User  # Assumed to use User model from your PDF

bcrypt = Bcrypt()
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# LOGIN ROUTE
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        identifier = request.form.get("email_or_username")  # Can be email or username
        password = request.form.get("password")
        db = current_app.config["db"]

        # Find user by email or username
        user_data = db.users.find_one({"$or": [{"email": identifier}, {"username": identifier}]})
        if user_data and User.check_password(user_data["password"], password):
            login_user(User(user_data))
            flash("Login successful!", "success")
            return redirect(url_for("main.index"))

        flash("Invalid username/email or password!", "danger")

    return render_template("auth/login.html")


# REGISTER ROUTE
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        email = request.form.get("email")
        username = request.form.get("username")
        phoneNumber = request.form.get("phoneNumber")  # Changed to match form
        password = request.form.get("password")
        name = request.form.get("name")
        country = request.form.get("country")  # Already correct
        profile_pic_url = request.form.get("profile_pic")
        genres = request.form.getlist("genres")

        db = current_app.config["db"]

        # Validate email, username, and phoneNumber
        if User.find_by_email(email):
            flash("Email already exists!", "danger")
            return redirect(url_for("auth.register"))
        if db.users.find_one({"username": username}):
            flash("Username already taken! Please choose another.", "danger")
            return redirect(url_for("auth.register"))
        if db.users.find_one({"phoneNumber": phoneNumber}):
            flash("Phone number is already registered!", "warning")
            return redirect(url_for("auth.register"))

        # Handle avatar: Extract only filename if provided
        if profile_pic_url:
            profile_pic = os.path.basename(profile_pic_url)
        else:
            # Fallback to a default avatar URL if needed
            profile_pic = f"avatar1.png"

        user_data = {
            "email": email,
            "username": username,
            "phoneNumber": phoneNumber,  # Store as phoneNumber
            "password": bcrypt.generate_password_hash(password).decode("utf-8"),
            "name": name,
            "country": country,  # Store as country
            "genres": genres,
            "profile_pic": profile_pic,
            "created_at": datetime.utcnow(),
        }

        db.users.insert_one(user_data)
        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# LOGOUT ROUTE
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


# EDIT PROFILE ROUTE
@auth_bp.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():

    db = current_app.config["db"]
    user_id = current_user.get_id()
    user = db.users.find_one({"_id": ObjectId(user_id)})

    if request.method == "POST":
        updates = {}

        # Retrieve form data – note: ensure your profile_edit.html inputs use these names.
        name = request.form.get("name")
        username = request.form.get("username")
        email = request.form.get("email")
        phoneNumber = request.form.get("phoneNumber")
        country = request.form.get("country")  # expecting input name "country"
        profile_pic = request.form.get("profile_pic")  # Selected avatar

        # Update only modified fields
        if name and name != user["name"]:
            updates["name"] = name
        if username and username != user["username"]:
            updates["username"] = username
        if email and email != user["email"]:
            updates["email"] = email
        if phoneNumber and phoneNumber != user.get("phoneNumber", ""):
            updates["phoneNumber"] = phoneNumber
        if country and country != user.get("country", ""):
            updates["country"] = country        # Update as country

        # Update avatar if changed
        if profile_pic and profile_pic != user.get("profile_pic", ""):
            updates["profile_pic"] = profile_pic

        # Handle password update if provided
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        if password and confirm_password and password == confirm_password:
            updates["password"] = bcrypt.generate_password_hash(password).decode("utf-8")

        if updates:
            db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
            flash("Profile updated successfully!", "success")
        else:
            flash("No changes detected.", "info")

        return redirect(url_for("auth.edit_profile"))

    return render_template("home/profile_edit.html", user=user)


# CHANGE PASSWORD ROUTE
@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        db = current_app.config["db"]

        user_data = db.users.find_one({"_id": ObjectId(current_user.get_id())})

        if not User.check_password(user_data["password"], current_password):
            flash("Incorrect current password!", "danger")
            return redirect(url_for("auth.change_password"))

        if new_password != confirm_password:
            flash("Passwords do not match!", "danger")
            return redirect(url_for("auth.change_password"))

        db.users.update_one(
            {"_id": ObjectId(current_user.get_id())},
            {"$set": {"password": bcrypt.generate_password_hash(new_password).decode("utf-8")}}
        )
        flash("Password updated successfully!", "success")
        return redirect(url_for("auth.edit_profile"))

    return render_template("auth/change_password.html")


# DELETE ACCOUNT ROUTE
@auth_bp.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    db = current_app.config["db"]
    user_id = current_user.get_id()
    password = request.form.get("confirm_delete_password")
    user_data = db.users.find_one({"_id": ObjectId(user_id)})

    if not User.check_password(user_data["password"], password):
        flash("Incorrect password. Account deletion failed!", "danger")
        return redirect(url_for("auth.edit_profile"))

    db.users.delete_one({"_id": ObjectId(user_id)})
    flash("Your account has been deleted.", "success")
    logout_user()
    return redirect(url_for("main.index"))
