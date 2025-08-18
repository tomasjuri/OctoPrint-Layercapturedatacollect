# coding=utf-8
from __future__ import absolute_import

import logging
import io
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from picamera2 import Picamera2
from libcamera import controls
import traceback


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
        if self._fake_camera_mode:
            self._logger.info("Fake camera mode enabled")
            self._camera_type = "fake"
            self._camera_available = True
        else:
            # Try to initialize real camera
            self._camera_available = self._init_real_camera()
    

    def _init_real_camera(self):
        """Initialize real camera"""

        self._camera = Picamera2()
        config = self._camera.create_still_configuration(
            main={"format": "RGB888", "size": self._size})
        self._camera.configure(config)
        self._camera.start()

        if self._focus_mode == "auto":
            self._camera.set_controls({"AfMode": controls.AfModeEnum.Auto})
            self._logger.info("Autofocus mode set to Auto")
        elif self._focus_mode == "manual":
            self._camera.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                       "LensPosition": 1/self._focus_distance})
            self._logger.info("Autofocus mode set to Manual")
        elif self._focus_mode == "continuous":
            self._camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            self._logger.info("Autofocus mode set to Continuous")
        
        self._focused = self._camera.autofocus_cycle()
        if not self._focused:
            self._logger.warning("Autofocus cycle failed")

        self._camera_type = "Picamera2"
        self._logger.info("Real camera initialized")
        
        self._camera_available = True
        return True
        
    def is_available(self):
        """Check if camera is available"""
        return self._camera_available
        
    def get_camera_type(self):
        """Get the type of camera being used"""
        return self._camera_type
        
    def capture_image(self):
        """Capture an image"""
        if not self._camera_available:
            raise Exception("Capture failed")
        
        if self._fake_camera_mode:
            return self._generate_fake_image()
        else:
            return self._capture_real_image()

# capteure times:
# 4608x2592 1.525618553161621 seconds
# 2304x1296 0.5843167304992676 seconds

    def _capture_real_image(self):
        """Capture image from real camera"""
        start_time = time.time()
        try:
            if self._focus_mode == "auto" or not self._focused:
                self._focused = self._camera.autofocus_cycle()
                if not self._focused:
                    self._logger.warning("Autofocus cycle failed")
                
            image_array = self._camera.capture_array("main")
            image_array = image_array[:, :, ::-1]  # Reverse the last dimension (channels)
            image = Image.fromarray(image_array)
            
            end_time = time.time()
            self._logger.info(f"Image captured in {end_time - start_time} seconds")
            
            return image
            
        except Exception as e:
            self._logger.error(f"Failed to capture real image: {e}")
            raise
            
    def _generate_fake_image(self):
        """Generate a fake camera image for testing"""
        try:
            # Create simple test image
            width, height = self._size
            image = Image.new('RGB', (width, height), color='lightblue')
            draw = ImageDraw.Draw(image)
            
            # Draw center crosshairs
            center_x, center_y = width // 2, height // 2
            cross_size = 20
            draw.line([(center_x - cross_size, center_y), (center_x + cross_size, center_y)], 
                     fill=(255, 0, 0), width=2)
            draw.line([(center_x, center_y - cross_size), (center_x, center_y + cross_size)], 
                     fill=(255, 0, 0), width=2)
            
            return image
            
        except Exception as e:
            self._logger.error(f"Failed to generate fake image: {e}")
            raise
            
    def cleanup(self):
        """Clean up camera resources"""
        try:
            if self._camera and self._camera_type == "Picamera2":
                # Stop the camera first
                self._camera.stop()
                
                # Wait a moment for the camera to fully stop
                time.sleep(0.5)
                
                # Close the camera
                self._camera.close()
                
                # Reset camera state
                self._camera = None
                self._camera_available = False
                self._camera_type = "none"
                
                self._logger.info("Camera cleanup completed successfully")
                
        except Exception as e:
            self._logger.warning(f"Error cleaning up camera: {e}")
        finally:
            # Ensure camera state is reset even if cleanup fails
            self._camera = None
            self._camera_available = False
            self._camera_type = "none"


    def __del__(self):
        self.cleanup()

def main():
    # Simple console logging setup
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    size = (4608, 2592)
    focus_mode = "manual"
    focus_distance = 0.06
    camera = Camera(
        size=size, focus_mode=focus_mode, focus_distance=focus_distance)
    camera.initialize()
    print("Camera initialized")
    image = camera.capture_image()
    print("Image captured")
    print(image)
    image.save("test.jpg")
    camera.cleanup()

if __name__ == "__main__":
    main()



