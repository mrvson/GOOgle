"""Utilities for automating Google AI Studio text-to-speech downloads.
Simple version with better error handling and profile management.
"""

from __future__ import annotations

import itertools
import os
import re
import time
import logging
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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
# Selenium automation - ĐƠN GIẢN HÓA
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    index: int
    original_path: Path
    final_path: Path

class DownloadTimeoutError(RuntimeError):
    pass

def setup_chrome_profile():
    """Tạo và thiết lập Chrome profile nếu chưa tồn tại"""
    user_data_dir = r"C:\Users\mrvso\AppData\Local\Google\Chrome\User Data"
    profile_path = Path(user_data_dir) / "SeleniumProfile"
    
    if not profile_path.exists():
        print("🆕 Tạo Chrome profile mới: SeleniumProfile")
        print("📝 LẦN ĐẦU: Bạn cần đăng nhập thủ công vào Google")
        input("Nhấn Enter sau khi đã đăng nhập xong...")

def build_driver(download_dir: Path) -> webdriver.Chrome:
    """Tạo Chrome driver với profile riêng"""
    setup_chrome_profile()
    
    opts = webdriver.ChromeOptions()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Sử dụng profile riêng
    user_data_dir = r"C:\Users\mrvso\AppData\Local\Google\Chrome\User Data"
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--profile-directory=SeleniumProfile")

    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

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

def simple_interaction_flow(driver: webdriver.Chrome, text: str) -> bool:
    """Luồng tương tác đơn giản: tìm elements và thao tác"""
    try:
        # Bước 1: Tìm và điền textarea
        print("🔍 Tìm textarea...")
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        for textarea in textareas:
            if textarea.is_displayed():
                textarea.clear()
                textarea.send_keys(text)
                print("✓ Đã điền text")
                break
        else:
            print("❌ Không tìm thấy textarea")
            return False

        time.sleep(2)

        # Bước 2: Tìm và click nút Generate
        print("🔍 Tìm nút Generate...")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        generate_clicked = False
        
        for button in buttons:
            try:
                button_text = button.text.lower()
                if "generate" in button_text and button.is_displayed() and button.is_enabled():
                    button.click()
                    print("✓ Đã click Generate")
                    generate_clicked = True
                    break
            except:
                continue
        
        if not generate_clicked:
            # Thử click bằng JavaScript
            for button in buttons:
                try:
                    button_text = button.text.lower()
                    if "generate" in button_text:
                        driver.execute_script("arguments[0].click();", button)
                        print("✓ Đã click Generate (JavaScript)")
                        generate_clicked = True
                        break
                except:
                    continue
        
        if not generate_clicked:
            print("❌ Không tìm thấy nút Generate")
            return False

        # Bước 3: Chờ audio
        print("⏳ Chờ audio generation...")
        time.sleep(15)  # Chờ cố định 15 giây
        
        # Bước 4: Tìm và click audio để download
        print("🔍 Tìm audio element...")
        audios = driver.find_elements(By.TAG_NAME, "audio")
        for audio in audios:
            try:
                audio.click()
                print("✓ Đã click audio để download")
                break
            except:
                continue
        else:
            print("⚠ Không thể click audio, tiếp tục anyway...")

        return True

    except Exception as e:
        print(f"❌ Lỗi trong luồng tương tác: {e}")
        return False

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

    # Kiểm tra file tồn tại
    for index, chunk in enumerate(chunks_list, start=1):
        target_name = filename_template.format(index=index)
        expected_file = download_path / target_name
        if expected_file.exists():
            print(f"✓ Bỏ qua chunk {index}")
            results.append(DownloadResult(index, expected_file, expected_file))
        else:
            chunks_to_process.append((index, chunk))

    if not chunks_to_process:
        print("🎉 Tất cả file đã tồn tại!")
        return results

    print(f"🔨 Cần xử lý: {len(chunks_to_process)} chunk")
    
    driver = None
    
    try:
        for index, chunk in chunks_to_process:
            try:
                if driver is None:
                    print("🚀 Khởi động Chrome...")
                    driver = build_driver(download_path)
                    print("🌐 Đang tải trang...")
                    driver.get("https://aistudio.google.com/generate-speech?model=gemini-2.5-flash-preview-tts")
                    time.sleep(5)
                    print("✓ Trang đã tải")

                print(f"\n🎯 Xử lý chunk {index}...")
                
                # Lấy file hiện có trước khi download
                existing_files = set(download_path.iterdir())
                
                # Thực hiện tương tác
                if not simple_interaction_flow(driver, chunk):
                    raise Exception("Tương tác thất bại")
                
                # Chờ download
                print("⏳ Chờ download...")
                downloaded_file = wait_for_new_file(download_path, existing_files)
                print(f"✓ Download: {downloaded_file.name}")

                # Validate file
                try:
                    AudioSegment.from_wav(downloaded_file)
                    print("✓ File hợp lệ")
                except CouldntDecodeError:
                    print("❌ File hỏng")
                    downloaded_file.unlink()
                    raise DownloadTimeoutError("File corrupt")

                # Rename
                target_name = build_target_name(filename_template, index, downloaded_file)
                final_path = rename_downloaded_file(downloaded_file, target_name)
                print(f"✓ Đổi tên: {final_path.name}")
                
                results.append(DownloadResult(index, downloaded_file, final_path))
                print(f"✅ Hoàn thành chunk {index}")

                # Delay giữa các chunk
                if delay_between_downloads > 0:
                    print(f"⏳ Chờ {delay_between_downloads}s...")
                    time.sleep(delay_between_downloads)

            except Exception as e:
                print(f"❌ Lỗi chunk {index}: {e}")
                if driver:
                    driver.quit()
                    driver = None
                print("🔄 Khởi động lại trình duyệt...")
                time.sleep(5)
                continue

    finally:
        if driver:
            driver.quit()
            print("🔚 Đã đóng trình duyệt")

    return results

def merge_audio_files(download_dir: Path, results: list[DownloadResult], total_chunks: int, final_filename: str):
    """Merge audio files"""
    print("\n🎧 Bắt đầu merge audio...")
    
    if len(results) != total_chunks:
        print(f"⚠ Không merge: {len(results)}/{total_chunks} file")
        return
    
    try:
        combined = AudioSegment.from_wav(results[0].final_path)
        for result in results[1:]:
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

    # Setup logging đơn giản
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    # Check FFmpeg
    ffmpeg_path = SCRIPT_DIR / "ffmpeg.exe"
    if not ffmpeg_path.exists():
        print("❌ Thiếu ffmpeg.exe")
        return

    AudioSegment.converter = str(ffmpeg_path)
    AudioSegment.ffprobe = str(ffmpeg_path)

    if not input_file.exists():
        print("❌ Không tìm thấy input.txt")
        return

    print("🚀 Bắt đầu automation...")
    chunks = split_text_file(input_file)
    print(f"📄 Đã chia thành {len(chunks)} chunk")

    results = automate_google_ai_simple(chunks, download_dir)
    
    print(f"\n📊 Kết quả: {len(results)}/{len(chunks)} chunk thành công")
    
    if results:
        merge_audio_files(download_dir, results, len(chunks), "output_final.wav")

if __name__ == "__main__":
    main()