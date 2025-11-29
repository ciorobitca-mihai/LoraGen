from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from extensions import supabase_admin

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def login_required_admin(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "is_admin" not in session:
            return redirect(url_for("auth.login_get"))
        return f(*args, **kwargs)

    return decorated_function


@admin_bp.post("/impersonate")
@login_required_admin
def impersonate():
    user_id = request.form.get("user_id")
    if not user_id:
        flash("User ID missing.", "danger")
        return redirect(url_for("admin.home"))

    user = supabase_admin.auth.admin.get_user_by_id(user_id).user
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin.home"))

    session["user_id"] = user.id
    session["user"] = user.email
    session["realtime"] = True

    flash(f"You are now impersonating {user.email}.", "info")
    return redirect(url_for("dashboard.home"))


@admin_bp.post("/stop_impersonation")
@login_required_admin
def stop_impersonation():
    session.clear()
    session["is_admin"] = True
    flash("Stopped impersonation. You are back as admin.", "success")
    return redirect(url_for("admin.home"))


@admin_bp.get("/")
@login_required_admin
def home():
    response = supabase_admin.auth.admin.list_users()
    return render_template("admin/admin.html", users=response)


@admin_bp.post("/verify")
@login_required_admin
def verify():
    user_id = request.form["user_id"]
    try:
        supabase_admin.auth.admin.update_user_by_id(user_id, {"email_confirm": True})
        flash("User verification updated.", "success")
    except Exception as e:
        flash(f"Error updating server ID: {str(e)}", "danger")
    return redirect(url_for("admin.home"))


@admin_bp.post("/disable")
@login_required_admin
def disable():
    user_id = request.form["user_id"]
    disabled_str = request.form["disabled"]
    disabled_bool = "True" if disabled_str == "False" else "False"
    try:
        supabase_admin.auth.admin.update_user_by_id(
            user_id, {"user_metadata": {"disabled": disabled_bool}}
        )
        flash("User verification updated.", "success")
    except Exception as e:
        flash(f"Error updating server ID: {str(e)}", "danger")
    return redirect(url_for("admin.home"))


@admin_bp.post("/delete_user")
@login_required_admin
def delete_user():
    user_id = request.form.get("user_id")
    try:
        supabase_admin.auth.admin.delete_user(user_id)
        flash("User deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting user: {str(e)}", "danger")
    return redirect(url_for("admin.home"))


@admin_bp.post("/update_credits")
@login_required_admin
def update_credits():
    user_id = request.form.get("user_id")
    credits = request.form.get("credits")

    if not user_id or credits is None:
        flash("Invalid request", "danger")
        return redirect(url_for("admin.home"))

    try:
        credits_int = int(credits)
        supabase_admin.auth.admin.update_user_by_id(
            user_id, {"user_metadata": {"credits": credits_int}}
        )
        flash("User credits updated successfully.", "success")
    except ValueError:
        flash("Credits must be a number.", "danger")
    except Exception as e:
        flash(f"Error updating credits: {str(e)}", "danger")

    return redirect(url_for("admin.home"))
