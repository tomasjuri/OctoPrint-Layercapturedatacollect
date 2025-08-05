# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.events
import octoprint.printer
import octoprint.util

import os
import logging
import time
import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io

LAYER_CAPTURE_TRIGGER_MCODE = "M240"

class LayerCaptureDatacollect(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.StartupPlugin,
):

    def __init__(self):    
        self._logger = logging.getLogger(__name__)
        self._detected_z_height = 0.0
        self._camera_available = False
        self._camera_type = "none"
        self._camera = None
        
        self._logger.info("Layer Capture Data Collect plugin initialized")

    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin starting up")
        self._logger.debug("Layer Capture Data Collect plugin starting up")
        # Initialize camera system
        self._init_camera()
        
        # Ensure save directory exists
        self._ensure_save_directory()

    def on_shutdown(self):
        """Clean up resources when OctoPrint shuts down"""
        self._logger.info("Layer Capture Data Collect plugin shutting down")
        self._cleanup_camera()

    ##~~ SettingsPlugin mixin
   
    def get_settings_defaults(self):
        return {
            # Camera Settings
            "fake_camera_mode": True,     # Use fake camera for testing
            "image_format": "jpg",        # Image format (jpg, png)
            "image_quality": 95,          # JPEG quality (1-100)
            "camera_resolution_x": 1640,  # Camera resolution width
            "camera_resolution_y": 1232,  # Camera resolution height
            
            # File Paths
            "save_path": "~/.octoprint/uploads/layer_captures",  # Directory for saving captures
        }

    ##~~ AssetPlugin mixin

    def get_assets(self):
        return {
            "js": ["js/LayerCaptureDatacollect.js"],
            "css": ["css/LayerCaptureDatacollect.css"],
            "less": ["less/LayerCaptureDatacollect.less"]
        }

    ##~~ TemplatePlugin mixin

    def get_template_configs(self):
        return [
            {
                "type": "settings",
                "custom_bindings": False
            }
        ]

    ##~~ EventHandlerPlugin mixin

    def on_event(self, event, payload):
        # Print lifecycle events
        if event == octoprint.events.Events.PRINT_STARTED:
            self._logger.debug("Print started")
        elif event in [octoprint.events.Events.PRINT_DONE, 
                      octoprint.events.Events.PRINT_FAILED, 
                      octoprint.events.Events.PRINT_CANCELLED]:
            self._logger.info("Print finished")

    ##~~ Camera Methods

    def _init_camera(self):
        """Initialize camera system"""
        try:
            if self._settings.get(["fake_camera_mode"]):
                self._logger.info("Fake camera mode enabled")
                self._camera_type = "fake"
                self._camera_available = True
            else:
                # Try to initialize real camera
                self._camera_available = self._init_real_camera()
        except Exception as e:
            self._logger.error(f"Failed to initialize camera: {e}")
            self._camera_available = False

    def _init_real_camera(self):
        """Initialize real camera"""
        try:
            from picamera2 import Picamera2
            self._camera = Picamera2()
            
            config = self._camera.create_still_configuration(
                main={
                    "size": (
                        self._settings.get(["camera_resolution_x"]),
                        self._settings.get(["camera_resolution_y"])
                    ),
                    "format": "RGB888"
                }
            )
            self._camera.configure(config)
            self._camera.start()
            
            self._camera_type = "libcamera"
            self._logger.info("Real camera initialized")
            return True
            
        except ImportError:
            self._logger.warning("Picamera2 not available")
            return False
        except Exception as e:
            self._logger.error(f"Failed to initialize real camera: {e}")
            return False

    def _capture_image(self, position_coords=None):
        """Capture an image"""
        if not self._camera_available:
            raise Exception("Camera not available")
        
        if self._settings.get(["fake_camera_mode"]):
            return self._generate_fake_image(position_coords)
        else:
            return self._capture_real_image(position_coords)

    def _capture_real_image(self, position_coords=None):
        """Capture image from real camera"""
        try:
            image_data = io.BytesIO()
            
            if self._camera_type == "libcamera":
                image_array = self._camera.capture_array("main")
                image = Image.fromarray(image_array)
                
                image.save(image_data, format="JPEG", 
                          quality=self._settings.get(["image_quality"]))
                
            image_data.seek(0)
            return image_data.getvalue()
            
        except Exception as e:
            self._logger.error(f"Failed to capture real image: {e}")
            raise

    def _generate_fake_image(self, position_coords=None):
        """Generate a fake camera image for testing"""
        try:
            width = self._settings.get(["camera_resolution_x"])
            height = self._settings.get(["camera_resolution_y"])
            
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
            
            # Add position info if provided
            if position_coords:
                try:
                    font = ImageFont.load_default()
                    info_text = f"X: {position_coords.get('x', 0):.1f} Y: {position_coords.get('y', 0):.1f} Z: {position_coords.get('z', 0):.1f}"
                    draw.text((10, 10), info_text, fill=(255, 255, 255), font=font)
                except:
                    pass
            
            # Add timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                font = ImageFont.load_default()
                draw.text((10, height - 30), f"M240 Capture: {timestamp}", fill=(255, 255, 255), font=font)
            except:
                pass
            
            # Convert to bytes
            image_data = io.BytesIO()
            image.save(image_data, format="JPEG", quality=self._settings.get(["image_quality"]))
            image_data.seek(0)
            return image_data.getvalue()
            
        except Exception as e:
            self._logger.error(f"Failed to generate fake image: {e}")
            raise

    def _cleanup_camera(self):
        """Clean up camera resources"""
        try:
            if self._camera and self._camera_type == "libcamera":
                self._camera.stop()
                self._camera.close()
                self._camera = None
        except Exception as e:
            self._logger.warning(f"Error cleaning up camera: {e}")

    ##~~ File Management

    def _get_save_path(self):
        """Get the configured save path"""
        save_path = self._settings.get(["save_path"])
        if save_path:
            return os.path.expanduser(save_path)
        return os.path.expanduser("~/.octoprint/uploads/layer_captures")

    def _ensure_save_directory(self):
        """Create save directory if it doesn't exist"""
        try:
            save_path = self._get_save_path()
            os.makedirs(save_path, exist_ok=True)
            self._logger.info(f"Save directory ready: {save_path}")
            return save_path
        except Exception as e:
            self._logger.error(f"Failed to create save directory: {e}")
            return None

    ##~~ GcodeCommandHook mixin - SIMPLE M240 IMPLEMENTATION

    def gcode_command_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        """Simple M240 capture hook"""
        self._logger.debug(f"G-code command sent: {cmd}")
        try:
            line = cmd.strip().upper()
            
            # Detect Z height from layer change
            if ";Z:" in line:
                try:
                    z_value = line.split(";Z:")[1].strip()
                    self._detected_z_height = float(z_value)
                    self._logger.debug(f"Layer Z: {self._detected_z_height}mm")
                except:
                    pass
            
            # Trigger capture on M240
            if "M240" in line:
                self._logger.info("M240 detected - starting simple capture")
                self._capture()
                
        except Exception as e:
            self._logger.error(f"G-code hook error: {e}")
        
        return None

    def get_current_position(self):
        """Get the current position of the printer"""
        current_data = self._printer.get_current_data()
        self._logger.debug(f"Current data from the printer: {current_data}")
        return {
                'x': current_data.get('currentX', 0),
                'y': current_data.get('currentY', 0), 
                'z': current_data.get('currentZ', 0)
            }

    def _capture(self):
        """Capture sequence"""
        self._logger.info("Camera capture sequence started")
        try:
            # Skip if not printing or no camera
            if not self._printer.is_printing() or not self._camera_available:
                self._logger.info("Skipping capture - not printing or no camera")
                return
            
            self._printer.pause_print()
            
            pos_before_capture = self.get_current_position()
            self._logger.debug(f"Position before capture: {pos_before_capture}")

            # Simple Z lift (5mm above current layer)
            capture_pos = {
                'x': 125.0,
                'y': 105.0,
                'z': self._detected_z_height + 5.0
            }
            
            # Simple movement command
            move_cmd = f"G1 X{capture_pos['x']} Y{capture_pos['y']} Z{capture_pos['z']} F3000"
            self._logger.info(f"Moving to capture position: {move_cmd}")
            self._printer.commands(move_cmd)
            
            # Wait for movement
            self._logger.info("Waiting for movement")
            time.sleep(0.2)
            
            # Capture image
            image_data = self._capture_image(capture_pos)
            
            # Save image with timestamp
            if image_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"m240_capture_{timestamp}.jpg"
                save_path = self._get_save_path()
                
                with open(os.path.join(save_path, filename), 'wb') as f:
                    f.write(image_data)
                
                self._logger.info(f"Image saved: {filename}")
            
            # Return to print (simple way - just lower Z)
            return_cmd = f"G1 Z{capture_pos['z']} F3000"
            self._logger.info(f"Moving to return position: {return_cmd}")
            self._printer.commands(return_cmd)
            self._printer.resume_print()
        
        except Exception as e:
            self._logger.error(f"Simple capture failed: {e}")

    ##~~ Softwareupdate hook

    def get_update_information(self):
        return {
            "LayerCaptureDatacollect": {
                "displayName": "Layer Capture Data Collect Plugin",
                "displayVersion": self._plugin_version,
                "type": "github_release",
                "user": "tomasjuri",
                "repo": "OctoPrint-Layercapturedatacollect",
                "current": self._plugin_version,
                "pip": "https://github.com/tomasjuri/OctoPrint-Layercapturedatacollect/archive/{target_version}.zip",
            }
        }


# Plugin metadata
__plugin_name__ = "Layer Capture Data Collect"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = LayerCaptureDatacollect()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.gcode_command_sent
    }