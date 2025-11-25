import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk, ImageGrab, ImageChops
import pyautogui
import pyperclip
import time
import json
import os
import threading
import webbrowser
import pandas as pd
import zipfile
import shutil
from datetime import datetime
import requests
import base64

# ==========================================
# 1. 엔진
# ==========================================

def robust_hotkey(key1, key2):
    """Ctrl+A / C / V가 씹히지 않게 여유를 두고 입력"""
    pyautogui.keyDown(key1)
    time.sleep(0.2)
    pyautogui.press(key2)
    time.sleep(0.2)
    pyautogui.keyUp(key1)
    time.sleep(0.2)


# ==========================================
# 웹 게시판 API (거래 시스템)
# ==========================================

class MarketplaceAPI:
    """웹 게시판 거래 시스템 API"""
    
    def __init__(self, base_url="http://localhost:8000/api"):
        self.base_url = base_url
        self.user_id = None
        self.user_token = None
        self.points = 0
        self._load_user_info()
    
    def _load_user_info(self):
        """사용자 정보 로드"""
        try:
            if os.path.exists("user_info.json"):
                with open("user_info.json", "r", encoding="utf-8") as f:
                    info = json.load(f)
                    self.user_id = info.get("user_id")
                    self.user_token = info.get("token")
                    self.points = info.get("points", 0)
        except Exception:
            pass
    
    def _save_user_info(self):
        """사용자 정보 저장"""
        try:
            info = {
                "user_id": self.user_id,
                "token": self.user_token,
                "points": self.points
            }
            with open("user_info.json", "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def login(self, user_id, password):
        """로그인"""
        try:
            response = requests.post(
                f"{self.base_url}/login",
                json={"user_id": user_id, "password": password},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                self.user_id = user_id
                self.user_token = data.get("token")
                self.points = data.get("points", 0)
                self._save_user_info()
                return True, "로그인 성공"
            else:
                return False, response.json().get("error", "로그인 실패")
        except requests.exceptions.RequestException as e:
            return False, f"서버 연결 실패: {e}"
    
    def get_points(self):
        """포인트 조회"""
        if not self.user_token:
            return 0
        try:
            response = requests.get(
                f"{self.base_url}/points",
                headers={"Authorization": f"Bearer {self.user_token}"},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                self.points = data.get("points", 0)
                self._save_user_info()
                return self.points
        except Exception:
            pass
        return self.points
    
    def list_items(self, item_type="macro"):
        """아이템 목록 조회 (macro 또는 job)"""
        try:
            response = requests.get(
                f"{self.base_url}/items",
                params={"type": item_type},
                timeout=10
            )
            if response.status_code == 200:
                return True, response.json().get("items", [])
            else:
                return False, response.json().get("error", "목록 조회 실패")
        except requests.exceptions.RequestException as e:
            return False, f"서버 연결 실패: {e}"
    
    def upload_item(self, item_type, name, zip_path, metadata):
        """아이템 업로드 (판매하기)"""
        if not self.user_token:
            return False, "로그인이 필요합니다"
        
        try:
            # ZIP 파일 읽기
            with open(zip_path, "rb") as f:
                zip_data = f.read()
            
            # base64 인코딩
            zip_base64 = base64.b64encode(zip_data).decode("utf-8")
            
            # 업로드
            response = requests.post(
                f"{self.base_url}/upload",
                json={
                    "type": item_type,
                    "name": name,
                    "zip_data": zip_base64,
                    "metadata": metadata
                },
                headers={"Authorization": f"Bearer {self.user_token}"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                self.points = data.get("points", self.points)
                self._save_user_info()
                return True, "업로드 성공"
            else:
                return False, response.json().get("error", "업로드 실패")
        except requests.exceptions.RequestException as e:
            return False, f"서버 연결 실패: {e}"
        except Exception as e:
            return False, f"업로드 중 오류: {e}"
    
    def download_item(self, item_id):
        """아이템 다운로드 (구매하기)"""
        if not self.user_token:
            return False, None, "로그인이 필요합니다"
        
        try:
            response = requests.post(
                f"{self.base_url}/download",
                json={"item_id": item_id},
                headers={"Authorization": f"Bearer {self.user_token}"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                self.points = data.get("points", self.points)
                self._save_user_info()
                
                # base64 디코딩
                zip_base64 = data.get("zip_data")
                zip_data = base64.b64decode(zip_base64)
                
                # 임시 파일로 저장
                temp_path = f"temp_download_{int(time.time())}.zip"
                with open(temp_path, "wb") as f:
                    f.write(zip_data)
                
                return True, temp_path, "다운로드 성공"
            else:
                error_msg = response.json().get("error", "다운로드 실패")
                if "포인트" in error_msg or "point" in error_msg.lower():
                    return False, None, f"포인트가 부족합니다. (현재 포인트: {self.points})"
                return False, None, error_msg
        except requests.exceptions.RequestException as e:
            return False, None, f"서버 연결 실패: {e}"
        except Exception as e:
            return False, None, f"다운로드 중 오류: {e}"


class MacroEngine:
    def __init__(self):
        self.macros = {}
        self.jobs = {}
        self.context = {}
        self.is_running = False

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.15

        self._load()

    # ---------- 저장 / 불러오기 ----------
    def _load(self):
        try:
            if os.path.exists("my_macros_v16.json"):
                with open("my_macros_v16.json", "r", encoding="utf-8") as f:
                    self.macros = json.load(f)
            if os.path.exists("my_jobs_v16.json"):
                with open("my_jobs_v16.json", "r", encoding="utf-8") as f:
                    self.jobs = json.load(f)
        except Exception:
            pass

    def save_all(self):
        with open("my_macros_v16.json", "w", encoding="utf-8") as f:
            json.dump(self.macros, f, ensure_ascii=False, indent=2)
        with open("my_jobs_v16.json", "w", encoding="utf-8") as f:
            json.dump(self.jobs, f, ensure_ascii=False, indent=2)

    # ---------- 판매하기 / 구매하기 (거래 시스템) ----------
    def export_macro(self, name, steps, output_path, metadata=None):
        """
        부품을 거래용 파일로 내보내기 (ZIP 형식)
        - metadata: {"author": "", "description": "", "price": 0, "version": "1.0"}
        """
        if name not in self.macros and not steps:
            return False
        
        data = steps if steps else self.macros.get(name, [])
        if not data:
            return False
        
        try:
            # 임시 디렉토리 생성
            temp_dir = f"temp_export_{int(time.time())}"
            os.makedirs(temp_dir, exist_ok=True)
            
            # 메타데이터 준비
            meta = {
                "type": "macro",
                "name": name,
                "version": "1.0",
                "export_date": datetime.now().isoformat(),
                "author": metadata.get("author", "") if metadata else "",
                "description": metadata.get("description", "") if metadata else "",
                "price": metadata.get("price", 0) if metadata else 0,
            }
            
            # 데이터 저장
            with open(os.path.join(temp_dir, "data.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 메타데이터 저장
            with open(os.path.join(temp_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            # 이미지 파일 수집 및 복사
            image_files = set()
            for step in data:
                if step.get("type") == "click":
                    img_path = step.get("value", "")
                    if img_path and os.path.exists(img_path):
                        image_files.add(img_path)
            
            # images 폴더 생성 및 이미지 복사
            if image_files:
                img_dir = os.path.join(temp_dir, "images")
                os.makedirs(img_dir, exist_ok=True)
                for img_path in image_files:
                    img_name = os.path.basename(img_path)
                    shutil.copy2(img_path, os.path.join(img_dir, img_name))
            
            # ZIP 파일 생성
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            # 임시 디렉토리 삭제
            shutil.rmtree(temp_dir, ignore_errors=True)
            return True
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
    
    def import_macro(self, zip_path, new_name=None):
        """
        거래용 파일에서 부품 가져오기
        """
        try:
            temp_dir = f"temp_import_{int(time.time())}"
            os.makedirs(temp_dir, exist_ok=True)
            
            # ZIP 파일 압축 해제
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(temp_dir)
            
            # 메타데이터 읽기
            meta_path = os.path.join(temp_dir, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                metadata = {}
            
            # 데이터 읽기
            data_path = os.path.join(temp_dir, "data.json")
            if not os.path.exists(data_path):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 이미지 파일 복원
            img_dir = os.path.join(temp_dir, "images")
            if os.path.exists(img_dir):
                if not os.path.exists("images"):
                    os.makedirs("images")
                for img_file in os.listdir(img_dir):
                    src = os.path.join(img_dir, img_file)
                    dst = os.path.join("images", img_file)
                    shutil.copy2(src, dst)
                    
                    # 데이터에서 이미지 경로 업데이트
                    for step in data:
                        if step.get("type") == "click":
                            old_path = step.get("value", "")
                            if os.path.basename(old_path) == img_file:
                                step["value"] = dst
            
            # 이름 결정
            final_name = new_name if new_name else metadata.get("name", "imported_macro")
            if final_name in self.macros:
                # 중복 시 번호 추가
                counter = 1
                while f"{final_name}_{counter}" in self.macros:
                    counter += 1
                final_name = f"{final_name}_{counter}"
            
            # 부품 추가
            self.macros[final_name] = data
            self.save_all()
            
            # 임시 디렉토리 삭제
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            return {
                "name": final_name,
                "metadata": metadata,
                "data": data
            }
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
    
    def export_job(self, name, steps, output_path, metadata=None):
        """
        조립품을 거래용 파일로 내보내기 (ZIP 형식)
        """
        if name not in self.jobs and not steps:
            return False
        
        data = steps if steps else self.jobs.get(name, [])
        if not data:
            return False
        
        try:
            temp_dir = f"temp_export_{int(time.time())}"
            os.makedirs(temp_dir, exist_ok=True)
            
            meta = {
                "type": "job",
                "name": name,
                "version": "1.0",
                "export_date": datetime.now().isoformat(),
                "author": metadata.get("author", "") if metadata else "",
                "description": metadata.get("description", "") if metadata else "",
                "price": metadata.get("price", 0) if metadata else 0,
            }
            
            with open(os.path.join(temp_dir, "data.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            with open(os.path.join(temp_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            return True
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
    
    def import_job(self, zip_path, new_name=None):
        """
        거래용 파일에서 조립품 가져오기
        """
        try:
            temp_dir = f"temp_import_{int(time.time())}"
            os.makedirs(temp_dir, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(temp_dir)
            
            meta_path = os.path.join(temp_dir, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                metadata = {}
            
            data_path = os.path.join(temp_dir, "data.json")
            if not os.path.exists(data_path):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            final_name = new_name if new_name else metadata.get("name", "imported_job")
            if final_name in self.jobs:
                counter = 1
                while f"{final_name}_{counter}" in self.jobs:
                    counter += 1
                final_name = f"{final_name}_{counter}"
            
            self.jobs[final_name] = data
            self.save_all()
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            return {
                "name": final_name,
                "metadata": metadata,
                "data": data
            }
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    # ---------- 이미지/좌표 ----------
    def get_location(self, val):
        # "x,y" 형태 좌표
        if isinstance(val, str) and "," in val:
            try:
                x, y = map(int, val.split(","))
                return x, y
            except Exception:
                return None

        # 파일 경로(이미지)
        if isinstance(val, str) and os.path.exists(val):
            try:
                pos = pyautogui.locateCenterOnScreen(val, confidence=0.8)
                if pos:
                    return pos.x, pos.y
            except Exception:
                return None

        return None

    # ---------- 스마트 대기 ----------
    def smart_wait(self, timeout=5.0, check_interval=0.5, status_callback=None):
        """
        스마트 대기: 화면이 바뀔 때까지 기다리되, 최대 timeout 초까지만 대기.
        - 화면이 변하면 바로 다음 단계 진행
        - timeout 지나면 그냥 다음 단계로 넘어감
        """
        try:
            if status_callback:
                status_callback(f"⏱ 스마트 대기 시작 (최대 {timeout}초)")

            start = time.time()
            # 첫 스크린샷
            base = ImageGrab.grab().convert("L")  # 흑백으로 단순화

            while time.time() - start < timeout and self.is_running:
                time.sleep(check_interval)
                cur = ImageGrab.grab().convert("L")
                diff = ImageChops.difference(base, cur)
                # 변화가 있으면 diff의 bbox가 생김
                if diff.getbbox():
                    if status_callback:
                        status_callback("⏱ 스마트 대기: 화면 변화 감지, 다음 단계로 진행")
                    return

            if status_callback:
                status_callback("⏱ 스마트 대기: 시간 초과, 다음 단계로 진행")
        except Exception as e:
            if status_callback:
                status_callback(f"⏱ 스마트 대기 중 오류: {e}")

    # ---------- 반복 로직 (조립라인 전체 실행) ----------
    def run_steps(self, steps, status_callback=None):
        """조립라인에 있는 step 리스트를 그대로 실행 (job 이름 없이도 실행 가능)"""
        if not steps:
            if status_callback:
                status_callback("⚠ 실행할 작업이 없습니다.")
            return

        # 반복 블록 짝 검사
        open_joints = 0
        for s in steps:
            if s["type"] in ("joint_start", "joint_list"):
                open_joints += 1
            elif s["type"] == "joint_end":
                open_joints -= 1
        if open_joints != 0 and status_callback:
            status_callback(f"⚠ '반복 시작/끝' 짝이 맞지 않습니다. (열림 수: {open_joints})")

        self.is_running = True
        self.context = {}

        if status_callback:
            status_callback("🚀 조립라인 실행 시작")

        i = 0
        loop_stack = []  # [{start, data, idx, is_dict}]

        # 조립라인 루프
        while i < len(steps) and self.is_running:
            step = steps[i]
            stype = step["type"]
            val = step.get("value", "")

            # ----- 1) 엑셀/횟수 반복 시작 -----
            if stype == "joint_start":
                data_list = []
                is_dict = False

                sval = str(val)
                # 엑셀 파일
                if sval.lower().endswith(".xlsx") or sval.lower().endswith(".xls"):
                    if os.path.exists(sval):
                        try:
                            df = pd.read_excel(sval).fillna("")
                            data_list = df.to_dict("records")
                            is_dict = True
                            if status_callback:
                                status_callback(f"📂 엑셀 로드: {len(data_list)}행")
                        except Exception as e:
                            if status_callback:
                                status_callback(f"❌ 엑셀 오류: {e}")
                # 숫자(횟수 반복)
                elif sval.isdigit():
                    count = int(sval)
                    data_list = list(range(1, count + 1))
                    is_dict = False
                    if status_callback:
                        status_callback(f"🔢 횟수 반복: {count}회")

                if data_list:
                    # 중첩 반복 지원: 스택에 추가
                    loop_stack.append(
                        {"start": i, "data": data_list, "idx": 0, "is_dict": is_dict, "level": len(loop_stack)}
                    )
                    item = data_list[0]
                    if is_dict:
                        # 엑셀의 컬럼명 → context 키
                        self.context.update(item)
                    else:
                        # 중첩 반복 시 변수명 구분 (외부: i, 내부: i2, i3, ...)
                        if len(loop_stack) > 1:
                            var_name = f"i{len(loop_stack)}"
                            self.context[var_name] = item
                            # 가장 최근 반복의 값은 i로도 사용 가능
                            self.context["i"] = item
                        else:
                            self.context["i"] = item
                    if status_callback:
                        level_info = f" (레벨 {len(loop_stack)})" if len(loop_stack) > 1 else ""
                        current_item = str(item)
                        current_display = current_item[:30] + "..." if len(current_item) > 30 else current_item
                        status_callback(f"🔁 반복 시작 (1/{len(data_list)}) - 현재 값: '{current_display}'{level_info}")
                else:
                    if status_callback:
                        status_callback("⚠ 반복할 데이터가 없습니다.")

            # ----- 2) 직접 입력 반복 (줄목록) -----
            elif stype == "joint_list":
                raw_text = str(val).strip()
                if raw_text:
                    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
                else:
                    lines = []

                if lines:
                    # 중첩 반복 지원: 스택에 추가
                    loop_stack.append(
                        {"start": i, "data": lines, "idx": 0, "is_dict": False, "level": len(loop_stack)}
                    )
                    # 중첩 반복 시 변수명 구분
                    if len(loop_stack) > 1:
                        var_name = f"i{len(loop_stack)}"
                        self.context[var_name] = lines[0]
                        # 가장 최근 반복의 값은 i로도 사용 가능
                        self.context["i"] = lines[0]
                    else:
                        self.context["i"] = lines[0]
                    
                    # 첫 번째 값 자동 입력 (Ctrl+A 후 붙여넣기)
                    if status_callback:
                        level_info = f" (레벨 {len(loop_stack)})" if len(loop_stack) > 1 else ""
                        current_value = lines[0][:20] + "..." if len(lines[0]) > 20 else lines[0]
                        status_callback(f"📝 직접입력 반복 시작 (1/{len(lines)}) - 현재 값: '{current_value}'{level_info}")
                    
                    # 자동 입력: Ctrl+A 후 첫 번째 값 붙여넣기
                    time.sleep(0.2)  # 사용자가 커서 위치를 설정할 시간
                    robust_hotkey("ctrl", "a")
                    time.sleep(0.1)
                    pyperclip.copy(lines[0])
                    time.sleep(0.1)
                    robust_hotkey("ctrl", "v")
                else:
                    if status_callback:
                        status_callback("⚠ 직접입력 반복에 내용이 없습니다.")

            # ----- 3) 반복 종료 -----
            elif stype == "joint_end":
                if loop_stack:
                    curr = loop_stack[-1]  # 가장 최근 반복 블록 (중첩 지원)
                    curr["idx"] += 1
                    if curr["idx"] < len(curr["data"]):
                        # 다음 반복 항목이 있음
                        item = curr["data"][curr["idx"]]
                        if curr["is_dict"]:
                            # 엑셀 데이터: 컬럼명을 context 키로 사용
                            self.context.update(item)
                        else:
                            # 직접입력/횟수 반복: 중첩 레벨에 따라 변수명 구분
                            level = curr.get("level", 0)
                            if level > 0:
                                var_name = f"i{level + 1}"
                                self.context[var_name] = item
                            # 가장 최근 반복의 값은 항상 i로도 사용 가능
                            self.context["i"] = item
                        if status_callback:
                            level_info = f" (레벨 {curr.get('level', 0) + 1})" if curr.get("level", 0) > 0 else ""
                            # 현재 반복 값 표시
                            current_item = str(item)
                            current_display = current_item[:20] + "..." if len(current_item) > 20 else current_item
                            status_callback(
                                f"🔁 반복 진행 ({curr['idx']+1}/{len(curr['data'])}) - 현재 값: '{current_display}'{level_info}"
                            )
                        
                        # 직접입력 반복인 경우 자동 입력 (Ctrl+A 후 붙여넣기)
                        if not curr.get("is_dict", False):
                            time.sleep(0.2)  # 사용자가 커서 위치를 설정할 시간
                            robust_hotkey("ctrl", "a")
                            time.sleep(0.1)
                            pyperclip.copy(str(item))
                            time.sleep(0.1)
                            robust_hotkey("ctrl", "v")
                        
                        # 반복 블록 시작 위치로 점프 (중첩 반복 지원)
                        # i += 1이 바로 다음에 실행되므로 curr["start"] + 1 위치로 이동
                        i = curr["start"]
                    else:
                        # 현재 반복 블록이 모두 끝남
                        loop_stack.pop()
                        if status_callback:
                            status_callback("⏹ 반복 블록 종료")
                else:
                    if status_callback:
                        status_callback("⚠ 반복 끝이 시작과 맞지 않습니다.")

            # ----- 4) 부품 실행 -----
            elif stype == "call_macro":
                m_name = str(val)
                if m_name in self.macros:
                    if status_callback:
                        status_callback(f"🧩 부품 실행: {m_name}")
                    self.run_macro_steps(self.macros[m_name], status_callback)
                else:
                    if status_callback:
                        status_callback(f"⚠ 부품 '{m_name}' 을(를) 찾을 수 없습니다.")

            # 다음 step 으로
            i += 1
            time.sleep(0.05)

        self.is_running = False
        if status_callback:
            status_callback("✅ 조립라인 실행 완료")

    # ---------- 부품(매크로) 실행 ----------
    def run_macro_steps(self, steps, status_callback=None):
        for idx, step in enumerate(steps):
            if not self.is_running:
                break

            atype = step["type"]
            raw_val = step.get("value", "")

            # context 적용: {i}, {차량번호}, ...
            sval = str(raw_val)
            if "{" in sval and "}" in sval:
                try:
                    sval = sval.format(**self.context)
                except Exception:
                    pass

            if status_callback:
                status_callback(f"  ▶ [{idx+1}/{len(steps)}] {atype}: {sval}")

            try:
                if atype == "cmd_a":
                    robust_hotkey("ctrl", "a")
                elif atype == "cmd_c":
                    robust_hotkey("ctrl", "c")
                elif atype == "cmd_v":
                    robust_hotkey("ctrl", "v")

                elif atype == "browser":
                    webbrowser.open(sval)

                elif atype == "click":
                    pos = self.get_location(sval)
                    if pos:
                        pyautogui.click(*pos)
                    else:
                        if status_callback:
                            status_callback(f"    ⚠ 클릭 대상 이미지를 찾지 못함: {sval}")

                elif atype == "click_xy":
                    x, y = map(int, sval.split(","))
                    pyautogui.click(x, y)

                elif atype == "right_click":
                    x, y = map(int, sval.split(","))
                    pyautogui.click(x, y, button="right")

                elif atype == "drag":
                    x1, y1, x2, y2 = map(int, sval.split(","))
                    pyautogui.moveTo(x1, y1)
                    pyautogui.dragTo(x2, y2, duration=0.8, button="left")

                elif atype == "ocr_area":
                    x1, y1, x2, y2 = map(int, sval.split(","))
                    left, top = min(x1, x2), min(y1, y2)
                    right, bottom = max(x1, x2), max(y1, y2)
                    if right > left and bottom > top:
                        img = ImageGrab.grab(bbox=(left, top, right, bottom))
                        img.save("ocr_preview.png")
                        if status_callback:
                            status_callback("  👁 OCR 영역 캡쳐(ocr_preview.png 저장). 실제 인식은 추후 연결.")
                    else:
                        if status_callback:
                            status_callback("  ⚠ OCR 영역 좌표가 잘못되었습니다.")

                elif atype == "type":
                    # 직접입력 반복 중이고 {i} 변수를 사용하는 경우, Ctrl+A 후 붙여넣기
                    if "i" in self.context and "{i}" in sval:
                        # {i}를 실제 값으로 치환
                        final_value = sval.replace("{i}", str(self.context["i"]))
                        # Ctrl+A로 전체 선택
                        robust_hotkey("ctrl", "a")
                        time.sleep(0.1)
                        # 치환된 값 복사 및 붙여넣기
                        pyperclip.copy(final_value)
                        time.sleep(0.1)
                        robust_hotkey("ctrl", "v")
                    else:
                        # 일반 입력
                        pyperclip.copy(sval)
                        time.sleep(0.2)
                        robust_hotkey("ctrl", "v")

                elif atype == "key":
                    pyautogui.press(sval)

                elif atype == "wait":
                    time.sleep(float(sval))

                elif atype == "smart_wait":
                    # 값이 비어있으면 기본 5초
                    try:
                        timeout = float(sval) if sval else 5.0
                    except Exception:
                        timeout = 5.0
                    self.smart_wait(timeout=timeout, status_callback=status_callback)

            except Exception as e:
                if status_callback:
                    status_callback(f"  ❌ 동작 에러: {e}")

            time.sleep(0.1)


# ==========================================
# 2. GUI
# ==========================================

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("GovPlayer AI (조립/부품 + 직접입력반복) / 충주시 AI 전문관 MS Labs   / 제휴 : kim0395kk@korea.kr")
        self.root.geometry("1280x850")

        self.engine = MacroEngine()
        self.marketplace = MarketplaceAPI()
        self.var_hide_window = tk.IntVar(value=0)

        self.current_job_steps = []
        self.current_macro = []
        self.selected_step_idx = None
        self.clipboard_steps = []

        self._build_ui()

    # ---------- 공통 ----------
    def set_status(self, msg: str):
        self.lbl_status.config(text=msg)

    def flash_popup(self, msg: str):
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 360, 80
        top.geometry(f"{w}x{h}+{sw//2 - w//2}+{sh//2 - h//2}")
        tk.Label(
            top,
            text=msg,
            font=("맑은 고딕", 12, "bold"),
            bg="#ffffcc",
            fg="black",
            bd=2,
            relief="solid",
        ).pack(expand=True, fill="both")
        self.root.update()
        time.sleep(1.0)
        top.destroy()

    # ---------- UI 빌드 ----------
    def _build_ui(self):
        # 하단 상태바
        self.lbl_status = tk.Label(
            self.root,
            text="준비 완료",
            bg="#24292f",
            fg="#79c0ff",
            anchor="w",
            padx=8,
        )
        self.lbl_status.pack(side="bottom", fill="x")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self.tab_job = tk.Frame(nb, bg="#f6f8fa")
        self.tab_macro = tk.Frame(nb, bg="#f6f8fa")
        nb.add(self.tab_job, text="🏭 1. 조립 공장")
        nb.add(self.tab_macro, text="🧩 2. 부품 공장")

        self._build_job_tab()
        self._build_macro_tab()

    # ---------- [탭1] 조립 공장 ----------
    def _build_job_tab(self):
        top = tk.Frame(self.tab_job, bg="#e1e4e8", pady=6)
        top.pack(fill="x")
        tk.Label(top, text="[실행 옵션]", bg="#e1e4e8").pack(side="left", padx=8)
        tk.Radiobutton(
            top,
            text="화면 유지",
            variable=self.var_hide_window,
            value=0,
            bg="#e1e4e8",
        ).pack(side="left")
        tk.Radiobutton(
            top,
            text="화면 숨기기",
            variable=self.var_hide_window,
            value=1,
            bg="#e1e4e8",
        ).pack(side="left")

        paned = tk.PanedWindow(
            self.tab_job, orient="horizontal", sashwidth=5, bg="#d0d7de"
        )
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # 왼쪽: 부품 창고
        left = tk.LabelFrame(
            paned, text="📦 부품 창고 (더블클릭 시 조립라인에 추가)", bg="white"
        )
        paned.add(left, width=260)
        self.list_macro_source = tk.Listbox(
            left, font=("맑은 고딕", 11), activestyle="none"
        )
        self.list_macro_source.pack(fill="both", expand=True, padx=4, pady=4)
        self.list_macro_source.bind("<Double-Button-1>", self.add_macro_to_job)

        tk.Button(
            left, text="🔄 부품 목록 새로고침", command=self.refresh_macro_source
        ).pack(fill="x", padx=4, pady=4)

        # 가운데: 조립 라인
        center = tk.LabelFrame(
            paned, text="🏭 조립 라인 (위에서 아래 순서로 실행)", bg="white"
        )
        paned.add(center, width=520)
        self.list_job = tk.Listbox(
            center, font=("맑은 고딕", 11), activestyle="none", selectmode="single"
        )
        self.list_job.pack(fill="both", expand=True, padx=4, pady=4)

        job_btns = tk.Frame(center, bg="white")
        job_btns.pack(fill="x", padx=4, pady=4)

        tk.Button(
            job_btns, text="🔼 위로", command=lambda: self.move_job_step(-1)
        ).pack(side="left", padx=2)
        tk.Button(
            job_btns, text="🔽 아래로", command=lambda: self.move_job_step(1)
        ).pack(side="left", padx=2)
        tk.Button(job_btns, text="❌ 삭제", command=self.delete_job_step).pack(
            side="left", padx=2
        )

        # 오른쪽: 반복/실행
        right = tk.LabelFrame(self.tab_job, text="🔧 반복 & 실행", bg="white")
        paned.add(right, width=280)

        fr_joint = tk.LabelFrame(right, text="반복 블록", bg="white")
        fr_joint.pack(fill="x", padx=6, pady=6)

        tk.Button(
            fr_joint,
            text="📝 직접입력 반복 시작",
            command=self.add_joint_list,
            bg="#fff8c5",
        ).pack(fill="x", padx=3, pady=2)

        tk.Button(
            fr_joint,
            text="🔁 엑셀/횟수 반복 시작",
            command=self.add_joint_start,
            bg="#dafbe1",
        ).pack(fill="x", padx=3, pady=2)

        tk.Button(
            fr_joint,
            text="⏹ 반복 끝 (여기까지)",
            command=self.add_joint_end,
            bg="#ffcccc",
        ).pack(fill="x", padx=3, pady=2)

        fr_run = tk.LabelFrame(right, text="작업 저장 / 실행", bg="white")
        fr_run.pack(fill="x", padx=6, pady=6)

        tk.Label(fr_run, text="작업 이름:", bg="white").pack(anchor="w", padx=4)
        self.entry_job_name = tk.Entry(fr_run)
        self.entry_job_name.pack(fill="x", padx=4, pady=2)

        tk.Button(fr_run, text="💾 현재 조립라인을 이름으로 저장", command=self.save_job).pack(
            fill="x", padx=4, pady=2
        )

        tk.Label(fr_run, text="저장된 작업 목록:", bg="white").pack(anchor="w", padx=4, pady=(6, 0))
        self.combo_jobs = ttk.Combobox(
            fr_run, state="readonly", values=list(self.engine.jobs.keys())
        )
        self.combo_jobs.pack(fill="x", padx=4, pady=2)
        self.combo_jobs.bind("<<ComboboxSelected>>", self.load_job)

        tk.Button(fr_run, text="🗑 선택 작업 삭제", command=self.delete_job).pack(
            fill="x", padx=4, pady=2
        )

        tk.Label(fr_run, text="[로컬 파일]", bg="white", fg="gray", font=("맑은 고딕", 9, "bold")).pack(
            anchor="w", padx=4, pady=(8, 0)
        )
        tk.Button(fr_run, text="💾 저장하기", command=self.export_job_local, bg="#0969da", fg="white").pack(
            fill="x", padx=4, pady=2
        )
        tk.Button(fr_run, text="📂 불러오기", command=self.import_job_local, bg="#6f42c1", fg="white").pack(
            fill="x", padx=4, pady=2
        )

        tk.Label(fr_run, text="[웹 게시판 거래]", bg="white", fg="#0969da", font=("맑은 고딕", 9, "bold")).pack(
            anchor="w", padx=4, pady=(8, 0)
        )
        self.lbl_job_points = tk.Label(fr_run, text=f"포인트: {self.marketplace.points}P", bg="white", fg="#ff6b00", font=("맑은 고딕", 9, "bold"))
        self.lbl_job_points.pack(anchor="w", padx=4, pady=2)
        tk.Button(fr_run, text="💰 판매하기", command=self.sell_job, bg="#ffa500", fg="white").pack(
            fill="x", padx=4, pady=2
        )
        tk.Button(fr_run, text="🛒 구매하기", command=self.buy_job, bg="#28a745", fg="white").pack(
            fill="x", padx=4, pady=2
        )

        tk.Button(
            fr_run,
            text="🚀 이 조립라인 실행",
            command=self.run_current_job,
            bg="#1f883d",
            fg="white",
            font=("맑은 고딕", 11, "bold"),
        ).pack(fill="x", padx=4, pady=(8, 4))
        
        # 긴급 정지 버튼
        self.btn_emergency_stop = tk.Button(
            fr_run,
            text="🛑 긴급 정지",
            command=self.emergency_stop,
            bg="#dc3545",
            fg="white",
            font=("맑은 고딕", 11, "bold"),
            state="disabled",
        )
        self.btn_emergency_stop.pack(fill="x", padx=4, pady=2)

        tk.Button(
            fr_run,
            text="🧹 조립라인 비우기",
            command=self.clear_job,
        ).pack(fill="x", padx=4, pady=2)

        self.refresh_macro_source()
        self.refresh_job_view()

    # ---------- [탭2] 부품 공장 ----------
    def _build_macro_tab(self):
        top = tk.Frame(self.tab_macro, bg="#e1e4e8", pady=6)
        top.pack(fill="x")

        tk.Label(top, text="부품 이름:", bg="#e1e4e8").pack(side="left", padx=4)
        self.entry_macro_name = tk.Entry(top, width=20)
        self.entry_macro_name.pack(side="left", padx=2)

        tk.Button(top, text="💾 저장", command=self.save_macro, bg="#0969da", fg="white").pack(
            side="left", padx=4
        )
        tk.Button(top, text="➕ 새 부품", command=self.new_macro).pack(side="left", padx=2)

        self.combo_macros = ttk.Combobox(
            top, state="readonly", values=list(self.engine.macros.keys()), width=20
        )
        self.combo_macros.pack(side="left", padx=10)
        self.combo_macros.bind("<<ComboboxSelected>>", self.load_macro)

        tk.Button(top, text="🗑 삭제", command=self.delete_macro, bg="#cf222e", fg="white").pack(
            side="left", padx=4
        )

        tk.Button(top, text="💾 저장하기", command=self.export_macro_local, bg="#0969da", fg="white").pack(
            side="left", padx=4
        )
        tk.Button(top, text="📂 불러오기", command=self.import_macro_local, bg="#6f42c1", fg="white").pack(
            side="left", padx=4
        )

        self.lbl_macro_points = tk.Label(top, text=f"포인트: {self.marketplace.points}P", bg="#e1e4e8", fg="#ff6b00", font=("맑은 고딕", 9, "bold"))
        self.lbl_macro_points.pack(side="left", padx=4)
        tk.Button(top, text="💰 판매하기", command=self.sell_macro, bg="#ffa500", fg="white").pack(
            side="left", padx=4
        )
        tk.Button(top, text="🛒 구매하기", command=self.buy_macro, bg="#28a745", fg="white").pack(
            side="left", padx=4
        )

        paned = tk.PanedWindow(
            self.tab_macro, orient="horizontal", sashwidth=5, bg="#d0d7de"
        )
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # 1: 도구 상자
        f1 = tk.LabelFrame(paned, text="1. 도구 상자", bg="white")
        paned.add(f1, width=180)

        tk.Label(f1, text="[기본 동작]", bg="white", fg="gray").pack(
            anchor="w", padx=4, pady=(4, 0)
        )
        tk.Button(f1, text="📸 이미지 클릭", command=lambda: self.add_step("click")).pack(
            fill="x", padx=4, pady=1
        )
        tk.Button(f1, text="📍 좌표 클릭", command=lambda: self.add_step("click_xy")).pack(
            fill="x", padx=4, pady=1
        )
        tk.Button(
            f1,
            text="🖱 우클릭",
            command=lambda: self.add_step("right_click"),
            bg="#fff0f0",
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1,
            text="🖱 드래그",
            command=lambda: self.add_step("drag"),
            bg="#fff0f0",
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(f1, text="✍ 글자 입력", command=lambda: self.add_step("type")).pack(
            fill="x", padx=4, pady=1
        )
        tk.Button(
            f1,
            text="⌨ 키 입력(enter)",
            command=lambda: self.add_step("key"),
        ).pack(fill="x", padx=4, pady=1)

        tk.Label(f1, text="[클립보드/AI]", bg="white", fg="#0969da").pack(
            anchor="w", padx=4, pady=(8, 0)
        )
        tk.Button(
            f1,
            text="🟦 전체선택 (Ctrl+A)",
            command=lambda: self.add_step("cmd_a"),
            bg="#ddf4ff",
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1,
            text="🟩 복사 (Ctrl+C)",
            command=lambda: self.add_step("cmd_c"),
            bg="#e6ffec",
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1,
            text="🟧 붙여넣기 (Ctrl+V)",
            command=lambda: self.add_step("cmd_v"),
            bg="#fff8c5",
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1,
            text="👁 OCR 영역 캡쳐",
            command=lambda: self.add_step("ocr_area"),
            bg="#e6fffa",
        ).pack(fill="x", padx=4, pady=1)

        tk.Label(f1, text="[기타]", bg="white", fg="gray").pack(
            anchor="w", padx=4, pady=(8, 0)
        )
        tk.Button(
            f1,
            text="🌐 브라우저 열기",
            command=lambda: self.add_step("browser"),
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1, text="⏱ 대기(1초)", command=lambda: self.add_step("wait")
        ).pack(fill="x", padx=4, pady=1)
        tk.Button(
            f1,
            text="⏱ 스마트 대기(화면변화)",
            command=lambda: self.add_step("smart_wait")
        ).pack(fill="x", padx=4, pady=1)

        # 2: 속성 설정
        self.f_prop = tk.LabelFrame(paned, text="2. 선택된 동작 설정", bg="white")
        paned.add(self.f_prop, width=320)
        self._build_prop_panel()

        # 3: 순서
        f3 = tk.LabelFrame(paned, text="3. 부품 동작 순서", bg="white")
        paned.add(f3, width=420)

        self.list_steps = tk.Listbox(
            f3, font=("맑은 고딕", 11), activestyle="none", selectmode="extended"
        )
        self.list_steps.pack(fill="both", expand=True, padx=4, pady=4)
        self.list_steps.bind("<<ListboxSelect>>", self.on_step_select)

        f3_btn1 = tk.Frame(f3, bg="white")
        f3_btn1.pack(fill="x", padx=4, pady=2)
        tk.Button(
            f3_btn1, text="📄 선택 복사", command=self.copy_steps
        ).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(
            f3_btn1, text="📋 붙여넣기", command=self.paste_steps
        ).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(
            f3_btn1, text="🗑 선택 삭제", command=self.delete_steps
        ).pack(side="left", expand=True, fill="x", padx=2)

        f3_btn2 = tk.Frame(f3, bg="white")
        f3_btn2.pack(fill="x", padx=4, pady=2)
        tk.Button(
            f3_btn2, text="▲", command=lambda: self.move_step(-1)
        ).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(
            f3_btn2, text="▼", command=lambda: self.move_step(1)
        ).pack(side="left", expand=True, fill="x", padx=2)

        tk.Button(
            f3,
            text="▶ 이 부품만 테스트 실행",
            command=self.test_current_macro,
            bg="#2da44e",
            fg="white",
        ).pack(fill="x", padx=6, pady=4)
        
        # 부품 테스트용 긴급 정지 버튼
        self.btn_emergency_stop_macro = tk.Button(
            f3,
            text="🛑 긴급 정지",
            command=self.emergency_stop,
            bg="#dc3545",
            fg="white",
            font=("맑은 고딕", 10, "bold"),
            state="disabled",
        )
        self.btn_emergency_stop_macro.pack(fill="x", padx=6, pady=2)

    # ---------- 속성 패널 ----------
    def _build_prop_panel(self):
        f = self.f_prop
        self.lbl_prop_guide = tk.Label(
            f,
            text="왼쪽에서 동작을 추가하고\n오른쪽 목록에서 하나를 선택하면\n여기에 상세 설정이 뜹니다.",
            bg="white",
            fg="gray",
            pady=16,
        )
        self.lbl_prop_guide.pack(fill="both", expand=True)

        self.prop_container = tk.Frame(f, bg="white")

        self.lbl_prop_title = tk.Label(
            self.prop_container,
            text="설정값:",
            bg="white",
            anchor="w",
            font=("맑은 고딕", 10, "bold"),
            wraplength=300,
            justify="left",
        )
        self.lbl_prop_title.pack(fill="x", padx=4, pady=(4, 2))
        self.ent_prop_val = tk.Entry(self.prop_container)
        self.ent_prop_val.pack(fill="x", padx=4, pady=2)
        self.ent_prop_val.bind("<KeyRelease>", self.on_prop_change)

        self.btn_recapture = tk.Button(
            self.prop_container, text="📸 이미지 다시 찍기", command=lambda: self.capture("click")
        )
        self.btn_recoord = tk.Button(
            self.prop_container,
            text="📍 좌표 다시 따기",
            command=lambda: self.capture("click_xy"),
        )
        self.btn_reright = tk.Button(
            self.prop_container,
            text="🖱 우클릭 좌표 다시 따기",
            command=lambda: self.capture("right_click"),
        )
        self.btn_redrag = tk.Button(
            self.prop_container,
            text="🖱 드래그 영역 다시 따기",
            command=lambda: self.capture("drag"),
        )
        self.btn_reocr = tk.Button(
            self.prop_container,
            text="👁 OCR 영역 다시 따기",
            command=lambda: self.capture("ocr_area"),
        )

        self.lbl_preview = tk.Label(self.prop_container, bg="white")

    def show_prop(self, step):
        self.lbl_prop_guide.pack_forget()
        self.prop_container.pack(fill="both", expand=True)

        t = step["type"]
        v = step.get("value", "")

        # 리셋
        for b in [
            self.btn_recapture,
            self.btn_recoord,
            self.btn_reright,
            self.btn_redrag,
            self.btn_reocr,
        ]:
            b.pack_forget()
        self.lbl_preview.pack_forget()
        self.ent_prop_val.pack(fill="x", padx=4, pady=2)

        self.ent_prop_val.delete(0, "end")
        self.ent_prop_val.insert(0, str(v))

        if t == "click":
            self.lbl_prop_title.config(text="이미지 파일 경로:")
            self.btn_recapture.pack(fill="x", padx=4, pady=2)
            self.show_image_preview(v)
        elif t == "click_xy":
            self.lbl_prop_title.config(text="좌표 (x,y):")
            self.btn_recoord.pack(fill="x", padx=4, pady=2)
        elif t == "right_click":
            self.lbl_prop_title.config(text="우클릭 좌표 (x,y):")
            self.btn_reright.pack(fill="x", padx=4, pady=2)
        elif t == "drag":
            self.lbl_prop_title.config(text="드래그 (x1,y1,x2,y2):")
            self.btn_redrag.pack(fill="x", padx=4, pady=2)
        elif t == "ocr_area":
            self.lbl_prop_title.config(text="OCR 영역 (x1,y1,x2,y2):")
            self.btn_reocr.pack(fill="x", padx=4, pady=2)
        elif t in ("cmd_a", "cmd_c", "cmd_v"):
            self.lbl_prop_title.config(text="단축키 전용 (설정값 필요 없음)")
            self.ent_prop_val.pack_forget()
        elif t == "type":
            self.lbl_prop_title.config(
                text="입력할 내용:\n반복 작업 시 {i} 사용 (예: {i})\n고정값은 그대로 입력"
            )
        elif t == "wait":
            self.lbl_prop_title.config(text="대기 시간(초):")
        elif t == "smart_wait":
            self.lbl_prop_title.config(
                text="스마트 대기 시간(초): 화면이 바뀌면 즉시 다음 단계로 진행"
            )
        elif t == "key":
            self.lbl_prop_title.config(text="키 이름 (예: enter, tab 등):")
        elif t == "browser":
            self.lbl_prop_title.config(text="URL 주소:")
        else:
            self.lbl_prop_title.config(text="설정값:")

    def show_image_preview(self, path):
        if isinstance(path, str) and os.path.exists(path):
            try:
                img = Image.open(path)
                img.thumbnail((220, 160))
                photo = ImageTk.PhotoImage(img)
                self.lbl_preview.config(image=photo)
                self.lbl_preview.image = photo
                self.lbl_preview.pack(padx=4, pady=4)
            except Exception:
                pass

    # ---------- 부품 편집 ----------
    def add_step(self, t):
        val = ""
        if t in ("click_xy", "right_click"):
            msg = "3초 뒤 좌표를 가져옵니다."
            self.flash_popup(msg)
            time.sleep(2)
            x, y = pyautogui.position()
            val = f"{x},{y}"
            if t == "click_xy":
                pyautogui.click(x, y)
            else:
                pyautogui.click(x, y, button="right")
        elif t == "click":
            self.flash_popup("3초 뒤 마우스 주변 이미지를 캡쳐합니다.")
            time.sleep(2)
            if not os.path.exists("images"):
                os.makedirs("images")
            fn = os.path.join("images", f"img_{int(time.time())}.png")
            x, y = pyautogui.position()
            pyautogui.screenshot(region=(x - 25, y - 25, 50, 50)).save(fn)
            val = fn
        elif t in ("drag", "ocr_area"):
            self.flash_popup("3초 뒤 [시작점] 좌표를 저장합니다.")
            time.sleep(2)
            x1, y1 = pyautogui.position()
            self.flash_popup("3초 뒤 [끝점] 좌표를 저장합니다.")
            time.sleep(2)
            x2, y2 = pyautogui.position()
            val = f"{x1},{y1},{x2},{y2}"
        elif t == "wait":
            val = "1.0"
        elif t == "smart_wait":
            # 기본 5초 동안 화면 변화를 감지
            val = "5.0"
        elif t == "key":
            val = "enter"
        elif t == "browser":
            val = "https://www.google.com"

        self.current_macro.append({"type": t, "value": val})
        self.refresh_step_list()
        self.list_steps.select_clear(0, "end")
        self.list_steps.select_set(len(self.current_macro) - 1)
        self.on_step_select(None)

    def capture(self, t):
        # 선택된 step 에 좌표/이미지 다시 반영
        if self.selected_step_idx is None:
            return
        idx = self.selected_step_idx

        if t in ("click_xy", "right_click"):
            self.flash_popup("3초 뒤 좌표를 다시 가져옵니다.")
            time.sleep(2)
            x, y = pyautogui.position()
            v = f"{x},{y}"
            if t == "click_xy":
                pyautogui.click(x, y)
            else:
                pyautogui.click(x, y, button="right")
        elif t in ("drag", "ocr_area"):
            self.flash_popup("3초 뒤 [시작점] 좌표를 다시 가져옵니다.")
            time.sleep(2)
            x1, y1 = pyautogui.position()
            self.flash_popup("3초 뒤 [끝점] 좌표를 다시 가져옵니다.")
            time.sleep(2)
            x2, y2 = pyautogui.position()
            v = f"{x1},{y1},{x2},{y2}"
        else:  # click
            self.flash_popup("3초 뒤 이미지를 다시 캡쳐합니다.")
            time.sleep(2)
            if not os.path.exists("images"):
                os.makedirs("images")
            v = os.path.join("images", f"img_{int(time.time())}.png")
            x, y = pyautogui.position()
            pyautogui.screenshot(region=(x - 25, y - 25, 50, 50)).save(v)

        self.current_macro[idx]["value"] = v
        self.ent_prop_val.delete(0, "end")
        self.ent_prop_val.insert(0, v)
        if t == "click":
            self.show_image_preview(v)
        self.refresh_step_list()

    def refresh_step_list(self):
        self.list_steps.delete(0, "end")
        for i, s in enumerate(self.current_macro):
            t = s["type"]
            v = str(s.get("value", ""))
            label = t
            if t == "cmd_a":
                label = "전체선택(Ctrl+A)"
            elif t == "cmd_c":
                label = "복사(Ctrl+C)"
            elif t == "cmd_v":
                label = "붙여넣기(Ctrl+V)"
            elif t == "drag":
                label = "드래그"
            elif t == "right_click":
                label = "우클릭"
            elif t == "ocr_area":
                label = "OCR 영역"
            elif t == "browser":
                label = "브라우저 열기"
            elif t == "smart_wait":
                label = "스마트 대기"
            elif t == "click":
                v = os.path.basename(v)
                label = "이미지 클릭"
            self.list_steps.insert("end", f"{i+1}. [{label}] {v}")

    def on_step_select(self, event):
        sels = self.list_steps.curselection()
        if not sels:
            self.selected_step_idx = None
            return
        self.selected_step_idx = sels[0]
        step = self.current_macro[self.selected_step_idx]
        self.show_prop(step)

    def on_prop_change(self, event):
        if self.selected_step_idx is None:
            return
        val = self.ent_prop_val.get()
        self.current_macro[self.selected_step_idx]["value"] = val
        self.refresh_step_list()
        self.list_steps.select_set(self.selected_step_idx)

    def copy_steps(self):
        sels = self.list_steps.curselection()
        if not sels:
            return
        self.clipboard_steps = [self.current_macro[i].copy() for i in sels]
        messagebox.showinfo("복사", f"{len(sels)}개의 동작을 복사했습니다.")

    def paste_steps(self):
        if not self.clipboard_steps:
            return
        sels = self.list_steps.curselection()
        insert_idx = sels[-1] + 1 if sels else len(self.current_macro)
        for st in self.clipboard_steps:
            self.current_macro.insert(insert_idx, st.copy())
            insert_idx += 1
        self.refresh_step_list()

    def delete_steps(self):
        sels = self.list_steps.curselection()
        if not sels:
            return
        for i in reversed(sels):
            del self.current_macro[i]
        self.refresh_step_list()
        self.selected_step_idx = None

    def move_step(self, d):
        sels = self.list_steps.curselection()
        if len(sels) != 1:
            return
        i = sels[0]
        j = i + d
        if 0 <= j < len(self.current_macro):
            self.current_macro[i], self.current_macro[j] = (
                self.current_macro[j],
                self.current_macro[i],
            )
            self.refresh_step_list()
            self.list_steps.select_set(j)
            self.on_step_select(None)

    def save_macro(self):
        name = self.entry_macro_name.get().strip()
        if not name:
            messagebox.showwarning("경고", "부품 이름을 입력하세요.")
            return
        self.engine.macros[name] = self.current_macro
        self.engine.save_all()
        self.combo_macros["values"] = list(self.engine.macros.keys())
        self.refresh_macro_source()
        messagebox.showinfo("저장", f"부품 '{name}' 저장 완료")

    def load_macro(self, event):
        name = self.combo_macros.get()
        if not name:
            return
        self.entry_macro_name.delete(0, "end")
        self.entry_macro_name.insert(0, name)
        self.current_macro = self.engine.macros.get(name, []).copy()
        self.refresh_step_list()
        self.selected_step_idx = None

    def delete_macro(self):
        name = self.combo_macros.get()
        if not name:
            return
        if not messagebox.askyesno("삭제", f"부품 '{name}' 을(를) 삭제할까요?"):
            return
        self.engine.macros.pop(name, None)
        self.engine.save_all()
        self.combo_macros.set("")
        self.combo_macros["values"] = list(self.engine.macros.keys())
        self.current_macro = []
        self.refresh_step_list()
        self.refresh_macro_source()

    def export_macro_local(self):
        """부품 로컬 파일로 저장하기"""
        name = self.entry_macro_name.get().strip()
        if not name and not self.current_macro:
            messagebox.showwarning("경고", "저장할 부품이 없습니다.")
            return
        
        if not name:
            name = simpledialog.askstring("부품 이름", "저장할 부품 이름을 입력하세요:")
            if not name:
                return
        
        file_path = filedialog.asksaveasfilename(
            title="부품 파일 저장",
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")],
            initialfile=f"{name}.zip"
        )
        
        if not file_path:
            return
        
        try:
            steps = self.current_macro if self.current_macro else self.engine.macros.get(name, [])
            metadata = {"author": "", "description": "", "price": 0}
            if self.engine.export_macro(name, steps, file_path, metadata):
                messagebox.showinfo("성공", f"부품 '{name}' 파일이 저장되었습니다.\n\n파일: {file_path}")
            else:
                messagebox.showerror("오류", "부품 저장에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"부품 저장 중 오류가 발생했습니다:\n{e}")
    
    def import_macro_local(self):
        """부품 로컬 파일에서 불러오기"""
        file_path = filedialog.askopenfilename(
            title="부품 파일 선택",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            result = self.engine.import_macro(file_path)
            if result:
                name = result["name"]
                messagebox.showinfo("성공", f"부품 '{name}' 불러오기 완료!")
                self.combo_macros["values"] = list(self.engine.macros.keys())
                self.combo_macros.set(name)
                self.load_macro(None)
                self.refresh_macro_source()
            else:
                messagebox.showerror("오류", "부품 불러오기에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"부품 불러오기 중 오류가 발생했습니다:\n{e}")
    
    def sell_macro(self):
        """부품 웹 게시판에 판매하기 - Streamlit 사이트로 바로 이동"""
        # Streamlit Cloud URL로 바로 이동
        marketplace_url = "https://marketplaceserver1-n8arrrkmjvyrqtmraftrpm.streamlit.app/"
        webbrowser.open(marketplace_url)
        messagebox.showinfo("마켓플레이스", f"마켓플레이스 사이트가 열렸습니다.\n\n{marketplace_url}\n\n사이트에서 로그인 후 판매하세요.")
    
    def buy_macro(self):
        """부품 웹 게시판에서 구매하기 (로그인 없이 목록 조회 가능)"""
        # 아이템 목록 조회 (로그인 불필요)
        success, items = self.marketplace.list_items("macro")
        if not success:
            messagebox.showerror("오류", f"아이템 목록 조회 실패:\n{items}")
            return
        
        if not items:
            messagebox.showinfo("알림", "판매 중인 부품이 없습니다.")
            return
        
        # 아이템 선택 다이얼로그
        top = tk.Toplevel(self.root)
        top.title("부품 마켓플레이스")
        top.geometry("600x500")
        top.transient(self.root)
        top.grab_set()
        
        tk.Label(top, text="구매할 부품을 선택하세요 (로그인 없이 조회 가능):", pady=4).pack(anchor="w", padx=10, pady=(10, 0))
        
        # 리스트박스
        listbox = tk.Listbox(top, width=70, height=15)
        listbox.pack(fill="both", expand=True, padx=10, pady=4)
        
        for item in items:
            name = item.get("name", "")
            author = item.get("author", "")
            price = item.get("price", 0)
            desc = item.get("description", "")[:30]
            item_id = item.get("id", "")
            price_text = f"{price}P" if price > 0 else "무료"
            display = f"[{item_id}] {name} | 작성자: {author} | 가격: {price_text} | {desc}"
            listbox.insert("end", display)
        
        def _buy():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("경고", "부품을 선택하세요.")
                return
            
            # 구매 시에만 로그인 확인
            if not self.marketplace.user_token:
                if not self._show_login_dialog():
                    messagebox.showinfo("알림", "구매하려면 로그인이 필요합니다.")
                    return
            
            selected_item = items[selection[0]]
            item_id = selected_item.get("id")
            item_name = selected_item.get("name", "")
            price = selected_item.get("price", 0)
            
            if price > 0:
                current_points = self.marketplace.get_points()
                if not messagebox.askyesno("구매 확인", f"'{item_name}' 구매하시겠습니까?\n가격: {price}포인트\n현재 포인트: {current_points}P"):
                    return
            
            top.destroy()
            
            # 다운로드
            success, zip_path, msg = self.marketplace.download_item(item_id)
            if success:
                try:
                    result = self.engine.import_macro(zip_path)
                    if result:
                        name = result["name"]
                        messagebox.showinfo("성공", f"부품 '{name}' 구매 완료!\n\n{msg}\n포인트: {self.marketplace.points}P")
                        self._update_points_display()
                        self.combo_macros["values"] = list(self.engine.macros.keys())
                        self.combo_macros.set(name)
                        self.load_macro(None)
                        self.refresh_macro_source()
                finally:
                    if zip_path and os.path.exists(zip_path):
                        os.remove(zip_path)
            else:
                messagebox.showerror("오류", f"구매 실패:\n{msg}")
        
        tk.Button(top, text="구매하기 (로그인 필요)", command=_buy, bg="#28a745", fg="white").pack(pady=10)
    
    def _show_login_dialog(self):
        """로그인 다이얼로그"""
        top = tk.Toplevel(self.root)
        top.title("로그인")
        top.geometry("300x150")
        top.transient(self.root)
        top.grab_set()
        
        tk.Label(top, text="사용자 ID:", pady=4).pack(anchor="w", padx=10, pady=(10, 0))
        entry_id = tk.Entry(top, width=30)
        entry_id.pack(fill="x", padx=10, pady=2)
        
        tk.Label(top, text="비밀번호:", pady=4).pack(anchor="w", padx=10, pady=(10, 0))
        entry_pw = tk.Entry(top, width=30, show="*")
        entry_pw.pack(fill="x", padx=10, pady=2)
        
        login_result = [False]
        
        def _login():
            user_id = entry_id.get().strip()
            password = entry_pw.get().strip()
            if not user_id or not password:
                messagebox.showwarning("경고", "ID와 비밀번호를 입력하세요.")
                return
            
            success, msg = self.marketplace.login(user_id, password)
            if success:
                login_result[0] = True
                messagebox.showinfo("성공", f"로그인 성공!\n포인트: {self.marketplace.points}P")
                self._update_points_display()
                top.destroy()
            else:
                messagebox.showerror("오류", f"로그인 실패:\n{msg}")
        
        tk.Button(top, text="로그인", command=_login, bg="#0969da", fg="white").pack(pady=10)
        
        top.wait_window()
        return login_result[0]
    
    def _update_points_display(self):
        """포인트 표시 업데이트"""
        self.marketplace.get_points()
        # 조립 공장 탭 포인트 표시 업데이트
        if hasattr(self, 'lbl_job_points'):
            self.lbl_job_points.config(text=f"포인트: {self.marketplace.points}P")
        # 부품 공장 탭 포인트 표시 업데이트
        if hasattr(self, 'lbl_macro_points'):
            self.lbl_macro_points.config(text=f"포인트: {self.marketplace.points}P")

    def new_macro(self):
        self.entry_macro_name.delete(0, "end")
        self.combo_macros.set("")
        self.current_macro = []
        self.refresh_step_list()
        self.selected_step_idx = None
        self.lbl_prop_guide.pack(fill="both", expand=True)
        self.prop_container.pack_forget()
        self.set_status("🧩 새 부품 편집을 시작합니다.")

    def test_current_macro(self):
        if not self.current_macro:
            messagebox.showwarning("경고", "테스트할 부품 동작이 없습니다.")
            return

        # 긴급 정지 버튼 활성화
        if hasattr(self, 'btn_emergency_stop_macro'):
            self.btn_emergency_stop_macro.config(state="normal")

        def _run():
            self.set_status("▶ 부품 테스트 실행 중...")
            self.engine.is_running = True
            self.engine.run_macro_steps(self.current_macro, self.set_status)
            self.engine.is_running = False
            self.set_status("✅ 부품 테스트 실행 완료")
            # 실행 완료 후 버튼 비활성화
            if hasattr(self, 'btn_emergency_stop_macro'):
                self.btn_emergency_stop_macro.config(state="disabled")

        threading.Thread(target=_run, daemon=True).start()

    # ---------- 조립 공장 로직 ----------
    def refresh_macro_source(self):
        self.list_macro_source.delete(0, "end")
        for name in self.engine.macros:
            self.list_macro_source.insert("end", name)

    def add_macro_to_job(self, event):
        sels = self.list_macro_source.curselection()
        if not sels:
            return
        name = self.list_macro_source.get(sels[0])
        self.current_job_steps.append({"type": "call_macro", "value": name})
        self.refresh_job_view()

    def add_joint_list(self):
        top = tk.Toplevel(self.root)
        top.title("직접입력 반복 값")
        top.geometry("420x420")

        tk.Label(
            top,
            text="한 줄에 하나씩 값을 입력하세요.\n예) 차량번호 목록, 이름 목록 등\n\n💡 팁: 부품에서 '입력' 스텝에 {i}를 사용하면\n   각 줄의 값이 자동으로 입력됩니다.",
            pady=6,
            justify="left",
        ).pack()
        txt = tk.Text(top, width=40, height=16)
        txt.pack(padx=8, pady=4)
        txt.focus_set()

        def _ok():
            content = txt.get("1.0", "end-1c").strip()
            if not content:
                top.destroy()
                return
            self.current_job_steps.append(
                {"type": "joint_list", "value": content}
            )
            self.refresh_job_view()
            top.destroy()

        tk.Button(top, text="확인", command=_ok, bg="#0969da", fg="white").pack(
            pady=6
        )

    def add_joint_start(self):
        choice = messagebox.askyesno(
            "반복 종류 선택",
            "엑셀 파일을 기준으로 반복하시겠습니까?\n\n예: 엑셀 반복 / 아니오: 횟수 반복",
        )
        if choice:
            fpath = filedialog.askopenfilename(
                title="반복에 사용할 엑셀 파일 선택",
                filetypes=[("Excel 파일", "*.xlsx;*.xls")],
            )
            if not fpath:
                return
            self.current_job_steps.append(
                {"type": "joint_start", "value": fpath}
            )
        else:
            cnt = simpledialog.askinteger("횟수 반복", "반복 횟수를 입력하세요:", minvalue=1)
            if not cnt:
                return
            self.current_job_steps.append(
                {"type": "joint_start", "value": str(cnt)}
            )
        self.refresh_job_view()

    def add_joint_end(self):
        self.current_job_steps.append({"type": "joint_end", "value": ""})
        self.refresh_job_view()

    def refresh_job_view(self):
        self.list_job.delete(0, "end")
        indent = 0
        for i, st in enumerate(self.current_job_steps):
            t = st["type"]
            v = st.get("value", "")
            if t == "joint_end":
                indent = max(0, indent - 1)
            prefix = "    " * indent
            if indent > 0:
                prefix += "└ "

            text = ""
            if t == "call_macro":
                text = f"🧩 부품: {v}"
            elif t == "joint_start":
                sval = str(v)
                if sval.lower().endswith((".xlsx", ".xls")):
                    text = f"🔁 [엑셀 반복 시작] ({os.path.basename(sval)})"
                else:
                    text = f"🔁 [횟수 반복 시작] ({sval}회)"
            elif t == "joint_list":
                lines = str(v).split("\n")
                preview = lines[0].strip() if lines else ""
                if len(lines) > 1:
                    preview += f" 외 {len(lines)-1}줄"
                text = f"📝 [직접입력 반복 시작] {preview}"
            elif t == "joint_end":
                text = "⏹ [반복 끝] (바로 위의 시작지점까지 반복)"

            self.list_job.insert("end", f"{prefix}{i+1}. {text}")
            if t in ("joint_start", "joint_list"):
                indent += 1

    def move_job_step(self, d):
        sels = self.list_job.curselection()
        if len(sels) != 1:
            return
        i = sels[0]
        j = i + d
        if 0 <= j < len(self.current_job_steps):
            self.current_job_steps[i], self.current_job_steps[j] = (
                self.current_job_steps[j],
                self.current_job_steps[i],
            )
            self.refresh_job_view()
            self.list_job.select_set(j)

    def delete_job_step(self):
        sels = self.list_job.curselection()
        if not sels:
            return
        idx = sels[0]
        del self.current_job_steps[idx]
        self.refresh_job_view()

    def clear_job(self):
        self.current_job_steps = []
        self.refresh_job_view()

    def save_job(self):
        name = self.entry_job_name.get().strip()
        if not name:
            messagebox.showwarning("경고", "작업 이름을 입력하세요.")
            return
        self.engine.jobs[name] = self.current_job_steps
        self.engine.save_all()
        self.combo_jobs["values"] = list(self.engine.jobs.keys())
        messagebox.showinfo("저장", f"작업 '{name}' 저장 완료")

    def load_job(self, event):
        name = self.combo_jobs.get()
        if not name:
            return
        self.current_job_steps = self.engine.jobs.get(name, [])
        self.refresh_job_view()
        self.entry_job_name.delete(0, "end")
        self.entry_job_name.insert(0, name)

    def delete_job(self):
        name = self.combo_jobs.get()
        if not name:
            return
        if not messagebox.askyesno("삭제", f"작업 '{name}' 을(를) 삭제할까요?"):
            return
        self.engine.jobs.pop(name, None)
        self.engine.save_all()
        self.combo_jobs.set("")
        self.combo_jobs["values"] = list(self.engine.jobs.keys())

    def export_job_local(self):
        """조립품 로컬 파일로 저장하기"""
        name = self.entry_job_name.get().strip()
        if not name and not self.current_job_steps:
            messagebox.showwarning("경고", "저장할 조립품이 없습니다.")
            return
        
        if not name:
            name = simpledialog.askstring("작업 이름", "저장할 조립품 이름을 입력하세요:")
            if not name:
                return
        
        file_path = filedialog.asksaveasfilename(
            title="조립품 파일 저장",
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")],
            initialfile=f"{name}.zip"
        )
        
        if not file_path:
            return
        
        try:
            steps = self.current_job_steps if self.current_job_steps else self.engine.jobs.get(name, [])
            metadata = {"author": "", "description": "", "price": 0}
            if self.engine.export_job(name, steps, file_path, metadata):
                messagebox.showinfo("성공", f"조립품 '{name}' 파일이 저장되었습니다.\n\n파일: {file_path}")
            else:
                messagebox.showerror("오류", "조립품 저장에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"조립품 저장 중 오류가 발생했습니다:\n{e}")
    
    def import_job_local(self):
        """조립품 로컬 파일에서 불러오기"""
        file_path = filedialog.askopenfilename(
            title="조립품 파일 선택",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            result = self.engine.import_job(file_path)
            if result:
                name = result["name"]
                messagebox.showinfo("성공", f"조립품 '{name}' 불러오기 완료!")
                self.combo_jobs["values"] = list(self.engine.jobs.keys())
                self.combo_jobs.set(name)
                self.load_job(None)
            else:
                messagebox.showerror("오류", "조립품 불러오기에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"조립품 불러오기 중 오류가 발생했습니다:\n{e}")
    
    def sell_job(self):
        """조립품 웹 게시판에 판매하기 - Streamlit 사이트로 바로 이동"""
        # Streamlit Cloud URL로 바로 이동
        marketplace_url = "https://marketplaceserver1-n8arrrkmjvyrqtmraftrpm.streamlit.app/"
        webbrowser.open(marketplace_url)
        messagebox.showinfo("마켓플레이스", f"마켓플레이스 사이트가 열렸습니다.\n\n{marketplace_url}\n\n사이트에서 로그인 후 판매하세요.")
    
    def buy_job(self):
        """조립품 웹 게시판에서 구매하기 (로그인 없이 목록 조회 가능)"""
        # 아이템 목록 조회 (로그인 불필요)
        success, items = self.marketplace.list_items("job")
        if not success:
            messagebox.showerror("오류", f"아이템 목록 조회 실패:\n{items}")
            return
        
        if not items:
            messagebox.showinfo("알림", "판매 중인 조립품이 없습니다.")
            return
        
        # 아이템 선택 다이얼로그
        top = tk.Toplevel(self.root)
        top.title("조립품 마켓플레이스")
        top.geometry("600x500")
        top.transient(self.root)
        top.grab_set()
        
        tk.Label(top, text="구매할 조립품을 선택하세요 (로그인 없이 조회 가능):", pady=4).pack(anchor="w", padx=10, pady=(10, 0))
        
        # 리스트박스
        listbox = tk.Listbox(top, width=70, height=15)
        listbox.pack(fill="both", expand=True, padx=10, pady=4)
        
        for item in items:
            name = item.get("name", "")
            author = item.get("author", "")
            price = item.get("price", 0)
            desc = item.get("description", "")[:30]
            item_id = item.get("id", "")
            price_text = f"{price}P" if price > 0 else "무료"
            display = f"[{item_id}] {name} | 작성자: {author} | 가격: {price_text} | {desc}"
            listbox.insert("end", display)
        
        def _buy():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("경고", "조립품을 선택하세요.")
                return
            
            # 구매 시에만 로그인 확인
            if not self.marketplace.user_token:
                if not self._show_login_dialog():
                    messagebox.showinfo("알림", "구매하려면 로그인이 필요합니다.")
                    return
            
            selected_item = items[selection[0]]
            item_id = selected_item.get("id")
            item_name = selected_item.get("name", "")
            price = selected_item.get("price", 0)
            
            if price > 0:
                current_points = self.marketplace.get_points()
                if not messagebox.askyesno("구매 확인", f"'{item_name}' 구매하시겠습니까?\n가격: {price}포인트\n현재 포인트: {current_points}P"):
                    return
            
            top.destroy()
            
            # 다운로드
            success, zip_path, msg = self.marketplace.download_item(item_id)
            if success:
                try:
                    result = self.engine.import_job(zip_path)
                    if result:
                        name = result["name"]
                        messagebox.showinfo("성공", f"조립품 '{name}' 구매 완료!\n\n{msg}\n포인트: {self.marketplace.points}P")
                        self._update_points_display()
                        self.combo_jobs["values"] = list(self.engine.jobs.keys())
                        self.combo_jobs.set(name)
                        self.load_job(None)
                finally:
                    if zip_path and os.path.exists(zip_path):
                        os.remove(zip_path)
            else:
                messagebox.showerror("오류", f"구매 실패:\n{msg}")
        
        tk.Button(top, text="구매하기 (로그인 필요)", command=_buy, bg="#28a745", fg="white").pack(pady=10)

    def emergency_stop(self):
        """긴급 정지"""
        self.engine.is_running = False
        self.set_status("🛑 긴급 정지 요청됨...")
        # 버튼 비활성화
        if hasattr(self, 'btn_emergency_stop'):
            self.btn_emergency_stop.config(state="disabled")
        if hasattr(self, 'btn_emergency_stop_macro'):
            self.btn_emergency_stop_macro.config(state="disabled")
        messagebox.showinfo("긴급 정지", "매크로 실행이 중지되었습니다.")
    
    def run_current_job(self):
        if not self.current_job_steps:
            messagebox.showwarning("경고", "조립 라인에 실행할 내용이 없습니다.")
            return

        if self.var_hide_window.get() == 1:
            self.root.iconify()

        # 긴급 정지 버튼 활성화
        if hasattr(self, 'btn_emergency_stop'):
            self.btn_emergency_stop.config(state="normal")

        def _run():
            self.engine.is_running = True
            self.engine.run_steps(self.current_job_steps, self.set_status)
            # 실행 완료 후 버튼 비활성화
            if hasattr(self, 'btn_emergency_stop'):
                self.btn_emergency_stop.config(state="disabled")

        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
