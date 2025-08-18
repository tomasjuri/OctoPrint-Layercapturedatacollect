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

from .camera import Camera

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
        self._camera = None  # Will be initialized in on_after_startup
        
        # Position tracking for pause/resume
        self._capture_in_progress = False
        self._original_position = None
        self._capture_positions = []
        self._waiting_for_position = False
        self._last_m114_position = None
        
        self._logger.info("Layer Capture Data Collect plugin initialized")

    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin starting up")
        self._logger.debug("Layer Capture Data Collect plugin starting up")
        # Initialize camera system
        self._camera = Camera() # TODO: add settings for fake camera mode, focus mode, focus distance, size
        self._camera.initialize()
        
        # Ensure save directory exists
        self._ensure_save_directory()

    def on_shutdown(self):
        """Clean up resources when OctoPrint shuts down"""
        self._logger.info("Layer Capture Data Collect plugin shutting down")
        self._camera.cleanup()

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

    ##~~ Camera Methods


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

        """Handle gcode responses from printer, especially M114 position reports"""
        # Look for M114 response: "X:123.45 Y:67.89 Z:12.34 E:45.67"
        if "X:" in line and "Y:" in line and "Z:" in line:
            try:
                import re
                position = {}
                for axis in ['X', 'Y', 'Z', 'E']:
                    pattern = rf'{axis}:\s*([+-]?\d*\.?\d+)'
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        position[axis.lower()] = float(match.group(1))
                
                if 'x' in position and 'y' in position and 'z' in position:
                    self._last_m114_position = position
                    # self._logger.debug(f"Updated M114 position: {position}")
            except Exception as e:
                self._logger.warning(f"Failed to parse M114 response '{line}': {e}")
        return line

    def gcode_command_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        """Capture sequence detection and capture action"""
        line = cmd.strip().upper()

        # detect:
        # M240 Z[layer_z] ZN[layer_num] MIN0[first_layer_print_min_0] MAX0[first_layer_print_max_0] MIN1[first_layer_print_min_1] MAX1[first_layer_print_max_1]    ; Start layer capture sequence

        
        # Trigger capture on M240
        if "M240" in line:
            self._logger.debug("1. M240 detected")
            
            # get variables from the command
            layer_z = re.search(r'Z\s*([+-]?\d*\.?\d+)', line).group(1)
            layer_num = re.search(r'ZN\s*([+-]?\d*\.?\d+)', line).group(1)
            self._logger.debug(f"Gcode command received: {line}")
            self._logger.debug(f"Layer z: {layer_z}")
            self._logger.debug(f"Layer num: {layer_num}")
            
            self._do_capture_sequence(layer_z, layer_num)



    def get_current_position(self):
        """Get the current position of the printer using M114"""
        self._logger.info("Getting current position with M114")
        
        old_position = self._last_m114_position
        # Send M114 and wait for response
        self._printer.commands("M114", force=True)
        
        # Wait for response with timeout
        max_wait_count = 10
        wait_count = 0
        
        while wait_count < max_wait_count:
            time.sleep(0.1)
            wait_count += 1
            if self._last_m114_position != old_position:
                self._logger.info(f"Got M114 position: {self._last_m114_position}")
                return self._last_m114_position
        
        # Fallback to OctoPrint's tracked position if M114 failed
        current_data = self._printer.get_current_data()
        fallback_position = {
            'x': current_data.get('currentX'),
            'y': current_data.get('currentY'), 
            'z': current_data.get('currentZ')
        }
        self._logger.warning(f"M114 timeout, using fallback: {fallback_position}")
        return fallback_position

    def _do_capture_sequence(self, layer_z, layer_num):
        """Do the capture sequence"""
        self._logger.debug(f"Doing capture sequence for layer {layer_num} at z {layer_z}")
        img = None

        if self._printer.set_job_on_hold(True):
            EXTRUDE_AMOUNT = 0.7
            EXTRUDE_SPEED = 5000
            self._printer.extrude(-EXTRUDE_AMOUNT, speed=EXTRUDE_SPEED)
            self._logger.debug("Extruded -0.7mm")
            random_range = (-10, 10)
            position = {"x": -75 + random.randint(random_range[0], random_range[1]),
                        "y": 18 + random.randint(random_range[0], random_range[1]),
                        "z": 60 + random.randint(random_range[0], random_range[1])}
            position_reverse = {"x":-position["x"],
                                "y":-position["y"],
                                "z":-position["z"]}

            self._logger.debug(f"Jogging to {position}")
            self._printer.jog(position, relative=True, speed=5000)
            img = self._camera.capture_image()
            self._logger.debug("Captured image: {img.shape}")
            # img save to save_path
            save_path = self._get_save_path()
            img.save(os.path.join(save_path, f"layer_{layer_num}_capture.jpg"))
            self._logger.debug(f"Saved image to {os.path.join(save_path, f'layer_{layer_num}_capture.jpg')}")
            

            self._printer.jog(position_reverse, relative=True, speed=5000)
            self._printer.extrude(EXTRUDE_AMOUNT, speed=EXTRUDE_SPEED)        
            
            self._printer.set_job_on_hold(False)
            self._logger.debug("Job resumed")
            return
                
                
    def _generate_capture_positions(self):
        """Generate capture positions based on settings"""
        # For now, simple single position - can be expanded to grid later
        capture_pos = {
            'x': 125.0,  # Should come from settings
            'y': 105.0,  # Should come from settings  
            'z': self._detected_z_height + 5.0  # Z offset from settings
        }
        return [capture_pos]

    def _wait_for_movement_completion(self):
        """Wait for printer movement to complete"""
        # Basic implementation - in production you might want to:
        # 1. Send M400 (wait for moves to complete) if supported
        # 2. Check printer state
        # 3. Use configurable delays
        time.sleep(2.0)  # Conservative wait time

    def _save_capture_metadata(self, captured_images):
        """Save metadata for the capture session"""
        try:
            metadata = {
                "layer": "unknown",  # Could be calculated from z_height
                "z_height": self._detected_z_height,
                "timestamp": datetime.now().isoformat(),
                "images": captured_images,
                "original_position": self._original_position
            }
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            metadata_filename = f"m240_capture_{timestamp}_metadata.json"
            save_path = self._get_save_path()
            
            with open(os.path.join(save_path, metadata_filename), 'w') as f:
                json.dump(metadata, f, indent=2)
                
            self._logger.info(f"Metadata saved: {metadata_filename}")
            
        except Exception as e:
            self._logger.error(f"Failed to save metadata: {e}")

    def _return_to_original_position_and_resume(self):
        """Return to original position and resume print"""
        try:
            if self._original_position:
                # Move back to original position
                return_cmd = (f"G1 X{self._original_position['x']} "
                            f"Y{self._original_position['y']} "
                            f"Z{self._original_position['z']} F3000")
                self._logger.info(f"Returning to original position: {return_cmd}")
                self._printer.commands(return_cmd)
                
                # Wait for movement
                self._wait_for_movement_completion()
                
                # Reset extruder position if available
                if 'e' in self._original_position and self._original_position['e'] is not None:
                    reset_e_cmd = f"G92 E{self._original_position['e']}"
                    self._printer.commands(reset_e_cmd)
                
                # Reset feedrate if available  
                if 'f' in self._original_position and self._original_position['f'] is not None:
                    feedrate_cmd = f"G1 F{self._original_position['f']}"
                    self._printer.commands(feedrate_cmd)
            
            # Resume the print
            self._logger.info("Resuming print")
            self._printer.resume_print()
            self._logger.info("Print resumed successfully")
            
        except Exception as e:
            self._logger.error(f"Failed to return to position and resume: {e}")
            # Still try to resume even if positioning failed
            try:
                self._printer.resume_print()
            except Exception as resume_error:
                self._logger.error(f"Critical: Failed to resume print: {resume_error}")

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

