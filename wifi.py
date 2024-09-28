# Author: Ben Neigher
# License: MIT
# Version: 1.0.0
# Description: Networking connectivity manager for MicroPython.

import gc
import sys
import network
import machine
import socket
import uasyncio as asyncio
import ure
import utime

DEFAULT_SSID = "ESP32"
DEFAULT_SSID_PASSWORD = "password"

SERVER_IP = '10.0.0.1'
SERVER_SUBNET = '255.255.255.0'
WIFI_CREDENTIALS_FILE = 'wifi.dat'

class WifiManager:
    def __init__(self, ssid=DEFAULT_SSID, password=DEFAULT_SSID_PASSWORD):
        self.ssid = ssid  # Store the provided SSID
        self.password = password  # Store the provided password
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_sta.active(True)
        self.wlan_sta.disconnect()  # Disconnect on startup
        self.wlan_ap = network.WLAN(network.AP_IF)
        self.wlan_ap.active(False)

    async def connect(self):
        """ Attempt to connect using saved credentials or provided defaults """
        profiles = self._read_profiles()
        if not profiles:
            # If no profiles, try connecting with the default SSID and password
            if await self._wifi_connect(self.ssid, self.password):
                return True
            else:
                return False

        for ssid, password in profiles.items():
            if await self._wifi_connect(ssid, password):
                return True
        return False

    async def _wifi_connect(self, ssid, password):
        print(f'Trying to connect to: {ssid}')
        self.wlan_sta.connect(ssid, password)
        for _ in range(100):  # Timeout after 10 seconds
            if self.wlan_sta.isconnected():
                print(f'\nConnected to {ssid}! Network info: {self.wlan_sta.ifconfig()}')
                return True

            print('.', end='')
            await asyncio.sleep(0.1)  # Use asyncio.sleep instead of utime.sleep_ms
        print(f'\nConnection to {ssid} failed!')
        self.wlan_sta.disconnect()
        return False

    def _read_profiles(self):
        """ Read stored WiFi profiles from the file """
        try:
            with open(WIFI_CREDENTIALS_FILE) as f:
                lines = f.readlines()
        except OSError:
            return {}

        profiles = {}
        for line in lines:
            ssid, password = line.strip().split(';')
            profiles[ssid] = password
        return profiles

    def _write_profiles(self, profiles):
        """ Write WiFi profiles to the file """
        with open(WIFI_CREDENTIALS_FILE, 'w') as f:
            for ssid, password in profiles.items():
                f.write(f'{ssid};{password}\n')

    async def start_captive_portal(self):
        """ Start the access point and DNS/HTTP server for captive portal """
        self._start_access_point()

        # Start HTTP server
        self.server = await asyncio.start_server(self.handle_http_connection, "0.0.0.0", 80)
        print('HTTP server started on 0.0.0.0:80')

        # Start the DNS server task
        asyncio.create_task(self.run_dns_server())

        # Loop forever handling requests
        print('Captive portal running...')
        try:
            async with self.server:
                await self.server.wait_closed()  # Wait until the server is closed
        except Exception as e:
            print(f"Server error: {e}")

        # When WiFi is connected, stop the access point
        self.wlan_ap.active(False)
        print('WiFi connected, stopping captive portal.')

    async def handle_http_connection(self, reader, writer):
        """ Handle the HTTP connection for captive portal """
        gc.collect()

        # Get the HTTP request line
        data = await reader.readline()
        request_line = data.decode()
        addr = writer.get_extra_info('peername')
        print(f'Received {request_line.strip()} from {addr}')

        # Read headers (to make client happy)
        headers = {}
        while True:
            gc.collect()
            line = await reader.readline()
            if line == b'\r\n':
                break
            # Parse the headers
            header = line.decode().strip()
            if ':' in header:
                key, value = header.split(': ', 1)
                headers[key.lower()] = value

        # Check if it's a POST request to save credentials
        if request_line.startswith("POST /configure"):
            if 'content-length' not in headers:
                print('No Content-Length header found')
                await writer.awrite('HTTP/1.0 400 Bad Request\r\n\r\nMissing Content-Length')
                await writer.aclose()
                return

            content_length = int(headers['content-length'])

            try:
                await reader.readexactly(2)  # Skip \r\n
                post_data = await reader.read(content_length)

                # Parse POST data (SSID and password)
                post_str = post_data.decode()
                match = ure.search(r'id=([^&]*)&password=(.*)', post_str)
                if match:
                    ssid = match.group(1)
                    password = match.group(2)

                    # Try to connect with the new credentials
                    if await self._wifi_connect(ssid, password):  # Ensure we await the connection
                        print(f'Successfully connected to {ssid}')
                        # Save the credentials
                        profiles = self._read_profiles()
                        profiles[ssid] = password
                        self._write_profiles(profiles)

                        # Send redirect response to the success page
                        response = 'HTTP/1.0 302 Found\r\nLocation: /success\r\n\r\n'
                        await writer.awrite(response)
                    else:
                        print(f'Failed to connect to {ssid}')
                        await writer.awrite('HTTP/1.0 200 OK\r\n\r\nFailed to connect to the network. Please try again.')
                else:
                    await writer.awrite('HTTP/1.0 400 Bad Request\r\n\r\nInvalid data!')
            except Exception as e:
                print(f'Error while processing POST data: {e}')
                await writer.awrite('HTTP/1.0 500 Internal Server Error\r\n\r\nError processing request.')
        elif request_line.startswith("GET /success"):
            # Serve the success page
            response = 'HTTP/1.0 200 OK\r\n\r\n' + self._generate_success_page()
            await writer.awrite(response)
            # TODO: Replace this with non Timer approach
            timer = machine.Timer(0)
            timer.init(period=int(500), mode=machine.Timer.ONE_SHOT, callback=lambda x: self.server.close())
        else:
            # Serve WiFi network selection form
            response = 'HTTP/1.0 200 OK\r\n\r\n' + self._generate_wifi_selection_page()
            await writer.awrite(response)

        await writer.aclose()
    
    def _generate_wifi_selection_page(self):
        """ Generate HTML form with a list of nearby WiFi networks """
        wifi_networks = self.wlan_sta.scan()
        wifi_options = ""
        for ssid, *_ in wifi_networks:
            ssid = ssid.decode("utf-8")
            if ssid:  # Check if SSID is not empty
                wifi_options += f'<option value="{ssid}">{ssid}</option>\n'

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WiFi Setup</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: #f0f0f0;
                    color: #333;
                    text-align: center;
                }}
                h1 {{
                    font-size: 24px;
                    margin: 20px 0;
                }}
                form {{
                    background-color: #fff;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                    margin: 20px auto;
                    max-width: 400px;
                    width: 100%;
                }}
                label {{
                    display: block;
                    margin-bottom: 10px;
                    font-size: 16px;
                }}
                select, input[type="password"], input[type="submit"] {{
                    width: calc(100% - 22px);
                    padding: 10px;
                    margin: 10px 0;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    font-size: 16px;
                }}
                input[type="submit"] {{
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    cursor: pointer;
                }}
                input[type="submit"]:hover {{
                    background-color: #45a049;
                }}
                input[type="submit"]:disabled {{
                    background-color: #ccc;
                    cursor: not-allowed;
                }}
                @media (max-width: 600px) {{
                    h1 {{
                        font-size: 20px;
                    }}
                    form {{
                        padding: 15px;
                        max-width: 90%;
                    }}
                }}
            </style>
            <script>
                function handleFormSubmit() {{
                    var submitButton = document.getElementById('submit-button');
                    submitButton.disabled = true;
                    submitButton.value = 'Connecting...';
                }}

                function resetButton() {{
                    var submitButton = document.getElementById('submit-button');
                    submitButton.disabled = false;
                    submitButton.value = 'Connect';
                }}

                // Call resetButton when the page loads
                window.onload = resetButton;

                // Add event listener for popstate to reset the button when navigating back
                window.addEventListener('popstate', function(event) {{
                    resetButton();
                }});
                
                window.addEventListener('pageshow', function(event) {{
                    resetButton();
                }});
            </script>
        </head>
        <body>
            <h1>Configure WiFi</h1>
            <form action="/configure" method="post" onsubmit="handleFormSubmit()">
                <label for="ssid">Select SSID:</label>
                <select id="ssid" name="ssid">
                    {wifi_options}
                </select>
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
                <input type="submit" id="submit-button" value="Connect">
            </form>
        </body>
        </html>
        """
        return html

    def _generate_success_page(self):
        """ Generate a simple success message page with a countdown timer """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Connected</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                h1 { color: #4CAF50; }
                p { font-size: 18px; }
                .countdown { font-size: 24px; color: #FF5722; }
            </style>
        </head>
        <body>
            <h1>Connected!</h1>
            <p>You are now connected to the WiFi network.  Closing window...</p>
        </body>
        </html>
        """
        return html

    def _start_access_point(self):
        """ Setup the access point """
        self.wlan_ap.active(True)
        self.wlan_ap.ifconfig((SERVER_IP, SERVER_SUBNET, SERVER_IP, SERVER_IP))
        self.wlan_ap.config(essid=self.ssid, authmode=network.AUTH_OPEN)
        print('AP network config:', self.wlan_ap.ifconfig())


    async def run_dns_server(self):
        """ Handle incoming DNS requests """
        udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udps.setblocking(False)
        udps.bind(('0.0.0.0', 53))

        while True:
            try:
                data, addr = udps.recvfrom(4096)
                if data:  # Ensure data is not None
                    dns_query = DNSQuery(data)
                    udps.sendto(dns_query.response(SERVER_IP), addr)
            except OSError as e:
                if e.errno == 11:  # EAGAIN, no data available
                    await asyncio.sleep(0.1)  # Wait before retrying
                else:
                    print(f'DNS server error: {e}')
            except Exception as e:
                print(f'Unexpected error in DNS server: {e}')

        udps.close()
        
class DNSQuery:
    def __init__(self, data):
        self.data = data
        self.domain = ''
        tipo = (data[2] >> 3) & 15  # Opcode bits
        if tipo == 0:  # Standard query
            ini = 12
            lon = data[ini]
            while lon != 0:
                self.domain += data[ini + 1:ini + lon + 1].decode('utf-8') + '.'
                ini += lon + 1
                lon = data[ini]

    def response(self, ip):
        if self.domain:
            packet = self.data[:2] + b'\x81\x80'
            packet += self.data[4:6] + self.data[4:6] + b'\x00\x00\x00\x00'  # Questions and Answers Counts
            packet += self.data[12:]  # Original Domain Name Question
            packet += b'\xC0\x0C'  # Pointer to domain name
            packet += b'\x00\x01\x00\x01\x00\x00\x00\x3C\x00\x04'  # Response type, ttl and resource data length -> 4 bytes
            packet += bytes(map(int, ip.split('.')))  # 4 bytes of IP address
        return packet
    
class SyncWifiManager:
    """ Synchronous wrapper for the WifiManager class """

    def __init__(self, ssid=DEFAULT_SSID, password=DEFAULT_SSID_PASSWORD):
        self.wifi_manager = WifiManager(ssid, password)

    def connect(self):
        """ Synchronously connect to WiFi, returns True if successful, False otherwise """
        loop = asyncio.new_event_loop()  # Create a new event loop

        try:
            # Run the async connect method and return the result
            return loop.run_until_complete(self.wifi_manager.connect())
        finally:
            loop.close()  # Close the event loop

    def start_captive_portal(self):
        """ Synchronously start the captive portal """
        loop = asyncio.new_event_loop()  # Create a new event loop

        try:
            loop.run_until_complete(self.wifi_manager.start_captive_portal())
        finally:
            loop.close()  # Close the event loop