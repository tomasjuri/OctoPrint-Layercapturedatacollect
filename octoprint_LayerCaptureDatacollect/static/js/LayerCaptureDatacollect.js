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

        // Observable properties for UI state
        self.statusMessage = ko.observable("");
        self.statusSuccess = ko.observable(true);
        self.isWorking = ko.observable(false);

        // Computed observables
        self.isPrinting = ko.computed(function() {
            return self.printerStateViewModel.isPrinting() || self.printerStateViewModel.isPaused();
        });

        self.isLoggedIn = ko.computed(function() {
            return self.loginStateViewModel.isUser();
        });

        // Plugin API base URL
        self.apiUrl = function(command) {
            return PLUGIN_BASEURL + "LayerCaptureDatacollect/api/" + command;
        };

        // Show status message temporarily
        self.showStatus = function(message, isSuccess) {
            self.statusMessage(message);
            self.statusSuccess(isSuccess !== false);
            
            // Auto-hide after 5 seconds
            setTimeout(function() {
                if (self.statusMessage() === message) {
                    self.statusMessage("");
                }
            }, 5000);
        };

        // API call wrapper with error handling
        self.callApi = function(command, data, successCallback, errorCallback) {
            if (self.isWorking()) {
                self.showStatus("Another operation is in progress...", false);
                return;
            }

            self.isWorking(true);
            
            $.ajax({
                url: self.apiUrl(command),
                type: "POST",
                dataType: "json",
                data: JSON.stringify(data || {}),
                contentType: "application/json; charset=UTF-8",
                success: function(response) {
                    self.isWorking(false);
                    if (response.success) {
                        if (successCallback) successCallback(response);
                        if (response.message) self.showStatus(response.message, true);
                    } else {
                        if (errorCallback) errorCallback(response);
                        self.showStatus(response.message || "Operation failed", false);
                    }
                },
                error: function(xhr, status, error) {
                    self.isWorking(false);
                    if (errorCallback) errorCallback({success: false, message: error});
                    self.showStatus("API call failed: " + error, false);
                }
            });
        };

        // Button click handlers
        self.testCamera = function() {
            if (!self.isLoggedIn()) {
                self.showStatus("Please log in to test camera", false);
                return;
            }

            self.callApi("test_camera", {}, function(response) {
                var message = "Camera test: " + (response.available ? "Available" : "Not available");
                self.showStatus(message, response.available);
            });
        };

        self.captureNow = function() {
            if (!self.isLoggedIn()) {
                self.showStatus("Please log in to trigger capture", false);
                return;
            }

            if (!self.isPrinting()) {
                self.showStatus("No active print to capture", false);
                return;
            }

            self.callApi("capture_now", {}, function(response) {
                self.showStatus("Capture sequence triggered", true);
            });
        };

        self.getStatus = function() {
            self.callApi("get_status", {}, function(response) {
                var status = "Status: " + 
                    (response.enabled ? "Enabled" : "Disabled") + 
                    " | Layer: " + response.current_layer + 
                    " | Last captured: " + response.last_captured_layer +
                    " | Camera: " + (response.camera_available ? "Available" : "Not available");
                
                if (response.print_file) {
                    status += " | File: " + response.print_file;
                }
                
                if (response.save_path) {
                    status += " | Save: " + response.save_path;
                }
                
                self.showStatus(status, true);
            });
        };

        self.testPaths = function() {
            if (!self.isLoggedIn()) {
                self.showStatus("Please log in to test paths", false);
                return;
            }

            self.callApi("test_paths", {}, function(response) {
                var message = "Path Test Results:\n";
                message += "Save Dir: " + (response.results.save_path.writable ? "✓ OK" : "✗ Failed") + 
                          " (" + response.results.save_path.path + ")\n";
                
                if (response.results.calibration_file.configured) {
                    message += "Calibration: " + (response.results.calibration_file.valid ? "✓ Valid" : "✗ Invalid") + 
                              " (" + response.results.calibration_file.message + ")";
                } else {
                    message += "Calibration: Not configured";
                }
                
                self.showStatus(message, response.success);
            });
        };

        // Grid preview functionality
        self.updateGridPreview = function() {
            var preview = $("#grid-preview");
            if (!preview.length) return;

            // Clear existing points
            preview.find(".grid-point").remove();

            try {
                var settings = self.settingsViewModel.settings.plugins.LayerCaptureDatacollect;
                
                var centerX = parseFloat(settings.grid_center_x()) || 125;
                var centerY = parseFloat(settings.grid_center_y()) || 105;
                var spacing = parseFloat(settings.grid_spacing()) || 20;
                var gridSize = parseInt(settings.grid_size()) || 3;
                var maxX = parseFloat(settings.max_x()) || 250;
                var maxY = parseFloat(settings.max_y()) || 210;

                // Calculate preview scaling
                var previewWidth = preview.width() - 20; // Account for padding
                var previewHeight = preview.height() - 20;
                var scaleX = previewWidth / maxX;
                var scaleY = previewHeight / maxY;

                // Generate grid points
                var offset = (gridSize - 1) * spacing / 2;
                
                for (var x = 0; x < gridSize; x++) {
                    for (var y = 0; y < gridSize; y++) {
                        var pointX = centerX - offset + x * spacing;
                        var pointY = centerY - offset + y * spacing;

                        // Skip points outside boundaries
                        if (pointX < 0 || pointX > maxX || pointY < 0 || pointY > maxY) {
                            continue;
                        }

                        // Convert to preview coordinates
                        var previewX = pointX * scaleX + 10;
                        var previewY = (maxY - pointY) * scaleY + 10; // Flip Y axis

                        // Create point element
                        var point = $('<div class="grid-point"></div>');
                        point.css({
                            position: 'absolute',
                            left: previewX - 3 + 'px',
                            top: previewY - 3 + 'px',
                            width: '6px',
                            height: '6px',
                            backgroundColor: '#007ACC',
                            borderRadius: '50%',
                            border: '1px solid #fff'
                        });

                        // Add tooltip with coordinates
                        point.attr('title', 'X: ' + pointX.toFixed(1) + ', Y: ' + pointY.toFixed(1));
                        
                        preview.append(point);
                    }
                }

                // Add center marker
                var centerPreviewX = centerX * scaleX + 10;
                var centerPreviewY = (maxY - centerY) * scaleY + 10;
                
                var centerMarker = $('<div class="grid-center"></div>');
                centerMarker.css({
                    position: 'absolute',
                    left: centerPreviewX - 2 + 'px',
                    top: centerPreviewY - 2 + 'px',
                    width: '4px',
                    height: '4px',
                    backgroundColor: '#FF6B35',
                    borderRadius: '50%'
                });
                centerMarker.attr('title', 'Grid Center: ' + centerX.toFixed(1) + ', ' + centerY.toFixed(1));
                
                preview.append(centerMarker);

            } catch (error) {
                console.error("Grid preview update failed:", error);
            }
        };

        // Settings change handlers
        self.onSettingsShown = function() {
            // Update grid preview when settings are shown
            setTimeout(self.updateGridPreview, 100);
        };

        self.onSettingsHidden = function() {
            // Clean up when settings are hidden
        };

        // Watch for settings changes to update preview
        self.setupGridPreviewWatchers = function() {
            if (!self.settingsViewModel.settings.plugins.LayerCaptureDatacollect) return;
            
            var settings = self.settingsViewModel.settings.plugins.LayerCaptureDatacollect;
            
            // Watch relevant settings for changes
            settings.grid_center_x.subscribe(self.updateGridPreview);
            settings.grid_center_y.subscribe(self.updateGridPreview);
            settings.grid_spacing.subscribe(self.updateGridPreview);
            settings.grid_size.subscribe(self.updateGridPreview);
            settings.max_x.subscribe(self.updateGridPreview);
            settings.max_y.subscribe(self.updateGridPreview);
            settings.max_z.subscribe(self.updateGridPreview);
            
            // Watch file path settings for validation (could add custom handlers later)
            settings.save_path.subscribe(function(newValue) {
                // Could add path validation here in the future
                console.log("Save path changed to:", newValue);
            });
            settings.calibration_file_path.subscribe(function(newValue) {
                // Could add file existence check here in the future
                console.log("Calibration file path changed to:", newValue);
            });
        };

        // Initialize when settings are loaded
        self.onStartupComplete = function() {
            // Set up grid preview watchers once settings are available
            setTimeout(self.setupGridPreviewWatchers, 1000);
        };

        // Bind to settings events
        self.onSettingsShown = function() {
            setTimeout(function() {
                self.setupGridPreviewWatchers();
                self.updateGridPreview();
            }, 100);
        };

        // Utility function to format coordinates
        self.formatCoordinate = function(value) {
            return parseFloat(value).toFixed(1);
        };

        // Check for updates on print state changes
        self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin === "LayerCaptureDatacollect") {
                if (data.type === "status_update") {
                    // Handle real-time status updates from plugin
                    console.log("Layer capture status update:", data);
                }
            }
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
