"""Utilities for automating Google AI Studio text-to-speech downloads.
Simple version with better error handling and profile management.

ĐÃ CẬP NHẬT: Sửa lỗi Chrome process still running và file locked.
"""

from __future__ import annotations

import itertools
import os
import re
import time
import logging
import random
import psutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

try:
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError
except ImportError:
    print("Lỗi: Không tìm thấy thư viện 'pydub'. Vui lòng cài đặt: pip install pydub")
    exit()

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, SessionNotCreatedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# IMPORT QUAN TRỌNG CHO VIỆC "CHỜ THÔNG MINH"
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------------------------------------------------------------------------
# Text utilities (giữ nguyên)
# ---------------------------------------------------------------------------

SENTENCE_END_REGEX = re.compile(r"(?<=[.!?])\s+")

def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def split_sentence(sentence: str, max_length: int) -> Iterator[str]:
    words = sentence.split()
    chunk: list[str] = []
    for word in words:
        candidate = " ".join((*chunk, word)) if chunk else word
        if len(candidate) <= max_length:
            chunk.append(word)
            continue
        if chunk:
            yield " ".join(chunk)
            chunk = [word]
        else:
            for start in range(0, len(word), max_length):
                yield word[start : start + max_length]
            chunk = []
    if chunk:
        yield " ".join(chunk)

def smart_split(text: str, max_length: int = 999) -> list[str]:
    text = normalise_whitespace(text)
    sentences = SENTENCE_END_REGEX.split(text) if text else []
    chunks: list[str] = []
    current = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_length:
            chunks.extend(split_sentence(sentence, max_length))
            continue
        prospective = " ".join((*current, sentence)) if current else sentence
        if len(prospective) <= max_length:
            current.append(sentence)
            continue
        if current:
            chunks.append(" ".join(current))
        current = [sentence]
    if current:
        chunks.append(" ".join(current))
    return chunks

def split_text_file(input_file: os.PathLike[str] | str, max_length: int = 999) -> list[str]:
    path = Path(input_file)
    text = path.read_text(encoding="utf-8")
    return smart_split(text, max_length)

# ---------------------------------------------------------------------------
# Selenium automation - ĐÃ CẬP NHẬT
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    index: int
    original_path: Path
    final_path: Path

class DownloadTimeoutError(RuntimeError):
    pass

def kill_chrome_processes():
    """Kill tất cả Chrome processes đang chạy"""
    try:
        killed_any = False
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and any(name in proc.info['name'].lower() for name in ['chrome', 'chromedriver']):
                    proc.kill()
                    killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if killed_any:
            time.sleep(3)  # Chờ lâu hơn để processes thực sự đóng
            print("✓ Đã kill Chrome processes")
        else:
            print("ℹ Không có Chrome process nào đang chạy")
    except Exception as e:
        print(f"⚠ Không thể kill Chrome processes: {e}")

def unlock_profile_directory(profile_path: Path):
    """Xóa các file lock trong profile directory"""
    try:
        # Xóa các file lock thường gặp
        lock_files = [
            profile_path / "SingletonLock",
            profile_path / "lockfile", 
            profile_path / "Default" / "lockfile",
        ]
        
        for lock_file in lock_files:
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    print(f"✓ Đã xóa {lock_file.name}")
                except Exception as e:
                    print(f"⚠ Không thể xóa {lock_file.name}: {e}")
    except Exception as e:
        print(f"⚠ Lỗi khi unlock profile: {e}")

def setup_chrome_profile() -> Path:
    """Tạo và thiết lập Chrome profile BIỆT LẬP trong thư mục script"""
    script_dir = Path(__file__).resolve().parent
    profile_path = script_dir / "SeleniumProfileData"
    
    if not profile_path.exists():
        profile_path.mkdir(parents=True, exist_ok=True)
        print(f"🆕 Tạo Chrome profile mới tại: {profile_path}")
        print("🔐 LẦN ĐẦU CHẠY: Script sẽ dừng lại để bạn đăng nhập Google.")
        print("‼️ QUAN TRỌNG: Nhân lúc này, hãy CHỌN VOICE VÀ MODE bạn muốn.")
        print("Cửa sổ Chrome sẽ tự động mở ra. Vui lòng đăng nhập VÀ CÀI ĐẶT VOICE.")
        
        # Kill Chrome processes trước khi bắt đầu
        kill_chrome_processes()
        
        opts = webdriver.ChromeOptions()
        opts.add_argument(f"--user-data-dir={str(profile_path)}")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option('useAutomationExtension', False)
        
        try:
            driver = webdriver.Chrome(options=opts)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            driver.get("https://aistudio.google.com/")
            
            input("Nhấn Enter sau khi bạn đã đăng nhập VÀ CHỌN VOICE xong...")
            driver.quit()
            print("✓ Đã lưu thông tin đăng nhập và cài đặt.")
        except SessionNotCreatedException:
            print("❌ Lỗi: Profile đang được sử dụng. Đang thử tạo profile mới...")
            # Kill Chrome processes và thử lại
            kill_chrome_processes()
            time.sleep(3)
            
            # Thử tạo profile với tên ngẫu nhiên
            profile_path = script_dir / f"SeleniumProfileData_{random.randint(1000,9999)}"
            profile_path.mkdir(parents=True, exist_ok=True)
            print(f"🆕 Tạo Chrome profile mới tại: {profile_path}")
            
            opts = webdriver.ChromeOptions()
            opts.add_argument(f"--user-data-dir={str(profile_path)}")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            
            driver = webdriver.Chrome(options=opts)
            driver.get("https://aistudio.google.com/")
            
            input("Nhấn Enter sau khi bạn đã đăng nhập VÀ CHỌN VOICE xong...")
            driver.quit()
            print("✓ Đã lưu thông tin đăng nhập và cài đặt.")
        
    return profile_path

def build_driver(download_dir: Path) -> webdriver.Chrome:
    """Tạo Chrome driver với profile riêng"""
    
    profile_path = setup_chrome_profile()
    
    # Kill Chrome processes trước khi tạo driver mới
    kill_chrome_processes()
    time.sleep(3)
    
    # Unlock profile directory
    unlock_profile_directory(profile_path)
    
    opts = webdriver.ChromeOptions()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"--user-data-dir={str(profile_path)}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)

    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)
    
    try:
        driver = webdriver.Chrome(options=opts)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except SessionNotCreatedException as e:
        print(f"❌ Lỗi khi khởi động Chrome: {e}")
        print("🔄 Đang thử khởi động lại với profile mới...")
        # Kill Chrome processes và xóa profile cũ
        kill_chrome_processes()
        time.sleep(3)
        
        import shutil
        if profile_path.exists():
            try:
                shutil.rmtree(profile_path)
                print("✓ Đã xóa profile cũ")
            except Exception as ex:
                print(f"⚠ Không thể xóa profile: {ex}")
        time.sleep(2)
        return build_driver(download_dir)  # Đệ quy thử lại

def wait_for_new_file(download_dir: Path, existing: set[Path], timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        for f in download_dir.iterdir():
            if f not in existing and f.is_file() and not f.name.endswith(".crdownload"):
                return f
        time.sleep(1)
    raise TimeoutException("Timeout waiting for download")

def build_target_name(template: str, index: int, original_path: Path) -> str:
    candidate = template.format(index=index)
    candidate_path = Path(candidate)
    if candidate_path.suffix:
        return candidate_path.name
    return f"{candidate_path.name}{original_path.suffix}"

def rename_downloaded_file(src: Path, target_name: str) -> Path:
    destination = src.with_name(target_name)
    counter = itertools.count(1)
    final_destination = destination
    while final_destination.exists():
        suffix = final_destination.suffix
        final_destination = destination.with_name(f"{destination.stem}_{next(counter)}{suffix}")
    return src.rename(final_destination)

def simple_interaction_flow(driver: webdriver.Chrome, text: str, download_dir: Path) -> Path | None:
    """
    Luồng tương tác tối ưu - hỗ trợ cả data URL và blob URL
    Xóa audio cũ TRƯỚC để tránh download nhầm
    """
    try:
        wait = WebDriverWait(driver, 30)
        long_wait = WebDriverWait(driver, 120)
        
        # === BƯỚC 1: LƯU SRC CŨ ĐỂ SO SÁNH ===
        print("📝 Lưu src audio cũ (nếu có)...")
        old_audio_src = None
        try:
            old_audios = driver.find_elements(By.TAG_NAME, "audio")
            if old_audios:
                print(f"   Tìm thấy {len(old_audios)} audio cũ")
                for old_audio in old_audios:
                    try:
                        src = old_audio.get_attribute("src")
                        if src:
                            old_audio_src = src
                            # Lưu hash của base64 để so sánh nhanh hơn
                            if src.startswith("data:audio"):
                                # Lấy 100 ký tự đầu của base64 làm fingerprint
                                import re
                                match = re.search(r'base64,(.{100})', src)
                                if match:
                                    old_fingerprint = match.group(1)
                                    print(f"   Fingerprint cũ: {old_fingerprint[:50]}...")
                            print(f"   Src cũ length: {len(src)} chars")
                            break
                    except:
                        pass
                print("   ✓ Đã lưu src cũ")
            else:
                print("   Không có audio cũ")
        except Exception as e:
            print(f"   ⚠ Không thể lưu src cũ: {e}")
            old_audio_src = None

        # === BƯỚC 2: ĐIỀN TEXT ===
        print("🔍 Tìm ô nhập text...")
        text_input_xpath = "//h4[contains(@class, 'section-title') and contains(text(), 'Text')]/following::textarea[1]"
        try:
            text_input = wait.until(
                EC.visibility_of_element_located((By.XPATH, text_input_xpath))
            )
        except TimeoutException:
            print("❌ Không tìm thấy ô Text")
            return None
        
        text_input.clear()
        text_input.send_keys(text)
        print("✓ Đã điền text chunk")

        # === BƯỚC 3: NHẤN CTRL+ENTER ĐỂ GENERATE ===
        print("⚡ Nhấn Ctrl+Enter để generate...")
        text_input.send_keys(Keys.CONTROL + Keys.ENTER)
        print("✓ Đã nhấn Ctrl+Enter")

        # === BƯỚC 4: TÌM AUDIO ELEMENT MỚI (KHÁC SRC CŨ) ===
        print("⏳ Chờ audio MỚI generation...")
        
        audio_element = None
        found_new_audio = False
        
        # Thử tìm trong 120 giây
        max_attempts = 600  # 120s / 0.2s
        for attempt in range(max_attempts):
            try:
                # Tìm tất cả audio elements
                all_audios = driver.find_elements(By.TAG_NAME, "audio")
                
                if all_audios:
                    for audio in all_audios:
                        try:
                            current_src = audio.get_attribute("src")
                            
                            # Bỏ qua nếu chưa có src
                            if not current_src:
                                continue
                            
                            # Kiểm tra khác với src cũ
                            if old_audio_src:
                                # So sánh độ dài trước (nhanh)
                                if len(current_src) == len(old_audio_src):
                                    # Cùng độ dài, kiểm tra fingerprint
                                    if current_src.startswith("data:audio"):
                                        import re
                                        match = re.search(r'base64,(.{100})', current_src)
                                        if match:
                                            current_fingerprint = match.group(1)
                                            if 'old_fingerprint' in locals() and current_fingerprint == old_fingerprint:
                                                continue  # Trùng fingerprint, bỏ qua
                                    elif current_src == old_audio_src:
                                        continue  # Trùng hoàn toàn, bỏ qua
                            
                            # Đây là audio MỚI!
                            audio_element = audio
                            found_new_audio = True
                            print(f"✓ Tìm thấy audio MỚI sau {attempt * 0.2:.1f}s")
                            print(f"   Src mới length: {len(current_src)} chars")
                            break
                            
                        except:
                            continue
                
                if found_new_audio:
                    break
                
                # Log mỗi 5 giây
                if attempt > 0 and attempt % 25 == 0:
                    print(f"   ... đang chờ audio mới ({attempt * 0.2:.0f}s)")
                
                time.sleep(0.2)
                
            except Exception as e:
                pass
        
        if not audio_element or not found_new_audio:
            print("❌ KHÔNG TÌM THẤY audio MỚI sau 120s")
            return None
        
        print("✓ Audio element MỚI đã xuất hiện")
        
        # DEBUG: In ra thông tin
        try:
            print("\n📋 DEBUG - Thông tin audio MỚI:")
            current_src = audio_element.get_attribute('src')
            print(f"   Src mới length: {len(current_src)} chars")
            if old_audio_src:
                print(f"   Src cũ length: {len(old_audio_src)} chars")
                print(f"   Khác biệt: {abs(len(current_src) - len(old_audio_src))} chars")
            print()
        except Exception as e:
            print(f"   Không lấy được debug info: {e}")
        
        # === BƯỚC 5: CHỜ AUDIO SRC SẴN SÀNG ===
        print("⏳ Chờ audio sẵn sàng...")
        max_wait = 90
        start_time = time.time()
        audio_src = audio_element.get_attribute("src")
        
        poll_interval = 0.2
        last_log_time = start_time
        
        # Nếu là data URL thì đã sẵn sàng luôn
        if audio_src and audio_src.startswith("data:audio"):
            print(f"✓ Data URL đã sẵn sàng!")
        # Nếu là blob URL thì chờ ready
        elif audio_src and audio_src.startswith("blob:"):
            while time.time() - start_time < max_wait:
                try:
                    ready_state = driver.execute_script("return arguments[0].readyState;", audio_element)
                    duration = driver.execute_script("return arguments[0].duration;", audio_element)
                    
                    current_time = time.time()
                    if current_time - last_log_time >= 5:
                        print(f"   ... đang chờ ({int(current_time - start_time)}s)")
                        last_log_time = current_time
                    
                    if ready_state >= 2 and duration > 0 and not (duration == float('inf') or duration != duration):
                        print(f"✓ Audio sẵn sàng (blob URL, duration: {duration:.2f}s)")
                        break
                    elif ready_state >= 1:
                        print(f"   Audio đang load... (readyState: {ready_state})")
                    
                except Exception as e:
                    pass
                
                time.sleep(poll_interval)
        else:
            print("❌ Không tìm thấy URL audio hợp lệ.")
            return None
        
        print(f"✓ Đã lấy audio URL (type: {'data URL' if audio_src.startswith('data:') else 'blob URL'})")
        
        # === BƯỚC 6: DOWNLOAD AUDIO ===
        import uuid
        import base64
        import re

        temp_filename = f"temp_{uuid.uuid4().hex}.wav"
        temp_path = download_dir / temp_filename
        
        # XỬ LÝ DATA URL (BASE64) - NHANH
        if audio_src.startswith("data:audio"):
            print("⏳ Decode base64 từ data URL...")
            try:
                base64_match = re.search(r'base64,(.+)', audio_src)
                if base64_match:
                    base64_str = base64_match.group(1)
                    audio_data = base64.b64decode(base64_str)
                    temp_path.write_bytes(audio_data)
                    print(f"✓ Decode thành công: {temp_path.name} ({len(audio_data)} bytes)")
                    return temp_path
                else:
                    print("❌ Không tìm thấy base64 data trong src")
                    return None
            except Exception as e:
                print(f"❌ Lỗi khi decode base64: {e}")
                return None
        
        # XỬ LÝ BLOB URL - CẦN DOWNLOAD
        if audio_src.startswith("blob:"):
            print("⏳ Đang download audio từ blob URL...")
            
            download_script = """
            var url = arguments[0];
            var callback = arguments[1];
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.responseType = 'blob';
            xhr.timeout = 60000;
            
            xhr.onload = function() {
                if (this.status === 200) {
                    var reader = new FileReader();
                    reader.onloadend = function() {
                        callback({success: true, data: reader.result});
                    }
                    reader.onerror = function() {
                        callback({success: false, error: 'FileReader error'});
                    }
                    reader.readAsDataURL(xhr.response);
                } else {
                    callback({success: false, error: 'HTTP ' + this.status});
                }
            };
            
            xhr.onerror = function() {
                callback({success: false, error: 'Network error'});
            };
            
            xhr.ontimeout = function() {
                callback({success: false, error: 'Timeout'});
            };
            
            xhr.send();
            """
            
            max_download_retries = 3
            for retry in range(max_download_retries):
                try:
                    if retry > 0:
                        print(f"🔄 Thử lại lần {retry + 1}...")
                    
                    result = driver.execute_async_script(download_script, audio_src)
                    
                    if not result or not result.get('success'):
                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                        print(f"⚠ Lỗi download: {error_msg}")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            print("❌ Đã thử tối đa số lần cho phép")
                            return None
                    
                    base64_data = result.get('data')
                    if not base64_data:
                        print("⚠ Không có dữ liệu")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return None
                    
                    base64_match = re.search(r'base64,(.+)', base64_data)
                    if base64_match:
                        audio_data = base64.b64decode(base64_match.group(1))
                        temp_path.write_bytes(audio_data)
                        print(f"✓ Download thành công: {temp_path.name} ({len(audio_data)} bytes)")
                        return temp_path
                    else:
                        print("❌ Không thể decode base64 data")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return None
                        
                except Exception as e:
                    print(f"⚠ Exception khi download (lần {retry + 1}): {e}")
                    if retry < max_download_retries - 1:
                        time.sleep(2)
                        continue
                    else:
                        print("❌ Lỗi khi download sau nhiều lần thử")
                        return None
            
            return None
        
        # URL không hợp lệ
        print(f"❌ URL không hợp lệ: {audio_src[:100]}")
        return None

    except TimeoutException as e:
        print(f"❌ Hết thời gian chờ: {e}")
        return None
    except Exception as e:
        print(f"❌ Lỗi trong luồng tương tác: {e}")
        import traceback
        traceback.print_exc()
        return None
    """
    Luồng tương tác tối ưu - hỗ trợ cả data URL và blob URL
    Xóa audio cũ TRƯỚC để tránh download nhầm
    """
    try:
        wait = WebDriverWait(driver, 30)
        long_wait = WebDriverWait(driver, 120)
        
        # === BƯỚC 1: XÓA AUDIO CŨ TRƯỚC (NẾU CÓ) ===
        print("🗑️ Xóa audio cũ trước khi bắt đầu...")
        old_audio_src = None
        try:
            old_audios = driver.find_elements(By.TAG_NAME, "audio")
            if old_audios:
                print(f"   Tìm thấy {len(old_audios)} audio cũ")
                for old_audio in old_audios:
                    try:
                        old_audio_src = old_audio.get_attribute("src")
                        if old_audio_src:
                            print(f"   Lưu src cũ để tránh: {old_audio_src[:80]}...")
                            break  # Chỉ cần lưu 1 src cũ
                    except:
                        pass
                
                # Xóa tất cả audio cũ bằng JavaScript
                driver.execute_script("""
                    var audios = document.querySelectorAll('audio');
                    audios.forEach(function(audio) {
                        audio.remove();
                    });
                """)
                print("   ✓ Đã xóa audio cũ")
                time.sleep(0.5)
            else:
                print("   Không có audio cũ")
        except Exception as e:
            print(f"   ⚠ Không thể xóa audio cũ: {e}")
            old_audio_src = None

        # === BƯỚC 2: ĐIỀN TEXT ===
        print("🔍 Tìm ô nhập text...")
        text_input_xpath = "//h4[contains(@class, 'section-title') and contains(text(), 'Text')]/following::textarea[1]"
        try:
            text_input = wait.until(
                EC.visibility_of_element_located((By.XPATH, text_input_xpath))
            )
        except TimeoutException:
            print("❌ Không tìm thấy ô Text")
            return None
        
        text_input.clear()
        text_input.send_keys(text)
        print("✓ Đã điền text chunk")

        # === BƯỚC 3: NHẤN CTRL+ENTER ĐỂ GENERATE ===
        print("⚡ Nhấn Ctrl+Enter để generate...")
        text_input.send_keys(Keys.CONTROL + Keys.ENTER)
        print("✓ Đã nhấn Ctrl+Enter")

        # === BƯỚC 4: TÌM AUDIO ELEMENT MỚI ===
        print("⏳ Chờ audio generation...")
        
        audio_element = None
        
        # Thử nhiều cách tìm khác nhau
        selectors_to_try = [
            ("tag_name", "audio", "Tìm bằng tag name"),
            ("xpath", "//audio", "Tìm bằng XPath đơn giản"),
            ("css", "audio", "Tìm bằng CSS selector"),
            ("xpath", "//audio[@controls]", "Tìm audio có controls"),
            ("xpath", "//audio[@src]", "Tìm audio có src"),
        ]
        
        print("🔍 Thử tìm audio element...")
        for selector_type, selector_value, description in selectors_to_try:
            try:
                print(f"   Thử: {description}...")
                
                if selector_type == "tag_name":
                    audio_element = long_wait.until(
                        EC.presence_of_element_located((By.TAG_NAME, selector_value))
                    )
                elif selector_type == "xpath":
                    audio_element = long_wait.until(
                        EC.presence_of_element_located((By.XPATH, selector_value))
                    )
                elif selector_type == "css":
                    audio_element = long_wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector_value))
                    )
                
                if audio_element:
                    print(f"✓ Tìm thấy bằng: {description}")
                    break
                    
            except TimeoutException:
                print(f"   ✗ Không tìm thấy bằng: {description}")
                continue
            except Exception as e:
                print(f"   ✗ Lỗi với {description}: {e}")
                continue
        
        if not audio_element:
            print("❌ KHÔNG TÌM THẤY audio element bằng BẤT KỲ cách nào")
            print("🔍 Debug: Đang tìm tất cả audio elements trong page...")
            try:
                all_audios = driver.find_elements(By.TAG_NAME, "audio")
                print(f"   Tổng số audio elements: {len(all_audios)}")
                for idx, audio in enumerate(all_audios):
                    try:
                        outer_html = audio.get_attribute("outerHTML")[:200]
                        print(f"   Audio {idx + 1}: {outer_html}...")
                    except:
                        print(f"   Audio {idx + 1}: (không lấy được HTML)")
                
                # Thử dùng JavaScript để tìm
                print("\n🔧 Thử tìm bằng JavaScript...")
                js_find_audio = """
                var audios = document.querySelectorAll('audio');
                if (audios.length > 0) {
                    return audios[0];
                }
                return null;
                """
                audio_element = driver.execute_script(js_find_audio)
                
                if audio_element:
                    print("✓ Tìm thấy audio bằng JavaScript!")
                else:
                    print("❌ JavaScript cũng không tìm thấy audio")
                    return None
                    
            except Exception as e:
                print(f"   Lỗi debug: {e}")
                return None
        
        print("✓ Audio element đã xuất hiện")
        
        # DEBUG: In ra thông tin về audio element
        try:
            print("\n📋 DEBUG - Thông tin audio element:")
            outer_html = audio_element.get_attribute("outerHTML")
            print(f"   HTML: {outer_html[:300]}...")
            current_src = audio_element.get_attribute('src')
            print(f"   Src ban đầu: {current_src[:100] if current_src else 'None'}...")
            
            # KIỂM TRA TRÙNG VỚI AUDIO CŨ
            if old_audio_src and current_src and current_src == old_audio_src:
                print("   ⚠️ CẢNH BÁO: Đây là audio CŨ! Chờ audio mới...")
                # Chờ audio mới xuất hiện
                for wait_attempt in range(30):  # Chờ tối đa 30 giây
                    time.sleep(1)
                    try:
                        new_audios = driver.find_elements(By.TAG_NAME, "audio")
                        for new_audio in new_audios:
                            new_src = new_audio.get_attribute("src")
                            if new_src and new_src != old_audio_src:
                                print(f"   ✓ Tìm thấy audio MỚI sau {wait_attempt + 1}s")
                                audio_element = new_audio
                                current_src = new_src
                                break
                        if current_src != old_audio_src:
                            break
                    except:
                        pass
                
                if current_src == old_audio_src:
                    print("   ❌ Không tìm thấy audio mới sau 30s")
                    return None
            else:
                print("   ✓ Đây là audio MỚI")
            
            print()
        except Exception as e:
            print(f"   Không lấy được debug info: {e}")
        
        # === BƯỚC 5: CHỜ AUDIO SRC SẴN SÀNG ===
        print("⏳ Chờ audio sẵn sàng...")
        max_wait = 90
        start_time = time.time()
        audio_src = None
        
        poll_interval = 0.2
        last_log_time = start_time
        
        while time.time() - start_time < max_wait:
            try:
                audio_src = audio_element.get_attribute("src")
                
                # KIỂM TRA KHÔNG PHẢI AUDIO CŨ
                if audio_src and old_audio_src and audio_src == old_audio_src:
                    print(f"   ⚠️ Bỏ qua audio cũ, tiếp tục chờ...")
                    time.sleep(poll_interval)
                    # Tìm audio mới
                    try:
                        new_audios = driver.find_elements(By.TAG_NAME, "audio")
                        for new_audio in new_audios:
                            new_src = new_audio.get_attribute("src")
                            if new_src and new_src != old_audio_src:
                                audio_element = new_audio
                                audio_src = new_src
                                print(f"   ✓ Chuyển sang audio mới")
                                break
                    except:
                        pass
                    continue
                
                current_time = time.time()
                if current_time - last_log_time >= 5:
                    print(f"   ... đang chờ ({int(current_time - start_time)}s)")
                    last_log_time = current_time
                
                if audio_src:
                    # Data URL (base64)
                    if audio_src.startswith("data:audio"):
                        print(f"✓ Tìm thấy data URL (base64) - size: {len(audio_src)} chars")
                        break
                    # Blob URL
                    elif audio_src.startswith("blob:"):
                        ready_state = driver.execute_script("return arguments[0].readyState;", audio_element)
                        duration = driver.execute_script("return arguments[0].duration;", audio_element)
                        
                        if ready_state >= 2 and duration > 0 and not (duration == float('inf') or duration != duration):
                            print(f"✓ Audio sẵn sàng (blob URL, duration: {duration:.2f}s)")
                            break
                        elif ready_state >= 1:
                            print(f"   Audio đang load... (readyState: {ready_state})")
                
            except Exception as e:
                try:
                    audio_element = driver.find_element(By.TAG_NAME, "audio")
                except:
                    pass
            
            time.sleep(poll_interval)
        
        if not audio_src:
            print("❌ Không tìm thấy URL audio.")
            return None
        
        print(f"✓ Đã lấy audio URL (type: {'data URL' if audio_src.startswith('data:') else 'blob URL'})")
        
        # === BƯỚC 6: DOWNLOAD AUDIO ===
        import uuid
        import base64
        import re

        temp_filename = f"temp_{uuid.uuid4().hex}.wav"
        temp_path = download_dir / temp_filename
        
        # XỬ LÝ DATA URL (BASE64) - NHANH
        if audio_src.startswith("data:audio"):
            print("⏳ Decode base64 từ data URL...")
            try:
                base64_match = re.search(r'base64,(.+)', audio_src)
                if base64_match:
                    base64_str = base64_match.group(1)
                    audio_data = base64.b64decode(base64_str)
                    temp_path.write_bytes(audio_data)
                    print(f"✓ Decode thành công: {temp_path.name} ({len(audio_data)} bytes)")
                    return temp_path
                else:
                    print("❌ Không tìm thấy base64 data trong src")
                    return None
            except Exception as e:
                print(f"❌ Lỗi khi decode base64: {e}")
                return None
        
        # XỬ LÝ BLOB URL - CẦN DOWNLOAD
        if audio_src.startswith("blob:"):
            print("⏳ Đang download audio từ blob URL...")
            
            download_script = """
            var url = arguments[0];
            var callback = arguments[1];
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.responseType = 'blob';
            xhr.timeout = 60000;
            
            xhr.onload = function() {
                if (this.status === 200) {
                    var reader = new FileReader();
                    reader.onloadend = function() {
                        callback({success: true, data: reader.result});
                    }
                    reader.onerror = function() {
                        callback({success: false, error: 'FileReader error'});
                    }
                    reader.readAsDataURL(xhr.response);
                } else {
                    callback({success: false, error: 'HTTP ' + this.status});
                }
            };
            
            xhr.onerror = function() {
                callback({success: false, error: 'Network error'});
            };
            
            xhr.ontimeout = function() {
                callback({success: false, error: 'Timeout'});
            };
            
            xhr.send();
            """
            
            max_download_retries = 3
            for retry in range(max_download_retries):
                try:
                    if retry > 0:
                        print(f"🔄 Thử lại lần {retry + 1}...")
                    
                    result = driver.execute_async_script(download_script, audio_src)
                    
                    if not result or not result.get('success'):
                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                        print(f"⚠ Lỗi download: {error_msg}")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            print("❌ Đã thử tối đa số lần cho phép")
                            return None
                    
                    base64_data = result.get('data')
                    if not base64_data:
                        print("⚠ Không có dữ liệu")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return None
                    
                    base64_match = re.search(r'base64,(.+)', base64_data)
                    if base64_match:
                        audio_data = base64.b64decode(base64_match.group(1))
                        temp_path.write_bytes(audio_data)
                        print(f"✓ Download thành công: {temp_path.name} ({len(audio_data)} bytes)")
                        return temp_path
                    else:
                        print("❌ Không thể decode base64 data")
                        if retry < max_download_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return None
                        
                except Exception as e:
                    print(f"⚠ Exception khi download (lần {retry + 1}): {e}")
                    if retry < max_download_retries - 1:
                        time.sleep(2)
                        continue
                    else:
                        print("❌ Lỗi khi download sau nhiều lần thử")
                        return None
            
            return None
        
        # URL không hợp lệ
        print(f"❌ URL không hợp lệ: {audio_src[:100]}")
        return None

    except TimeoutException as e:
        print(f"❌ Hết thời gian chờ: {e}")
        return None
    except Exception as e:
        print(f"❌ Lỗi trong luồng tương tác: {e}")
        import traceback
        traceback.print_exc()
        return None
def automate_google_ai_simple(
    text_chunks: Iterable[str],
    download_dir: os.PathLike[str] | str,
    filename_template: str = "audio_chunk_{index:02d}.wav",
    delay_between_downloads: float = 10.0,
) -> list[DownloadResult]:
    """Phiên bản đơn giản - dễ debug"""

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    
    chunks_list = list(text_chunks)
    results: list[DownloadResult] = []
    chunks_to_process: list[tuple[int, str]] = []
    
    print(f"📦 Tổng chunk: {len(chunks_list)}")

    for index, chunk in enumerate(chunks_list, start=1):
        target_name = filename_template.format(index=index)
        expected_file = download_path / target_name
        if expected_file.exists():
            print(f"✓ Bỏ qua chunk {index}")
        else:
            chunks_to_process.append((index, chunk))

    if not chunks_to_process:
        print("🎉 Tất cả file đã tồn tại!")
        all_results = []
        for i in range(1, len(chunks_list) + 1):
             target_name = filename_template.format(index=i)
             expected_file = download_path / target_name
             if expected_file.exists():
                all_results.append(DownloadResult(i, expected_file, expected_file))
        return all_results

    print(f"🔨 Cần xử lý: {len(chunks_to_process)} chunk")
    
    driver = None
    retry_count = 0
    max_retries = 3
    
    try:
        for index, chunk in chunks_to_process:
            try:
                if driver is None:
                    print("🚀 Khởi động Chrome...")
                    driver = build_driver(download_path)
                    print("🌐 Đang tải trang Google AI Studio...")
                    driver.get("https://aistudio.google.com/")
                    print("⏳ Chờ 20 giây để trang load và đăng nhập...")
                    time.sleep(20)  # Chờ trang load và đăng nhập
                    print("✓ Đã tải trang thành công")
                    retry_count = 0  # Reset retry count khi khởi động thành công

                print(f"\n🎯 Xử lý chunk {index}...")
                
                existing_files = set(download_path.iterdir())
                
                result = simple_interaction_flow(driver, chunk, download_path)
                
                if not result:
                    print("🔄 Tương tác thất bại, thử tải lại trang...")
                    driver.refresh()
                    time.sleep(3)
                    existing_files = set(download_path.iterdir())
                    result = simple_interaction_flow(driver, chunk, download_path)
                    if not result:
                        raise Exception("Tương tác thất bại lần 2")

                print("⏳ Chờ file download...")
                downloaded_file = wait_for_new_file(download_path, existing_files)
                print(f"✓ Download: {downloaded_file.name}")

                try:
                    AudioSegment.from_wav(downloaded_file)
                    print("✓ File hợp lệ")
                except CouldntDecodeError:
                    print("❌ File hỏng")
                    downloaded_file.unlink()
                    raise DownloadTimeoutError("File corrupt")

                target_name = build_target_name(filename_template, index, downloaded_file)
                final_path = rename_downloaded_file(downloaded_file, target_name)
                print(f"✓ Đổi tên: {final_path.name}")
                
                results.append(DownloadResult(index, downloaded_file, final_path))
                print(f"✅ Hoàn thành chunk {index}")

                if delay_between_downloads > 0:
                    print(f"⏳ Chờ {delay_between_downloads}s...")
                    time.sleep(delay_between_downloads)

                retry_count = 0  # Reset retry count khi thành công

            except SessionNotCreatedException as e:
                print(f"❌ Lỗi session Chrome: {e}")
                retry_count += 1
                if retry_count >= max_retries:
                    print("❌ Đã thử quá số lần cho phép, dừng lại...")
                    break
                    
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                    
                # Kill Chrome processes trước khi thử lại
                kill_chrome_processes()
                time.sleep(3)
                
                print(f"🔄 Khởi động lại trình duyệt (lần {retry_count})...")
                continue
                
            except Exception as e:
                print(f"❌ Lỗi chunk {index}: {e}")
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                    
                # Kill Chrome processes trước khi thử lại
                kill_chrome_processes()
                time.sleep(3)
                
                print("🔄 Khởi động lại trình duyệt...")
                continue

    finally:
        if driver:
            try:
                driver.quit()
                print("🔚 Đã đóng trình duyệt")
            except:
                pass
        # Kill Chrome processes khi kết thúc
        kill_chrome_processes()

    all_results = []
    for i in range(1, len(chunks_list) + 1):
        target_name = filename_template.format(index=i)
        expected_file = download_path / target_name
        if expected_file.exists():
            all_results.append(DownloadResult(i, expected_file, expected_file))
        else:
            print(f"⚠ Thiếu file chunk {i} để merge")

    return all_results

def merge_audio_files(download_dir: Path, results: list[DownloadResult], total_chunks: int, final_filename: str):
    """Merge audio files"""
    print("\n🎧 Bắt đầu merge audio...")
    
    results.sort(key=lambda r: r.index)
    
    if len(results) != total_chunks:
        print(f"⚠ Không merge: Chỉ có {len(results)}/{total_chunks} file hoàn chỉnh.")
        return
    
    try:
        combined = AudioSegment.empty()
        for result in results:
            segment = AudioSegment.from_wav(result.final_path)
            combined += segment

        output_path = download_dir / final_filename
        combined.export(output_path, format="wav")
        print(f"✅ Merge thành công: {output_path}")
    except Exception as e:
        print(f"❌ Lỗi merge: {e}")

def main():
    SCRIPT_DIR = Path(__file__).resolve().parent
    input_file = SCRIPT_DIR / "input.txt"
    download_dir = SCRIPT_DIR / "downloads"
    filename_template = "audio_chunk_{index:04d}.wav"
    final_filename = "output_final.wav"

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    ffmpeg_path = SCRIPT_DIR / "ffmpeg.exe"
    if not ffmpeg_path.exists():
        print("❌ Thiếu ffmpeg.exe trong cùng thư mục với script.")
        input("Nhấn Enter để thoát...")
        return

    AudioSegment.converter = str(ffmpeg_path.resolve())
    AudioSegment.ffprobe = str(ffmpeg_path.resolve())

    if not input_file.exists():
        print(f"❌ Không tìm thấy file 'input.txt' trong thư mục: {SCRIPT_DIR}")
        input("Nhấn Enter để thoát...")
        return

    print("🚀 Bắt đầu automation...")
    chunks = split_text_file(input_file)
    print(f"📄 Đã chia thành {len(chunks)} chunk")

    results = automate_google_ai_simple(
        chunks, 
        download_dir, 
        filename_template=filename_template
    )
    
    print(f"\n📊 Kết quả: {len(results)}/{len(chunks)} chunk có trong thư mục 'downloads'")
    
    if results:
        merge_audio_files(download_dir, results, len(chunks), final_filename)
    
    print("\n🎉 Hoàn tất!")
    input("Nhấn Enter để thoát...")


if __name__ == "__main__":
    main()
