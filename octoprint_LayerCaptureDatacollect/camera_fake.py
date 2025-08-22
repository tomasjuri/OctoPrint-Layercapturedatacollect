# coding=utf-8
from __future__ import absolute_import

import logging
from PIL import Image

class CameraFake:
    """Manages camera operations for layer capture plugin"""
    
    def __init__(self, *args, **kwargs):
        """Initialize camera system"""
        self._logger = logging.getLogger(__name__)
        self._logger.info("Fake camera mode enabled")

    def initialize(self):
        """Initialize camera system"""
        self._logger.info("Fake camera mode initialized")
        self._camera_available = True
        self._camera_type = "fake"
        return True

    
    def is_available(self):
        """Check if camera is available"""
        return self._camera_available
        
    def get_camera_type(self):
        """Get the type of camera being used"""
        return self._camera_type
        
    def capture_image(self):
        """Capture an image and return PIL Image"""
        image = Image.open("/Users/tomasjurica/projects/OctoPrint-Layercapturedatacollect/test_capture.jpg")
        return image
          
    def cleanup(self):
        """Clean up camera resources"""
        pass

    def __del__(self):
        self.cleanup()



