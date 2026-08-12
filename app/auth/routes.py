from flask import render_template, request, redirect, url_for, flash, session

from app.services.auth import (
    admin_exists, get_admin, create_admin, verify_password,
    is_locked, register_failed_login, register_successful_login,
    LOCKOUT_MINUTES,
)
from . import auth_bp


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if not admin_exists():
        return redirect(url_for("auth.setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = get_admin(username)

        if admin and is_locked(admin):
            flash(
                f"Too many failed login attempts. This account is locked "
                f"for {LOCKOUT_MINUTES} minutes.",
                "error",
            )
        elif admin and verify_password(password, admin["password_hash"]):
            register_successful_login(admin["id"])
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            flash(f"Welcome back, {username}.", "success")
            return redirect(request.args.get("next") or url_for("admin.dashboard"))
        else:
            if admin:
                register_failed_login(admin["id"])
            flash("Invalid username or password.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if admin_exists():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        errors = []
        if not username:
            errors.append("Username is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template("auth/setup.html", errors=errors, username=username)

        create_admin(username, password)
        admin = get_admin(username)
        session["admin_id"] = admin["id"]
        session["admin_username"] = username
        flash(f"Admin account '{username}' created. You're logged in.", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("auth/setup.html", errors=[], username="")
