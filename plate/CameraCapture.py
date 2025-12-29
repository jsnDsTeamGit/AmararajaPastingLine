import os
import cv2
import time
import uuid
import traceback
import threading
import numpy as np
from datetime import datetime, timezone
from MvCameraControl_class import *
from ctypes import cast, POINTER, c_ubyte, CFUNCTYPE, c_void_p, c_uint

saveFolder = r"LineData"
os.makedirs(saveFolder, exist_ok=True)

# Pixel format constants
PixelType_Gvsp_Mono8 = 0x01080001
PixelType_Gvsp_BayerGR8 = 0x01080008
PixelType_Gvsp_BayerRG8 = 0x01080009
PixelType_Gvsp_BayerGB8 = 0x0108000A
PixelType_Gvsp_BayerBG8 = 0x0108000B
PixelType_Gvsp_YUV422_YUYV_Packed = 0x01080016

# Error codes for disconnection detection
MV_E_HANDLE = 0x80000000
MV_E_NETER = 0x80000101
MV_E_NODATA = 0x80000102
MV_E_UNKNOW = 0x800000FF

LOG_FILE = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
    "SinglePlateModel.log"
)

# Global flag for camera disconnection
camera_disconnected = threading.Event()

def log(msg: str):
    try:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] {msg}"
        print(log_msg)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except Exception:
        pass

# Exception callback function type
EXCEPTION_CALLBACK = CFUNCTYPE(None, c_uint, c_void_p)

def exception_callback(nMsgType, pUser):
    """Callback function triggered when camera encounters an exception (like disconnection)"""
    log(f"Camera exception detected! Message type: {hex(nMsgType)}")
    if nMsgType == 0x00008001:  # MV_EXCEPTION_DEV_DISCONNECT
        log("CAMERA DISCONNECTED!")
    camera_disconnected.set()

# Keep reference to prevent garbage collection
g_exception_callback = EXCEPTION_CALLBACK(exception_callback)

def is_disconnection_error(ret_code):
    """Check if the return code indicates a camera disconnection"""
    disconnection_codes = [
        MV_E_HANDLE,   # Invalid handle
        MV_E_NETER,    # Network error
        0x80000201,    # USB error
        0x80000104,    # Device not connected
    ]
    return ret_code in disconnection_codes

def rotate_image(image, angle=180):
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = np.abs(M[0, 0]), np.abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    M[0, 2] += (new_w / 2) - center[0]
    M[1, 2] += (new_h / 2) - center[1]
    return cv2.warpAffine(image, M, (new_w, new_h))

def convert_yuyv_to_bgr(data, frame_len, height):
    width = frame_len // (2 * height)
    img = np.frombuffer(data, dtype=np.uint8, count=frame_len).reshape((height, width, 2))
    return cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUY2)

def convert_bayer_to_bgr(data, width, height, bayer_type):
    raw = np.frombuffer(data, dtype=np.uint8, count=width * height).reshape((height, width))
    bayer_map = {
        PixelType_Gvsp_BayerRG8: cv2.COLOR_BAYER_RG2BGR,
        PixelType_Gvsp_BayerBG8: cv2.COLOR_BAYER_BG2BGR,
        PixelType_Gvsp_BayerGB8: cv2.COLOR_BAYER_GB2BGR,
        PixelType_Gvsp_BayerGR8: cv2.COLOR_BAYER_GR2BGR,
    }
    if bayer_type in bayer_map:
        return cv2.cvtColor(raw, bayer_map[bayer_type])
    raise ValueError("Unsupported Bayer format")

def get_device_info_by_serial(serial_number: str):
    deviceList = MV_CC_DEVICE_INFO_LIST()
    tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
    ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
    if ret != 0 or deviceList.nDeviceNum == 0:
        log("No camera found.")
        return None

    for i in range(deviceList.nDeviceNum):
        deviceInfo = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
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

def cleanup_camera(cam):
    """Safely cleanup camera resources"""
    try:
        cam.MV_CC_StopGrabbing()
    except:
        pass
    try:
        cam.MV_CC_CloseDevice()
    except:
        pass
    try:
        cam.MV_CC_DestroyHandle()
    except:
        pass
    log("Camera resources cleaned up.")

def startCam1():
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 10  # Consider disconnected after this many failures
    
    try:
        camera_disconnected.clear()
        deviceList = MV_CC_DEVICE_INFO_LIST()
        tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        cam = MvCamera()

        ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
        if deviceList.nDeviceNum == 0:
            log("No camera found")
            return

        deviceInfo = get_device_info_by_serial("DA2568835")
        if deviceInfo is None:
            log("Target camera not found")
            return

        ret = cam.MV_CC_CreateHandle(deviceInfo)
        if ret != 0:
            log(f"Create Handle failed: {hex(ret)}")
            return

        ret = cam.MV_CC_OpenDevice()
        if ret != 0:
            log(f"Open Device failed: {hex(ret)}")
            return

        # Register exception callback for disconnection detection
        ret = cam.MV_CC_RegisterExceptionCallBack(g_exception_callback, None)
        if ret != 0:
            log(f"Warning: Failed to register exception callback: {hex(ret)}")
        else:
            log("Exception callback registered successfully")

        # Camera parameters setup
        cam.MV_CC_SetEnumValue("TriggerMode", 1)
        cam.MV_CC_SetEnumValue("TriggerSelector", 0)
        cam.MV_CC_SetEnumValue("TriggerSource", 0)
        try:
            cam.MV_CC_SetEnumValue("TriggerActivation", 0)
        except:
            pass

        cam.MV_CC_SetEnumValue("AcquisitionMode", 2)
        cam.MV_CC_SetFloatValue("ExposureTime", 2000.0)
        cam.MV_CC_SetFloatValue("Gain", 24.0)
        cam.MV_CC_SetEnumValue("GainAuto", 0)
        cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
        cam.MV_CC_SetFloatValue("AcquisitionFrameRate", 100000.0)
        cam.MV_CC_SetEnumValue("ExposureAuto", 0)

        stEnumValue = MVCC_ENUMVALUE()
        ret = cam.MV_CC_GetEnumValue("PixelFormat", stEnumValue)
        if ret == 0:
            log(f"Pixel Format: {hex(stEnumValue.nCurValue)}")
        else:
            log("Failed to get pixel format.")

        cam.MV_CC_StartGrabbing()
        log("Camera started, capturing frames...")

        stFrameInfo = MV_FRAME_OUT_INFO_EX()
        data_size = 1920 * 1200 * 3

        while not camera_disconnected.is_set():
            data_buf = (c_ubyte * data_size)()
            ret = cam.MV_CC_GetOneFrameTimeout(data_buf, data_size, stFrameInfo, 1000)
            
            if ret == 0:
                consecutive_failures = 0  # Reset on success
                
                if stEnumValue.nCurValue in [
                    PixelType_Gvsp_BayerRG8, PixelType_Gvsp_BayerBG8,
                    PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerGR8
                ]:
                    image = convert_bayer_to_bgr(
                        data_buf, stFrameInfo.nWidth, stFrameInfo.nHeight, stEnumValue.nCurValue
                    )
                elif stEnumValue.nCurValue == PixelType_Gvsp_Mono8:
                    image = np.frombuffer(
                        data_buf, dtype=np.uint8, count=stFrameInfo.nWidth * stFrameInfo.nHeight
                    ).reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                elif stEnumValue.nCurValue == PixelType_Gvsp_YUV422_YUYV_Packed:
                    image = convert_yuyv_to_bgr(data_buf, stFrameInfo.nFrameLen, stFrameInfo.nHeight)
                else:
                    log(f"Unsupported pixel format: {hex(stEnumValue.nCurValue)}")
                    break

                image = rotate_image(image, 90)
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                imPath = f"{saveFolder}/{uuid.uuid4()}.jpg"
                cv2.imwrite(imPath, image)

            else:
            # MV_E_NODATA is normal in trigger mode - no frame available yet
                if ret == MV_E_NODATA:
                    # This is expected behavior, not an error - just continue waiting
                    continue

                # Only count REAL errors as failures
                consecutive_failures += 1
                log(f"Frame grab failed (ret={hex(ret)}), failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")

                # Check for specific disconnection errors
                if is_disconnection_error(ret):
                    log(f"CAMERA DISCONNECTED! Error code: {hex(ret)}")
                    camera_disconnected.set()
                    break

                # Check consecutive failures threshold
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log(f"Too many consecutive failures ({consecutive_failures}). Camera likely disconnected.")
                    camera_disconnected.set()
                    break
                
                time.sleep(0.05)

        # Cleanup
        log("Exiting capture loop - camera disconnected or error occurred")
        cleanup_camera(cam)
        
    except Exception as e:
        log(f"Error while capturing Image: {str(e)}")
        log(traceback.format_exc())
        try:
            cleanup_camera(cam)
        except:
            pass
        time.sleep(5)
        sys.exit(1)

# if __name__ == "__main__":
#     startCam1()