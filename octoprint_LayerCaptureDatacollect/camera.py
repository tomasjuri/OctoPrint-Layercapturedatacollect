# coding=utf-8
from __future__ import absolute_import

import logging
import io
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from picamera2 import Picamera2

class Camera:
    """Manages camera operations for layer capture plugin"""
    
    def __init__(self, logger=None, fake_camera_mode=False):
        self._fake_camera_mode = fake_camera_mode
        self._logger = logger or logging.getLogger(__name__)
        self._camera_available = False
        self._camera_type = "none"
        self._camera = None

    def initialize(self):
        """Initialize camera system"""
        try:
            if self._fake_camera_mode:
                self._logger.info("Fake camera mode enabled")
                self._camera_type = "fake"
                self._camera_available = True
            else:
                # Try to initialize real camera
                self._camera_available = self._init_real_camera()
        except Exception as e:
            self._logger.error(f"Failed to initialize camera: {e}")
            self._camera_available = False
    
    # def _apply_settings(self, settings):
    #     """Apply settings to camera"""
    #     self._settings = settings
    #     self._camera_resolution_x = self._settings.get(["camera_resolution_x"])
    #     self._camera_resolution_y = self._settings.get(["camera_resolution_y"])
    #     self._image_quality = self._settings.get(["image_quality"])
    #     self._fake_camera_mode = self._settings.get(["fake_camera_mode"])
        
    #     self._logger.info(f"Settings applied: {self._settings}")

    def _init_real_camera(self):
        """Initialize real camera"""
        try:
            self._camera = Picamera2()
            
            config = self._camera.create_still_configuration(main={"format": "RGB888"})
            self._camera.configure(config)
            self._camera.start()

            # self._camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            
            # dst_meters = 0.05
            # self._camera.set_controls(
            # {"AfMode": controls.AfModeEnum.Manual, "LensPosition": 1/dst_meters})
            
            #self._camera.set_controls({"AfMode": controls.AfModeEnum.Auto})
            
            self._camera_type = "Picamera2"
            self._logger.info("Real camera initialized")
            
            self._camera_available = True
            return True
            
        except ImportError:
            self._logger.warning("Picamera2 not available")
            return False
        except Exception as e:
            self._logger.error(f"Failed to initialize real camera: {e}")
            return False
            
    def is_available(self):
        """Check if camera is available"""
        return self._camera_available
        
    def get_camera_type(self):
        """Get the type of camera being used"""
        return self._camera_type
        
    def capture_image(self, autofocus=True):
        """Capture an image"""
        if not self._camera_available:
            raise Exception("Capture failed")
        
        if self._fake_camera_mode:
            return self._generate_fake_image()
        else:
            return self._capture_real_image(autofocus)
            
    def _capture_real_image(self, autofocus=True):
        """Capture image from real camera"""
        start_time = time.time()
        try:
            if autofocus:
                self._camera.autofocus_cycle()
                
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
            width = 640
            height = 480
            
            # Create simple test image
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
    camera = Camera()
    camera.initialize()
    print("Camera initialized")
    image = camera.capture_image()
    print("Image captured")
    print(image)
    image.save("test.jpg")
    camera.cleanup()

if __name__ == "__main__":
    main()



