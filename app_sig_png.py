import cv2
import numpy as np
import sys
import os

def process_signature(input_path, output_path=None):
    """
    Extracts a signature from an image by making the background transparent.
    Uses Otsu's thresholding to separate dark ink from light paper.
    """
    if not os.path.exists(input_path):
        print(f"Error: File {input_path} not found.")
        return

    print(f"Processing {input_path}...")

    # Load image
    img = cv2.imread(input_path)
    if img is None:
        print("Error: Failed to load image.")
        return

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply Gaussian Blur to reduce noise (paper texture)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Thresholding
    # THRESH_BINARY_INV: Pixel > threshold -> 0 (black), Pixel < threshold -> 255 (white)
    # We want the signature (dark) to become white in the mask (opaque)
    # Otsu's method determines the best threshold value automatically
    thresh_val, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    print(f"Otsu's threshold value: {thresh_val}")

    # Create BGRA image
    b, g, r = cv2.split(img)
    
    # Use the mask as the alpha channel
    # White in mask (signature) = Opaque
    # Black in mask (background) = Transparent
    rgba = cv2.merge([b, g, r, mask])

    # Determine output path
    if output_path is None:
        filename, ext = os.path.splitext(input_path)
        output_path = f"{filename}_transparent.png"

    # Save
    cv2.imwrite(output_path, rgba)
    print(f"Successfully saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 app_sig_png.py <input_image_path> [output_image_path]")
        print("Example: python3 app_sig_png.py signature.jpg")
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        process_signature(input_file, output_file)