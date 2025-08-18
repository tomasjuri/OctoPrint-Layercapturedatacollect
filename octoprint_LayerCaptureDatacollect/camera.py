# coding=utf-8
from __future__ import absolute_import

import logging
import io
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import traceback
import requests

SNAPSHOT_URL = "http://127.0.0.1:8080/?action=snapshot"

def capture_from_octoprint_stream(snapshot_url=SNAPSHOT_URL, timeout=5):
    """
    Capture an image from OctoPrint's webcam stream and return as PIL Image
    """
    try:
        # Get the snapshot from OctoPrint's webcam endpoint
        response = requests.get(snapshot_url, timeout=timeout, stream=True)
        response.raise_for_status()
        
        if 'image' not in response.headers.get('content-type', ''):
            raise ValueError("Response is not an image")
        
        # Create PIL Image directly from response content
        image = Image.open(io.BytesIO(response.content))
        # Convert to RGB if necessary (some formats might be in different modes)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        return image
    except Exception as e:
        raise Exception(f"Failed to capture from webcam stream: {e}")


class Camera:
    """Manages camera operations for layer capture plugin"""
    
    def __init__(self, fake_camera_mode=False, 
                 focus_mode="manual", focus_distance=0.06, 
                 size=(4608, 2592)):
        """Initialize camera system"""

        self._logger = logging.getLogger(__name__)

        self._fake_camera_mode = fake_camera_mode
        self._focus_mode = focus_mode
        assert self._focus_mode in ["auto", "manual", "continuous"], "Invalid focus mode"
        if self._focus_mode == "manual":
            self._focus_distance = focus_distance
        self._size = size
        self._camera_available = False
        self._camera_type = "none"
        self._focused = False
        self._camera = None

    def initialize(self):
        """Initialize camera system"""
        self._logger.info("Fake camera mode enabled")
        self._camera_type = "fake"
        self._camera_available = True
        
        return self._camera_available
    
       
    def is_available(self):
        """Check if camera is available"""
        return self._camera_available
        
    def get_camera_type(self):
        """Get the type of camera being used"""
        return self._camera_type
        
    def capture_image(self):
        """Capture an image and return PIL Image"""
        image = capture_from_octoprint_stream()
        self._logger.info("Image captured from OctoPrint stream")
        return image
    
            
    def cleanup(self):
        """Clean up camera resources"""
        pass

    def __del__(self):
        self.cleanup()

def main():
    # Simple console logging setup
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    camera = Camera()
    camera.initialize()
    print("Camera initialized")
    img = camera.capture_image()
    print(img.size)
    img.save("test_capture.jpg")
    camera.cleanup()

if __name__ == "__main__":
    main()



