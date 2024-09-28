# micropython-wifi-manger
This is a library which is designed to be a one stop shop for enabling your micropython device to be a connected device.  With both the ability to connect to your local network as well as an intuitive captive portal fallback, you should be able to have your device setup easily without needing to reboot your system or determine the local ip address of the access point.  This module stands on the shoulders of the other code inspiration pieces listed below

## Usage
There are two ways to use this library, asynchronous and synchronous.  

### Async
```python
import uasyncio as asyncio
from wifi import WifiManager
async def main():
    wifi_manager = WifiManager(ssid="Your_SSID", password="Your_Password")

    # Try to connect to WiFi
    connected = await wifi_manager.connect()
    if not connected:
        print("No WiFi credentials found or failed to connect. Starting captive portal...")
        await wifi_manager.start_captive_portal()
    
    print("Connected!")
# Run the main function using asyncio
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Interrupted")

```

### Sync
```python
from wifi import SyncWifiManager

sync_manager = SyncWifiManager("Your_SSID", "Your_Password")
connected = sync_manager.connect()  # This will block until the connection is established
if not connected:
    sync_manager.start_captive_portal()  # This will block until the captive portal is closed

print("Connected!")
```


## Inspirations
- https://github.com/ferreira-igor/micropython-wifi_manager
- https://github.com/metachris/micropython-captiveportal
