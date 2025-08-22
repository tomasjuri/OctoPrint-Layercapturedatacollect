# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.events
import octoprint.printer
import octoprint.util

import os
import re
import logging
import time
import json
from datetime import datetime
import random
import threading

from .camera import Camera
from .camera_fake import CameraFake

LAYER_CAPTURE_TRIGGER_MCODE = "M240"
DEFAULT_SAVE_PATH = "~/.octoprint/uploads/layer_captures"

CAM_X_OFFSET = -35
CAM_Y_OFFSET = 18
CAM_Z_OFFSET = 60

class LayerCaptureDatacollect(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.StartupPlugin,
):
    
    def __init__(self):    
        self._logger = logging.getLogger(__name__)
        self._camera = None
        self._capture_in_progress = False
        self._job_on_hold = False
        
        # Position tracking for pause/resume
        self._capture_in_progress = False
        self._original_position = None
        self._capture_positions = []
        self._waiting_for_position = False
        self._last_m114_position = None
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Movement synchronization
        self._position_event = threading.Event()
        self._position_response = None
        self._movement_timeout = 30.0  # 30 second timeout for movements
        
        self._logger.info("Layer Capture Data Collect plugin initialized!")

    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin starting up")

        # Initialize camera system
        self._camera = CameraFake()
        # self._camera = Camera()
        self._camera.initialize()
        
        # Ensure save directory exists
        self._ensure_save_directory()
        self._save_path = self._get_save_path()

    def on_shutdown(self):
        """Clean up resources when OctoPrint shuts down"""
        self._logger.info("Layer Capture Data Collect plugin shutting down")
        self._camera.cleanup()

    def get_assets(self):
        return {
            "js": ["js/LayerCaptureDatacollect.js"],
            "css": ["css/LayerCaptureDatacollect.css"],
            "less": ["less/LayerCaptureDatacollect.less"]
        }

    def get_settings_defaults(self):
        return {
            # Plugin control
            "enabled": True,
            
            # Grid configuration
            "grid_center_x": 100.0,
            "grid_center_y": 100.0,
            "grid_spacing": 20,
            "grid_size": 3,
            "z_offset": 10.0,
            
            # Capture settings
            "layer_interval": 5,
            
            # Safety boundaries
            "min_x": 0.0,
            "max_x": 200.0,
            "min_y": 0.0,
            "max_y": 200.0,
            "max_z": 200.0,
            
            # Camera settings
            "camera_enabled": True,
            "image_format": "jpg",
            "image_quality": 85,
            "fake_camera_mode": True,
            "camera_resolution_x": 1640,
            "camera_resolution_y": 1232,
            "camera_iso": 100,
            "camera_rotation": 0,
            "camera_shutter_speed": 0,
            
            # Advanced camera controls
            "exposure_mode": "auto",
            "white_balance_mode": "auto",
            "brightness": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "sharpness": 1.0,
            "noise_reduction_mode": "auto",
            "enable_image_processing": False,
            "auto_enhance": False,
            
            # Advanced settings
            "move_speed": 3000,
            "capture_delay": 1.0,
            "enable_movement": True,
            
            # File paths
            "save_path": DEFAULT_SAVE_PATH,
            "calibration_file_path": ""
        }

    def get_template_configs(self):
        return [
            {
                "type": "settings",
                "custom_bindings": False
            }
        ]

    def on_event(self, event, payload):
        # Print lifecycle events
        if event == octoprint.events.Events.PRINT_STARTED:
            self._logger.debug("OnEvent: Print started")
            # Reset capture state
            self._capture_in_progress = False
            self._original_position = None
        elif event in [octoprint.events.Events.PRINT_DONE, 
                      octoprint.events.Events.PRINT_FAILED, 
                      octoprint.events.Events.PRINT_CANCELLED]:
            self._logger.debug("OnEvent: Print finished")
            # Reset capture state
            self._capture_in_progress = False
            self._original_position = None
        elif event == "layer_capture_event":
            # self._logger.debug(f"Layer capture event received: {payload}")
            # self._capture(payload)
            pass

        elif event == octoprint.events.Events.PRINT_PAUSED:
            pass
        elif event == octoprint.events.Events.PRINT_RESUMED:
            pass

    def _get_save_path(self):
        """Get the configured save path"""
        save_path = self._settings.get(["save_path"])
        if not save_path:
            save_path = DEFAULT_SAVE_PATH
        save_path = os.path.expanduser(save_path)
        save_path = os.path.join(save_path, self._timestamp)
        return save_path

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

    def on_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        """Intercept gcode before it's sent to printer"""
        if not self._printer.is_printing():
            return None
            
        line = cmd.strip().upper()
        
        # Detect M240 trigger
        if "M240" in line:
            self._logger.info("M240 detected, starting capture sequence")
            
            # Extract parameters
            try:
                layer_z = re.search(r'Z\s*([+-]?\d*\.?\d+)', line).group(1)
                layer_num = re.search(r'ZN\s*([+-]?\d*\.?\d+)', line).group(1)
            except:
                self._logger.error("Failed to parse M240 parameters")
                return None
            
            # Briefly set job on hold to suppress this command
            if self._printer.set_job_on_hold(True):
                self._logger.debug("Job on hold acquired")
                
                # Start capture in separate thread
                thread = threading.Thread(
                    target=self._do_capture_sequence_async, 
                    args=[layer_z, layer_num, cmd]
                )
                thread.daemon = True
                thread.start()
                
                # wait for the thread to finish
                self._printer.set_job_on_hold(False)
                self._logger.debug("Job hold released immediately")
                
                # Suppress the M240 command (we'll send it later)
                return None,


        
        return None  # Let other commands pass through

    def _do_capture_sequence_async(self, layer_z, layer_num, original_cmd):
        """Execute capture sequence in separate thread - NO JOB HOLD"""
        try:
            self._logger.info(f"Starting capture sequence for layer {layer_num}")
            
            # Small delay to ensure the job hold release is processed
            time.sleep(0.1)
            
            # Now we can send commands normally (job is not on hold)
            current_pos = self._get_current_position_sync()
            if current_pos is None:
                self._logger.error("Failed to get current position")
                return
            else:
                self._logger.debug(f"Current position received: {current_pos}")
                
            # Execute movement sequence
            success = self._execute_movement_sequence(current_pos, layer_z, layer_num)
            
            if success:
                # Send the original M240 command to continue the print
                self._printer.commands([original_cmd], tags={'layer-capture-resume'})
                self._logger.debug("Original M240 command sent to resume print")
                
        except Exception as e:
            self._logger.error(f"Error in capture sequence: {e}")
            # Send the original command anyway to continue the print
            self._printer.commands([original_cmd], tags={'layer-capture-resume'})

    def _get_current_position_sync(self):
        """Get current position - job is NOT on hold here"""
        self._position_event.clear()
        self._position_response = None
        self._waiting_for_position = True
        
        try:
            # Send M400 (wait for moves) + M114 (get position) 
            self._printer.commands(["M400", "M114"], tags={'layer-capture-position'})
            
            # Wait for position response with timeout
            if self._position_event.wait(5.0):
                return self._position_response
            else:
                self._logger.error("Position request timeout")
                return None
                
        finally:
            self._waiting_for_position = False

    def _execute_movement_sequence(self, current_pos, layer_z, layer_num):
        """Execute the movement and capture sequence - simplified version"""
        try:
            # Retract extruder
            self._logger.debug("Retracting extruder...")
            self._printer.commands([
                "M83",  # Relative extruder mode
                "G1 E-0.7 F1800",  # Retract
                "M400"  # Wait for completion
            ], tags={'layer-capture-retract'})
            
            # Small delay for retraction
            time.sleep(0.1)
            
            # Calculate target position
            target_x = current_pos['x'] + CAM_X_OFFSET + random.randint(-10, 10)
            target_y = current_pos['y'] + CAM_Y_OFFSET + random.randint(-10, 10)
            target_z = current_pos['z'] + CAM_Z_OFFSET + random.randint(-10, 10)
            
            # Move to capture position
            self._logger.debug(f"Moving to capture position: X{target_x} Y{target_y} Z{target_z}")
            self._printer.commands([
                "G90",  # Absolute positioning
                f"G0 X{target_x} Y{target_y} Z{target_z} F5000",
                "M400"  # Wait for completion
            ], tags={'layer-capture-move'})
            
            # Wait for movement and vibrations to settle
            time.sleep(1.0)
            
            # Capture image
            self._logger.debug("Capturing image...")
            img = self._camera.capture_image()
            self._logger.debug(f"Captured image: {img.size}")
            
            # Save image and metadata using existing methods
            self._save_image_and_metadata(img, layer_num, layer_z, current_pos, target_x, target_y, target_z)
            
            # Return to original position
            self._logger.debug(f"Returning to original position: X{current_pos['x']} Y{current_pos['y']} Z{current_pos['z']}")
            self._printer.commands([
                f"G0 X{current_pos['x']} Y{current_pos['y']} Z{current_pos['z']} F5000",
                "M400"
            ], tags={'layer-capture-return'})
            
            # Wait for return movement
            time.sleep(0.5)
            
            # Un-retract extruder
            self._logger.debug("Un-retracting extruder...")
            self._printer.commands([
                "M83",  # Relative extruder mode  
                "G1 E0.7 F1800",  # Un-retract
                "M400"
            ], tags={'layer-capture-unretract'})
            
            return True
            
        except Exception as e:
            self._logger.error(f"Movement sequence failed: {e}")
            return False

    def _save_image_and_metadata(self, img, layer_num, layer_z, current_pos, target_x, target_y, target_z):
        """Save image and metadata - extracted from existing code"""
        # Save image and metadata
        img_path = os.path.join(self._save_path, f"layer_{layer_num}_img.jpg")
        meta_path = os.path.join(self._save_path, f"layer_{layer_num}_meta.json")
        
        img.save(img_path)
        self._logger.debug(f"Saved image to {img_path}")
        
        # Calculate relative position for metadata
        position_relative = {
            "x": target_x - current_pos['x'],
            "y": target_y - current_pos['y'], 
            "z": target_z - current_pos['z']
        }
        
        gen_metadata = self._generate_capture_metadata(
            layer_num, layer_z, position_relative, img)
        with open(meta_path, "w") as f:
            json.dump(gen_metadata, f)
        self._logger.debug(f"Saved metadata to {meta_path}")

    # Keep your existing gcode_received method for position parsing
    def gcode_received(self, comm_instance, line, *args, **kwargs):
        """Handle position responses"""
        position = {"x": None, "y": None, "z": None, "e": None}

        pos_re = r'^ok X:(\d+\.\d+) Y:(\d+\.\d+) Z:(\d+\.\d+) E:(\d+\.\d+) Count: A:'
        pos_matched = re.search(pos_re, line)
        if pos_matched:
            position["x"] = float(pos_matched.group(1))
            position["y"] = float(pos_matched.group(2))
            position["z"] = float(pos_matched.group(3))
            position["e"] = float(pos_matched.group(4))
            
            self._logger.debug(f"Position received: X: {position['x']}, Y: {position['y']}, Z: {position['z']}, E: {position['e']}")

        if self._waiting_for_position and pos_matched:
            self._waiting_for_position = False
            self._position_event.set()
            self._position_response = position
        return line

    def _send_gcode_and_wait_for_completion(self, gcode_commands, timeout=None):
        """Send G-code commands and wait for movement completion using M400/M114"""
        if timeout is None:
            timeout = self._movement_timeout
            
        self._logger.debug(f"Sending G-code commands: {gcode_commands}")
        
        # Clear any previous position response
        self._position_event.clear()
        self._position_response = None
        self._waiting_for_position = True
        
        try:
            # Send the movement commands
            for cmd in gcode_commands:
                self._printer.commands([cmd])
            
            # Send M400 (wait for moves to finish) and M114 (get position)
            self._printer.commands(["M400", "M114"])
            
            # Wait for position response
            if self._position_event.wait(timeout):
                self._logger.debug("Movement completed successfully")
                return self._position_response
            else:
                self._logger.error(f"Movement timeout after {timeout} seconds")
                return None
                
        except Exception as e:
            self._logger.error(f"Error during synchronized movement: {e}")
            return None
        finally:
            self._waiting_for_position = False

    def _move_to_absolute_position(self, x, y, z, speed=None):
        """Move to absolute position using synchronized G-code commands"""
        gcode_commands = []
        
        # Set to absolute positioning
        gcode_commands.append("G90")
        
        # Build movement command
        move_cmd = f"G0 X{x} Y{y} Z{z}"
        if speed:
            move_cmd += f" F{speed}"
        
        gcode_commands.append(move_cmd)
        
        return self._send_gcode_and_wait_for_completion(gcode_commands)

    def _move_relative(self, x, y, z, speed=None):
        """Move relative using synchronized G-code commands"""
        gcode_commands = []
        
        # Set to relative positioning  
        gcode_commands.append("G91")
        
        # Build movement command
        move_cmd = f"G0 X{x} Y{y} Z{z}"
        if speed:
            move_cmd += f" F{speed}"
        
        gcode_commands.append(move_cmd)
        
        # Return to absolute positioning (safer default)
        gcode_commands.append("G90")
        
        return self._send_gcode_and_wait_for_completion(gcode_commands)

    def _generate_capture_metadata(self, layer_num, layer_z, position_relative, img):
        """Generate capture metadata"""
        metadata = {
            "layer_num": layer_num,
            "layer_z": layer_z,
            "position_relative": position_relative,
            "img_shape": img.size}
        return metadata
                
                
    

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

