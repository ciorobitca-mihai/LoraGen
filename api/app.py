from flask import Flask, render_template, redirect, url_for, request, session, jsonify
from blueprints.auth.routes import auth_bp
from blueprints.dashboard.routes import dashboard_bp
from blueprints.admin.routes import admin_bp
from blueprints.images.routes import images_bp, init_cache
from os import getenv
import io
from extensions import upload_to_gcs
import requests

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.secret_key = getenv("FLASK_KEY")
    app.config.update(
        SESSION_COOKIE_SAMESITE="None",
        SESSION_COOKIE_SECURE=True,
    )


    init_cache(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(images_bp)

    @app.before_request
    def check_for_maintenance():
        if getenv("MAINTENANCE", "").upper() == "TRUE":
            allowed_users = ["admin@mail.com", "mihaiciorobitca985@gmail.com"]
            
            if request.path.startswith("/api"):
                return None

            if request.path.startswith("/dashboard"):
                if session.get("user") and session["user"] not in allowed_users:
                    return render_template("maintenance.html"), 503
        if not session.get("realtime") and not session.get("is_admin"):
            session.clear()
        return None

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.home"))

    @app.route("/pricing")
    def pricing():
        return render_template("pricing.html")

    @app.route("/success")
    def success():
        return render_template("success.html")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    @app.route("/faq")
    def faq():
        return render_template("faq.html")

    @app.route("/health")
    def health_check():
        return "OK", 200
    
    @app.post("/upload")
    def upload_file():
        try:
            image_url = request.form.get("image_url")
            folder = request.form.get("folder")
            filename = request.form.get("filename")

            if not image_url:
                return jsonify({"error": "Missing image URL"}), 400
            if not folder or not filename:
                return jsonify({"error": "Missing folder or filename"}), 400

            response = requests.get(image_url, stream=True)
            if response.status_code != 200:
                return jsonify({"error": f"Failed to fetch image: {response.status_code}"}), 400

            file_stream = io.BytesIO(response.content)

            public_url = upload_to_gcs(file_stream, folder, filename)

            return jsonify({"url": public_url}), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500


    return app


app = create_app()
