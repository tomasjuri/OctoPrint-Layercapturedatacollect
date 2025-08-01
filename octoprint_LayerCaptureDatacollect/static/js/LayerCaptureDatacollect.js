/*
 * View model for OctoPrint-LayerCaptureDatacollect
 *
 * Author: Tomáš Juřica
 * License: AGPL-3.0-or-later
 */
$(function() {
    function LayerCaptureDatacollectViewModel(parameters) {
        var self = this;

        // Assign injected parameters
        self.settingsViewModel = parameters[0];
        self.loginStateViewModel = parameters[1];
        self.printerStateViewModel = parameters[2];

        // Settings events
        self.onSettingsHidden = function() {
            // Clean up when settings are hidden
        };

        // Settings change watchers for camera and paths
        self.setupSettingsWatchers = function() {
            if (!self.settingsViewModel.settings.plugins.LayerCaptureDatacollect) return;
            
            var settings = self.settingsViewModel.settings.plugins.LayerCaptureDatacollect;
            
            // Watch file path settings for validation (could add custom handlers later)
            settings.save_path.subscribe(function(newValue) {
                // Could add path validation here in the future
                console.log("Save path changed to:", newValue);
            });
            settings.calibration_file_path.subscribe(function(newValue) {
                // Could add file existence check here in the future
                console.log("Calibration file path changed to:", newValue);
            });
            
            // Watch camera settings for feedback
            settings.fake_camera_mode.subscribe(function(newValue) {
                console.log("Fake camera mode:", newValue ? "ENABLED" : "DISABLED");
            });
            settings.camera_resolution_x.subscribe(function(newValue) {
                console.log("Camera resolution X changed to:", newValue);
            });
            settings.camera_resolution_y.subscribe(function(newValue) {
                console.log("Camera resolution Y changed to:", newValue);
            });
        };

        // Initialize when settings are loaded
        self.onStartupComplete = function() {
            // Set up settings watchers once settings are available
            setTimeout(self.setupSettingsWatchers, 1000);
        };

        // Settings events - consolidated to avoid duplicates
        self.onSettingsShown = function() {
            setTimeout(function() {
                self.setupSettingsWatchers();
            }, 100);
        };


    }

    // Register the view model
    OCTOPRINT_VIEWMODELS.push({
        construct: LayerCaptureDatacollectViewModel,
        dependencies: [
            "settingsViewModel", 
            "loginStateViewModel",
            "printerStateViewModel"
        ],
        elements: [
            "#settings_plugin_LayerCaptureDatacollect"
        ]
    });
});
