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
            self._logger.debug(f"Gcode command received: {line}")
            self._logger.debug(f"Layer z: {layer_z}")
            self._logger.debug(f"Layer num: {layer_num}")
            
            self._do_capture_sequence(layer_z, layer_num)

    def _generate_capture_metadata(self, layer_num, layer_z, position_relative, img):
        """Generate capture metadata"""
        metadata = {
            "layer_num": layer_num,
            "layer_z": layer_z,
            "position_relative": position_relative,
            "img_shape": img.size}
        return metadata

    def _do_capture_sequence(self, layer_z, layer_num):
        """Do the capture sequence"""
        self._logger.debug(f"Doing capture sequence for layer {layer_num} at z {layer_z}")
        img = None

        if self._printer.set_job_on_hold(True):
            EXTRUDE_AMOUNT = 0.7
            EXTRUDE_SPEED = 5000
            # self._printer.extrude(-EXTRUDE_AMOUNT, speed=EXTRUDE_SPEED)
            self._logger.debug("Extruded -0.7mm")
            random_range = (-10, 10)
            position = {"x": CAM_X_OFFSET + random.randint(random_range[0], random_range[1]),
                        "y": CAM_Y_OFFSET + random.randint(random_range[0], random_range[1]),
                        "z": CAM_Z_OFFSET + random.randint(random_range[0], random_range[1])}
            position_reverse = {"x":-position["x"],
                                "y":-position["y"],
                                "z":-position["z"]}

            self._logger.debug(f"Jogging to {position}")
            self._printer.jog(position, relative=True, speed=5000)
            
            time.sleep(3)
            img = self._camera.capture_image()
            self._logger.debug(f"Captured image: {img.size}")
            img_path = os.path.join(self._save_path, f"layer_{layer_num}_img.jpg")
            meta_path = os.path.join(self._save_path, f"layer_{layer_num}_meta.json")
            
            img.save(img_path)
            self._logger.debug(f"Saved image to {img_path}")
            gen_metadata = self._generate_capture_metadata(
                layer_num, layer_z, position, img)
            with open(meta_path, "w") as f:
                json.dump(gen_metadata, f)
            self._logger.debug(f"Saved metadata to {meta_path}")

            self._printer.jog(position_reverse, relative=True, speed=5000)
            # self._printer.extrude(EXTRUDE_AMOUNT, speed=EXTRUDE_SPEED)        
            
            self._printer.set_job_on_hold(False)
            self._logger.debug("Job resumed")
            return
                
                
    

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

