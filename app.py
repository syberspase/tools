#!/usr/bin/env python3
"""
Video streaming server with browser-compatible playback.
Only serves MP4 (H.264/AAC) files that browsers can play.
"""

import os
import magic
from flask import Flask, render_template_string, abort, Response, request, url_for
from urllib.parse import quote

app = Flask(__name__)

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------
VIDEO_ROOT = "/media/lius/shep-protected/Videos/movies"
mime = magic.Magic(mime=True)

# Only allow MP4 with H.264 video + AAC audio
SUPPORTED_PATTERN = "video/mp4"  # We'll check codec separately if needed

# ----------------------------------------------------------------------
# Helper: Recursively collect browser-playable videos
# ----------------------------------------------------------------------
def is_browser_playable(filepath):
    try:
        m = mime.from_file(filepath)
        if m != "video/mp4":
            return False
        # Optional: use ffprobe to check codec (advanced)
        # For now, assume .mp4 = playable if it's not corrupted
        return True
    except:
        return False

def list_videos_recursive():
    videos = []
    if not os.path.isdir(VIDEO_ROOT):
        return videos

    for root, dirs, files in os.walk(VIDEO_ROOT):
        dirs.sort(key=str.lower)
        for file in sorted(files, key=str.lower):
            if file.lower().endswith('.mp4'):
                fullpath = os.path.join(root, file)
                rel_path = os.path.relpath(fullpath, VIDEO_ROOT)
                if is_browser_playable(fullpath):
                    videos.append(rel_path)
                else:
                    print(f"Skipping (not browser-playable): {rel_path}")
    return videos

# ----------------------------------------------------------------------
# Build folder tree
# ----------------------------------------------------------------------
def build_tree():
    tree = {}
    videos = list_videos_recursive()
    for video in videos:
        parts = video.split(os.sep)
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {'_type': 'folder', '_children': {}}
            current = current[part]['_children']
        current[parts[-1]] = {'_type': 'file', 'path': video}
    return tree

# ----------------------------------------------------------------------
# HTML Template
# ----------------------------------------------------------------------
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Video Library</title>
  <style>
    body {font-family: Arial, sans-serif; margin: 2rem; background:#f9f9f9; color:#333;}
    h1 {color:#222;}
    .tree {line-height: 1.6;}
    .folder > a {color: #0066cc; text-decoration: none; font-weight: bold;}
    .folder > a:hover {text-decoration: underline;}
    .file > a {color: #d14; text-decoration: none;}
    .file > a:hover {text-decoration: underline;}
    .indent {margin-left: 1.5rem;}
    video {width:100%; max-width:900px; margin-top:2rem; background:#000; border:1px solid #ccc;}
    .back {margin-bottom: 1rem;}
    .back a {color: #666; text-decoration: none;}
    .back a:hover {text-decoration: underline;}
    .warning {color: #b33; font-size: 0.9rem; margin-top: 2rem; padding: 1rem; background: #fff8f8; border-left: 4px solid #b33;}
  </style>
</head>
<body>
  <h1>Video Library</h1>

  {% if current_path != '.' %}
    <div class="back">
      <a href="{{ parent_url }}">Back to parent folder</a>
    </div>
  {% endif %}

  {% if selected %}
    <h2>Now playing: <em>{{ selected }}</em></h2>
    <video controls autoplay>
      <source src="/stream/{{ selected|urlencode }}" type="video/mp4">
      Your browser cannot play this video.
    </video>
    <hr>
  {% endif %}

  <div class="tree">
    {% macro render_node(node, path_parts) %}
      {% for name, data in node.items()|list %}
        {% set current_path = path_parts + [name] %}
        {% set full_path = current_path|join('/') %}
        {% if data._type == 'folder' %}
          <div class="folder">
            <a href="/browse/{{ full_path }}">Folder: {{ name }}</a>
          </div>
          <div class="indent">
            {{ render_node(data._children, current_path) }}
          </div>
        {% else %}
          <div class="file">
            <a href="/watch/{{ data.path|urlencode }}">{{ name }}</a>
          </div>
        {% endif %}
      {% endfor %}
    {% endmacro %}

    {{ render_node(tree, []) }}
  </div>

  {% if not tree and not selected %}
    <p><em>No browser-playable .mp4 videos found.</em></p>
    <div class="warning">
      <strong>Tip:</strong> Only <code>.mp4</code> files with <strong>H.264 video + AAC audio</strong> can play in browsers.<br>
      Use <code>ffmpeg</code> to convert others: <br>
      <code>ffmpeg -i input.mkv -c:v libx264 -c:a aac output.mp4</code>
    </div>
  {% endif %}
</body>
</html>
"""

@app.route("/")
def index():
    tree = build_tree()
    return render_template_string(
        INDEX_HTML,
        tree=tree,
        selected=None,
        current_path='.',
        parent_url=None
    )

@app.route("/browse/<path:subpath>")
def browse(subpath):
    tree = build_tree()
    parts = subpath.split('/') if subpath else []
    current = tree
    for part in parts:
        if part not in current or current[part]['_type'] != 'folder':
            abort(404)
        current = current[part]['_children']
    parent_parts = parts[:-1]
    parent_url = "/browse/" + "/".join(parent_parts) if parent_parts else "/"
    return render_template_string(
        INDEX_HTML,
        tree=current,
        selected=None,
        current_path=subpath,
        parent_url=parent_url
    )

@app.route("/watch/<path:filename>")
def watch(filename):
    fullpath = os.path.abspath(os.path.join(VIDEO_ROOT, filename))
    if not fullpath.startswith(os.path.abspath(VIDEO_ROOT)) or not os.path.isfile(fullpath):
        abort(404)
    if not is_browser_playable(fullpath):
        abort(415)  # Unsupported Media Type
    tree = build_tree()
    return render_template_string(
        INDEX_HTML,
        tree=tree,
        selected=filename,
        current_path='.',
        parent_url=None
    )

# ----------------------------------------------------------------------
# Streaming with correct MIME
# ----------------------------------------------------------------------
def generate_stream(filepath):
    file_size = os.path.getsize(filepath)
    range_header = request.headers.get("Range", None)
    content_type = mime.from_file(filepath)

    if not range_header:
        def gen():
            with open(filepath, "rb") as f:
                while chunk := f.read(1024 * 256):
                    yield chunk
        return Response(gen(), mimetype=content_type)

    # Parse Range
    start, end = 0, file_size - 1
    if range_header.startswith("bytes="):
        r = range_header[6:]
        parts = r.split("-")
        if parts[0]: start = int(parts[0])
        if len(parts) > 1 and parts[1]: end = int(parts[1])

    if start >= file_size:
        return Response("", 416, {"Content-Range": f"bytes */{file_size}"})

    def gen():
        with open(filepath, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk: break
                yield chunk
                remaining -= len(chunk)

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": content_type,
    }
    return Response(gen(), 206, headers)

@app.route("/stream/<path:filename>")
def stream(filename):
    fullpath = os.path.abspath(os.path.join(VIDEO_ROOT, filename))
    if not fullpath.startswith(os.path.abspath(VIDEO_ROOT)) or not os.path.isfile(fullpath):
        abort(404)
    if not is_browser_playable(fullpath):
        return "This video format is not supported in web browsers. Convert to H.264/AAC MP4.", 415
    return generate_stream(fullpath)

# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)