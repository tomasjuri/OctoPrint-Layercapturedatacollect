# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.events
import octoprint.printer
import octoprint.util

import os
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
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.StartupPlugin
):

    def __init__(self):
        self._capture_active = False
        self._current_layer = 0
        self._last_captured_layer = -1
        self._print_start_time = None
        self._current_gcode_file = None
        self.calibration_file = None
        self._capture_thread = None

    ##~~ StartupPlugin mixin

    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin initialized")
        # Initialize camera system
        self._init_camera()
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
            
            # Camera Settings
            "camera_enabled": True,        # Enable camera capture
            "fake_camera_mode": False,     # Use fake camera for testing (no physical camera needed)
            "image_format": "jpg",         # Image format (jpg, png)
            "image_quality": 95,           # JPEG quality (1-100)
            "camera_resolution_x": 1640,   # Camera resolution width
            "camera_resolution_y": 1232,   # Camera resolution height
            "camera_iso": 100,             # Camera ISO setting (100-800)
            "camera_shutter_speed": 0,     # Camera shutter speed (0 = auto, microseconds)
            "camera_rotation": 0,          # Camera rotation (0, 90, 180, 270)
            
            # Advanced Settings
            "move_speed": 3000,           # Speed for positioning moves (mm/min)
            "capture_delay": 0.1,         # Delay after positioning before capture (seconds)
            
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
        if event == octoprint.events.Events.PRINT_STARTED:
            self._on_print_started(payload)
        elif event == octoprint.events.Events.PRINT_DONE:
            self._on_print_finished(payload)
        elif event == octoprint.events.Events.PRINT_FAILED:
            self._on_print_finished(payload)
        elif event == octoprint.events.Events.PRINT_CANCELLED:
            self._on_print_finished(payload)
        elif event == octoprint.events.Events.Z_CHANGE:
            self._on_z_change(payload)

    ##~~ SimpleApiPlugin mixin

    def get_api_commands(self):
        return {
            "capture_now": [],
            "get_status": [],
            "enable": [],
            "disable": [],
            "test_camera": [],
            "test_paths": []
        }

    def on_api_command(self, command, data):
        if command == "capture_now":
            return self._api_capture_now()
        elif command == "get_status":
            return self._api_get_status()
        elif command == "enable":
            return self._api_enable()
        elif command == "disable":
            return self._api_disable()
        elif command == "test_camera":
            return self._api_test_camera()
        elif command == "test_paths":
            return self._api_test_paths()

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
        """Initialize real Raspberry Pi camera (only Pi camera supported)"""
        try:
            # Try picamera2 first (newer, preferred for Raspberry Pi)
            try:
                from picamera2 import Picamera2
                self._camera = Picamera2()
                
                # Configure camera
                config = self._camera.create_still_configuration(
                    main={
                        "size": (
                            self._settings.get(["camera_resolution_x"]),
                            self._settings.get(["camera_resolution_y"])
                        )
                    }
                )
                self._camera.configure(config)
                
                # Set camera parameters
                controls = {}
                shutter_speed = self._settings.get(["camera_shutter_speed"])
                if shutter_speed > 0:
                    controls["ExposureTime"] = shutter_speed
                
                iso = self._settings.get(["camera_iso"])
                if iso:
                    controls["AnalogueGain"] = float(iso / 100.0)
                
                if controls:
                    self._camera.set_controls(controls)
                
                self._camera.start()
                self._camera_type = "picamera2"
                self._logger.info("Initialized Raspberry Pi Camera with Picamera2")
                return True
                
            except ImportError:
                self._logger.debug("Picamera2 not available, trying legacy picamera")
                
                # Fallback to legacy picamera (for older Raspberry Pi systems)
                try:
                    import picamera
                    self._camera = picamera.PiCamera()
                    
                    # Configure camera
                    self._camera.resolution = (
                        self._settings.get(["camera_resolution_x"]),
                        self._settings.get(["camera_resolution_y"])
                    )
                    self._camera.rotation = self._settings.get(["camera_rotation"])
                    self._camera.iso = self._settings.get(["camera_iso"])
                    
                    shutter_speed = self._settings.get(["camera_shutter_speed"])
                    if shutter_speed > 0:
                        self._camera.shutter_speed = shutter_speed
                    
                    # Warm up camera
                    time.sleep(2)
                    
                    self._camera_type = "picamera"
                    self._logger.info("Initialized Raspberry Pi Camera with legacy picamera")
                    return True
                    
                except ImportError:
                    self._logger.warning("Raspberry Pi camera libraries not available (picamera2 or picamera). Only fake camera mode is supported on this system.")
                    return False
                    
        except Exception as e:
            self._logger.error(f"Failed to initialize Raspberry Pi camera: {e}")
            return False

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
        """Capture image from real camera"""
        try:
            image_data = io.BytesIO()
            
            if self._camera_type == "picamera2":
                # Capture with picamera2
                image_array = self._camera.capture_array()
                image = Image.fromarray(image_array)
                
                # Apply rotation if needed
                rotation = self._settings.get(["camera_rotation"])
                if rotation:
                    image = image.rotate(-rotation, expand=True)
                
                # Save to BytesIO
                image.save(image_data, format=self._settings.get(["image_format"]).upper(), 
                          quality=self._settings.get(["image_quality"]))
                
            elif self._camera_type == "picamera":
                # Capture with legacy picamera
                self._camera.capture(image_data, format=self._settings.get(["image_format"]))
            
            else:
                raise Exception(f"Unknown camera type: {self._camera_type}")
            
            image_data.seek(0)
            self._logger.debug(f"Captured real image ({len(image_data.getvalue())} bytes)")
            return image_data.getvalue()
            
        except Exception as e:
            self._logger.error(f"Failed to capture real image: {e}")
            raise

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
        """Clean up camera resources"""
        try:
            if self._camera and self._camera_type in ["picamera", "picamera2"]:
                if self._camera_type == "picamera2":
                    self._camera.stop()
                    self._camera.close()
                elif self._camera_type == "picamera":
                    self._camera.close()
                
                self._camera = None
                self._logger.debug("Camera resources cleaned up")
                
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
        self._print_start_time = datetime.now()
        self._current_gcode_file = payload.get("name", "unknown.gcode")

    def _on_print_finished(self, payload):
        """Handle print end events"""
        self._logger.info("Print finished - stopping layer capture")
        self._capture_active = False
        self._current_layer = 0
        self._last_captured_layer = -1
        self._print_start_time = None
        self._current_gcode_file = None

    def _on_z_change(self, payload):
        """Handle Z-axis change (layer change) event"""
        if not self._capture_active or not self._settings.get(["enabled"]):
            return

        new_z = payload.get("new", 0)
        old_z = payload.get("old", 0)

        # Estimate current layer (rough calculation)
        # TODO: Improve layer detection logic
        estimated_layer = int(new_z / 0.2)  # Assuming 0.2mm layer height
        
        if estimated_layer > self._current_layer:
            self._current_layer = estimated_layer
            self._check_capture_needed()

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
                # Wait for pause to complete
                time.sleep(2)
            
            # Get current Z position
            current_z = 0
            try:
                if hasattr(self._printer, 'get_current_data'):
                    printer_data = self._printer.get_current_data()
                    if printer_data and 'currentZ' in printer_data:
                        current_z = printer_data['currentZ'] or 0
            except:
                pass
            
            # 2. Generate grid positions
            grid_positions = self._calculate_grid_positions(current_z)
            
            # 3. Capture images at each grid position
            layer_info = {
                'layer': self._current_layer,
                'z_height': current_z
            }
            
            captured_images = []
            for i, position in enumerate(grid_positions):
                try:
                    self._logger.info(f"Capturing image {i+1}/{len(grid_positions)} at position X:{position['x']:.1f} Y:{position['y']:.1f} Z:{position['z']:.1f}")
                    
                    # Note: In a real implementation, you would move the print head here
                    # For now we just capture with position metadata
                    result = self._capture_and_save_image(position, layer_info)
                    captured_images.append(result)
                    
                    # Small delay between captures
                    time.sleep(self._settings.get(["capture_delay"]))
                    
                except Exception as e:
                    self._logger.error(f"Failed to capture image {i+1}: {e}")
                    continue
            
            # 4. Mark as captured
            self._last_captured_layer = self._current_layer
            
            # 5. Resume print
            if self._printer.is_paused():
                self._logger.info("Resuming print after capture sequence")
                self._printer.resume_print()
            
            self._logger.info(f"Capture sequence completed for layer {self._current_layer} - captured {len(captured_images)} images")
            
        except Exception as e:
            self._logger.error(f"Capture sequence failed: {e}")
            
            # Try to resume print if it was paused
            try:
                if self._printer.is_paused():
                    self._logger.info("Attempting to resume print after error")
                    self._printer.resume_print()
            except:
                self._logger.error("Failed to resume print after capture error")

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

    ##~~ API Methods

    def _api_capture_now(self):
        """API command to capture images now"""
        try:
            if not self._camera_available:
                return {"success": False, "message": "Camera not available"}
            
            # Get current position or use defaults
            current_position = 0
            if hasattr(self._printer, 'get_current_data'):
                printer_data = self._printer.get_current_data()
                if printer_data and 'currentZ' in printer_data:
                    current_position = printer_data['currentZ'] or 0
            
            # Capture at current grid center position
            capture_position = {
                'x': self._settings.get(["grid_center_x"]),
                'y': self._settings.get(["grid_center_y"]),
                'z': current_position + self._settings.get(["z_offset"]),
                'index': 0
            }
            
            layer_info = {
                'layer': 'MANUAL',
                'z_height': current_position
            }
            
            # Capture and save image
            result = self._capture_and_save_image(capture_position, layer_info)
            
            return {
                "success": True,
                "message": f"Manual capture successful - saved {result['filename']}",
                "image_path": result['image_path'],
                "metadata_path": result['metadata_path']
            }
            
        except Exception as e:
            self._logger.error(f"Manual capture failed: {e}")
            return {"success": False, "message": f"Capture failed: {str(e)}"}

    def _api_get_status(self):
        """API command to get plugin status"""
        return {
            "enabled": self._settings.get(["enabled"]),
            "capture_active": self._capture_active,
            "current_layer": self._current_layer,
            "last_captured_layer": self._last_captured_layer,
            "camera_available": getattr(self, '_camera_available', False),
            "camera_type": getattr(self, '_camera_type', 'none'),
            "fake_camera_mode": self._settings.get(["fake_camera_mode"]),
            "print_file": self._current_gcode_file,
            "save_path": self._get_save_path(),
            "calibration_file": self._get_calibration_file_path()
        }

    def _api_enable(self):
        """API command to enable plugin"""
        self._settings.set(["enabled"], True)
        self._settings.save()
        return {"success": True, "message": "Plugin enabled"}

    def _api_disable(self):
        """API command to disable plugin"""
        self._settings.set(["enabled"], False)
        self._settings.save()
        return {"success": True, "message": "Plugin disabled"}

    def _api_test_camera(self):
        """API command to test camera"""
        try:
            if not self._camera_available:
                return {
                    "success": False,
                    "message": "Camera not available",
                    "available": False,
                    "camera_type": getattr(self, '_camera_type', 'none')
                }
            
            # Capture a test image
            test_position = {
                'x': 125.0,
                'y': 105.0,
                'z': 5.0,
                'layer': 'TEST'
            }
            
            image_data = self._capture_image(test_position)
            
            # Save test image
            save_path = self._ensure_save_directory()
            if save_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"camera_test_{timestamp}.{self._settings.get(['image_format'])}"
                filepath = os.path.join(save_path, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(image_data)
                
                return {
                    "success": True,
                    "message": f"Camera test successful - image saved as {filename}",
                    "available": True,
                    "camera_type": self._camera_type,
                    "image_size": len(image_data),
                    "filepath": filepath
                }
            else:
                return {
                    "success": False,
                    "message": "Camera test failed - could not create save directory",
                    "available": True,
                    "camera_type": self._camera_type
                }
                
        except Exception as e:
            self._logger.error(f"Camera test failed: {e}")
            return {
                "success": False,
                "message": f"Camera test failed: {str(e)}",
                "available": getattr(self, '_camera_available', False),
                "camera_type": getattr(self, '_camera_type', 'none')
            }

    def _api_test_paths(self):
        """API command to test file paths configuration"""
        results = {}
        
        # Test save path
        save_path = self._ensure_save_directory()
        results["save_path"] = {
            "path": save_path,
            "exists": save_path is not None and os.path.exists(save_path),
            "writable": save_path is not None and os.access(save_path, os.W_OK) if save_path else False
        }
        
        # Test calibration file
        cal_valid, cal_message = self._validate_calibration_file()
        cal_path = self._get_calibration_file_path()
        results["calibration_file"] = {
            "path": cal_path,
            "configured": cal_path is not None and cal_path != "",
            "valid": cal_valid,
            "message": cal_message
        }
        
        success = results["save_path"]["writable"] and (
            not results["calibration_file"]["configured"] or results["calibration_file"]["valid"]
        )
        
        return {
            "success": success,
            "message": "Path configuration tested",
            "results": results
        }

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
