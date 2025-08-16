# Find PIDs using camera devices
sudo fuser /dev/video*
sudo fuser /dev/media*

# Kill them (replace PID with actual process ID)
sudo kill -9 <PID>




# or 
sudo fuser /dev/video* | xargs sudo kill -9