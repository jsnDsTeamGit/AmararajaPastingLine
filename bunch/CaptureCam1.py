import os
import cv2
import time
import uuid
import traceback
import numpy as np
from datetime import datetime,timezone
from MvCameraControl_class import *
from ctypes import cast, POINTER, c_ubyte
# from CaptureCam2 import get_current_image

saveFolder = r"LineData"
os.makedirs(saveFolder,exist_ok=True)
# Pixel format constants (from Hikrobot SDK)
PixelType_Gvsp_Mono8     = 0x01080001
PixelType_Gvsp_BayerGR8  = 0x01080008
PixelType_Gvsp_BayerRG8  = 0x01080009
PixelType_Gvsp_BayerGB8  = 0x0108000A
PixelType_Gvsp_BayerBG8  = 0x0108000B
PixelType_Gvsp_YUV422_YUYV_Packed = 0x01080016

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

robotSideCam = "DA5728612"
catcherSideCam = "DA5728604"

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def rotate_image(image, angle = 180):
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    M[0, 2] += (new_w / 2) - center[0]
    M[1, 2] += (new_h / 2) - center[1]
    rotated_image = cv2.warpAffine(image, M, (new_w, new_h))
    return rotated_image

def convert_yuyv_to_bgr(data, frame_len, height):
    width = frame_len // (2 * height)
    img = np.frombuffer(data, dtype=np.uint8, count=frame_len).reshape((height, width, 2))
    bgr_img = cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUY2)
    return bgr_img

def convert_bayer_to_bgr(data, width, height, bayer_type):
    raw = np.frombuffer(data, dtype=np.uint8, count=width*height).reshape((height, width))
    if bayer_type == PixelType_Gvsp_BayerRG8:
        return cv2.cvtColor(raw, cv2.COLOR_BAYER_RG2BGR)
    elif bayer_type == PixelType_Gvsp_BayerBG8:
        return cv2.cvtColor(raw, cv2.COLOR_BAYER_BG2BGR)
    elif bayer_type == PixelType_Gvsp_BayerGB8:
        return cv2.cvtColor(raw, cv2.COLOR_BAYER_GB2BGR)
    elif bayer_type == PixelType_Gvsp_BayerGR8:
        return cv2.cvtColor(raw, cv2.COLOR_BAYER_GR2BGR)
    else:
        raise ValueError("Unsupported Bayer format")

def get_device_info_by_serial(serial_number: str):
    """
    Find device info by serial number.
    Returns MV_CC_DEVICE_INFO if found, else None.
    """
    deviceList = MV_CC_DEVICE_INFO_LIST()
    tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE

    # Enumerate devices
    ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
    if ret != 0 or deviceList.nDeviceNum == 0:
        log("No camera found.")
        return None

    for i in range(deviceList.nDeviceNum):
        deviceInfo = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
        # For GigE devices, use SpecialInfo.stGigEInfo
        if deviceInfo.nTLayerType == MV_GIGE_DEVICE:
            sn = bytes(deviceInfo.SpecialInfo.stGigEInfo.chSerialNumber).decode('utf-8').strip('\x00')
        elif deviceInfo.nTLayerType == MV_USB_DEVICE:
            sn = bytes(deviceInfo.SpecialInfo.stUsb3VInfo.chSerialNumber).decode('utf-8').strip('\x00')
        else:
            continue

        if sn == serial_number:
            return deviceInfo

    log(f"Camera with serial {serial_number} not found.")
    return None

def startCam():
    try:
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE

        cam = MvCamera()

        # Enumerate devices
        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        if deviceList.nDeviceNum == 0:
            log("No camera found")
            return

        # Select first device
        # deviceInfo = cast(deviceList.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
        deviceInfo = get_device_info_by_serial(catcherSideCam)  # Change to your camera's serial number
        ret = cam.MV_CC_CreateHandle(deviceInfo)
        if ret != 0:
            log("Create Handle failed:")
            return

        ret = cam.MV_CC_OpenDevice()
        if ret != 0:
            log("Open Device failed:")
            return


        # SET CAMERA PARAMETERS
        
        # 0-off (continuous mode); 1-on (trigger mode)
        cam.MV_CC_SetEnumValue("TriggerMode", 1)             # 0=Off, 1=On
        # cam.MV_CC_SetEnumValue("TriggerSelector", 0)         # 0=FrameStart (most cameras)
        # Set your line here: 0=Line0, 1=Line1, etc. Use Software=7 if you want SW trigger.
        cam.MV_CC_SetEnumValue("TriggerSource", 0)           # External Line0
        # Optional but common:
        # 0=RisingEdge, 1=FallingEdge, 2=AnyEdge (value may vary by model)
        # try:
        #     cam.MV_CC_SetEnumValue("TriggerActivation", 0)   # Rising edge
        # except:
        #     pass  # Some models don't expose this 

        # 0-single frame (the camera acquires a single frame per command)
        # 1-multi-frame (the camera acquires a set number of frames per command)
        # 2-continuous (the camera continuously acquires frames)
        cam.MV_CC_SetEnumValue("AcquisitionMode", 2)

        # Set exposure time to 10000 microseconds (10 ms)
        cam.MV_CC_SetFloatValue("ExposureTime", 1000.0)

        # Gain in dB (e.g., 0.0 = minimum gain)
        # Typical range: 0.0~24.0
        cam.MV_CC_SetFloatValue("Gain", 20.0)
        # 0-Off (manual gain)
        # 1-Once (auto once)
        # 2-Continuous (auto continuous)
        cam.MV_CC_SetEnumValue("GainAuto", 0)

        # Enable/disable acquisition frame rate control
        cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)

        # Set acquisition frame rate (frames per second)
        # Range: 0.1~max fps of camera
        cam.MV_CC_SetFloatValue("AcquisitionFrameRate", 100000.0)  

        # Exposure auto mode
        # 0=Off, 1=Once, 2=Continuous
        cam.MV_CC_SetEnumValue("ExposureAuto", 0)

        stEnumValue = MVCC_ENUMVALUE()
        ret = cam.MV_CC_GetEnumValue("PixelFormat", stEnumValue)
        if ret == 0:
            log(f"Pixel Format: {hex(stEnumValue.nCurValue)}")
        else:
            log("Failed to get pixel format.")

        # Start grabbing
        cam.MV_CC_StartGrabbing()

        stFrameInfo = MV_FRAME_OUT_INFO_EX()
        data_size = 1920 * 1200 * 3  # Max expected size (adjust if needed)
        trigger = 0

        last_connection_check = time.time()
        CONNECTION_CHECK_INTERVAL = 60  # seconds        
        data_buf = (c_ubyte * data_size)()
        while True:
            # Check camera connection every minute
            if time.time() - last_connection_check >= CONNECTION_CHECK_INTERVAL:
                if not cam.MV_CC_IsDeviceConnected():
                    log(f"WARNING: Camera disconnected!")
                last_connection_check = time.time()    

            ret = cam.MV_CC_GetOneFrameTimeout(data_buf, data_size, stFrameInfo, 1000)
            if ret == 0:
                if trigger == 1:
                    trigger = 0
                    pass
                else:
                    trigger = 1
                    continue
                if stEnumValue.nCurValue in [
                    PixelType_Gvsp_BayerRG8, PixelType_Gvsp_BayerBG8,
                    PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerGR8
                ]:
                    image = convert_bayer_to_bgr(
                        data_buf, stFrameInfo.nWidth, stFrameInfo.nHeight, stEnumValue.nCurValue
                    )
                elif stEnumValue.nCurValue == PixelType_Gvsp_Mono8:
                    image = np.frombuffer(data_buf, dtype=np.uint8, count=stFrameInfo.nWidth * stFrameInfo.nHeight)
                    image = image.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)  # Convert grayscale to BGR for display
                elif stEnumValue.nCurValue == PixelType_Gvsp_YUV422_YUYV_Packed:
                    image = convert_yuyv_to_bgr(data_buf, stFrameInfo.nFrameLen, stFrameInfo.nHeight)
                else:
                    log(f"Unsupported pixel format: {hex(stEnumValue.nCurValue)}")
                    break
                # time.sleep(4)
                # image2 = get_current_image(serialNo=catcherSideCam, trigger_source='Software', use_software_trigger=True)
                # time.sleep(0.5)
                processId = f"{uuid.uuid4()}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                image1 = rotate_image(image, 180)
                image1 = cv2.cvtColor(image1, cv2.COLOR_BGR2RGB)
                im1Path = f"{saveFolder}/1__{processId}.jpg"
                # im2Path = f"{saveFolder}/2__{processId}.jpg"
                cv2.imwrite(im1Path, image1)
                # if image2 is not None:
                #     cv2.imwrite(im2Path, image2)

            else:
                # log(f"GetOneFrameTimeout failed: ret={hex(ret)}")
                time.sleep(0.05)

        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
    except:
        print("Error while capturing Image.....")
        log(traceback.format_exc())
        time.sleep(5)
        sys.exit(1)