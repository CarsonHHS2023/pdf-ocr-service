"""Image preprocessing utilities for PDF pages using OpenCV."""

from __future__ import annotations

import logging
import cv2
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Handles image preprocessing for scanned documents."""

    @staticmethod
    def grayscale(img: np.ndarray) -> np.ndarray:
        """
        Convert image to grayscale.

        Args:
            img: Input image (BGR or already grayscale)

        Returns:
            Grayscale image
        """
        if len(img.shape) == 2:
            # Already grayscale
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def denoise(img: np.ndarray, h: int = 10) -> np.ndarray:
        """
        Denoise image using bilateral filter.

        Args:
            img: Input grayscale image
            h: Denoising strength (higher = more denoising, slower)

        Returns:
            Denoised image
        """
        try:
            # Use bilateral filter for edge-preserving denoising
            denoised = cv2.bilateralFilter(img, 9, h, h)
            logger.debug(f"Image denoised with strength h={h}")
            return denoised
        except Exception as e:
            logger.error(f"Failed to denoise image: {e}")
            return img

    @staticmethod
    def detect_skew(img: np.ndarray) -> Optional[float]:
        """
        Detect text skew angle using Hough line transform.

        Args:
            img: Input grayscale image

        Returns:
            Skew angle in degrees (negative means CCW), or None if detection fails
        """
        try:
            # Detect edges
            edges = cv2.Canny(img, 50, 150, apertureSize=3)
            
            # Use Hough line transform
            lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)
            
            if lines is None or len(lines) == 0:
                logger.debug("No skew detected (no lines found)")
                return None
            
            # Extract angles
            angles = []
            for line in lines:
                rho, theta = line[0]
                # Convert theta to degrees and adjust
                angle = np.degrees(theta) - 90
                angles.append(angle)
            
            # Get median angle
            median_angle = np.median(angles)
            
            # Normalize to -45 to 45 degrees
            if median_angle > 45:
                median_angle -= 90
            elif median_angle < -45:
                median_angle += 90
            
            logger.debug(f"Detected skew angle: {median_angle:.2f} degrees")
            return median_angle
            
        except Exception as e:
            logger.error(f"Failed to detect skew: {e}")
            return None

    @staticmethod
    def correct_skew(img: np.ndarray) -> np.ndarray:
        """
        Correct text skew in image.

        Args:
            img: Input grayscale image

        Returns:
            Skew-corrected image
        """
        try:
            angle = ImagePreprocessor.detect_skew(img)
            
            if angle is None or abs(angle) < 0.5:
                logger.debug("Skew correction: angle < 0.5°, skipping")
                return img
            
            # Get rotation matrix
            h, w = img.shape
            center = (w / 2, h / 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            
            # Apply rotation
            corrected = cv2.warpAffine(
                img,
                matrix,
                (w, h),
                borderMode=cv2.BORDER_REPLICATE
            )
            
            logger.debug(f"Skew corrected by {angle:.2f} degrees")
            return corrected
            
        except Exception as e:
            logger.error(f"Failed to correct skew: {e}")
            return img

    @staticmethod
    def enhance_contrast(img: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
        """
        Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization).

        Args:
            img: Input grayscale image
            clip_limit: Contrast limit (1.0 = no enhancement, higher = more enhancement)

        Returns:
            Contrast-enhanced image
        """
        try:
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
            enhanced = clahe.apply(img)
            logger.debug(f"Contrast enhanced with clip_limit={clip_limit}")
            return enhanced
        except Exception as e:
            logger.error(f"Failed to enhance contrast: {e}")
            return img

    @staticmethod
    def preprocess(img: np.ndarray, 
                   denoise_strength: int = 10,
                   enhance_contrast_limit: float = 2.0) -> np.ndarray:
        """
        Complete preprocessing pipeline for scanned documents.

        Steps:
        1. Convert to grayscale
        2. Denoise (bilateral filter)
        3. Correct skew
        4. Enhance contrast (CLAHE)

        Args:
            img: Input image (BGR or grayscale)
            denoise_strength: Denoising strength (higher = more denoising)
            enhance_contrast_limit: Contrast enhancement limit

        Returns:
            Preprocessed image
        """
        try:
            logger.info("Starting image preprocessing pipeline")
            
            # Step 1: Grayscale
            gray = ImagePreprocessor.grayscale(img)
            logger.debug("Step 1: Converted to grayscale")
            
            # Step 2: Denoise
            denoised = ImagePreprocessor.denoise(gray, h=denoise_strength)
            logger.debug("Step 2: Denoising completed")
            
            # Step 3: Correct skew
            corrected = ImagePreprocessor.correct_skew(denoised)
            logger.debug("Step 3: Skew correction completed")
            
            # Step 4: Enhance contrast
            enhanced = ImagePreprocessor.enhance_contrast(corrected, clip_limit=enhance_contrast_limit)
            logger.debug("Step 4: Contrast enhancement completed")
            
            logger.info("Image preprocessing completed successfully")
            return enhanced
            
        except Exception as e:
            logger.error(f"Error in preprocessing pipeline: {e}")
            return img


# Convenience function
def preprocess_image(img: np.ndarray, 
                    denoise_strength: int = 10,
                    enhance_contrast_limit: float = 2.0) -> np.ndarray:
    """
    Preprocess image using default pipeline.

    Args:
        img: Input image
        denoise_strength: Denoising strength
        enhance_contrast_limit: Contrast enhancement limit

    Returns:
        Preprocessed image
    """
    return ImagePreprocessor.preprocess(img, denoise_strength, enhance_contrast_limit)
