import argparse
import asyncio
import subprocess

from rich.console import Console

import serial
import json
import os
import time
import logging

import media_handler
import http_commands
import config
import atexit
import threading
import shlex

def exit_handler():
    os.system("python /home/raspi/opengopro-python/main_test.py")
    return

def init_logger():
    logger = logging.getLogger('GoProLogger')
    logger.setLevel(logging.DEBUG)
    os.system('sudo chmod 666 app.log')
    file_handler = logging.FileHandler('app.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(file_handler)
    return logger

console = Console()  # rich consoler printer
streaming = False

def disconnect_bt():
    # subprocess.run(["bluetoothctl", "disconnect", "EB:95:65:61:51:80"])
    print("disconnect BT")
    
def connect_bt():
    # subprocess.run(["bluetoothctl", "connect", "EB:95:65:61:51:80"])
    print("connect BT")

count = 0
async def main(args: argparse.Namespace) -> None:
    global streaming
    global last_updated
    
    # Auto restart program if error occurs
    atexit.register(exit_handler)
    logger = init_logger()
    
    logger.info("App start/restart")
    console.print("[green]App started")
    ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.5)
    ser.write("Raspi turned on".encode())
    await asyncio.sleep(1)
    command_on_buff = ""
    is_connected_ble = False
    buffer = b""
    
    while True:
        console.print("[cyan]Attempting to disconnect BT")
        disconnect_bt()
        last_command_time = time.time()
        is_sleep = False
        try:
            console.print("[bright_cyan]Connecting to GoPro..")
            logger.info("Connecting to GoPro")
            connect_bt()
            await asyncio.sleep(5)  # Simulate connection delay
        except Exception as e:
            is_connected_ble = False
            ser.write("ble disconnected".encode())
            await asyncio.sleep(1)
            logger.error(f"Failed connecting to GoPro: {e}")
            console.print("[red3]Failed connecting to GoPro..")
            disconnect_bt()
            await asyncio.sleep(0.5)
        else:
            is_connected_ble = True
            ser.write("ble connected".encode())
            await asyncio.sleep(1)
            logger.info("GoPro connected")
            request_config(ser, logger)
            console.print("[bright_cyan]GoPro connected. Waiting for JSON command..")
            while True:
                logger.info(f"Waiting for JSON command for {count}")

                if command_on_buff:
                    last_command_time = time.time()
                    await process_command(command_on_buff, ser, args, logger)
                    command_on_buff = ""
                    
                if ser.in_waiting:
                    asyncio.sleep(0.1)
                    last_command_time = time.time()
                    serial_string = ser.readline().replace(b'\x00', b'')  # Remove null
                    
                    console.print(f"[bright_yellow]Received from serial: {serial_string}")
                    logger.info(f"Received from serial: {serial_string}")
                    
                    print(serial_string)
                    if is_json(serial_string):  # Only decode if serial_string is in JSON format
                        # if is_bluetooth_connected():
                        if True:
                            await process_command(serial_string, ser, args, logger)
                        else:
                            command_on_buff = serial_string
                            break
                    else:
                        console.print("[red3]Data is not in JSON format")
                        logger.warning("Data is not in JSON format")
                        
                last_updated = time.time()  # Update progress
        last_updated = time.time()  # Update progress
                        
# Asynchronous watchdog function
async def watchdog(timeout=120):
    global last_updated
    while True:
        await asyncio.sleep(timeout)
        if time.time() - last_updated > timeout:
            console.print("[red]Script is stuck! Restarting...")
            os.execl(sys.executable, sys.executable, *sys.argv)  # Restart script
            
# Main function to run both the script and watchdog
async def main_wd():
    # Run the main script and watchdog concurrently
    await asyncio.gather(
        main(parse_arguments()),
        watchdog()
    )

async def process_command(serial_string, ser, args, logger):
    console.print(f"[bright_cyan]Receiving command !")
    json_data = json.loads(serial_string)
    # if is_need_http_connection(json_data):
    #     check_if_connected_to_gopro_AP()

    if "DeviceReady" in json_data:
        ser.write("DeviceReady".encode())
        await asyncio.sleep(1)
        logger.info("Device Ready")
    
    if "capture" in json_data:
        logger.info("capture")
        ser.write("capture".encode())
        await asyncio.sleep(0.6)
        
        time.sleep(2)
        # media_handler.download_last_captured_media()
        logger.info("media downloaded")
        ser.write("media downloaded".encode())
        await asyncio.sleep(0.6)
        
        ser.write("captured".encode())
        await asyncio.sleep(1)
        
        logger.info("GoPro sleep")
        ser.write("gopro sleep".encode())
        await asyncio.sleep(0.6)
        
        logger.info("Connecting to %s", config.wifi_ssid)
        console.print(f"[yellow]Connecting to {config.wifi_ssid}")
        # os.system("sudo nmcli d wifi connect {} password {}".format(shlex.quote(config.wifi_ssid), shlex.quote(config.wifi_password)))
        console.print(f"[yellow]Connected to {config.wifi_ssid}")
        
        try:
            # os.chdir("gdrive_auto_backup_files") #change directories
            # os.system("npm start")
            # Run npm start with a timeout of 10 seconds (adjust as needed)
            # result = subprocess.run(["npm", "start"], timeout=300)
            
            os.chdir("external")  # change directories
            result = subprocess.Popen(["python3", "main_app.py"])
            os.chdir("..")  # back to old working directories

            console.print(f"[yellow]ready for next command..")
            logger.info("auto backup done\n")

            ser.write("backup done".encode())
            
        except subprocess.TimeoutExpired:
            os.chdir("..")  # Ensure you return to the old working directory even on failure
            logger.error("npm start command timed out")
            console.print(f"[red]npm start command timed out")

            ser.write("backup failed: timeout".encode())
            
        await asyncio.sleep(0.6)
        
        logger.info("Raspi Shutdown after capture")
        ser.write("Raspi shutdown".encode())
        await asyncio.sleep(0.5)
        # os.system("sudo shutdown now")
                    

    if "skippedCapture" in json_data:
        num_skip = json_data['skippedCapture']
        for i in range(num_skip):
            logger.info("capture %i", i+1)
            time.sleep(2)
            media_handler.download_last_captured_media()
            logger.info("media downloaded %i", i+1)
        
        logger.info("Connecting to %s", config.wifi_ssid)
        console.print(f"[yellow]Connecting to {config.wifi_ssid}")
        os.system("sudo nmcli d wifi connect {} password {}".format(config.wifi_ssid, config.wifi_password))
        console.print(f"[yellow]Connected to {config.wifi_ssid}")
        
        os.chdir("gdrive_auto_backup_files")  # change directories
        os.system("npm start")
        os.chdir("..")  # back to old working directories
        console.print(f"[yellow]ready for next command..")
        logger.info("auto backup done\n")
            
    if "reqConfig" in json_data:
        request_config(ser, logger)
    if "stream" in json_data:
        global streaming
        start_stream = json_data['stream']
        if start_stream == 1 and not streaming:
            time.sleep(1)
            streaming = True
            try:
                logger.info("Starting Livestream..")
                await asyncio.sleep(5)  # Simulate livestream start delay
            except:
                ser.write("streamFailed".encode())  # send feedback to ESP
                await asyncio.sleep(1)
                logger.info("Raspi Reboot")
                os.system("sudo reboot")
            else:
                console.print("[bright_cyan] Livestream start")
                logger.info("Livestream start")
                ser.write("streamStart".encode())
                await asyncio.sleep(1)
                
        elif start_stream == 0:
            await stop_stream(ser, args, logger)
        
    if "shu" in json_data:  # check if "shutter" key exist in json
        shutter = json_data['shu']
        if shutter != config.CURRENT_SHUTTER:
            console.print(f"[yellow]Changing shutter speed into {config.SHUTTER[shutter]}")
            config.CURRENT_SHUTTER = shutter
            logger.info("Changing shutter speed into %s", config.SHUTTER[shutter])
        if "iso" in json_data:
            iso = json_data['iso']
            if iso != config.CURRENT_ISO:
                console.print(f"[yellow]Changing ISO into {config.ISO[iso]}")
                config.CURRENT_ISO = iso
                logger.info("Changing ISO into %s", config.ISO[iso])
        if "wb" in json_data:
            awb = json_data['wb']
            if awb != config.CURRENT_AWB:
                console.print(f"[yellow]Changing AWB into {config.AWB[awb]}")
                config.CURRENT_AWB = awb
                logger.info("Changing AWB into %s", config.AWB[awb])
        if "ev" in json_data:
            ev = json_data['ev']
            if ev != config.CURRENT_EV:
                console.print(f"[yellow]Changing EV into {config.EV[ev]}")
                config.CURRENT_EV = ev
                logger.info("Changing EV into %s", config.EV[ev])
        request_config(ser, logger)
        await asyncio.sleep(1)
        ser.write("recConfig".encode())
        await asyncio.sleep(1)
        
async def stop_stream(ser, args, logger):
    global streaming
    try:
        logger.info("Stopping Livestream..")
        await asyncio.sleep(5)  # Simulate livestream stop delay
    except Exception as e:
        logger.warning(f"Failed to stop livestream: {e}")
        os.system("sudo reboot")
    else:
        streaming = False
        logger.info("Livestream stopped")
        ser.write("streamStop".encode())
        logger.info("Raspi Shutdown after live stream")
        await asyncio.sleep(3)
        ser.write("Raspi shutdown".encode())
        os.system("sudo shutdown now")
                
def is_bluetooth_connected():
    output = subprocess.check_output('./check_bluetooth_connection.sh')
    if "No".encode() in output:
        return False
    else:
        return True

def request_config(ser: serial, logger):
    settings_json = {
        "camera_name": "GoPro",
        "total_photos": 100,
        "remaining_photos": 50,
        "battery_percentage": 80,
        "memory_remaining": 32,
        "shutter": "Auto",
        "iso": "100",
        "awb": "Auto",
        "ev": "0",
    }
    json_string = json.dumps(settings_json)
    json_string = json_string.encode()
    console.print(f"[bright_yellow]Sent to serial: {json_string}")
    ser.write(json_string)
    time.sleep(1)
    console.log("bright_cyan]Done Request GoPro config..")
    logger.info("Done Request GoPro config..")

def is_need_http_connection(json_data):
    for command in config.need_http:
        if command in json_data:
            return True
    return False

def check_if_connected_to_gopro_AP():
    if is_connected_to_gopro_AP():
        print("Already connected to GoPro AP")
    else:
        print("Connecting to GoPro AP")
        os.system("sudo nmcli d wifi connect {} password {}".format(config.gopro_ssid, config.gopro_password))
    
def is_connected_to_gopro_AP():
    ps = subprocess.Popen(['iwgetid'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output = subprocess.check_output(('grep', 'ESSID'), stdin=ps.stdout)
        if config.gopro_ssid.encode() in output:
            return True
        else:
            return False
    except subprocess.CalledProcessError:
        print("No wireless networks connected")

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to the GoPro via BLE only, configure then start a Livestream, then display it with CV2."
    )
    parser.add_argument("--ssid", type=str, help="WiFi SSID to connect to.", default=config.wifi_ssid)
    parser.add_argument("--password", type=str, help="Password of WiFi SSID.", default=config.wifi_password)
    parser.add_argument("--url", type=str, help="RTMP server URL to stream to.", default=config.rtmp_URL)
    parser.add_argument("--encode", type=bool, help="Minimum bitrate.", default=0)
    parser.add_argument("--min_bit", type=int, help="Minimum bitrate.", default=1000)
    parser.add_argument("--max_bit", type=int, help="Maximum bitrate.", default=1000)
    parser.add_argument("--start_bit", type=int, help="Starting bitrate.", default=1000)
    return parser.parse_args()

def is_json(myJson):
    try:
        json.loads(myJson)
    except ValueError as e:
        print(f"Invalid JSON: {e}")
        return False
    return True

if __name__ == "__main__":
    asyncio.run(main_wd())
