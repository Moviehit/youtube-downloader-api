import os
import json
import uuid
import shutil
import subprocess

from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

DOWNLOAD_DIR = "/tmp/ytdlp_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

YTDLP = "yt-dlp"
FFMPEG = "ffmpeg"


# --------------------------------------------------
# Run yt-dlp metadata
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
    "--extractor-args",
    "youtube:player_client=android_vr,web_embedded",
    url
]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        raise Exception(result.stderr[-3000:])

    return json.loads(result.stdout)


# --------------------------------------------------
# Home
# --------------------------------------------------

@app.get("/")
def home():
    return jsonify({
        "status": "ok",
        "service": "YouTube Downloader API",
        "version": "1.0"
    })


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "healthy"
    })


# --------------------------------------------------
# Test page
# --------------------------------------------------

@app.get("/test")
def test_page():
    test_file = "/app/test.html"

    if not os.path.exists(test_file):
        return jsonify({
            "success": False,
            "error": "test.html not found"
        }), 404

    with open(test_file, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------
# YouTube video information
# --------------------------------------------------

@app.post("/info")
def info():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()

    if not url:
        return jsonify({
            "success": False,
            "error": "YouTube URL is required"
        }), 400

    try:

        info_data = run_ytdlp(url)

        heights = set()
        audio_available = False

        for fmt in info_data.get("formats", []):

            height = fmt.get("height")
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")

            # Video formats
            if (
                height
                and vcodec
                and vcodec != "none"
            ):
                try:
                    heights.add(int(height))
                except:
                    pass

            # Audio formats
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
            "title": info_data.get("title"),
            "channel": (
                info_data.get("channel")
                or info_data.get("uploader")
            ),
            "thumbnail": info_data.get("thumbnail"),
            "duration": info_data.get("duration"),
            "qualities": qualities,
            "audio_available": audio_available
        })

    except subprocess.TimeoutExpired:

        return jsonify({
            "success": False,
            "error": "Information request timed out"
        }), 504

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# --------------------------------------------------
# Download selected video quality
# --------------------------------------------------

@app.post("/download")
def download():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()
    quality = data.get("quality")

    if not url:
        return jsonify({
            "success": False,
            "error": "YouTube URL is required"
        }), 400

    try:
        quality = int(quality)
    except:

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

    # Unique job folder
    job_id = uuid.uuid4().hex

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    output = os.path.join(
        job_dir,
        f"video_{quality}p.%(ext)s"
    )

    cmd = [
        YTDLP,

        "--no-playlist",
        "--no-warnings",

        "--js-runtimes",
        "deno",

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
        output,

        url
    ]

    try:

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600
        )

        if result.returncode != 0:

            error_message = result.stderr[-3000:]

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "error": error_message
            }), 500

        files = os.listdir(job_dir)

        if not files:

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "error": "Download file was not created"
            }), 500

        # Find actual generated file
        file_path = None

        for filename in files:

            full_path = os.path.join(
                job_dir,
                filename
            )

            if os.path.isfile(full_path):

                file_path = full_path
                break

        if not file_path:

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "error": "Generated file not found"
            }), 500

        response = send_file(
            file_path,
            as_attachment=True,
            download_name=f"video_{quality}p.mp4"
        )

        @response.call_on_close
        def cleanup():

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

        return response

    except subprocess.TimeoutExpired:

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )

        return jsonify({
            "success": False,
            "error": "Download timed out"
        }), 504

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
# Start server
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
