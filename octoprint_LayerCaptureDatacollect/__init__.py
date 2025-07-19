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
            "image_format": "jpg",        # Image format (jpg, png)
            "image_quality": 95,          # JPEG quality (1-100)
            
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
            if self._settings.get(["debug_mode"]):
                self._logger.info("Debug mode enabled - using fake camera")
                self._camera_available = True
            else:
                # Try to initialize real camera (will implement in camera integration task)
                self._camera_available = self._check_camera_availability()
        except Exception as e:
            self._logger.error(f"Failed to initialize camera: {e}")
            self._camera_available = False

    def _check_camera_availability(self):
        """Check if camera is available (stub for now)"""
        # TODO: Implement actual camera detection
        return True

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
            self._logger.info(f"Starting capture sequence for layer {self._current_layer}")
            
            # TODO: Implement full capture sequence:
            # 1. Pause print safely
            # 2. Move to grid positions
            # 3. Capture images
            # 4. Save metadata
            # 5. Resume print
            
            # For now, just mark as captured
            self._last_captured_layer = self._current_layer
            self._logger.info(f"Capture sequence completed for layer {self._current_layer}")
            
        except Exception as e:
            self._logger.error(f"Capture sequence failed: {e}")

    ##~~ API Methods

    def _api_capture_now(self):
        """API command to trigger immediate capture"""
        if not self._capture_active:
            return {"success": False, "message": "No active print"}
        
        self._schedule_capture()
        return {"success": True, "message": "Capture triggered"}

    def _api_get_status(self):
        """API command to get plugin status"""
        return {
            "enabled": self._settings.get(["enabled"]),
            "capture_active": self._capture_active,
            "current_layer": self._current_layer,
            "last_captured_layer": self._last_captured_layer,
            "camera_available": getattr(self, '_camera_available', False),
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
        # TODO: Implement camera test
        return {
            "success": True, 
            "message": "Camera test - implementation pending",
            "available": getattr(self, '_camera_available', False)
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
