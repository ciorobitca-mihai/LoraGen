from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from urllib.parse import urlencode
from extensions import *
from utils.supabase_helpers import user_exists
from os import getenv
from requests import post

ADMIN_EMAIL = getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = getenv("ADMIN_PASSWORD")
HCAPTCHA_SITE_KEY = getenv("HCAPTCHA_SITE_KEY")
HCAPTCHA_SECRET = getenv("HCAPTCHA_SECRET")


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.get("/login")
def login_get():
    if "user" in session:
        return redirect(url_for("dashboard.home"))
    elif "is_admin" in session:
        return redirect(url_for("admin.home"))
    return render_template("auth/login.html")


@auth_bp.post("/login")
def login_post():
    # Expect JSON only
    if not request.is_json:
        return jsonify({"success": False, "message": "Request must be JSON"}), 400

    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return (
            jsonify({"success": False, "message": "Email and password are required"}),
            400,
        )

    # Admin login
    if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"success": True, "redirect": url_for("admin.home")})

    try:
        resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        user, session_data = resp.user, resp.session
        if user and session_data:
            session["user"] = user.email
            session["user_id"] = user.id
            session["access_token"] = session_data.access_token
            session["refresh_token"] = session_data.refresh_token
            session["realtime"] = True

            resp = supabase_admin.auth.admin.get_user_by_id(user.id)
            current_metadata = resp.user.user_metadata or {}
            if current_metadata.get("last_data", False):
                for key, value in current_metadata.get("last_data").items():
                    if session.get(key) != value:
                        session[key] = value
                        session["modified"] = True

            return jsonify({"success": True, "redirect": url_for("dashboard.home")})

        return jsonify({"success": False, "message": "Invalid email or password"}), 401
    except Exception as e:
        return jsonify({"success": False, "message": f"Login failed: {str(e)}"}), 500


@auth_bp.get("/register")
def register_get():
    if "user" in session:
        return redirect(url_for("dashboard.home"))
    elif "is_admin" in session:
        return redirect(url_for("admin.home"))
    return render_template("auth/register.html", HCAPTCHA_SITE_KEY=HCAPTCHA_SITE_KEY)


@auth_bp.post("/register")
def register_post():
    data = request.get_json() or request.form

    email = data.get("email")
    password = data.get("password")
    fname = data.get("fname")
    lname = data.get("lname")
    hcaptcha_token = data.get("h-captcha-response")

    if user_exists(email):
        return jsonify({"success": False, "message": "This email is already registered. Please log in."}), 400

    if request.remote_addr != "127.0.0.1":
        verify_url = "https://hcaptcha.com/siteverify"
        payload = {
            "secret": HCAPTCHA_SECRET,
            "response": hcaptcha_token,
            "remoteip": request.remote_addr,
        }
        resp = post(verify_url, data=payload).json()
        if not resp.get("success"):
            return jsonify({"success": False, "message": "Captcha verification failed. Try again."}), 400

    try:
        resp = supabase.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {"full_name": f"{fname} {lname}", "disabled": "True"},
                    "email_redirect_to": request.url_root.rstrip("/") + "/auth/login",
                },
            }
        )

        user = getattr(resp, "user", None)
        if not user:
            return jsonify({"success": False, "message": "User registration failed."}), 500

        try:
            email = user.email
            subfolders = ["my_images", "generated_images"]
            create_gcs_folder(f"/storage/{email}")
            for sub in subfolders:
                create_gcs_folder(f"/storage/{email}/{sub}")
        except Exception as e:
            print(f"pCloud storage setup error: {e}")

        return jsonify({"success": True, "message": "Registration successful! Please verify your email."}), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Registration failed: {str(e)}"}), 500

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@auth_bp.route("/login/google")
def login_google():
    try:
        response = supabase.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": url_for("auth.google_callback", _external=True),
                    "query_params": {"prompt": "select_account"},
                },
            }
        )
        return redirect(response.url)
    except Exception as e:
        # Return JSON instead of flashing
        return jsonify({"success": False, "message": f"Google login setup failed: {str(e)}"}), 400


@auth_bp.route("/google/callback")
def google_callback():
    code = request.args.get("code")
    next_url = request.args.get("next", "/dashboard")

    def redirect_with_error(message):
        params = urlencode({"error": message})
        return redirect(f"/auth/login?{params}")

    if not code:
        return redirect_with_error("Google login failed. No authorization code.")

    try:
        response = supabase.auth.exchange_code_for_session({"auth_code": code})
        if not response.user:
            return redirect_with_error("Google login failed: no user returned.")

        user = response.user

        try:
            session["user"] = user.email
            session["user_id"] = user.id
            session["access_token"] = response.session.access_token
            session["refresh_token"] = response.session.refresh_token
            session["realtime"] = True
        except Exception as e:
            return redirect_with_error(f"Login failed: unable to set session data. {str(e)}")

        try:
            resp = supabase_admin.auth.admin.get_user_by_id(user.id)
            current_metadata = resp.user.user_metadata or {}
            if current_metadata.get("last_data", False):
                for key, value in current_metadata.get("last_data").items():
                    if session.get(key) != value:
                        session[key] = value
                        session["modified"] = True
        except Exception as e:
            return redirect_with_error(f"Login failed: unable to sync user metadata. {str(e)}")

        try:
            if not user.user_metadata.get("disabled"):
                supabase_admin.auth.admin.update_user_by_id(
                    user.id, {"user_metadata": {"disabled": "True"}}
                )
                subfolders = ["my_images", "generated_images"]
                create_gcs_folder(f"/storage/{user.email}")
                for sub in subfolders:
                    create_gcs_folder(f"/storage/{user.email}/{sub}")
        except Exception as e:
            print(f"pCloud storage setup error: {e}")

        return redirect(next_url)

    except Exception as e:
        return redirect_with_error(f"Google login failed: {str(e)}")


@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    if "user" not in session:
        flash("You must be logged in to reset your password.", "login_danger")
        return redirect(url_for("auth.login"))

    new_password = request.form.get("new_password")

    if not new_password or len(new_password) < 6:
        flash("Password must be at least 6 characters long.", "login_danger")
        return redirect(url_for("dashboard.profile"))

    try:
        user = supabase.auth.get_user(session["access_token"]).user

        if not user:
            flash("User not found.", "error")
            return redirect(url_for("dashboard.profile"))

        supabase.auth.update_user({"password": new_password})

        flash("Password reset successfully ✅", "success")
        return redirect(url_for("dashboard.profile"))

    except Exception as e:
        flash("Something went wrong while resetting password.", "error")
        return redirect(url_for("dashboard.profile"))


@auth_bp.get("/resend")
def resend_get():
    return render_template("auth/resend.html")


@auth_bp.post("/resend")
def resend_post():
    email = request.form.get("email")

    try:
        users = supabase_admin.auth.admin.list_users()
        user = next((user for user in users if user.email == email), None)

        if not user:
            flash("No account found with that email.", "resend_danger")
            return redirect(url_for("auth.resend_get"))

        if user.user_metadata.get("email_confirmed") or user.confirmed_at:
            flash("Your email is already confirmed. Please log in.", "login_warning")
            return redirect(url_for("auth.login_get"))

        supabase_admin.auth.admin.generate_link(
            {
                "type": "signup",
                "email": email,
                "options": {
                    "email_redirect_to": url_for("auth.login_get", _external=True)
                },
            }
        )
        flash(
            "A new confirmation email has been sent. Check your inbox.", "login_success"
        )
        return redirect(url_for("auth.login_get"))

    except Exception as e:
        flash(f"Failed to resend confirmation email: {str(e)}", "resend_danger")

    return redirect(url_for("auth.resend_get"))
