#!/usr/bin/env python3
"""
YouTube Music Downloader - Downloads audio at the highest bitrate possible.
Usage: python youtube_music_downloader.py <youtube_url>
"""

import sys
import os
import subprocess
from pathlib import Path

# YouTube gates its highest-bitrate audio (256-290kbps, formats 141/774) behind
# a logged-in Premium account. Getting them requires: (1) browser cookies from
# an account with an active Premium subscription, and (2) a JS runtime new
# enough for yt-dlp's signature-challenge solver (Node >= 22; Deno also works
# but isn't installed here). We install Node 22 out-of-band via nvm - see
# ~/.nvm/versions/node/. This path is what makes the Premium formats visible.
_NODE22_CANDIDATES = [
    os.path.expanduser('~/.nvm/versions/node/v22.14.0/bin/node'),
]
NODE22_PATH = next((p for p in _NODE22_CANDIDATES if os.path.isfile(p)), None)
COOKIE_BROWSER = 'firefox'


def check_yt_dlp():
    """Check if yt-dlp is installed."""
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_yt_dlp():
    """Install yt-dlp using pip."""
    print("Installing yt-dlp...")
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp'], check=True)


def update_yt_dlp_if_stale():
    """
    Best-effort auto-update of yt-dlp. YouTube frequently changes its
    delivery mechanism, and an outdated yt-dlp is the most common cause of
    'HTTP Error 403: Forbidden' when downloading. This keeps the tool
    working without requiring the user to remember to update manually.
    """
    try:
        print("Checking for yt-dlp updates...")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-q', '-U', 'yt-dlp'],
            check=True,
            timeout=60,
        )
    except Exception:
        # Non-fatal: continue with whatever version is currently installed.
        print("⚠️  Could not check/update yt-dlp, continuing with current version.")


def get_auth_args():
    """
    Build extra yt-dlp args that unlock YouTube Premium-only audio formats
    (141/774, 256-290kbps) by authenticating as a logged-in Premium account
    and enabling the JS runtime needed to solve YouTube's signature challenge.
    Returns [] if the Node 22 runtime isn't available, so downloads still
    work (falling back to the ~149kbps formats available to anyone).
    """
    if not NODE22_PATH:
        return []
    return [
        '--cookies-from-browser', COOKIE_BROWSER,
        '--js-runtimes', f'node:{NODE22_PATH}',
        '--remote-components', 'ejs:github',
    ]


def run_yt_dlp(cmd, retry_client: str = 'android'):
    """
    Run a yt-dlp command with live output. First tries with Premium
    authentication (cookies + JS runtime) to get the highest-bitrate audio;
    if that fails (e.g. cookies expired, browser locked), falls back to an
    anonymous download, then to an alternate player client as a last resort.
    """
    auth_args = get_auth_args()
    attempts = []
    if auth_args:
        attempts.append(cmd + auth_args)
    attempts.append(cmd)  # anonymous fallback
    attempts.append(cmd + ['--extractor-args', f'youtube:player_client={retry_client}'])

    result = None
    for i, attempt_cmd in enumerate(attempts):
        if i > 0:
            print(f"\n⚠️  Previous attempt failed, retrying (attempt {i + 1}/{len(attempts)})...\n")
        result = subprocess.run(attempt_cmd)
        if result.returncode == 0:
            return result

    raise subprocess.CalledProcessError(result.returncode, cmd)


def download_music(url: str, output_dir: str = None):
    """
    Download YouTube audio at the highest bitrate.
    
    Args:
        url: YouTube video/music URL
        output_dir: Directory to save the file (defaults to current directory)
    """
    if output_dir is None:
        output_dir = os.getcwd()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Output template: title.extension
    output_template = str(output_dir / '%(title)s.%(ext)s')
    
    # yt-dlp options for highest quality audio
    cmd = [
        'yt-dlp',
        '--extract-audio',              # Extract audio only
        '--audio-format', 'best',       # Best audio format (keeps original if possible)
        '--audio-quality', '0',         # Highest quality (0 = best, 10 = worst)
        '--embed-thumbnail',            # Embed thumbnail in audio file
        '--embed-metadata',             # Embed metadata
        '--no-playlist',                # Don't download playlists (single video only)
        '-o', output_template,          # Output filename template
        '--progress',                   # Show progress
        '--no-warnings',                # Suppress warnings
        url
    ]
    
    print(f"\n🎵 Downloading audio from: {url}")
    print(f"📁 Output directory: {output_dir}\n")
    
    try:
        # First, show available formats
        print("Checking available audio formats...")
        info_cmd = ['yt-dlp', '-F', url]
        subprocess.run(info_cmd, check=False)
        print("\n" + "="*60 + "\n")
        
        # Download the audio
        run_yt_dlp(cmd)
        print(f"\n✅ Download complete! Check: {output_dir}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error downloading: {e}")
        return False


def download_music_as_mp3(url: str, output_dir: str = None, bitrate: str = "320"):
    """
    Download YouTube audio and convert to MP3 at specified bitrate.
    
    Args:
        url: YouTube video/music URL
        output_dir: Directory to save the file
        bitrate: MP3 bitrate (e.g., "320" for 320kbps)
    """
    if output_dir is None:
        output_dir = os.getcwd()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_template = str(output_dir / '%(title)s.%(ext)s')
    
    cmd = [
        'yt-dlp',
        '--extract-audio',
        '--audio-format', 'mp3',        # Convert to MP3
        '--audio-quality', f'{bitrate}K',  # Bitrate (e.g., 320K)
        '--embed-thumbnail',
        '--embed-metadata',
        '--no-playlist',
        '-o', output_template,
        '--progress',
        url
    ]
    
    print(f"\n🎵 Downloading and converting to MP3 ({bitrate}kbps): {url}")
    print(f"📁 Output directory: {output_dir}\n")
    
    try:
        run_yt_dlp(cmd)
        print(f"\n✅ Download complete! Check: {output_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error downloading: {e}")
        return False


def download_music_as_m4a(url: str, output_dir: str = None):
    """
    Download YouTube audio and package it as M4A (AAC container).

    Opus (.opus) files are not reliably playable/previewable inside chat
    apps like WeChat. M4A is universally supported there, so this remuxes
    (or re-encodes, if the source isn't AAC) into a widely-compatible
    container without discarding any available source quality.

    Args:
        url: YouTube video/music URL
        output_dir: Directory to save the file
    """
    if output_dir is None:
        output_dir = os.getcwd()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_template = str(output_dir / '%(title)s.%(ext)s')
    
    cmd = [
        'yt-dlp',
        # Prefer a source that's already AAC (itag 141, Premium-only 258kbps) so
        # yt-dlp can remux straight into .m4a instead of re-encoding from Opus,
        # which would be a lossy-to-lossy transcode. Falls back to bestaudio.
        '-f', 'bestaudio[acodec^=mp4a]/bestaudio',
        '--extract-audio',
        '--audio-format', 'm4a',        # AAC in an .m4a container, for wide compatibility (WeChat, etc.)
        # YouTube's source audio tops out around 130-290kbps, so '--audio-quality 0'
        # (which targets a very high AAC bitrate) would just bloat the file with no
        # real quality gain if a re-encode is needed. 256k comfortably covers it.
        '--audio-quality', '256K',
        '--embed-thumbnail',
        '--embed-metadata',
        '--no-playlist',
        '-o', output_template,
        '--progress',
        url
    ]
    
    print(f"\n🎵 Downloading and packaging as M4A/AAC (WeChat-friendly): {url}")
    print(f"📁 Output directory: {output_dir}\n")
    
    try:
        run_yt_dlp(cmd)
        print(f"\n✅ Download complete! Check: {output_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error downloading: {e}")
        return False


def download_music_as_flac(url: str, output_dir: str = None):
    """
    Download YouTube audio and convert to FLAC (lossless).
    
    Args:
        url: YouTube video/music URL
        output_dir: Directory to save the file
    """
    if output_dir is None:
        output_dir = os.getcwd()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_template = str(output_dir / '%(title)s.%(ext)s')
    
    cmd = [
        'yt-dlp',
        '--extract-audio',
        '--audio-format', 'flac',       # Convert to FLAC (lossless)
        '--audio-quality', '0',         # Best quality
        '--embed-thumbnail',
        '--embed-metadata',
        '--no-playlist',
        '-o', output_template,
        '--progress',
        url
    ]
    
    print(f"\n🎵 Downloading and converting to FLAC (lossless): {url}")
    print(f"📁 Output directory: {output_dir}\n")
    
    try:
        run_yt_dlp(cmd)
        print(f"\n✅ Download complete! Check: {output_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error downloading: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("YouTube Music Downloader")
        print("=" * 40)
        print("\nUsage:")
        print(f"  {sys.argv[0]} <youtube_url> [format] [output_dir]")
        print("\nFormats:")
        print("  best  - Keep original format at highest quality (default, usually .opus)")
        print("  m4a   - AAC in .m4a container (best for sharing via WeChat etc.)")
        print("  mp3   - Convert to MP3 at 320kbps")
        print("  flac  - Convert to FLAC (lossless, but no better than source since YouTube audio is lossy)")
        print("\nExamples:")
        print(f"  {sys.argv[0]} https://youtube.com/watch?v=xxxxx")
        print(f"  {sys.argv[0]} https://youtube.com/watch?v=xxxxx m4a")
        print(f"  {sys.argv[0]} https://youtube.com/watch?v=xxxxx mp3")
        print(f"  {sys.argv[0]} https://youtube.com/watch?v=xxxxx flac ./music")
        sys.exit(1)
    
    # Check/install yt-dlp
    if not check_yt_dlp():
        print("yt-dlp not found. Installing...")
        install_yt_dlp()
    else:
        # An outdated yt-dlp is the #1 cause of YouTube downloads failing
        # with 403 errors, so keep it fresh automatically.
        update_yt_dlp_if_stale()
    
    url = sys.argv[1]
    format_type = sys.argv[2] if len(sys.argv) > 2 else "best"
    output_dir = sys.argv[3] if len(sys.argv) > 3 else None
    
    # Download based on format
    if format_type.lower() == "mp3":
        success = download_music_as_mp3(url, output_dir)
    elif format_type.lower() == "flac":
        success = download_music_as_flac(url, output_dir)
    elif format_type.lower() == "m4a":
        success = download_music_as_m4a(url, output_dir)
    else:
        success = download_music(url, output_dir)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
