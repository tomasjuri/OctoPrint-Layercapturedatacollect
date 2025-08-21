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
        self._detected_z_height = 0.0
        self._camera = None  # Will be initialized in on_after_startup
        
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
        
        self._logger.info("Layer Capture Data Collect plugin initialized")

    def on_after_startup(self):
        self._logger.info("Layer Capture Data Collect plugin starting up")

        # Initialize camera system
        self._camera = Camera()
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

    def gcode_command_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        """Capture sequence detection and capture action"""
        line = cmd.strip().upper()

        # detect:
        # M240 Z[layer_z] ZN[layer_num]; Start layer capture sequence
        # Trigger capture on M240
        if "M240" in line:
            self._logger.debug("1. M240 detected")
            
            # get variables from the command
            layer_z = re.search(r'Z\s*([+-]?\d*\.?\d+)', line).group(1)
            layer_num = re.search(r'ZN\s*([+-]?\d*\.?\d+)', line).group(1)
            self._logger.debug(f"Gcode command sent to printer: {line}")
            self._logger.debug(f"Layer z: {layer_z}")
            self._logger.debug(f"Layer num: {layer_num}")
            
            self._do_capture_sequence(layer_z, layer_num)

    def gcode_received(self, comm_instance, line, *args, **kwargs):
        """Handle G-code responses from printer, specifically M114 position responses"""
        # self._logger.debug(f"Gcode received: {line}")
        
        position = {
            "x": None,
            "y": None,
            "z": None,
            "e": None
        }

        pos_re = r'^ok X:(\d+\.\d+) Y:(\d+\.\d+) Z:(\d+\.\d+) E:(\d+\.\d+) Count: A:'
        pos_matched = re.search(pos_re, line)
        if pos_matched:
            position["x"] = float(pos_matched.group(1))
            position["y"] = float(pos_matched.group(2))
            position["z"] = float(pos_matched.group(3))
            position["e"] = float(pos_matched.group(4))
            
            self._logger.debug(f"Position received: X: {position['x']}, Y: {position['y']}, Z: {position['z']}, E: {position['e']}")

        if self._waiting_for_position and pos_matched:
            self._logger.debug(f"Received position response: {line}")
            try:
                self._position_response = position
                self._waiting_for_position = False
                self._position_event.set()
                self._logger.debug(f"Position parsed: {position}")
            except Exception as e:
                self._logger.error(f"Error parsing position response: {e}")
                self._position_response = None
                self._waiting_for_position = False
                self._position_event.set()
        
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

    def _do_capture_sequence(self, layer_z, layer_num):
        """Do the capture sequence with proper movement synchronization"""
        self._logger.debug(f"Doing capture sequence for layer {layer_num} at z {layer_z}")
        
        with self._printer.job_on_hold(True):
            self._logger.debug("Print job on hold")
         
            try:
                # Get current position first
                self._logger.debug("Getting current position and sending")
                current_pos = self._send_gcode_and_wait_for_completion(["M114"])
                if current_pos is None:
                    self._logger.error("Failed to get current position")
                    return
                    
                self._logger.debug(f"Current position: {current_pos}")
                
                # Retract extruder to prevent oozing
                EXTRUDE_AMOUNT = 0.7
                EXTRUDE_SPEED = 1800  # F1800 = 30mm/s typical retraction speed
                retract_gcode = [
                    "M83",  # Set extruder to relative mode
                    f"G1 E-{EXTRUDE_AMOUNT} F{EXTRUDE_SPEED}"  # Retract
                ]
                self._logger.debug("Retracting extruder...")
                if self._send_gcode_and_wait_for_completion(retract_gcode) is None:
                    self._logger.error("Failed to retract extruder")
                    return
                
                # Calculate absolute target position
                random_range = (-10, 10)
                target_x = current_pos['x'] + CAM_X_OFFSET + random.randint(random_range[0], random_range[1])
                target_y = current_pos['y'] + CAM_Y_OFFSET + random.randint(random_range[0], random_range[1])  
                target_z = current_pos['z'] + CAM_Z_OFFSET + random.randint(random_range[0], random_range[1])
                
                self._logger.debug(f"Moving to capture position: X{target_x} Y{target_y} Z{target_z}")
                
                # Move to capture position with synchronized movement
                capture_pos = self._move_to_absolute_position(target_x, target_y, target_z, speed=5000)
                if capture_pos is None:
                    self._logger.error("Failed to move to capture position")
                    return
                    
                # Capture image
                self._logger.debug("Capturing image...")
                img = self._camera.capture_image()
                self._logger.debug(f"Captured image: {img.size}")
                
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

                # Return to original position
                self._logger.debug(f"Returning to original position: X{current_pos['x']} Y{current_pos['y']} Z{current_pos['z']}")
                return_pos = self._move_to_absolute_position(
                    current_pos['x'], current_pos['y'], current_pos['z'], speed=5000)
                if return_pos is None:
                    self._logger.error("Failed to return to original position")
                    return
                
                # Un-retract extruder
                unretract_gcode = [
                    "M83",  # Ensure extruder is in relative mode
                    f"G1 E{EXTRUDE_AMOUNT} F{EXTRUDE_SPEED}"  # Un-retract
                ]
                self._logger.debug("Un-retracting extruder...")
                if self._send_gcode_and_wait_for_completion(unretract_gcode) is None:
                    self._logger.error("Failed to un-retract extruder")
                    return
                    
            except Exception as e:
                self._logger.error(f"Error during capture sequence: {e}")
            finally:
                # Always resume the print job
                self._logger.debug("Job resumed")
                
                
    

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

