import os
import re
import uuid
import subprocess
from urllib.parse import urlparse

from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

DOWNLOAD_DIR = "/tmp/downloads"
FFMPEG = "ffmpeg"

# Render Environment Variable me ye set karna:
# RENDER_API_KEY = apna-secret-key
API_KEY = os.environ.get("RENDER_API_KEY", "")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def check_api_key():
    if not API_KEY:
        return True

    key = request.headers.get("X-API-Key", "")

    return key == API_KEY


def allowed_stream_url(url):
    """
    Sirf YouTube/Google video stream URLs allow karo.
    Isse Render ko arbitrary URL downloader banne se roka jata hai.
    """

    if not url:
        return False

    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()

        allowed = (
            host.endswith(".googlevideo.com")
            or host == "googlevideo.com"
            or host.endswith(".youtube.com")
            or host == "youtube.com"
        )

        return p.scheme == "https" and allowed

    except Exception:
        return False


def safe_filename(name):
    if not name:
        name = "youtube-video"

    name = re.sub(r'[\\/:*?"<>|]+', "", name)
    name = re.sub(r"\s+", " ", name).strip()

    if not name:
        name = "youtube-video"

    return name[:150]


def run_ffmpeg(args):
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900
    )

    return process.returncode, process.stdout, process.stderr


@app.get("/")
def home():
    return jsonify({
        "success": True,
        "service": "YouTube Stream Downloader",
        "status": "online"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "healthy"
    })


@app.post("/download")
def download():

    if not check_api_key():
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}

    video_url = data.get("video_url", "")
    audio_url = data.get("audio_url", "")
    filename = safe_filename(data.get("filename", "youtube-video"))
    quality = str(data.get("quality", ""))

    if not video_url:
        return jsonify({
            "success": False,
            "error": "video_url is required"
        }), 400

    if not allowed_stream_url(video_url):
        return jsonify({
            "success": False,
            "error": "Invalid video stream URL"
        }), 400

    if audio_url and not allowed_stream_url(audio_url):
        return jsonify({
            "success": False,
            "error": "Invalid audio stream URL"
        }), 400

    job_id = uuid.uuid4().hex

    job_dir = os.path.join(
        DOWNLOAD_DIR,
        job_id
    )

    os.makedirs(job_dir, exist_ok=True)

    video_file = os.path.join(
        job_dir,
        "video_stream"
    )

    audio_file = os.path.join(
        job_dir,
        "audio_stream"
    )

    output_file = os.path.join(
        job_dir,
        filename + ".mp4"
    )

    headers = (
        "User-Agent: Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36\r\n"
        "Referer: https://www.youtube.com/\r\n"
    )

    try:

        # -------------------------------------------------
        # CASE 1
        # Progressive stream
        # Video + Audio already together
        # -------------------------------------------------

        if not audio_url:

            ffmpeg_cmd = [
                FFMPEG,
                "-y",

                "-headers",
                headers,

                "-i",
                video_url,

                "-c",
                "copy",

                "-movflags",
                "+faststart",

                output_file
            ]

            code, stdout, stderr = run_ffmpeg(ffmpeg_cmd)

        # -------------------------------------------------
        # CASE 2
        # Adaptive stream
        # Video + separate Audio
        # -------------------------------------------------

        else:

            # Download video
            video_cmd = [
                FFMPEG,
                "-y",

                "-headers",
                headers,

                "-i",
                video_url,

                "-c",
                "copy",

                video_file
            ]

            code, stdout, stderr = run_ffmpeg(video_cmd)

            if code != 0:
                return jsonify({
                    "success": False,
                    "error": "Video stream download failed",
                    "details": stderr[-4000:]
                }), 500

            # Download audio
            audio_cmd = [
                FFMPEG,
                "-y",

                "-headers",
                headers,

                "-i",
                audio_url,

                "-c",
                "copy",

                audio_file
            ]

            code, stdout, stderr = run_ffmpeg(audio_cmd)

            if code != 0:
                return jsonify({
                    "success": False,
                    "error": "Audio stream download failed",
                    "details": stderr[-4000:]
                }), 500

            # Merge
            merge_cmd = [
                FFMPEG,
                "-y",

                "-i",
                video_file,

                "-i",
                audio_file,

                "-map",
                "0:v:0",

                "-map",
                "1:a:0",

                "-c:v",
                "copy",

                "-c:a",
                "aac",

                "-b:a",
                "128k",

                "-movflags",
                "+faststart",

                output_file
            ]

            code, stdout, stderr = run_ffmpeg(merge_cmd)

        if code != 0:

            return jsonify({
                "success": False,
                "error": "FFmpeg failed",
                "details": stderr[-5000:]
            }), 500

        if not os.path.isfile(output_file):

            return jsonify({
                "success": False,
                "error": "Output file was not created"
            }), 500

        if os.path.getsize(output_file) < 1000:

            return jsonify({
                "success": False,
                "error": "Output file is empty"
            }), 500

        return send_file(
            output_file,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=filename + ".mp4"
        )

    except subprocess.TimeoutExpired:

        return jsonify({
            "success": False,
            "error": "Download timed out"
        }), 504

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        # Cleanup
        try:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
