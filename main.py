import argparse
import asyncio
import subprocess

from open_gopro import Params, WirelessGoPro, constants, proto
from open_gopro.logger import setup_logging
from open_gopro.util import add_cli_args_and_parse, ainput
from rich.console import Console

import serial
import json
import os
import time
import logging

import media_handler
import http_commands
import livestream
import config
import atexit
import threading
import shlex

def exit_handler():
    os.system("python /home/raspi/opengopro-python/main.py")
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
    subprocess.run(["bluetoothctl", "disconnect", "EB:95:65:61:51:80"])
    
def connect_bt():
    subprocess.run(["bluetoothctl", "connect", "EB:95:65:61:51:80"])
    
# async def net_is_connected():
#     try:
#         # Try to resolve the host to check internet connectivity
#         socket.gethostbyname("www.google.com")
#         return True
#     except socket.gaierror:
#         return False

# async def wait_for_internet():
#     print("Waiting for internet connection...")
#     while not await net_is_connected():
#         print("No internet connection. Retrying in 5 seconds...")
#         await asyncio.sleep(5)
#     print("Connected to the internet!")

# async def ping(host):
#     # Run the ping command asynchronously
#     while True:
#         try:
#             # Pinging 8.8.8.8 with 1 packet (-c 1)
#             output = subprocess.run(["ping", "-c", "1", host], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
#             # If ping was successful, return True
#             if output.returncode == 0:
#                 print(f"Connected to {host}")
#                 return True
#             else:
#                 print(f"Waiting for internet connection...")
#         except Exception as e:
#             print(f"Error during ping: {e}")
        
#         # Wait 5 seconds before trying again
#         await asyncio.sleep(5)

count = 0
async def main(args: argparse.Namespace) -> None:
    global streaming
    global last_updated
    # auto restart program if error occurred
    atexit.register(exit_handler)
    logger = init_logger()
    
    logger.info("App start/restart")
    print("app started")
    setup_logging(__name__, args.log)
    ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.5)
    ser.write("Raspi turned on".encode())
    await asyncio.sleep(1)
    command_on_buff = ""
    is_connected_ble = False
    # ser.write("ble disconnected".encode())
    
    while True:
        #open connection to gopro (BLE & AP)
        gopro = WirelessGoPro(args.identifier)
        # await gopro.close()
        print("1")
        disconnect_bt()
        print("2")
        last_command_time = time.time()
        is_sleep = False
        try:
            os.system("sudo hciconfig hci0 up")
            console.print("[bright_cyan]Connecting to GoPro..")
            logger.info("Connecting to GoPro")
            connect_bt()
            await gopro.open(timeout = 5) #EB_95_65_61_51_80
        except:
            is_connected_ble = False
            ser.write("ble disconnected".encode())
            await asyncio.sleep(1)
            logger.error("failed connecting to GoPro")
            console.print("[red3]Failed connecting to GoPro..")
            # os.system("sudo hciconfig hci0 down")
            disconnect_bt()
            time.sleep(0.5)
        else:
            is_connected_ble = True
            ser.write("ble connected".encode())
            await asyncio.sleep(1)
            logger.info("GoPro connected")
            request_config(ser, logger)
            console.print("[bright_cyan]Waiting for json command..")
            while True:
                # auto-sleep GoPro if reach timeout
                # if((time.time() - last_command_time > 180) and (not is_sleep) and (not streaming)):
                # if((time.time() - last_command_time > 30)):
                #     count += 30
                console.print("[bright_cyan]Waiting for json command for ", count)
                logger.warning("Waiting for json command for ", count)
                #     #gopro sleep and close connection
                #     await gopro.ble_command.sleep()
                #     await gopro.close()
                #     logger.info("GoPro sleep")
                #     is_sleep = True
                    # logger.info("Raspi shutdown")
                    # ser.write("Raspi shutdown".encode())
                    # await asyncio.sleep(1)
                    # os.system("sudo shutdown now")

                # execute command that comes while gopro sleeps
                if command_on_buff != "":
                    last_command_time = time.time()
                    await process_command(command_on_buff, gopro, ser, args, logger)
                    command_on_buff = ""
                    
                if ser.in_waiting:
                    last_command_time = time.time()
                    serial_string = ser.readline()
                    serial_string = serial_string.replace(b'\x00',b'') #remove null
                    
                    console.print(f"[bright_yellow]Received from serial: {serial_string}")
                    logger.info("Received from serial: %s\n", serial_string)
                    
                    if is_json(serial_string):	#only decode if serial_string in json format
                        if is_bluetooth_connected():
                            await process_command(serial_string, gopro, ser, args, logger)
                        else:
                            command_on_buff = serial_string
                            break
                    else:
                        console.print("[red3]data is not in json format")
                        logger.warning("data is not in json format")
                        
                last_updated = time.time()  # Update progress
        last_updated = time.time()  # Update progress
                        
# Asynchronous watchdog function
async def watchdog(timeout=120):
    global last_updated
    while True:
        await asyncio.sleep(timeout)
        if time.time() - last_updated > timeout:
            console.print("[red]Script is stuck! Restarting...")
            # logger.info("Script is stuck! Restarting...")
            os.execl(sys.executable, sys.executable, *sys.argv)  # Restart script
            
# Main function to run both the script and watchdog
async def main_wd():
    # Run the main script and watchdog concurrently
    await asyncio.gather(
        main(parse_arguments()),
        watchdog()
    )

async def process_command(serial_string, gopro, ser, args, logger):
    console.print(f"[bright_cyan]Receiving command !")
    json_data = json.loads(serial_string)
    if is_need_http_connection(json_data):
        #gopro = WirelessGoPro(args.identifier, enable_wifi = True)
        ##await gopro.open(timeout = 5)
        #await gopro.ble_command.enable_wifi_ap(enable = True)
        #await gopro._wifi.open(config.gopro_ssid, gopro_password)
        check_if_connected_to_gopro_AP()

    if "DeviceReady" in json_data:
        ser.write("DeviceReady".encode())
        await asyncio.sleep(1)
        logger.info("Device Ready")
    
    if "capture" in json_data:
        #take picture
        assert (await gopro.ble_command.set_shutter(shutter=Params.Toggle.ENABLE)).ok
        logger.info("capture")
        ser.write("capture".encode())
        await asyncio.sleep(0.6)
        
        #download last captured media
        time.sleep(2)
        media_handler.download_last_captured_media()
        logger.info("media downloaded")
        ser.write("media downloaded".encode())
        await asyncio.sleep(0.6)
        
        #inform success captured to ESP
        ser.write("captured".encode())
        await asyncio.sleep(1)
        
        #gopro sleep and close connection
        await gopro.ble_command.sleep()
        await gopro.close()
        logger.info("GoPro sleep")
        ser.write("gopro sleep".encode())
        await asyncio.sleep(0.6)
        
        # await gopro.ble_command.enable_wifi_ap(enable=False)
        # ser.write("gopro AP off".encode())
        # await asyncio.sleep(0.6)
        
        #switch to internet AP
        logger.info("Connecting to %s", config.wifi_ssid)
        console.print(f"[yellow]Connecting to {config.wifi_ssid}")
        # os.system("sudo nmcli d wifi connect + \"{}\" password {}".format(config.wifi_ssid, config.wifi_password))
        os.system("sudo nmcli d wifi connect {} password {}".format(shlex.quote(config.wifi_ssid), shlex.quote(config.wifi_password)))
        console.print(f"[yellow]Connected to {config.wifi_ssid}")
        
        # logger.info("connecting to internet...")
        # ser.write("device connecting to internet")
        # await asyncio.sleep(0.6)
        # await wait_for_internet()
        # # logger.info("connected to internet")
        # ser.write("device connected to internet")
        # await asyncio.sleep(0.6)
        
        try:
            #run auto backup program
            os.chdir("gdrive_auto_backup_files") #change directories

            # os.system("npm start")
            # Run npm start with a timeout of 10 seconds (adjust as needed)
            result = subprocess.run(["npm", "start"], timeout=120)

            os.chdir("..") #back to old working directories

            console.print(f"[yellow]ready for next command..")
            logger.info("auto backup done\n")

            ser.write("backup done".encode())
            
        except subprocess.TimeoutExpired:
            os.chdir("..")  # Ensure you return to the old working directory even on failure
            # Handle the timeout case
            logger.error("npm start command timed out")
            console.print(f"[red]npm start command timed out")

            ser.write("backup failed: timeout".encode())
            
        await asyncio.sleep(0.6)
        
        logger.info("Raspi Shutdown after capture")
        ser.write("Raspi shutdown".encode())
        await asyncio.sleep(0.5)
        os.system("sudo shutdown now")
                    

    if "skippedCapture" in json_data:
        num_skip = json_data['skippedCapture']
        for i in range (0, num_skip):
            #take picture
            assert (await gopro.ble_command.set_shutter(shutter=Params.Toggle.ENABLE)).ok
            logger.info("capture %i", i+1)
            
            #download last captured media
            time.sleep(2)
            media_handler.download_last_captured_media()
            logger.info("media downloaded %i", i+1)
            
        #gopro sleep and close connection
        # await gopro.ble_command.sleep()
        # await gopro.close()
        # logger.info("GoPro sleep")
        
        #switch to internet AP
        logger.info("Connecting to %s", config.wifi_ssid)
        console.print(f"[yellow]Connecting to {config.wifi_ssid}")
        os.system("sudo nmcli d wifi connect {} password {}".format(config.wifi_ssid, config.wifi_password))
        console.print(f"[yellow]Connected to {config.wifi_ssid}")
        
        #run auto backup program
        os.chdir("gdrive_auto_backup_files") #change directories
        os.system("npm start")
        os.chdir("..") #back to old working directories
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
            # Start a timer to stop the stream after 1 minute
            # console.print("[bright_cyan] Scheduling auto stop stream")
            # asyncio.create_task(limit_stream_duration(gopro, ser, args, logger))
            
            try:
                logger.info("Starting Livestream..")
                await livestream.start(args, gopro)
            except:
                ser.write("streamFailed".encode())   #send feedback to ESP
                await asyncio.sleep(1)
                logger.info("Raspi Reboot")
                os.system("sudo reboot")
            else:
                console.print("[bright_cyan] Livestream start")
                logger.info("Livestream start")
                ser.write("streamStart".encode())
                await asyncio.sleep(1)
                
        elif start_stream == 0:
            await stop_stream(gopro, ser, args, logger)
        
    if "shu" in json_data:	#check if "shutter" key exist in json/home/raspi/opengopro-python/check_bluetooth_connection.sh
        shutter = json_data['shu']
        if shutter != config.CURRENT_SHUTTER:
            command = config.GOPRO_BASE_URL + "/gp/gpControl/setting/" + config.SHUTTER_ID + "/" + str(shutter)
            response = http_commands.send(command)
            console.print(f"[yellow]Changing shutter speed into {config.SHUTTER[shutter]}")
            config.CURRENT_SHUTTER =  shutter
            logger.info("Changing shutter speed into %s", config.SHUTTER[shutter])
        if "iso" in json_data:
            iso = json_data['iso']
            if iso != config.CURRENT_ISO:
                command = config.GOPRO_BASE_URL + "/gp/gpControl/setting/" + config.ISO_ID + "/" + str(iso)
                response = http_commands.send(command)
                console.print(f"[yellow]Changing ISO into {config.ISO[iso]}")
                config.CURRENT_ISO = iso
                logger.info("Changing ISO into %s", config.ISO[iso])
        if "wb" in json_data:
            awb = json_data['wb']
            if awb != config.CURRENT_AWB:
                command= config.GOPRO_BASE_URL + "/gp/gpControl/setting/" + config.AWB_ID + "/" + str(awb)
                response = http_commands.send(command)
                console.print(f"[yellow]Changing AWB into {config.AWB[awb]}")
                config.CURRENT_AWB = awb
                logger.info("Changing AWB into %s", config.AWB[awb])
        if "ev" in json_data:
            ev = json_data['ev']
            if ev != config.CURRENT_EV:
                command = config.GOPRO_BASE_URL + "/gp/gpControl/setting/" + config.EV_ID + "/" + str(ev)
                response = http_commands.send(command)
                console.print(f"[yellow]Changing EV into {config.EV[ev]}")
                config.CURRENT_EV = ev
                logger.info("Changing EV into %s", config.EV[ev])
        request_config(ser, logger)
        await asyncio.sleep(1)
        ser.write("recConfig".encode())
        await asyncio.sleep(1)
        
async def limit_stream_duration(gopro, ser, args, logger):
    console.print("[yellow]Timer start, auto stop stream in 1 minute..")
    await asyncio.sleep(75)  # Wait for 1 minute
    console.print("[yellow]Stream stopped, timeout reached")
    if streaming:  # Ensure streaming is still active
        console.print("[yellow]streaming reaches duration limit, streaming is stopped")
        logger.info("Streaming reaches duration limit, streaming is stopped")
        await stop_stream(gopro, ser, args, logger)


async def stop_stream(gopro, ser, args, logger):
    global streaming
    try:
        logger.info("Stopping Livestream..")
        await livestream.stop(args, gopro)
        await gopro.ble_command.sleep()
        logger.info("GoPro sleep")
        await gopro.close()
    except Exception as e:
        logger.warning(f"Failed to stop livestream: {e}")
        os.system("sudo reboot")
    else:
        streaming = False
        logger.info("Livestream stopped")
        ser.write("streamStop".encode())
        # logger.info("reboot after live stream")
        logger.info("Raspi Shutdown after live stream")
        await asyncio.sleep(3)
        # os.system("sudo reboot")
        ser.write("Raspi shutdown".encode())
        # await asyncio.sleep(1)
        os.system("sudo shutdown now")
                
def is_bluetooth_connected():
    output = subprocess.check_output('./check_bluetooth_connection.sh')
    if "No".encode() in output:
        return False
    else:
        return True

def request_config(ser: serial, logger):
    command = config.GOPRO_BASE_URL + "/gp/gpControl/status"
    try:
        settings_json = http_commands.send(command)
        console.print("[yellow]Getting current GoPro config..")
        logger.info("Requesting GoPro Config..")
    except:
        console.print("[red3]Failed to get GoPro Config..")
        logger.error("Failed to get GoPro Config..")
    else:
        #get camera current state
        config.CAMERA_NAME              = settings_json['status'][config.CAMERA_NAME_ID]
        config.CURRENT_TOTAL_PHOTOS     = settings_json['status'][config.TOTAL_PHOTOS_ID]
        config.CURRENT_REMAINING_PHOTOS = settings_json['status'][config.REMAINING_PHOTOS_ID]
        config.CURRENT_BATTERY_PERC     = settings_json['status'][config.BATTERY_PERC_ID]
        config.CURRENT_MEMORY_REMAINING = settings_json['status'][config.MEMORY_REMAINING_ID]
        
        #get camera current setting
        config.CURRENT_SHUTTER  = settings_json['settings'][config.SHUTTER_ID]  #int
        config.CURRENT_ISO      = settings_json['settings'][config.ISO_ID]
        config.CURRENT_AWB      = settings_json['settings'][config.AWB_ID]
        config.CURRENT_EV       = settings_json['settings'][config.EV_ID]
        
        #convert kilobytes 1024 into gigabytes 1000
        config.CURRENT_MEMORY_REMAINING = config.CURRENT_MEMORY_REMAINING * 1024 / 10**9
        
        #build JSON using dictionary
        settings_json = {
            "camera_name"       : config.CAMERA_NAME,
            "total_photos"      : config.CURRENT_TOTAL_PHOTOS,
            "remaining_photos"  : config.CURRENT_REMAINING_PHOTOS,
            "battery_percentage": config.CURRENT_BATTERY_PERC,
            "memory_remaining"  : config.CURRENT_MEMORY_REMAINING,
            "shutter"           : config.SHUTTER[config.CURRENT_SHUTTER],
            "iso"               : config.ISO[config.CURRENT_ISO],
            "awb"               : config.AWB[config.CURRENT_AWB],
            "ev"                : config.EV[config.CURRENT_EV],
        }
        json_string = json.dumps(settings_json)
        json_string = json_string.encode()
        console.print(f"[bright_yellow]Sent to serial: {json_string}")
        ser.write(json_string)
        time.sleep(1)
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
        # grep did not match any lines
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
    parser.add_argument(
        "--resolution",
        help="Resolution.",
        choices=list(proto.EnumWindowSize.values()),
        default=proto.EnumWindowSize.WINDOW_SIZE_720,
    )
    parser.add_argument(
        "--fov", help="Field of View.", choices=list(proto.EnumLens.values()), default=proto.EnumLens.LENS_LINEAR
    )
    return add_cli_args_and_parse(parser, wifi=False)


def is_json(myJson):
    try:
        json.loads(myJson)
    except ValueError as e:
         return False
    return True


if __name__ == "__main__":
    # asyncio.run(main(parse_arguments()))
    asyncio.run(main_wd())
