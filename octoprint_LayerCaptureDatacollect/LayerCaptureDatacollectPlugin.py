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
import threading
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io

class LayerCaptureDatacollectPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.StartupPlugin,
):

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.DEBUG)
        
        self._capture_active = False
        self._current_layer = 0
        self._last_captured_layer = -1
        self._current_z_height = 0.0
        self._print_start_time = None
        self._current_gcode_file = None
        self.calibration_file = None
        self._capture_thread = None
        self._print_progress = 0.0
        self._original_position = None  # Store position before movement
        self._movement_in_progress = False
        self._print_paused_for_capture = False

        self._logger.info("Layer Capture Data Collect plugin initialized")
        self._logger.debug("Layer Capture Data Collect plugin initialized (debug)")
        self._logger.warning("Layer Capture Data Collect plugin initialized (warning)")
        self._logger.error("Layer Capture Data Collect plugin initialized (error)")
        self._logger.critical("Layer Capture Data Collect plugin initialized (critical)")


    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin initialized")
        # Initialize camera system
        self._init_camera()
        
        # Log camera status
        if self._camera_available:
            self._logger.info(f"Camera system ready: {self._camera_type}")
        else:
            self._logger.warning("Camera system not available - only fake camera mode supported")
            self._logger.info("To enable real camera support, install FFmpeg dependencies and reinstall with camera support")
            self._logger.info("Or enable 'Fake Camera Mode' in plugin settings for testing")
        
        # Ensure save directory exists
        self._ensure_save_directory()
        # Validate calibration file if configured
        is_valid, message = self._validate_calibration_file()
        if not is_valid and self._get_calibration_file_path():
            self._logger.warning(f"Calibration file issue: {message}")

    def on_shutdown(self):
        """Clean up resources when OctoPrint shuts down"""
        self._logger.info("Layer Capture Data Collect plugin shutting down")
        self._cleanup_camera()

    ##~~ SettingsPlugin mixin
 
    def get_settings_defaults(self):
        return {
            # Grid Configuration
            "grid_center_x": 125.0,        # X coordinate of grid center (mm)
            "grid_center_y": 105.0,        # Y coordinate of grid center (mm)
            "grid_spacing": 20.0,          # Distance between capture points (mm)
            "grid_size": 3,                # Grid size (1x1, 3x3, or 5x5)
            "z_offset": 5.0,               # Height above print surface for capture (mm)
            
            # Capture Settings
            "layer_interval": 3,          # Capture every N layers
            "enabled": True,               # Plugin enabled/disabled
            
            # Safety Boundaries
            "max_x": 250.0,               # Maximum X coordinate (mm)
            "max_y": 210.0,               # Maximum Y coordinate (mm)
            "max_z": 220.0,               # Maximum Z coordinate (mm)
            "min_x": 0.0,                 # Minimum X coordinate (mm)
            "min_y": 0.0,                 # Minimum Y coordinate (mm)
            
            # Camera Settings (modernized with camera-streamer inspiration)
            "camera_enabled": True,        # Enable camera capture
            "fake_camera_mode": False,     # Use fake camera for testing (no physical camera needed)
            "image_format": "jpg",         # Image format (jpg, png)
            "image_quality": 95,           # JPEG quality (1-100)
            "camera_resolution_x": 1640,   # Camera resolution width
            "camera_resolution_y": 1232,   # Camera resolution height
            "camera_iso": 100,             # Camera ISO setting (100-800)
            "camera_shutter_speed": 0,     # Camera shutter speed (0 = auto, microseconds)
            "camera_rotation": 0,          # Camera rotation (0, 90, 180, 270)
            
            # Advanced Camera Controls (camera-streamer inspired)
            "exposure_mode": "auto",       # Exposure mode (auto, manual)
            "white_balance_mode": "auto",  # White balance (auto, daylight, tungsten, fluorescent)
            "brightness": 0.0,             # Brightness adjustment (-1.0 to 1.0)
            "contrast": 1.0,               # Contrast adjustment (0.0 to 2.0)
            "saturation": 1.0,             # Saturation adjustment (0.0 to 2.0)
            "sharpness": 1.0,              # Sharpness adjustment (0.0 to 2.0)
            "noise_reduction_mode": "auto", # Noise reduction (auto, off, fast, high_quality)
            "enable_image_processing": True, # Enable post-capture processing
            "auto_enhance": False,         # Enable automatic image enhancement
            
            # Advanced Settings
            "move_speed": 3000,           # Speed for positioning moves (mm/min)
            "capture_delay": 0.1,         # Delay after positioning before capture (seconds)
            "enable_movement": True,      # Enable actual print head movement (disable for testing)
            
            # File Paths
            "save_path": "~/.octoprint/uploads/layer_captures",  # Directory for saving captures
            "calibration_file_path": "/data/calibration.json",  # Path to calibration file
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
            self._on_print_started(payload)
        elif event == octoprint.events.Events.PRINT_DONE:
            self._on_print_finished(payload, "completed")
        elif event == octoprint.events.Events.PRINT_FAILED:
            self._on_print_finished(payload, "failed")
        elif event == octoprint.events.Events.PRINT_CANCELLED:
            self._on_print_finished(payload, "cancelled")
        elif event == octoprint.events.Events.PRINT_PAUSED:
            self._on_print_paused(payload)
        elif event == octoprint.events.Events.PRINT_RESUMED:
            self._on_print_resumed(payload)
        
        # Layer tracking events
        elif event == octoprint.events.Events.POSITION_UPDATE:
            self._logger.info(f"Position update event: {payload}")
            self._on_z_change(payload)
        elif event == octoprint.events.Events.Z_CHANGE:
            self._logger.info(f"Z change event: {payload}")
            self._on_z_change(payload)

        # Error handling events
        elif event == octoprint.events.Events.ERROR:
            self._on_error(payload)
        elif event == octoprint.events.Events.DISCONNECTED:
            self._on_disconnected(payload)

    ##~~ Core Plugin Methods

    def _init_camera(self):
        """Initialize camera system"""
        try:
            self._camera = None
            self._camera_type = "none"
            
            if self._settings.get(["fake_camera_mode"]):
                self._logger.info("Fake camera mode enabled - using generated test images")
                self._camera_type = "fake"
                self._camera_available = True
            else:
                # Try to initialize real camera
                self._camera_available = self._init_real_camera()
        except Exception as e:
            self._logger.error(f"Failed to initialize camera: {e}")
            self._camera_available = False
            self._camera_type = "none"

    def _init_real_camera(self):
        """Initialize real camera using modern libcamera-based approach similar to camera-streamer"""
        try:
            # Modern libcamera-based initialization (inspired by camera-streamer)
            try:
                from picamera2 import Picamera2
                self._camera = Picamera2()
                
                # Configure camera with modern controls similar to camera-streamer
                config = self._camera.create_still_configuration(
                    main={
                        "size": (
                            self._settings.get(["camera_resolution_x"]),
                            self._settings.get(["camera_resolution_y"])
                        ),
                        "format": "RGB888"  # Use RGB format for better compatibility
                    },
                    # Add buffer configuration for better performance
                    buffer_count=4
                )
                self._camera.configure(config)
                
                # Apply modern camera controls (inspired by camera-streamer approach)
                controls = self._get_camera_controls()
                if controls:
                    self._camera.set_controls(controls)
                
                self._camera.start()
                self._camera_type = "libcamera"
                self._logger.info("Initialized camera with modern libcamera controls (camera-streamer style)")
                return True
                
            except ImportError as e:
                self._logger.warning(f"Modern libcamera (Picamera2) not available: {e}")
                self._logger.info("Modern camera controls require libcamera. Install with: sudo apt install python3-picamera2")
                return False
                    
        except Exception as e:
            self._logger.error(f"Failed to initialize camera: {e}")
            self._logger.info("Ensure libcamera is properly installed: sudo apt install libcamera-apps python3-picamera2")
            return False

    def _get_camera_controls(self):
        """Get modern camera controls configuration (inspired by camera-streamer)"""
        controls = {}
        
        try:
            # Exposure controls (similar to camera-streamer's exposure handling)
            exposure_mode = self._settings.get(["exposure_mode"], "auto")
            if exposure_mode == "auto":
                controls["AeEnable"] = True
                controls["AwbEnable"] = True
            else:
                controls["AeEnable"] = False
                # Manual exposure time (microseconds)
                exposure_time = self._settings.get(["camera_shutter_speed"])
                if exposure_time > 0:
                    controls["ExposureTime"] = exposure_time
                
            # ISO/Gain controls (camera-streamer style)
            iso = self._settings.get(["camera_iso"])
            if iso and iso > 0:
                # Convert ISO to analogue gain (camera-streamer approach)
                analogue_gain = float(iso / 100.0)
                controls["AnalogueGain"] = analogue_gain
                
            # White balance controls (modern libcamera approach)
            awb_mode = self._settings.get(["white_balance_mode"], "auto")
            if awb_mode == "auto":
                controls["AwbEnable"] = True
            else:
                controls["AwbEnable"] = False
                if awb_mode == "daylight":
                    controls["ColourGains"] = [1.5, 1.5]  # Daylight gains
                elif awb_mode == "tungsten":
                    controls["ColourGains"] = [1.2, 2.5]  # Tungsten gains
                elif awb_mode == "fluorescent":
                    controls["ColourGains"] = [1.8, 1.2]  # Fluorescent gains
                    
            # Brightness/Contrast controls
            brightness = self._settings.get(["brightness"], 0.0)
            if brightness != 0.0:
                controls["Brightness"] = brightness
                
            contrast = self._settings.get(["contrast"], 1.0)
            if contrast != 1.0:
                controls["Contrast"] = contrast
                
            # Saturation controls
            saturation = self._settings.get(["saturation"], 1.0)
            if saturation != 1.0:
                controls["Saturation"] = saturation
                
            # Sharpness controls
            sharpness = self._settings.get(["sharpness"], 1.0)
            if sharpness != 1.0:
                controls["Sharpness"] = sharpness
                
            # Noise reduction (similar to camera-streamer's approach)
            noise_reduction = self._settings.get(["noise_reduction_mode"], "auto")
            if noise_reduction == "off":
                controls["NoiseReductionMode"] = 0  # Off
            elif noise_reduction == "fast":
                controls["NoiseReductionMode"] = 1  # Fast
            elif noise_reduction == "high_quality":
                controls["NoiseReductionMode"] = 2  # High quality
            # auto = default (don't set control)
                
            self._logger.debug(f"Applied camera controls: {controls}")
            return controls
            
        except Exception as e:
            self._logger.warning(f"Error configuring camera controls: {e}")
            return {}

    def _check_camera_availability(self):
        """Check if camera is available"""
        if self._settings.get(["fake_camera_mode"]):
            return True
        return self._camera_available

    def _capture_image(self, position_info=None):
        """Capture an image using the configured camera"""
        if not self._camera_available:
            raise Exception("Camera not available")
        
        if self._settings.get(["fake_camera_mode"]):
            return self._generate_fake_image(position_info)
        else:
            return self._capture_real_image()

    def _capture_real_image(self):
        """Capture image from real camera using modern libcamera approach"""
        try:
            image_data = io.BytesIO()
            
            if self._camera_type == "libcamera":
                # Modern libcamera capture (camera-streamer inspired)
                # Update controls before capture for dynamic adjustment
                controls = self._get_camera_controls()
                if controls:
                    self._camera.set_controls(controls)
                
                # Capture high-quality image
                image_array = self._camera.capture_array("main")
                image = Image.fromarray(image_array)
                
                # Apply rotation if needed
                rotation = self._settings.get(["camera_rotation"])
                if rotation:
                    image = image.rotate(-rotation, expand=True)
                
                # Apply any post-processing filters
                image = self._apply_image_processing(image)
                
                # Save with optimal quality settings
                save_format = self._settings.get(["image_format"]).upper()
                if save_format == "JPG":
                    save_format = "JPEG"
                    
                image.save(image_data, format=save_format, 
                          quality=self._settings.get(["image_quality"]),
                          optimize=True)
                
            else:
                raise Exception(f"Unsupported camera type: {self._camera_type}")
            
            image_data.seek(0)
            self._logger.debug(f"Captured high-quality image ({len(image_data.getvalue())} bytes)")
            return image_data.getvalue()
            
        except Exception as e:
            self._logger.error(f"Failed to capture image: {e}")
            raise

    def _apply_image_processing(self, image):
        """Apply image processing similar to camera-streamer optimizations"""
        try:
            # Apply any additional processing based on settings
            processing_enabled = self._settings.get(["enable_image_processing"], True)
            if not processing_enabled:
                return image
                
            # Auto-enhancement (inspired by camera-streamer's processing)
            auto_enhance = self._settings.get(["auto_enhance"], False)
            if auto_enhance:
                from PIL import ImageEnhance
                
                # Subtle automatic enhancements
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(1.1)  # Slight contrast boost
                
                enhancer = ImageEnhance.Sharpness(image)
                image = enhancer.enhance(1.05)  # Slight sharpness boost
                
            return image
            
        except Exception as e:
            self._logger.warning(f"Image processing failed, using original: {e}")
            return image

    def _generate_fake_image(self, position_info=None):
        """Generate a fake camera image for testing"""
        try:
            # Create image with specified resolution
            width = self._settings.get(["camera_resolution_x"])
            height = self._settings.get(["camera_resolution_y"])
            
            # Create base image with gradient background
            image = Image.new('RGB', (width, height), color='lightblue')
            draw = ImageDraw.Draw(image)
            
            # Draw gradient background
            for y in range(height):
                intensity = int(200 + (y / height) * 55)  # 200-255 gradient
                color = (intensity - 50, intensity - 30, intensity)
                draw.line([(0, y), (width, y)], fill=color)
            
            # Draw grid overlay to simulate print bed/positioning
            grid_size = 50
            grid_color = (100, 100, 100, 128)  # Semi-transparent gray
            
            for x in range(0, width, grid_size):
                draw.line([(x, 0), (x, height)], fill=grid_color)
            for y in range(0, height, grid_size):
                draw.line([(0, y), (width, y)], fill=grid_color)
            
            # Draw center crosshairs
            center_x, center_y = width // 2, height // 2
            cross_size = 20
            cross_color = (255, 0, 0)  # Red
            draw.line([(center_x - cross_size, center_y), (center_x + cross_size, center_y)], 
                     fill=cross_color, width=2)
            draw.line([(center_x, center_y - cross_size), (center_x, center_y + cross_size)], 
                     fill=cross_color, width=2)
            
            # Add position information if provided
            if position_info:
                text_y = 10
                try:
                    # Try to load a font (fallback to default if not available)
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                except:
                    font = ImageFont.load_default()
                
                info_text = f"X: {position_info.get('x', 0):.1f} Y: {position_info.get('y', 0):.1f} Z: {position_info.get('z', 0):.1f}"
                draw.text((10, text_y), info_text, fill=(255, 255, 255), font=font)
                text_y += 30
                
                if position_info.get('layer'):
                    layer_text = f"Layer: {position_info['layer']}"
                    draw.text((10, text_y), layer_text, fill=(255, 255, 255), font=font)
                    text_y += 30
            
            # Add timestamp
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                font = ImageFont.load_default()
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            draw.text((10, height - 30), f"Fake Cam: {timestamp}", fill=(255, 255, 255), font=font)
            
            # Add "FAKE CAMERA" watermark
            try:
                watermark_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            except:
                watermark_font = ImageFont.load_default()
            
            watermark_text = "FAKE CAMERA"
            # Calculate text size for centering
            bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Draw semi-transparent background for watermark
            watermark_x = (width - text_width) // 2
            watermark_y = (height - text_height) // 2
            
            # Create overlay for transparency
            overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.text((watermark_x, watermark_y), watermark_text, 
                            fill=(255, 0, 0, 128), font=watermark_font)
            
            # Composite the overlay onto the main image
            image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
            
            # Apply rotation if needed
            rotation = self._settings.get(["camera_rotation"])
            if rotation:
                image = image.rotate(-rotation, expand=True)
            
            # Convert to bytes
            image_data = io.BytesIO()
            image.save(image_data, format=self._settings.get(["image_format"]).upper(), 
                      quality=self._settings.get(["image_quality"]))
            
            image_data.seek(0)
            self._logger.debug(f"Generated fake image ({len(image_data.getvalue())} bytes)")
            return image_data.getvalue()
            
        except Exception as e:
            self._logger.error(f"Failed to generate fake image: {e}")
            raise

    def _save_image_with_metadata(self, image_data, position, layer_info):
        """Save image with metadata to configured directory"""
        try:
            save_path = self._ensure_save_directory()
            if not save_path:
                raise Exception("Could not create save directory")
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            layer_num = str(layer_info.get('layer', 0)).zfill(4)
            pos_index = str(position.get('index', 0)).zfill(2)
            
            filename = f"layer_{layer_num}_pos_{pos_index}_{timestamp}.{self._settings.get(['image_format'])}"
            filepath = os.path.join(save_path, filename)
            
            # Save image
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            # Create metadata
            metadata = {
                "layer": layer_info.get('layer'),
                "z_height": layer_info.get('z_height'),
                "timestamp": datetime.now().isoformat(),
                "gcode_file": self._current_gcode_file,
                "print_start_time": getattr(self, '_print_start_time', None),
                "calibration_file_path": self._get_calibration_file_path(),
                                 "images": [
                     {
                         "path": filename,
                         "position": position,
                         "index": position.get('index', 0)
                     }
                 ],
                "settings": {
                    "grid_spacing": self._settings.get(["grid_spacing"]),
                    "grid_center": {
                        "x": self._settings.get(["grid_center_x"]),
                        "y": self._settings.get(["grid_center_y"])
                    },
                    "grid_size": self._settings.get(["grid_size"]),
                    "z_offset": self._settings.get(["z_offset"]),
                    "camera_type": getattr(self, '_camera_type', 'none'),
                    "fake_camera_mode": self._settings.get(["fake_camera_mode"])
                }
            }
            
            # Save metadata JSON
            metadata_filename = f"layer_{layer_num}_pos_{pos_index}_{timestamp}.json"
            metadata_filepath = os.path.join(save_path, metadata_filename)
            
            with open(metadata_filepath, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            self._logger.info(f"Saved image and metadata: {filename}")
            return {
                "image_path": filepath,
                "metadata_path": metadata_filepath,
                "filename": filename
            }
            
        except Exception as e:
            self._logger.error(f"Failed to save image with metadata: {e}")
            raise

    def _capture_and_save_image(self, position, layer_info):
        """Capture image and save with metadata"""
        try:
            # Capture image with position information
            image_data = self._capture_image(position)
            
            # Save image with metadata
            result = self._save_image_with_metadata(image_data, position, layer_info)
            
            return result
            
        except Exception as e:
            self._logger.error(f"Failed to capture and save image: {e}")
            raise

    def _cleanup_camera(self):
        """Clean up camera resources (modern libcamera approach)"""
        try:
            if self._camera and self._camera_type == "libcamera":
                # Modern cleanup for libcamera
                self._camera.stop()
                self._camera.close()
                self._camera = None
                self._logger.debug("Modern camera resources cleaned up")
                
        except Exception as e:
            self._logger.warning(f"Error cleaning up camera: {e}")

    def _get_save_path(self):
        """Get the configured save path, expanding user directory"""
        save_path = self._settings.get(["save_path"])
        if save_path:
            return os.path.expanduser(save_path)
        return os.path.expanduser("~/.octoprint/uploads/layer_captures")

    def _ensure_save_directory(self):
        """Create save directory if it doesn't exist"""
        try:
            save_path = self._get_save_path()
            os.makedirs(save_path, exist_ok=True)
            self._logger.info(f"Save directory ensured: {save_path}")
            return save_path
        except Exception as e:
            self._logger.error(f"Failed to create save directory: {e}")
            return None

    def _get_calibration_file_path(self):
        """Get the configured calibration file path"""
        cal_path = self._settings.get(["calibration_file_path"])
        if cal_path:
            return os.path.expanduser(cal_path)
        return None

    def _validate_calibration_file(self):
        """Check if calibration file exists and is valid"""
        cal_path = self._get_calibration_file_path()
        if not cal_path:
            return False, "No calibration file configured"
        
        if not os.path.exists(cal_path):
            return False, f"Calibration file not found: {cal_path}"
        
        try:
            with open(cal_path, 'r') as f:
                import json
                json.load(f)
            return True, "Calibration file is valid"
        except Exception as e:
            return False, f"Invalid calibration file: {e}"

    def _on_print_started(self, payload):
        """Handle print start event"""
        if not self._settings.get(["enabled"]):
            return

        self._logger.info("Print started - initializing layer capture")
        self._capture_active = True
        self._current_layer = 0
        self._last_captured_layer = -1
        self._current_z_height = 0.0
        self._print_start_time = datetime.now()
        self._current_gcode_file = payload.get("name", "unknown.gcode")
        self._print_progress = 0.0
        self._original_position = None
        self._movement_in_progress = False
        self._print_paused_for_capture = False
        
        # Log capture configuration
        layer_interval = self._settings.get(["layer_interval"])
        grid_size = self._settings.get(["grid_size"])
        self._logger.info(f"Layer capture active - interval: every {layer_interval} layers, grid: {grid_size}x{grid_size}")

    def _on_print_finished(self, payload, reason):
        """Handle print end events"""
        self._logger.info(f"Print {reason} - stopping layer capture")
        
        # Clean up any ongoing operations
        if self._movement_in_progress:
            self._logger.warning("Print ended during movement - attempting cleanup")
            self._movement_in_progress = False
        
        if self._print_paused_for_capture:
            self._logger.info("Print ended while paused for capture")
            self._print_paused_for_capture = False
        
        # Reset state
        self._capture_active = False
        self._current_layer = 0
        self._last_captured_layer = -1
        self._current_z_height = 0.0
        self._print_start_time = None
        self._current_gcode_file = None
        self._print_progress = 0.0
        self._original_position = None
        self._movement_in_progress = False

    def _on_print_paused(self, payload):
        """Handle print pause event"""
        if not self._capture_active:
            return
            
        # Only log if this wasn't a pause we initiated
        if not self._print_paused_for_capture:
            self._logger.debug("Print paused by user/system")

    def _on_print_resumed(self, payload):
        """Handle print resume event"""
        if not self._capture_active:
            return
            
        if self._print_paused_for_capture:
            self._logger.debug("Print resumed after capture sequence")
            self._print_paused_for_capture = False
        else:
            self._logger.debug("Print resumed by user/system")

    def _on_error(self, payload):
        """Handle error events"""
        if not self._capture_active:
            return
            
        self._logger.warning(f"Error during print: {payload.get('error', 'Unknown error')}")
        
        # Clean up any ongoing operations
        if self._movement_in_progress:
            self._logger.warning("Error occurred during movement - cleaning up")
            self._movement_in_progress = False
            # Try to return to original position if possible
            self._attempt_position_recovery()

    def _on_disconnected(self, payload):
        """Handle printer disconnection"""
        if self._capture_active:
            self._logger.warning("Printer disconnected during active capture session")
            self._capture_active = False
            self._movement_in_progress = False
            self._print_paused_for_capture = False

    def _attempt_position_recovery(self):
        """Attempt to recover original position after error"""
        try:
            if self._original_position and self._printer.is_ready():
                self._logger.info("Attempting to recover original position")
                x, y, z = self._original_position
                self._send_gcode_command(f"G1 X{x:.2f} Y{y:.2f} Z{z:.2f} F{self._settings.get(['move_speed'])}")
                self._original_position = None
        except Exception as e:
            self._logger.error(f"Failed to recover position: {e}")

    def _on_z_change(self, payload):
        """Handle Z-axis change (layer change) event"""
        if not self._capture_active or not self._settings.get(["enabled"]):
            return

        new_z = payload.get("new", 0)
        old_z = payload.get("old", 0)

        # Only process upward Z movements (layer changes)
        if new_z <= old_z:
            return

        # Improved layer detection - try to get from gcode analysis first
        estimated_layer = self._estimate_layer_from_z(new_z)
        
        if estimated_layer > self._current_layer:
            self._logger.debug(f"Layer change detected: {self._current_layer} -> {estimated_layer} (Z: {old_z:.2f} -> {new_z:.2f})")
            self._current_layer = estimated_layer
            self._current_z_height = new_z
            self._check_capture_needed()

    def _estimate_layer_from_z(self, z_height):
        """Estimate layer number from Z height with improved logic"""
        try:
            # Try to get layer height from printer profile or job analysis
            layer_height = 0.2  # Default fallback
            
            # Try to get from current job analysis
            if hasattr(self._printer, 'get_current_job'):
                job = self._printer.get_current_job()
                if job and 'file' in job and 'analysis' in job['file']:
                    analysis = job['file']['analysis']
                    if 'printingArea' in analysis and 'z' in analysis['printingArea']:
                        # Estimate layer height from total height and estimated layers
                        if 'max' in analysis['printingArea']['z']:
                            total_height = analysis['printingArea']['z']['max']
                            # Very rough estimation - could be improved with gcode parsing
                            estimated_layers = max(1, total_height / 0.2)
                            layer_height = total_height / estimated_layers
            
            # Calculate layer number
            if z_height <= layer_height:
                return 1  # First layer
            else:
                return int((z_height - layer_height) / layer_height) + 1
                
        except Exception as e:
            self._logger.debug(f"Layer estimation error: {e}, using Z/0.2 fallback")
            return max(1, int(z_height / 0.2))

    def _check_capture_needed(self):
        """Check if we need to capture at current layer"""
        layer_interval = self._settings.get(["layer_interval"])
        
        if (self._current_layer > 0 and 
            self._current_layer % layer_interval == 0 and 
            self._current_layer != self._last_captured_layer):
            
            self._logger.info(f"Layer {self._current_layer} - triggering capture sequence")
            self._schedule_capture()

    def _schedule_capture(self):
        """Schedule a capture sequence in a separate thread"""
        if self._capture_thread and self._capture_thread.is_alive():
            self._logger.warning("Capture already in progress, skipping")
            return

        self._capture_thread = threading.Thread(target=self._execute_capture_sequence)
        self._capture_thread.daemon = True
        self._capture_thread.start()

    def _execute_capture_sequence(self):
        """Execute the full capture sequence"""
        try:
            if not self._camera_available:
                self._logger.error("Camera not available for capture sequence")
                return
                
            self._logger.info(f"Starting capture sequence for layer {self._current_layer}")
            
            # 1. Pause print safely
            if self._printer.is_printing():
                self._logger.info("Pausing print for capture sequence")
                self._printer.pause_print()
                self._print_paused_for_capture = True
                # Wait for pause to complete
                time.sleep(2)
                
                # Verify print is actually paused
                if not self._printer.is_paused():
                    raise Exception("Failed to pause print for capture")
            
            # Get current Z position (use tracked value or query printer)
            current_z = self._current_z_height or 0
            
            # 2. Generate grid positions
            grid_positions = self._calculate_grid_positions(current_z)
            
            if not grid_positions:
                raise Exception("No valid grid positions calculated")
            
            # 3. Execute grid movement and capture sequence
            layer_info = {
                'layer': self._current_layer,
                'z_height': current_z
            }
            
            captured_images = self._execute_grid_movement_sequence(grid_positions, layer_info)
            
            # 4. Mark as captured
            self._last_captured_layer = self._current_layer
            
            # 5. Resume print
            if self._printer.is_paused() and self._print_paused_for_capture:
                self._logger.info("Resuming print after capture sequence")
                self._printer.resume_print()
                self._print_paused_for_capture = False
            
            self._logger.info(f"Capture sequence completed for layer {self._current_layer} - captured {len(captured_images)} images")
            
        except Exception as e:
            self._logger.error(f"Capture sequence failed: {e}")
            
            # Clean up movement state
            if self._movement_in_progress:
                self._movement_in_progress = False
                # Try to restore position if possible
                self._attempt_position_recovery()
            
            # Try to resume print if it was paused
            try:
                if self._printer.is_paused() and self._print_paused_for_capture:
                    self._logger.info("Attempting to resume print after error")
                    self._printer.resume_print()
                    self._print_paused_for_capture = False
            except Exception as resume_error:
                self._logger.error(f"Failed to resume print after capture error: {resume_error}")

    def _calculate_grid_positions(self, current_z):
        """Calculate grid positions for capture"""
        positions = []
        
        grid_size = self._settings.get(["grid_size"])
        grid_spacing = self._settings.get(["grid_spacing"])
        grid_center_x = self._settings.get(["grid_center_x"])
        grid_center_y = self._settings.get(["grid_center_y"])
        z_offset = self._settings.get(["z_offset"])
        
        # Calculate capture Z position
        capture_z = current_z + z_offset
        
        # Generate grid positions
        if grid_size == 1:
            # Single position at center
            positions.append({
                'x': grid_center_x,
                'y': grid_center_y,
                'z': capture_z,
                'index': 0
            })
        else:
            # Multi-position grid
            half_size = (grid_size - 1) / 2
            index = 0
            
            for row in range(grid_size):
                for col in range(grid_size):
                    x = grid_center_x + (col - half_size) * grid_spacing
                    y = grid_center_y + (row - half_size) * grid_spacing
                    
                    # Check boundaries
                    if (self._settings.get(["min_x"]) <= x <= self._settings.get(["max_x"]) and
                        self._settings.get(["min_y"]) <= y <= self._settings.get(["max_y"]) and
                        0 <= capture_z <= self._settings.get(["max_z"])):
                        
                        positions.append({
                            'x': x,
                            'y': y,
                            'z': capture_z,
                            'index': index
                        })
                        index += 1
        
        return positions

    ##~~ Grid Positioning and Movement Methods

    def _send_gcode_command(self, command):
        """Send G-code command to printer"""
        try:
            if self._printer.is_ready() or self._printer.is_paused():
                self._logger.debug(f"Sending G-code: {command}")
                self._printer.commands(command)
                return True
            else:
                self._logger.warning(f"Printer not ready for G-code command: {command}")
                return False
        except Exception as e:
            self._logger.error(f"Failed to send G-code command '{command}': {e}")
            return False

    def _get_current_position(self):
        """Get current printer position"""
        try:
            # Send M114 to get current position
            self._send_gcode_command("M114")
            
            # Try to get position from printer data
            if hasattr(self._printer, 'get_current_data'):
                data = self._printer.get_current_data()
                if data and 'currentZ' in data:
                    return {
                        'x': data.get('currentX', 0),
                        'y': data.get('currentY', 0), 
                        'z': data.get('currentZ', 0)
                    }
            
            return None
        except Exception as e:
            self._logger.error(f"Failed to get current position: {e}")
            return None

    def _store_current_position(self):
        """Store current position for later restoration"""
        try:
            # If movement is disabled, simulate stored position
            if not self._settings.get(["enable_movement"]):
                self._original_position = (0, 0, 0)  # Dummy position
                self._logger.debug("Movement disabled - simulating position storage")
                return True
            
            position = self._get_current_position()
            if position:
                self._original_position = (position['x'], position['y'], position['z'])
                self._logger.debug(f"Stored original position: X{position['x']:.2f} Y{position['y']:.2f} Z{position['z']:.2f}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"Failed to store current position: {e}")
            return False

    def _move_to_position(self, x, y, z, speed=None):
        """Move print head to specified position"""
        try:
            if not self._validate_position(x, y, z):
                raise Exception(f"Position validation failed: X{x:.2f} Y{y:.2f} Z{z:.2f}")
            
            # Check if movement is enabled
            if not self._settings.get(["enable_movement"]):
                self._logger.info(f"Movement disabled - simulating move to: X{x:.2f} Y{y:.2f} Z{z:.2f}")
                # Just add delay for simulation
                capture_delay = self._settings.get(["capture_delay"])
                if capture_delay > 0:
                    time.sleep(capture_delay)
                return True
            
            speed = speed or self._settings.get(["move_speed"])
            
            # Move to position with specified speed
            command = f"G1 X{x:.2f} Y{y:.2f} Z{z:.2f} F{speed}"
            success = self._send_gcode_command(command)
            
            if success:
                # Add small delay to allow movement to complete
                capture_delay = self._settings.get(["capture_delay"])
                if capture_delay > 0:
                    time.sleep(capture_delay)
                
                self._logger.debug(f"Moved to position: X{x:.2f} Y{y:.2f} Z{z:.2f}")
                return True
            else:
                raise Exception("G-code command failed")
                
        except Exception as e:
            self._logger.error(f"Failed to move to position X{x:.2f} Y{y:.2f} Z{z:.2f}: {e}")
            return False

    def _validate_position(self, x, y, z):
        """Validate that position is within safety boundaries"""
        try:
            min_x = self._settings.get(["min_x"])
            max_x = self._settings.get(["max_x"])
            min_y = self._settings.get(["min_y"])
            max_y = self._settings.get(["max_y"])
            max_z = self._settings.get(["max_z"])
            
            if not (min_x <= x <= max_x):
                self._logger.warning(f"X position {x:.2f} outside bounds [{min_x:.2f}, {max_x:.2f}]")
                return False
                
            if not (min_y <= y <= max_y):
                self._logger.warning(f"Y position {y:.2f} outside bounds [{min_y:.2f}, {max_y:.2f}]")
                return False
                
            if not (0 <= z <= max_z):
                self._logger.warning(f"Z position {z:.2f} outside bounds [0, {max_z:.2f}]")
                return False
                
            return True
            
        except Exception as e:
            self._logger.error(f"Position validation error: {e}")
            return False

    def _restore_original_position(self):
        """Restore print head to original position"""
        try:
            if not self._original_position:
                self._logger.warning("No original position stored to restore")
                return False
                
            x, y, z = self._original_position
            self._logger.info(f"Restoring original position: X{x:.2f} Y{y:.2f} Z{z:.2f}")
            
            success = self._move_to_position(x, y, z)
            if success:
                self._original_position = None
                return True
            else:
                self._logger.error("Failed to restore original position")
                return False
                
        except Exception as e:
            self._logger.error(f"Error restoring original position: {e}")
            return False

    def _execute_grid_movement_sequence(self, grid_positions, layer_info):
        """Execute the complete grid movement and capture sequence"""
        captured_images = []
        self._movement_in_progress = True
        
        try:
            # Store original position
            if not self._store_current_position():
                raise Exception("Failed to store original position")
            
            # Execute captures at each grid position
            for i, position in enumerate(grid_positions):
                try:
                    self._logger.info(f"Moving to capture position {i+1}/{len(grid_positions)}: X{position['x']:.1f} Y{position['y']:.1f} Z{position['z']:.1f}")
                    
                    # Move to position
                    if not self._move_to_position(position['x'], position['y'], position['z']):
                        self._logger.error(f"Failed to move to position {i+1}")
                        continue
                    
                    # Capture image at this position
                    result = self._capture_and_save_image(position, layer_info)
                    captured_images.append(result)
                    
                    self._logger.info(f"Successfully captured image {i+1}/{len(grid_positions)}")
                    
                except Exception as e:
                    self._logger.error(f"Failed to capture at position {i+1}: {e}")
                    continue
            
            # Restore original position
            if not self._restore_original_position():
                self._logger.warning("Failed to restore original position - print may be affected")
            
            self._movement_in_progress = False
            return captured_images
            
        except Exception as e:
            self._logger.error(f"Grid movement sequence failed: {e}")
            
            # Attempt to restore position on error
            try:
                self._restore_original_position()
            except:
                self._logger.error("Failed to restore position after error")
            
            self._movement_in_progress = False
            raise

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
    __plugin_implementation__ = LayerCaptureDatacollectPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
