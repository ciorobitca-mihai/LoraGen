from flask import (
    Blueprint,
    render_template,
    request,
    session,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    Response, 
    stream_with_context
)
import json
import zipfile
import io
from extensions import supabase, supabase_admin
import logging, traceback
from functools import wraps
import uuid
import asyncio
import httpx
from extensions import *
import requests
from io import BytesIO

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

STORAGE_LINK = "https://storage.googleapis.com/secret-api/storage"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id", False):
            return redirect(url_for("auth.login_get"))
        try:
            user_id = session["user_id"]
            user = supabase_admin.auth.admin.get_user_by_id(user_id).user
            if not user:
                session.clear()
                return redirect(url_for("auth.login_get"))
        except Exception as e:
            session.clear()
            return redirect(url_for("auth.login_get"))
        return f(user.user_metadata, *args, **kwargs)

    return decorated_function

download_progress = {}  # simple in-memory dict: {email: {"current": X, "total": Y}}

@dashboard_bp.get("/jobs/download/progress")
@login_required
def download_progress_status(user):
    email = session["user"]
    prog = download_progress.get(email, {"current": 0, "total": 0})
    return jsonify(prog)


@dashboard_bp.get("/")
@login_required
def home(user):
    email = session["user"]

    credits = int(user.get("credits") or 0)

    all_files = (
        supabase_admin.table("my_images")
        .select("id")
        .eq("email", email)
        .order("created_at", desc=True) 
        .execute()
        .data
    )

    images = [
        {
            "id": f["id"],
            "url": f"{STORAGE_LINK}/{email}/my_images/{f['id']}.jpeg"
        }
        for f in all_files
    ]

    max_repeat = min(5, credits)
    return render_template(
        "dashboard/dashboard.html",
        user=user,
        restricted=not user.get("email_verified"),
        images=images,
        credits=credits,
        max_repeat=max_repeat,
    )


@dashboard_bp.post("/")
@login_required
def post_home(user):
    email = session["user"]
    user_id = session["user_id"]
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request"}), 400

    prompt = data.get("prompt")
    repeat = int(data.get("repeat", 1))
    selected_images = data.get("images", [])
    width = int(data.get("width"))
    height = int(data.get("height"))
    selected_type = data.get("type")

    session_values = {
        "last_prompt": prompt,
        "last_selected_images": selected_images,
        "last_width": width,
        "last_height": height,
        "last_repeat": repeat,
        "last_resolution": data.get("resolution", "1:1-1K"),
        "last_type": selected_type ,
    }

    for key, value in session_values.items():
        if session.get(key) != value:
            session[key] = value
            session["modified"] = True

    if session.get("modified", False):
        resp = supabase_admin.auth.admin.get_user_by_id(user_id)
        current_metadata = resp.user.user_metadata or {}
        current_metadata["last_data"] = {
            "last_prompt": prompt,
            "last_selected_images": selected_images,
            "last_width": width,
            "last_height": height,
            "last_repeat": repeat,
            "last_resolution": data.get("resolution", "1:1-1K"),
            "last_type": selected_type ,
        }

        supabase_admin.auth.admin.update_user_by_id(
            user_id, {"user_metadata": current_metadata}
        )

    credits = int(user.get("credits") or 0)

    if user.get("disabled") == "True":
        return jsonify({"error": "Your account is temporarily disabled."}), 403

    if credits <= 0:
        return jsonify({"error": "No credits left."}), 403

    url = "https://secret-api-gt36.onrender.com/webhook/generate-image"

    async def send_request(payload):
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json=payload, timeout=60)
                return True
            except Exception as e:
                logging.error(
                    "Image generation failed: %s\n%s", e, traceback.format_exc()
                )
                return False

    async def send_multiple_requests():
        tasks = []
        images = [
            f"{STORAGE_LINK}/{email}/my_images/{id}.jpeg"
            for id in selected_images
        ]
        for _ in range(repeat):
            unique_id = str(uuid.uuid4())
            payload = {
                "email": email,
                "id": unique_id,
                "prompt": prompt,
                "data": [
                    {
                        "taskType": "imageInference",
                        "taskUUID": unique_id,
                        "numberResults": 1,
                        "outputFormat": "JPEG",
                        "width": width,
                        "height": height,
                        "outputType": ["URL"],
                        "referenceImages": images,
                        "model": "bytedance:5@0" if selected_type == "NSFW" else "google:4@2",
                        "positivePrompt": prompt,
                    }
                ],
            }
            print(payload)
            tasks.append(send_request(payload))
        return await asyncio.gather(*tasks)

    results = asyncio.run(send_multiple_requests())

    if all(results):
        new_credits = max(credits - repeat, 0)
        try:
            resp = supabase_admin.auth.admin.get_user_by_id(user_id)
            current_metadata = resp.user.user_metadata or {}
            current_metadata["credits"] = new_credits

            supabase_admin.auth.admin.update_user_by_id(
                user_id, {"user_metadata": current_metadata}
            )
            return jsonify({"message": f"{repeat} job(s) submitted successfully."})
        except Exception as e:
            logging.error(f"Failed to update credits: {e}")
            return jsonify({"error": "Job submitted but credits not updated."}), 500
    else:
        return jsonify({"error": "Some jobs failed to submit."}), 500


@dashboard_bp.get("/jobs/")
@login_required
def jobs(user):
    email = session["user"]

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 12))

    start = (page - 1) * per_page
    end = page * per_page - 1

    response = (
        supabase_admin.table("generated_images")
        .select("status")
        .eq("email", email)
        .execute()
    )

    jobs = response.data if response.data else []
    session["pending"] = len([job for job in jobs if job["status"] == "pending"])
    session["failed"] = len([job for job in jobs if job["status"] == "failed"])
    session["completed"] = len(
        [job for job in jobs if job["status"] == "completed"]
    )
    session["total"] = session["pending"] + session["failed"] + session["completed"]

    response = (
        supabase_admin.table("generated_images")
        .select("id, created_at, email, prompt, status, message")
        .eq("email", email)
        .order("created_at", desc=True)
        .range(start, end)
        .execute()
    )

    jobs = response.data if response.data else []

    return render_template(
        "dashboard/jobs.html",
        jobs=jobs,
        user=user,
        page=page,
        per_page=per_page,
        storage_link=STORAGE_LINK
    )


@dashboard_bp.get("/jobs/count")
@login_required
def job_count(user):
    email = session["user"]

    resp = (
        supabase_admin.table("generated_images")
        .select("id", count="exact")
        .eq("email", email)
        .eq("status", "completed")
        .execute()
    )

    return jsonify({"total_completed": resp.count})


@dashboard_bp.post("/jobs/")
@login_required
def post_jobs(user):
    email = session["user"]

    job_ids = request.json.get("job_ids")
    if not job_ids:
        return jsonify({"success": False, "message": "No jobs selected"}), 400

    deleted_jobs = []
    errors = []

    for job_id in job_ids:
        try:
            supabase_admin.table("generated_images").delete().eq("email", email).eq(
                "id", job_id
            ).execute()
            path = f"/storage/{email}/generated_images/{job_id}.jpeg"
            delete_from_gcs(path)

            deleted_jobs.append(job_id)
        except Exception as e:
            errors.append({"job_id": job_id, "error": str(e)})

    try:
        response = (
            supabase_admin.table("generated_images")
            .select("status")
            .eq("email", email)
            .execute()
        )
        jobs = response.data if response.data else []

        session["pending"] = len([job for job in jobs if job["status"] == "pending"])
        session["failed"] = len([job for job in jobs if job["status"] == "failed"])
        session["completed"] = len(
            [job for job in jobs if job["status"] == "completed"]
        )
        session["total"] = session["pending"] + session["failed"] + session["completed"]
    except Exception as e:
        logging.error(f"Failed to update session counts: {e}")

    return jsonify(
        {
            "success": True,
            "deleted_jobs": deleted_jobs,
            "errors": errors,
            "message": f"{len(deleted_jobs)} job(s) deleted successfully",
        }
    )


@dashboard_bp.delete("/jobs")
@login_required
def delete_all_jobs(user):
    email = session["user"]

    try:
        response = (
            supabase_admin.table("generated_images")
            .select("id")
            .eq("email", email)
            .execute()
        )

        job_rows = response.data or []
        job_ids = [row["id"] for row in job_rows]

        if not job_ids:
            return (
                jsonify({"success": False, "message": "No jobs found to delete."}),
                404,
            )

        deleted_files = []
        errors = []

        for job_id in job_ids:
            path = f"/{email}/generated_images/{job_id}.jpeg"
            try:
                delete_from_gcs(path)
                deleted_files.append(path)
            except Exception as e:
                errors.append({"job_id": job_id, "error": str(e)})

        supabase_admin.table("generated_images").delete().eq("email", email).execute()

        session["total"] = 0
        session["pending"] = 0
        session["completed"] = 0
        session["failed"] = 0

        return (
            jsonify(
                {
                    "success": True,
                    "deleted_jobs": job_ids,
                    "deleted_files": deleted_files,
                    "errors": errors,
                    "message": f"Deleted {len(job_ids)} job(s) and related files successfully.",
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify({"success": False, "message": f"Error deleting jobs: {str(e)}"}),
            500,
        )


@dashboard_bp.post("/jobs/download")
@login_required
def download_all_jobs(user):
    email = session["user"]

    try:
        response = (
            supabase_admin.table("generated_images")
            .select("id, status")
            .eq("email", email)
            .execute()
        )
        job_rows = response.data or []
        completed_jobs = [row["id"] for row in job_rows if row["status"] == "completed"]

        if not completed_jobs:
            return jsonify({"success": False, "message": "No completed jobs found"}), 404

        # initialize progress
        download_progress[email] = {"current": 0, "total": len(completed_jobs)}

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, job_id in enumerate(completed_jobs, start=1):
                image_url = f"{STORAGE_LINK}/{email}/generated_images/{job_id}.jpeg"
                try:
                    resp = requests.get(image_url, stream=True)
                    if resp.status_code == 200:
                        zf.writestr(f"{job_id}.jpeg", resp.content)
                except Exception as e:
                    print(f"❌ Error fetching {image_url}: {e}")

                # update progress
                download_progress[email]["current"] = i

        memory_file.seek(0)

        # remove progress after download
        download_progress[email] = {"current": download_progress[email]["total"], "total": download_progress[email]["total"]}

        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name="all_jobs.zip"
        )

    except Exception as e:
        print("❌ Error creating ZIP:", e)
        return jsonify({"success": False, "message": str(e)}), 500


@dashboard_bp.get('/jobs/download/<job_id>')
@login_required
def download_job(user, job_id):
    email = session["user"]
    url = f"{STORAGE_LINK}/{email}/generated_images/{job_id}.jpeg"
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        return f"Failed to fetch image: {resp.status_code}", 404

    return send_file(
        BytesIO(resp.content),
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=f"{job_id}.jpeg"
    )

@dashboard_bp.get("/profile/")
@login_required
def profile(user):
    return render_template("dashboard/profile.html", user=user)


@dashboard_bp.post("/profile/")
@login_required
def update_profile(user):
    user_id = session["user_id"]
    print(user_id)
    data = request.get_json()

    full_name = data.get("full_name", "").strip()
    password = data.get("password", "").strip()

    if full_name:
        supabase_admin.auth.admin.update_user_by_id(
            user_id, {"user_metadata": {"full_name": full_name}}
        )
    if password:
        supabase_admin.auth.admin.update_user_by_id(user_id, {"password": password})

    return jsonify({"message": "Profile updated successfully."}), 200


@dashboard_bp.get("/basket/")
@login_required
def basket_get(user):
    email = session["user"]
    all_files = (
        supabase_admin.table("my_images")
        .select("id")
        .eq("email", email)
        .order("created_at", desc=True) 
        .execute()
        .data
    )

    images = [
        {
            "id": f["id"],
            "url": f"{STORAGE_LINK}/{email}/my_images/{f['id']}.jpeg",
        }
        for f in all_files
    ]

    return render_template("dashboard/basket.html", user=user, images=images)


@dashboard_bp.post("/basket/")
@login_required
def basket_post(user):
    email = session["user"]
    uploaded_files = request.files.getlist("new_images")

    if not uploaded_files:
        return jsonify({"success": False, "message": "No files uploaded"}), 400

    uploaded_ids = []

    for file in uploaded_files:
        if file and file.filename:
            filename = f"{uuid.uuid4()}.jpeg"
            file.stream.seek(0)
            upload_to_gcs(
                file.stream, f"/storage/{email}/my_images", filename
            )
            supabase_admin.table("my_images").insert(
                {"email": email, "id": filename[:-5]}
            ).execute()

            uploaded_ids.append(filename[:-5])

    return (
        jsonify(
            {
                "success": True,
                "message": f"Uploaded {len(uploaded_ids)} image(s) successfully.",
                "uploaded": uploaded_ids,
            }
        ),
        200,
    )


@dashboard_bp.delete("/basket/")
@login_required
def delete_image(user):
    try:
        to_delete = request.json.get("delete_images", [])
        print(to_delete)
        email = session["user"]

        deleted = []

        for image_id in to_delete:
            path = f"/storage/{email}/my_images/{image_id}.jpeg"
            delete_from_gcs(path)
            result = (
                supabase_admin.table("my_images")
                .delete()
                .eq("email", email)
                .eq("id", image_id)
                .execute()
            )
            deleted.append(image_id)
        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Deleted {len(deleted)} image(s).",
                    "deleted_ids": deleted,
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify({"success": False, "message": f"Error deleting images: {str(e)}"}),
            500,
        )


@dashboard_bp.post("/reset_password")
def reset():
    password = request.form.get("password")
    try:
        supabase.auth.update_user({"password": password})
        flash("Password reset succesfully.", "reset_success")
    except Exception as e:
        flash(str(e), "reset_danger")
    return redirect(url_for("dashboard.dashboard_user"))
