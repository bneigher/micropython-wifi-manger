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