#!/usr/bin/env python3
"""
hardware_presets.py — Tự động phát hiện phần cứng và chọn preset FFmpeg tối ưu.

Hỗ trợ:
  - ThinkPad T14 Gen3 (Intel 12th Gen / AMD Ryzen 6000)
  - Máy có GPU NVIDIA (NVENC)
  - Máy có Intel QSV (Quick Sync Video)
  - Máy có AMD AMF/VCE
  - Fallback CPU-only cho mọi máy khác

Cách dùng:
  from core.hardware_presets import get_optimal_preset
  preset = get_optimal_preset()
  # preset.video_codec, preset.preset_name, preset.crf, ...
"""
import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class HardwareInfo:
    """Thông tin phần cứng đã phát hiện."""
    cpu_name: str = ""
    cpu_cores: int = 4
    cpu_threads: int = 8
    cpu_arch: str = ""  # x86_64, aarch64, etc.
    ram_gb: float = 8.0
    has_nvidia_gpu: bool = False
    nvidia_gpu_name: str = ""
    has_intel_qsv: bool = False
    has_amd_amf: bool = False
    is_thinkpad_t14: bool = False
    machine_profile: str = "generic"  # thinkpad_t14_intel, thinkpad_t14_amd, desktop_nvidia, etc.


@dataclass
class FFmpegPreset:
    """Preset FFmpeg tối ưu cho phần cứng cụ thể."""
    # Video encoding
    video_codec: str = "libx264"
    preset_name: str = "veryfast"
    crf: int = 23
    # Hardware acceleration
    hwaccel: str = ""  # cuda, qsv, vaapi, ""
    hwaccel_device: str = ""
    # Extra codec params
    extra_video_params: list = field(default_factory=list)
    # Audio
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    # Threading
    threads: int = 0  # 0 = auto
    # Filter
    filter_threads: int = 0
    # Description
    description: str = ""
    machine_profile: str = "generic"

    def build_video_args(self) -> list[str]:
        """Tạo danh sách args cho ffmpeg video encoding."""
        args = []
        if self.hwaccel:
            args += ["-hwaccel", self.hwaccel]
            if self.hwaccel_device:
                args += ["-hwaccel_device", self.hwaccel_device]
        return args

    def build_output_args(self) -> list[str]:
        """Tạo danh sách args cho output encoding."""
        args = ["-c:v", self.video_codec]
        if self.video_codec == "libx264":
            args += ["-preset", self.preset_name, "-crf", str(self.crf)]
        elif self.video_codec == "h264_nvenc":
            args += ["-preset", self.preset_name, "-cq", str(self.crf)]
        elif self.video_codec == "h264_qsv":
            args += ["-preset", self.preset_name, "-global_quality", str(self.crf)]
        elif self.video_codec == "h264_amf":
            args += ["-quality", self.preset_name, "-rc", "cqp", "-qp_i", str(self.crf), "-qp_p", str(self.crf)]

        args += self.extra_video_params

        if self.threads > 0:
            args += ["-threads", str(self.threads)]

        args += ["-c:a", self.audio_codec, "-b:a", self.audio_bitrate]
        return args


# ── Hardware detection ────────────────────────────────────────────────────────

def _detect_cpu_info() -> dict:
    """Phát hiện thông tin CPU."""
    info = {"name": "", "cores": 4, "threads": 8, "arch": platform.machine()}

    system = platform.system()
    if system == "Windows":
        # 1. Native registry CPU name detection (extremely fast, no subprocess)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                info["name"] = name.strip()
        except Exception:
            pass

        # 2. Try wmic for cores/threads (might fail on Windows 11 if disabled)
        wmic_success = False
        try:
            r = subprocess.run(
                ["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors", "/format:list"],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    line = line.strip()
                    if line.startswith("Name=") and not info["name"]:
                        info["name"] = line.split("=", 1)[1].strip()
                    elif line.startswith("NumberOfCores="):
                        val = line.split("=", 1)[1].strip()
                        if val.isdigit():
                            info["cores"] = int(val)
                            wmic_success = True
                    elif line.startswith("NumberOfLogicalProcessors="):
                        val = line.split("=", 1)[1].strip()
                        if val.isdigit():
                            info["threads"] = int(val)
                            wmic_success = True
        except Exception:
            pass

        # 3. Fallback to PowerShell if wmic failed
        if not wmic_success:
            try:
                r = subprocess.run(
                    ["powershell", "-Command", "Get-CimInstance Win32_Processor | Select-Object NumberOfCores, NumberOfLogicalProcessors | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0 and r.stdout.strip():
                    import json
                    data = json.loads(r.stdout.strip())
                    if isinstance(data, list):
                        data = data[0]
                    if "NumberOfCores" in data:
                        info["cores"] = int(data["NumberOfCores"])
                    if "NumberOfLogicalProcessors" in data:
                        info["threads"] = int(data["NumberOfLogicalProcessors"])
                    wmic_success = True
            except Exception:
                pass

        if not wmic_success:
            logical = os.cpu_count() or 4
            info["threads"] = logical
            info["cores"] = max(1, logical // 2)
    elif system == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
            m = re.search(r"model name\s*:\s*(.+)", content)
            if m:
                info["name"] = m.group(1).strip()
            info["cores"] = os.cpu_count() or 4
            info["threads"] = info["cores"]
        except Exception:
            info["cores"] = os.cpu_count() or 4
            info["threads"] = info["cores"]
    elif system == "Darwin":
        try:
            r = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                               capture_output=True, text=True, timeout=5)
            info["name"] = r.stdout.strip()
            info["cores"] = os.cpu_count() or 4
            info["threads"] = info["cores"]
        except Exception:
            info["cores"] = os.cpu_count() or 4
            info["threads"] = info["cores"]

    if not info["name"]:
        info["cores"] = os.cpu_count() or 4
        info["threads"] = info["cores"]

    return info


def _detect_nvidia_gpu(ffmpeg: Optional[str] = None) -> dict:
    """Phát hiện GPU NVIDIA và khả năng NVENC."""
    info = {"has_gpu": False, "name": ""}

    # Check nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            info["has_gpu"] = True
            info["name"] = r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, Exception):
        pass

    # Verify ffmpeg supports nvenc
    if info["has_gpu"] and ffmpeg:
        try:
            r = subprocess.run(
                [ffmpeg, "-encoders"],
                capture_output=True, text=True, timeout=5
            )
            if "h264_nvenc" not in (r.stdout or ""):
                info["has_gpu"] = False
                logger.info("NVIDIA GPU found but ffmpeg lacks h264_nvenc support")
        except Exception:
            pass

    return info


def _detect_intel_qsv(ffmpeg: Optional[str] = None) -> bool:
    """Phát hiện Intel Quick Sync Video."""
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        return "h264_qsv" in (r.stdout or "")
    except Exception:
        return False


def _detect_amd_amf(ffmpeg: Optional[str] = None) -> bool:
    """Phát hiện AMD AMF/VCE encoder."""
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        return "h264_amf" in (r.stdout or "")
    except Exception:
        return False


def _detect_ram_gb() -> float:
    """Phát hiện RAM (GB)."""
    system = platform.system()
    if system == "Windows":
        # 1. Try ctypes (native, most robust, no subprocess)
        try:
            import ctypes
            from ctypes import wintypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024**3), 1)
        except Exception:
            pass

        # 2. Try wmic
        try:
            r = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory", "/format:list"],
                capture_output=True, text=True, timeout=3
            )
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("TotalPhysicalMemory="):
                    val = line.split("=", 1)[1].strip()
                    if val.isdigit():
                        return round(int(val) / (1024**3), 1)
        except Exception:
            pass

        # 3. Try PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-Command", "(Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum).Sum"],
                capture_output=True, text=True, timeout=5
            )
            val = r.stdout.strip()
            if val.isdigit():
                return round(int(val) / (1024**3), 1)
        except Exception:
            pass

        # 4. Try alternate PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                capture_output=True, text=True, timeout=5
            )
            val = r.stdout.strip()
            if val.isdigit():
                return round(int(val) / (1024**3), 1)
        except Exception:
            pass
    elif system == "Linux":
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(re.search(r"\d+", line).group())
                        return round(kb / (1024**2), 1)
        except Exception:
            pass
    elif system == "Darwin":
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"],
                               capture_output=True, text=True, timeout=5)
            return round(int(r.stdout.strip()) / (1024**3), 1)
        except Exception:
            pass
    return 8.0


def _detect_machine_model() -> str:
    """Phát hiện model máy (ThinkPad, etc.)."""
    system = platform.system()
    if system == "Windows":
        # 1. Try Registry (native, BIOS product/manufacturer)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
                try:
                    model, _ = winreg.QueryValueEx(key, "SystemProductName")
                except Exception:
                    model = ""
                try:
                    family, _ = winreg.QueryValueEx(key, "SystemFamily")
                except Exception:
                    family = ""
                try:
                    manufacturer, _ = winreg.QueryValueEx(key, "SystemManufacturer")
                except Exception:
                    manufacturer = ""
                
                parts = []
                if manufacturer and manufacturer.strip().lower() not in ("to be filled by o.e.m.", "system manufacturer"):
                    parts.append(manufacturer.strip())
                if family and family.strip().lower() not in ("to be filled by o.e.m.", "system family"):
                    parts.append(family.strip())
                if model and model.strip().lower() not in ("to be filled by o.e.m.", "system product name"):
                    parts.append(model.strip())
                
                res = " ".join(parts).strip()
                if res:
                    return res
        except Exception:
            pass

        # 2. Try wmic
        try:
            model = ""
            r = subprocess.run(
                ["wmic", "computersystem", "get", "Model", "/format:list"],
                capture_output=True, text=True, timeout=3
            )
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("Model="):
                    model = line.split("=", 1)[1].strip()
                    break

            r2 = subprocess.run(
                ["wmic", "computersystem", "get", "SystemFamily", "/format:list"],
                capture_output=True, text=True, timeout=3
            )
            family = ""
            for line in r2.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("SystemFamily="):
                    family = line.split("=", 1)[1].strip()
                    break

            if family:
                return f"{family} {model}".strip()
            if model:
                return model
        except Exception:
            pass

        # 3. Try PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-Command", "(Get-CimInstance Win32_ComputerSystem).Model"],
                capture_output=True, text=True, timeout=5
            )
            model = r.stdout.strip()
            if model:
                return model
        except Exception:
            pass
    elif system == "Linux":
        try:
            model_file = Path("/sys/devices/virtual/dmi/id/product_name")
            if model_file.exists():
                return model_file.read_text().strip()
        except Exception:
            pass
    return ""


def detect_hardware(ffmpeg: Optional[str] = None) -> HardwareInfo:
    """Phát hiện toàn bộ thông tin phần cứng."""
    hw = HardwareInfo()

    # CPU
    cpu = _detect_cpu_info()
    hw.cpu_name = cpu["name"]
    hw.cpu_cores = cpu["cores"]
    hw.cpu_threads = cpu["threads"]
    hw.cpu_arch = cpu["arch"]

    # RAM
    hw.ram_gb = _detect_ram_gb()

    # GPU
    nvidia = _detect_nvidia_gpu(ffmpeg)
    hw.has_nvidia_gpu = nvidia["has_gpu"]
    hw.nvidia_gpu_name = nvidia["name"]

    # Intel QSV
    hw.has_intel_qsv = _detect_intel_qsv(ffmpeg)

    # AMD AMF
    hw.has_amd_amf = _detect_amd_amf(ffmpeg)

    # Machine model
    model = _detect_machine_model()
    hw.is_thinkpad_t14 = bool(re.search(r"thinkpad.*t14", model, re.IGNORECASE))

    # Determine profile
    hw.machine_profile = _classify_machine(hw, model)

    logger.info(
        "Hardware detected: %s | %d cores/%d threads | RAM %.1fGB | GPU: %s | QSV: %s | AMF: %s | Profile: %s",
        hw.cpu_name, hw.cpu_cores, hw.cpu_threads, hw.ram_gb,
        hw.nvidia_gpu_name or "None", hw.has_intel_qsv, hw.has_amd_amf, hw.machine_profile
    )

    return hw


def _classify_machine(hw: HardwareInfo, model: str) -> str:
    """Phân loại máy thành profile."""
    model_lower = model.lower()

    # ThinkPad T14 Gen3 — detect by name or Lenovo model codes
    # 21AH* = ThinkPad T14 Gen3 Intel, 21CF* = ThinkPad T14 Gen3 AMD
    is_t14_gen3 = (
        ("t14" in model_lower and ("gen 3" in model_lower or "gen3" in model_lower))
        or model.startswith("21AH")  # T14 Gen3 Intel
        or model.startswith("21CF")  # T14 Gen3 AMD
    )

    if is_t14_gen3 or hw.is_thinkpad_t14:
        if "amd" in hw.cpu_name.lower() or "ryzen" in hw.cpu_name.lower():
            return "thinkpad_t14_gen3_amd"
        return "thinkpad_t14_gen3_intel"

    # ThinkPad generic (detect by family name or model code patterns)
    is_thinkpad = (
        "thinkpad" in model_lower
        or "think pad" in model_lower
    )
    if is_thinkpad:
        if hw.has_intel_qsv:
            return "thinkpad_intel_qsv"
        if "amd" in hw.cpu_name.lower():
            return "thinkpad_amd"
        return "thinkpad_generic"

    # Desktop/Workstation with NVIDIA
    if hw.has_nvidia_gpu:
        return "desktop_nvidia"

    # Intel with QSV
    if hw.has_intel_qsv:
        return "intel_qsv"

    # AMD with AMF
    if hw.has_amd_amf:
        return "amd_amf"

    # High-core CPU
    if hw.cpu_cores >= 8:
        return "high_core_cpu"

    # Low-power / generic
    if hw.cpu_cores <= 2:
        return "low_power"

    return "generic"


# ── Preset selection ──────────────────────────────────────────────────────────

_PRESETS: dict[str, FFmpegPreset] = {
    # ThinkPad T14 Gen3 Intel (12th Gen, 10-14 cores, Intel Iris Xe with QSV)
    "thinkpad_t14_gen3_intel": FFmpegPreset(
        video_codec="h264_qsv",
        preset_name="faster",
        crf=23,
        hwaccel="qsv",
        extra_video_params=["-look_ahead", "1"],
        threads=0,
        description="ThinkPad T14 Gen3 Intel — QSV hardware encoding (Iris Xe)",
        machine_profile="thinkpad_t14_gen3_intel",
    ),
    # ThinkPad T14 Gen3 AMD (Ryzen 6000, 8 cores, Radeon 680M)
    "thinkpad_t14_gen3_amd": FFmpegPreset(
        video_codec="libx264",
        preset_name="fast",
        crf=22,
        threads=12,  # Ryzen 6000 has 8C/16T, use 12 threads
        extra_video_params=["-tune", "fastdecode"],
        description="ThinkPad T14 Gen3 AMD — CPU x264 optimized for Ryzen 6000 (8C/16T)",
        machine_profile="thinkpad_t14_gen3_amd",
    ),
    # ThinkPad generic with Intel QSV
    "thinkpad_intel_qsv": FFmpegPreset(
        video_codec="h264_qsv",
        preset_name="faster",
        crf=24,
        hwaccel="qsv",
        threads=0,
        description="ThinkPad Intel — QSV hardware encoding",
        machine_profile="thinkpad_intel_qsv",
    ),
    # ThinkPad AMD (no AMF in ffmpeg builds usually)
    "thinkpad_amd": FFmpegPreset(
        video_codec="libx264",
        preset_name="fast",
        crf=23,
        threads=0,
        description="ThinkPad AMD — CPU x264 multi-threaded",
        machine_profile="thinkpad_amd",
    ),
    # ThinkPad generic
    "thinkpad_generic": FFmpegPreset(
        video_codec="libx264",
        preset_name="fast",
        crf=23,
        threads=0,
        description="ThinkPad generic — balanced CPU encoding",
        machine_profile="thinkpad_generic",
    ),
    # Desktop with NVIDIA GPU
    "desktop_nvidia": FFmpegPreset(
        video_codec="h264_nvenc",
        preset_name="p4",  # NVENC preset: p1(fastest) → p7(best quality)
        crf=23,
        hwaccel="cuda",
        extra_video_params=["-b:v", "0", "-rc", "constqp"],
        threads=0,
        description="Desktop NVIDIA — NVENC hardware encoding (fast, high quality)",
        machine_profile="desktop_nvidia",
    ),
    # Intel QSV (non-ThinkPad)
    "intel_qsv": FFmpegPreset(
        video_codec="h264_qsv",
        preset_name="faster",
        crf=23,
        hwaccel="qsv",
        threads=0,
        description="Intel QSV — hardware encoding",
        machine_profile="intel_qsv",
    ),
    # AMD AMF
    "amd_amf": FFmpegPreset(
        video_codec="h264_amf",
        preset_name="speed",
        crf=23,
        threads=0,
        description="AMD AMF — hardware encoding",
        machine_profile="amd_amf",
    ),
    # High-core CPU (8+ cores)
    "high_core_cpu": FFmpegPreset(
        video_codec="libx264",
        preset_name="medium",
        crf=22,
        threads=0,  # let ffmpeg auto-detect
        extra_video_params=["-tune", "fastdecode"],
        description="High-core CPU — x264 medium preset (better quality, still fast)",
        machine_profile="high_core_cpu",
    ),
    # Low-power (2 cores or less)
    "low_power": FFmpegPreset(
        video_codec="libx264",
        preset_name="ultrafast",
        crf=25,
        threads=2,
        description="Low-power device — ultrafast encoding to avoid overload",
        machine_profile="low_power",
    ),
    # Generic fallback
    "generic": FFmpegPreset(
        video_codec="libx264",
        preset_name="veryfast",
        crf=23,
        threads=0,
        description="Generic — balanced veryfast x264 encoding",
        machine_profile="generic",
    ),
}

# Cache detected hardware
_cached_hardware: Optional[HardwareInfo] = None
_cached_preset: Optional[FFmpegPreset] = None


def get_optimal_preset(ffmpeg: Optional[str] = None, force_redetect: bool = False) -> FFmpegPreset:
    """
    Phát hiện phần cứng và trả về preset FFmpeg tối ưu.
    Kết quả được cache sau lần đầu.
    """
    global _cached_hardware, _cached_preset

    if _cached_preset and not force_redetect:
        return _cached_preset

    hw = detect_hardware(ffmpeg)
    _cached_hardware = hw

    preset = _PRESETS.get(hw.machine_profile, _PRESETS["generic"])

    # Validate: test if the chosen codec actually works
    if preset.video_codec != "libx264" and ffmpeg:
        if not _test_encoder(ffmpeg, preset.video_codec):
            logger.warning(
                "Encoder %s không hoạt động, fallback về libx264",
                preset.video_codec
            )
            preset = _get_cpu_fallback(hw)

    _cached_preset = preset
    logger.info("Selected FFmpeg preset: %s (%s)", preset.machine_profile, preset.description)
    return preset


def _test_encoder(ffmpeg: str, encoder: str) -> bool:
    """Test nhanh xem encoder có hoạt động không."""
    try:
        r = subprocess.run(
            [ffmpeg, "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
             "-c:v", encoder, "-f", "null", "-", "-y"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


def _get_cpu_fallback(hw: HardwareInfo) -> FFmpegPreset:
    """Fallback CPU preset dựa trên số cores."""
    if hw.cpu_cores >= 8:
        return _PRESETS["high_core_cpu"]
    elif hw.cpu_cores <= 2:
        return _PRESETS["low_power"]
    return _PRESETS["generic"]


def get_hardware_info(ffmpeg: Optional[str] = None) -> dict:
    """Trả về thông tin phần cứng dạng dict (cho API/UI)."""
    global _cached_hardware
    if not _cached_hardware:
        _cached_hardware = detect_hardware(ffmpeg)
    hw = _cached_hardware
    preset = get_optimal_preset(ffmpeg)
    return {
        "cpu_name": hw.cpu_name,
        "cpu_cores": hw.cpu_cores,
        "cpu_threads": hw.cpu_threads,
        "ram_gb": hw.ram_gb,
        "has_nvidia_gpu": hw.has_nvidia_gpu,
        "nvidia_gpu_name": hw.nvidia_gpu_name,
        "has_intel_qsv": hw.has_intel_qsv,
        "has_amd_amf": hw.has_amd_amf,
        "is_thinkpad_t14": hw.is_thinkpad_t14,
        "machine_profile": hw.machine_profile,
        "selected_preset": {
            "video_codec": preset.video_codec,
            "preset_name": preset.preset_name,
            "crf": preset.crf,
            "hwaccel": preset.hwaccel,
            "description": preset.description,
        },
    }


def get_all_presets() -> dict[str, dict]:
    """Trả về tất cả presets có sẵn (cho UI chọn thủ công)."""
    return {
        name: {
            "video_codec": p.video_codec,
            "preset_name": p.preset_name,
            "crf": p.crf,
            "hwaccel": p.hwaccel,
            "description": p.description,
        }
        for name, p in _PRESETS.items()
    }
