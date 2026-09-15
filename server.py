import os
import json
import uuid
import shutil
import subprocess

from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

DOWNLOAD_DIR = "/tmp/ytdlp_downloads"
COOKIES_FILE = "/etc/secrets/cookies.txt"

YTDLP = "yt-dlp"
FFMPEG = "ffmpeg"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# --------------------------------------------------
# Helper: Check cookies
# --------------------------------------------------

def cookies_available():
    return os.path.isfile(COOKIES_FILE)


# --------------------------------------------------
# Helper: Run yt-dlp
# --------------------------------------------------

def run_ytdlp(url):

    cmd = [
        YTDLP,

        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",

        "--js-runtimes",
        "deno",
    ]

    # Add cookies only when Secret File exists
    if cookies_available():
        cmd.extend([
            "--cookies",
            COOKIES_FILE
        ])

    cmd.append(url)

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180
    )

    if result.returncode != 0:
        raise Exception(
            result.stderr[-5000:]
        )

    return json.loads(result.stdout)


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.get("/")
def home():

    return jsonify({
        "status": "ok",
        "service": "YouTube Downloader API",
        "version": "1.0"
    })


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health():

    return jsonify({
        "status": "healthy"
    })


# --------------------------------------------------
# TEST PAGE
# --------------------------------------------------

@app.get("/test")
def test_page():

    test_file = "/app/test.html"

    if not os.path.exists(test_file):

        return jsonify({
            "success": False,
            "error": "test.html not found"
        }), 404

    try:

        with open(
            test_file,
            "r",
            encoding="utf-8"
        ) as file:

            return file.read()

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# --------------------------------------------------
# YOUTUBE INFO
# --------------------------------------------------

@app.post("/info")
def info():

    data = request.get_json(
        silent=True
    ) or {}

    url = data.get(
        "url",
        ""
    ).strip()

    if not url:

        return jsonify({
            "success": False,
            "error": "YouTube URL is required"
        }), 400

    try:

        info_data = run_ytdlp(url)

        heights = set()

        audio_available = False

        formats = info_data.get(
            "formats",
            []
        )

        for fmt in formats:

            height = fmt.get(
                "height"
            )

            vcodec = fmt.get(
                "vcodec"
            )

            acodec = fmt.get(
                "acodec"
            )

            # Video
            if (
                height
                and vcodec
                and vcodec != "none"
            ):

                try:

                    heights.add(
                        int(height)
                    )

                except (ValueError, TypeError):

                    pass

            # Audio
            if (
                acodec
                and acodec != "none"
            ):

                audio_available = True

        qualities = sorted(
            heights,
            reverse=True
        )

        return jsonify({

            "success": True,

            "title": info_data.get(
                "title"
            ),

            "channel": (
                info_data.get("channel")
                or info_data.get("uploader")
            ),

            "thumbnail": info_data.get(
                "thumbnail"
            ),

            "duration": info_data.get(
                "duration"
            ),

            "qualities": qualities,

            "audio_available":
                audio_available,

            "cookies_enabled":
                cookies_available()

        })

    except subprocess.TimeoutExpired:

        return jsonify({
            "success": False,
            "error": "YouTube information request timed out"
        }), 504

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# --------------------------------------------------
# VIDEO DOWNLOAD
# --------------------------------------------------

@app.post("/download")
def download():

    data = request.get_json(
        silent=True
    ) or {}

    url = data.get(
        "url",
        ""
    ).strip()

    quality = data.get(
        "quality"
    )

    # -----------------------------
    # URL validation
    # -----------------------------

    if not url:

        return jsonify({
            "success": False,
            "error": "YouTube URL is required"
        }), 400

    # -----------------------------
    # Quality validation
    # -----------------------------

    try:

        quality = int(
            quality
        )

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "error": "Invalid quality"
        }), 400

    allowed_qualities = [
        144,
        240,
        360,
        480,
        720,
        1080,
        1440,
        2160
    ]

    if quality not in allowed_qualities:

        return jsonify({
            "success": False,
            "error": "Unsupported quality"
        }), 400

    # -----------------------------
    # Create temporary job folder
    # -----------------------------

    job_id = uuid.uuid4().hex

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    output_template = os.path.join(
        job_dir,
        f"video_{quality}p.%(ext)s"
    )

    # -----------------------------
    # yt-dlp command
    # -----------------------------

    cmd = [

        YTDLP,

        "--no-playlist",
        "--no-warnings",

        "--js-runtimes",
        "deno",

    ]

    # -----------------------------
    # Cookies
    # -----------------------------

    if cookies_available():

        cmd.extend([
            "--cookies",
            COOKIES_FILE
        ])

    # -----------------------------
    # Format
    # -----------------------------

    cmd.extend([

        "-f",

        (
            f"bestvideo[height={quality}]"
            f"+bestaudio/"
            f"best[height={quality}]"
        ),

        "--merge-output-format",
        "mp4",

        "--ffmpeg-location",
        FFMPEG,

        "-o",
        output_template,

        url
    ])

    # -----------------------------
    # Execute
    # -----------------------------

    try:

        result = subprocess.run(

            cmd,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

            timeout=3600
        )

        # -------------------------
        # Error
        # -------------------------

        if result.returncode != 0:

            error_message = (
                result.stderr[-5000:]
                or result.stdout[-5000:]
            )

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({

                "success": False,

                "error": error_message

            }), 500

        # -------------------------
        # Find generated file
        # -------------------------

        files = os.listdir(
            job_dir
        )

        file_path = None

        for filename in files:

            full_path = os.path.join(
                job_dir,
                filename
            )

            if os.path.isfile(
                full_path
            ):

                file_path = full_path

                break

        # -------------------------
        # File not found
        # -------------------------

        if not file_path:

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({

                "success": False,

                "error":
                    "Download file was not created"

            }), 500

        # -------------------------
        # Send file
        # -------------------------

        response = send_file(

            file_path,

            as_attachment=True,

            download_name=
                f"video_{quality}p.mp4"
        )

        # -------------------------
        # Cleanup after download
        # -------------------------

        @response.call_on_close
        def cleanup():

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

        return response

    # -----------------------------
    # Timeout
    # -----------------------------

    except subprocess.TimeoutExpired:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        return jsonify({

            "success": False,

            "error":
                "Download timed out"

        }), 504

    # -----------------------------
    # General error
    # -----------------------------

    except Exception as e:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(

        host="0.0.0.0",

        port=port
    )
