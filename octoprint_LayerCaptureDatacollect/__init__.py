from .LayerCaptureDatacollectPlugin import LayerCaptureDatacollectPlugin

__plugin_name__ = "Layer Capture Data Collect"
__plugin_pythoncompat__ = ">=3,<4"
__plugin_version__ = "1.0.0"
__plugin_description__ = "An OctoPrint plugin that automatically captures images at specified print layers with configurable grid positions for 3D print monitoring and analysis."

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = LayerCaptureDatacollectPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }