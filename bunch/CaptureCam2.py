import os
import sys
import cv2
import sys
import time
import numpy as np
from datetime import datetime,timezone
from MvCameraControl_class import *
from ctypes import cast, POINTER, c_ubyte


PixelType_Gvsp_Mono8     = 0x01080001
PixelType_Gvsp_BayerGR8  = 0x01080008
PixelType_Gvsp_BayerRG8  = 0x01080009
PixelType_Gvsp_BayerGB8  = 0x0108000A
PixelType_Gvsp_BayerBG8  = 0x0108000B
PixelType_Gvsp_YUV422_YUYV_Packed = 0x01080016

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

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
    cos = np.abs(M[0, 0]); sin = np.abs(M[0, 1])
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
# --------------------------------------------

class HikCamera:
    """
    Open once, grab on demand.
    - trigger_source: 'Line0' (external) or 'Software'
    - rotate_deg: rotate output image (e.g., 180)
    """
    def __init__(self, serialNo, trigger_source='Line0', exposure_us=700.0, gain_db=20.0, rotate_deg=180):
        self.serialNo = serialNo
        self.trigger_source = trigger_source
        self.exposure_us = exposure_us
        self.gain_db = gain_db
        self.rotate_deg = rotate_deg

        self.cam = None
        self.pixel_format = None
        self.opened = False
    def get_device_info_by_serial(self,serial_number: str):
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

    def open(self):
        if self.opened:
            return True
        try:
            deviceList = MV_CC_DEVICE_INFO_LIST()
            tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE

            ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
            if ret != 0 or deviceList.nDeviceNum == 0:
                log("No camera found")
                return False

            self.cam = MvCamera()
            # deviceInfo = cast(deviceList.pDeviceInfo[self.device_index], POINTER(MV_CC_DEVICE_INFO)).contents
            deviceInfo = self.get_device_info_by_serial(self.serialNo)

            ret = self.cam.MV_CC_CreateHandle(deviceInfo)
            if ret != 0:
                log(f"Create Handle failed: {ret}")
                return False

            ret = self.cam.MV_CC_OpenDevice()
            if ret != 0:
                log(f"Open Device failed: {ret}")
                return False

            # --- Camera configuration (similar to your original) ---
            self.cam.MV_CC_SetEnumValue("TriggerMode", 1)           # On
            # self.cam.MV_CC_SetEnumValue("TriggerSelector", 0)       # FrameStart

            if self.trigger_source.lower() == 'software':
                # 7 is commonly Software trigger for Hikrobot; may vary by model
                self.cam.MV_CC_SetEnumValue("TriggerSource", 7)
            else:
                self.cam.MV_CC_SetEnumValue("TriggerSource", 0)     # Line0 (external)

            # try:
            #     self.cam.MV_CC_SetEnumValue("TriggerActivation", 0) # Rising edge (if supported)
            # except:
            #     pass

            self.cam.MV_CC_SetEnumValue("AcquisitionMode", 2)       # Continuous
            self.cam.MV_CC_SetFloatValue("ExposureTime", float(self.exposure_us))
            self.cam.MV_CC_SetFloatValue("Gain", float(self.gain_db))
            self.cam.MV_CC_SetEnumValue("GainAuto", 0)              # Manual
            self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            # You can set a realistic FPS if needed:
            self.cam.MV_CC_SetFloatValue("AcquisitionFrameRate", 100000.0)
            self.cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            # Get pixel format
            stEnumValue = MVCC_ENUMVALUE()
            ret = self.cam.MV_CC_GetEnumValue("PixelFormat", stEnumValue)
            if ret == 0:
                self.pixel_format = int(stEnumValue.nCurValue)
                log(f"Pixel Format: {hex(self.pixel_format)}")
            else:
                log("Failed to get pixel format.")
                self.pixel_format = None

            # Start grabbing
            ret = self.cam.MV_CC_StartGrabbing()
            if ret != 0:
                log(f"StartGrabbing failed: {ret}")
                return False

            self.opened = True
            return True

        except Exception as e:
            log(f"Exception in open(): {repr(e)}")
            self.close()  # Ensure to close camera on error
            return False

    def close(self):
        """Safely closes the camera handle."""
        try:
            if self.cam:
                try:
                    self.cam.MV_CC_StopGrabbing()
                except Exception as e:
                    log(f"Error stopping grabbing: {repr(e)}")
                try:
                    self.cam.MV_CC_CloseDevice()
                except Exception as e:
                    log(f"Error closing device: {repr(e)}")
                try:
                    self.cam.MV_CC_DestroyHandle()
                except Exception as e:
                    log(f"Error destroying handle: {repr(e)}")
        finally:
            self.cam = None
            self.opened = False
            log("Camera successfully closed.")

    def get_frame(self, timeout_ms=1000, fire_software_trigger=None):
        """
        Returns a single frame as RGB np.ndarray, or None on timeout/error.
        If fire_software_trigger is None: infer from self.trigger_source.
        """
        if not self.opened and not self.open():
            return None

        # Decide whether to fire software trigger now
        do_sw_trigger = (
            fire_software_trigger
            if fire_software_trigger is not None
            else (self.trigger_source.lower() == 'software')
        )

        try:
            if do_sw_trigger:
                # Fire one software trigger for this frame
                # (String may differ by model; this is common)
                self.cam.MV_CC_SetCommandValue("TriggerSoftware")

            stFrameInfo = MV_FRAME_OUT_INFO_EX()
            # Use a comfortably large buffer (e.g., up to 4096x3000x3)
            data_size = 1920 * 1200 * 3 * 3
            data_buf = (c_ubyte * data_size)()

            ret = self.cam.MV_CC_GetOneFrameTimeout(data_buf, data_size, stFrameInfo, timeout_ms)
            if ret != 0:
                # No frame received in time (likely waiting for external trigger)
                return None

            # Build image depending on pixel format
            fmt = self.pixel_format
            if fmt in (PixelType_Gvsp_BayerRG8, PixelType_Gvsp_BayerBG8,
                       PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerGR8):
                bgr = convert_bayer_to_bgr(data_buf, stFrameInfo.nWidth, stFrameInfo.nHeight, fmt)

            elif fmt == PixelType_Gvsp_Mono8:
                gray = np.frombuffer(data_buf, dtype=np.uint8,
                                     count=stFrameInfo.nWidth * stFrameInfo.nHeight)
                gray = gray.reshape((stFrameInfo.nHeight, stFrameInfo.nWidth))
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

            elif fmt == PixelType_Gvsp_YUV422_YUYV_Packed:
                bgr = convert_yuyv_to_bgr(data_buf, stFrameInfo.nFrameLen, stFrameInfo.nHeight)

            else:
                log(f"Unsupported pixel format: {hex(fmt) if fmt is not None else 'None'}")
                return None
            time.sleep(0.5)
            # Rotate if requested
            if self.rotate_deg and self.rotate_deg % 360 != 0:
                bgr = rotate_image(bgr, self.rotate_deg)

            # Return as RGB (common for display libs). If you need BGR, skip this line.
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            return rgb

        except Exception as e:
            log(f"Exception in get_frame(): {repr(e)}")
            self.close()  # Ensure to close camera on error
            return None

# -------- Simple global accessor (call this from your code) --------
_cam_singleton = None

def get_current_image(serialNo, trigger_source='Line0', timeout_ms=1000, rotate_deg=180, use_software_trigger=False):
    """
    Returns the current image (RGB np.ndarray) or None if not available.
    - trigger_source: 'Line0' for external HW trigger, 'Software' for on-demand.
    - use_software_trigger: if True, fires one SW trigger for this call.
    """
    global _cam_singleton
    if _cam_singleton is None:
        _cam_singleton = HikCamera(
            serialNo=serialNo,
            trigger_source=trigger_source,
            rotate_deg=rotate_deg, 
            exposure_us=1000.0,
            gain_db=20.0
        )
        if not _cam_singleton.open():
            log("Failed to open camera in get_current_image")
            return None

    return _cam_singleton.get_frame(timeout_ms=timeout_ms, fire_software_trigger=use_software_trigger)

