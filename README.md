# OctoPrint-Layercapturedatacollect

An OctoPrint plugin that automatically captures images at specified print layers with configurable grid positions for 3D print monitoring and analysis. Data collection phase.

# OctoPrint Layer Capture Plugin

An OctoPrint plugin that automatically captures images at specified print layers with configurable grid positions for 3D print monitoring and analysis.

## Features

- 🔄 **Automatic Layer Detection**: Captures images at predefined layer intervals
- 📍 **Configurable Grid Capture**: Takes multiple images in a grid pattern around the print
- 🎯 **Precise Positioning**: Moves print head to exact X, Y, and Z coordinates for consistent captures
- 🖼️ **Multiple Formats**: Saves images as JPG with comprehensive JSON metadata
- 🛡️ **Safety Features**: Boundary checking and position validation
- 🧪 **Debug Mode**: Fake camera support for testing without hardware
- ⚙️ **Highly Configurable**: Extensive settings for grid spacing, layer intervals, and capture behavior


### Grid Configuration
- **Grid Center**: X/Y coordinates of the capture grid center
- **Grid Spacing**: Distance between capture points (default: 20mm)
- **Grid Size**: Number of capture positions (1x1, 3x3, or 5x5)
- **Z Offset**: Distance above print surface for capture positions (default: 5mm)
- **Bed Boundaries**: Maximum X/Y coordinates for safety validation


### Grid Positioning
For each capture, the plugin calculates a grid of positions around the configured center point:
- **X Coordinate**: Horizontal position on the print bed
- **Y Coordinate**: Vertical position on the print bed  
- **Z Coordinate**: Current layer height + Z offset for optimal capture angle

### Capture Sequence
1. **Pause Print**: Safely pauses the print job with timeout validation
2. **Move to Position**: Moves print head to each grid position with safety checks
3. **Capture Image**: Takes photo at current X, Y, Z coordinates
4. **Save Metadata**: Records position data and print information
5. **Resume Print**: Safely resumes the print job with error recovery

### Metadata Output
Each capture session generates a JSON file containing:
**Note**: The Z coordinate in position data includes the configured Z offset (e.g., if layer height is 3.0mm and Z offset is 5.0mm, the capture Z position will be 8.0mm).
```json
{
  "layer": 15,
  "z_height": 3.0,
  "timestamp": "2024-01-15T10:30:00",
  "gcode_file": "print.gcode",
  "print_start_time": "2024-01-15T10:00:00",
  "calibration_file_path": "calib.json",
  "images": [
    {
      "path": "layer_0015_pos_00_20240115_103000.jpg",
      "position": {
        "x": 125.0,
        "y": 105.0,
        "z": 8.0
      },
      "index": 0
    }
  ],
  "settings": {
    "grid_spacing": 20.0,
    "grid_center": {
      "x": 125.0,
      "y": 105.0
    },
    "grid_size": 3
  }
}
```

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/tomasjuri/OctoPrint-Layercapturedatacollect/archive/master.zip

**TODO:** Describe how to install your plugin, if more needs to be done than just installing it via pip or through
the plugin manager.

## Configuration

**TODO:** Describe your plugin's configuration options (if any).
