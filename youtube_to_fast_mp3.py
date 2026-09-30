#!/usr/bin/env python3
"""
YouTube to Fast MP3 Converter
Downloads YouTube video as MP3, speeds it up by 50%, and exports without metadata.
"""

import subprocess
import sys
import os
import shutil
from datetime import datetime
import argparse


SHARED_DIR = "/media/lius/shep-protected/downloads/shared"


def get_date_prefix():
    """Get current date as MMDD format."""
    return datetime.now().strftime("%m%d")


def download_youtube_as_mp3(url: str, output_path: str) -> bool:
    """Download YouTube video as MP3 using yt-dlp."""
    print(f"Downloading: {url}")
    print(f"Output: {output_path}")
    
    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=android",  # Use Android client (more reliable)
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--audio-quality", "0",  # Best quality
        "-o", output_path,
        url
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Download complete!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error downloading: {e.stderr}")
        return False


def speed_up_audio(input_path: str, output_path: str, tempo: float = 1.5) -> bool:
    """
    Speed up audio using ffmpeg's atempo filter.
    tempo=1.5 means 50% faster (1.5x speed).
    """
    print(f"Speeding up audio by {tempo}x...")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    
    # atempo filter only accepts values between 0.5 and 2.0
    # For values outside this range, chain multiple atempo filters
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", input_path,
        "-filter:a", f"atempo={tempo}",
        "-codec:a", "libmp3lame",
        "-q:a", "9",  # VBR quality 9 (~50kbps, smallest for podcasts)
        "-map_metadata", "-1",  # Remove all metadata
        "-fflags", "+bitexact",  # Reproducible output
        "-flags:a", "+bitexact",
        "-id3v2_version", "0",  # No ID3 tags
        "-write_xing", "0",  # No Xing header
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Speed adjustment complete!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error processing audio: {e.stderr}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download YouTube video as MP3 and speed it up"
    )
    parser.add_argument("url", help="YouTube URL to download")
    parser.add_argument(
        "-n", "--name",
        help="Base output filename (default: MMDD date format)",
        default=None
    )
    parser.add_argument(
        "-t", "--tempo",
        type=float,
        default=1.5,
        help="Tempo multiplier (default: 1.5 for 50%% faster)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=".",
        help="Output directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    # Get base filename
    base_name = args.name if args.name else get_date_prefix()
    
    # Set up file paths
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    full_mp3 = os.path.join(output_dir, f"{base_name}.full.mp3")
    short_mp3 = os.path.join(output_dir, f"{base_name}.short.mp3")
    
    print("=" * 50)
    print("YouTube to Fast MP3 Converter")
    print("=" * 50)
    print(f"Base filename: {base_name}")
    print(f"Tempo: {args.tempo}x")
    print()
    
    # Step 1: Download YouTube as MP3
    if not download_youtube_as_mp3(args.url, full_mp3):
        print("Failed to download video.")
        sys.exit(1)
    
    # Verify the file exists
    if not os.path.exists(full_mp3):
        print(f"Error: Downloaded file not found at {full_mp3}")
        sys.exit(1)
    
    print()
    
    # Step 2: Speed up and remove metadata
    if not speed_up_audio(full_mp3, short_mp3, args.tempo):
        print("Failed to process audio.")
        sys.exit(1)
    
    # Step 3: Copy short mp3 to shared directory
    os.makedirs(SHARED_DIR, exist_ok=True)
    shared_path = os.path.join(SHARED_DIR, f"{base_name}.short.mp3")
    shutil.copy2(short_mp3, shared_path)
    print(f"Copied to: {shared_path}")
    
    print()
    print("=" * 50)
    print("Success!")
    print(f"Full MP3: {full_mp3}")
    print(f"Fast MP3: {short_mp3}")
    print(f"Shared:   {shared_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
