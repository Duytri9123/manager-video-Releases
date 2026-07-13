from datetime import datetime
from typing import Union


def parse_timestamp(timestamp: Union[int, str], fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    if isinstance(timestamp, str):
        timestamp = int(timestamp)
    return datetime.fromtimestamp(timestamp).strftime(fmt)


def format_size(bytes_size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def ensure_playwright_chromium(logger_func=None):
    """
    Checks if playwright chromium is available. If not, attempts to download it.
    If downloading fails, checks if a local system browser (Chrome/Edge/Brave) is available.
    Only raises RuntimeError if neither is available.
    """
    try:
        import playwright
    except ImportError:
        raise RuntimeError("Playwright library is not installed.")
        
    import subprocess
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    
    try:
        driver_executable, driver_cli = compute_driver_executable()
        if logger_func:
            logger_func("Playwright: Checking/Installing Chromium browser...")
        proc = subprocess.run([str(driver_executable), str(driver_cli), "install", "chromium"], env=get_driver_env(), capture_output=True, text=True)
        if proc.returncode == 0:
            if logger_func:
                logger_func("Playwright Chromium is ready.")
            return
        
        # Check local browser fallback if install command failed (e.g. node.exe fails to run on client machine)
        local_browser = find_local_browser()
        if local_browser:
            if logger_func:
                logger_func(f"Playwright installation failed, but found local system browser: {local_browser}. Falling back.")
            return
        else:
            raise RuntimeError(f"Playwright installation failed and no local browser found. Error: {proc.stderr}")
    except Exception as e:
        # Check local browser fallback if exception occurred
        local_browser = find_local_browser()
        if local_browser:
            if logger_func:
                logger_func(f"Playwright installation encountered error, but found local system browser: {local_browser}. Falling back.")
            return
        else:
            raise RuntimeError(f"Failed to install Playwright Chromium and no local browser found: {e}")


def find_local_browser():
    import os
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def launch_playwright_browser_sync(chromium_object, is_persistent=True, **kwargs):
    try:
        if is_persistent:
            return chromium_object.launch_persistent_context(**kwargs)
        else:
            return chromium_object.launch(**kwargs)
    except Exception as default_err:
        local_browser = find_local_browser()
        if not local_browser:
            raise default_err
            
        kwargs["executable_path"] = local_browser
        if "channel" in kwargs:
            del kwargs["channel"]
            
        if is_persistent:
            return chromium_object.launch_persistent_context(**kwargs)
        else:
            return chromium_object.launch(**kwargs)


async def launch_playwright_browser_async(chromium_object, is_persistent=True, **kwargs):
    try:
        if is_persistent:
            return await chromium_object.launch_persistent_context(**kwargs)
        else:
            return await chromium_object.launch(**kwargs)
    except Exception as default_err:
        local_browser = find_local_browser()
        if not local_browser:
            raise default_err
            
        kwargs["executable_path"] = local_browser
        if "channel" in kwargs:
            del kwargs["channel"]
            
        if is_persistent:
            return await chromium_object.launch_persistent_context(**kwargs)
        else:
            return await chromium_object.launch(**kwargs)

