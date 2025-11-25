"""
웹 게시판 마켓플레이스 서버 (Streamlit + FastAPI)
행정망 환경에서도 작동하도록 구성
"""

import streamlit as st
import sqlite3
import json
import os
import hashlib
import secrets
import base64
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ==========================================
# 데이터베이스 설정
# ==========================================

DB_FILE = "marketplace.db"

def init_db():
    """데이터베이스 초기화"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 사용자 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            points INTEGER DEFAULT 100,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 아이템 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,
            name TEXT NOT NULL,
            author TEXT NOT NULL,
            description TEXT,
            price INTEGER DEFAULT 0,
            zip_data BLOB NOT NULL,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            download_count INTEGER DEFAULT 0
        )
    ''')
    
    # 거래 기록 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items(id)
        )
    ''')
    
    # 토큰 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ==========================================
# FastAPI 서버
# ==========================================

app = FastAPI(title="마켓플레이스 API")

# CORS 설정 (행정망 환경 고려)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic 모델
class LoginRequest(BaseModel):
    user_id: str
    password: str

class UploadRequest(BaseModel):
    type: str
    name: str
    zip_data: str  # base64
    metadata: dict

class DownloadRequest(BaseModel):
    item_id: int

class RegisterRequest(BaseModel):
    user_id: str
    password: str

# 헬퍼 함수
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_token(token: str) -> str:
    """토큰 검증 및 사용자 ID 반환"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM tokens WHERE token = ? AND expires_at > datetime('now')", (token,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def get_user_points(user_id: str) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def update_user_points(user_id: str, points: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET points = ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()

# API 엔드포인트
@app.post("/api/register")
async def register(request: RegisterRequest):
    """회원가입"""
    conn = get_db()
    c = conn.cursor()
    
    # 중복 확인
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (request.user_id,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="이미 존재하는 사용자 ID입니다.")
    
    # 사용자 생성
    password_hash = hash_password(request.password)
    c.execute("INSERT INTO users (user_id, password_hash, points) VALUES (?, ?, ?)",
              (request.user_id, password_hash, 100))  # 신규 사용자에게 100포인트 지급
    
    conn.commit()
    conn.close()
    
    return {"success": True, "message": "회원가입 성공! 100포인트가 지급되었습니다."}

@app.post("/api/login")
async def login(request: LoginRequest):
    """로그인"""
    conn = get_db()
    c = conn.cursor()
    
    # 사용자 확인
    password_hash = hash_password(request.password)
    c.execute("SELECT user_id, points FROM users WHERE user_id = ? AND password_hash = ?", 
              (request.user_id, password_hash))
    user = c.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 잘못되었습니다.")
    
    # 토큰 생성
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now().replace(hour=23, minute=59, second=59).isoformat()
    
    # 기존 토큰 삭제
    c.execute("DELETE FROM tokens WHERE user_id = ?", (request.user_id,))
    
    # 새 토큰 저장
    c.execute("INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
              (token, request.user_id, expires_at))
    
    conn.commit()
    conn.close()
    
    return {
        "token": token,
        "points": user[1],
        "user_id": request.user_id
    }

@app.get("/api/points")
async def get_points(authorization: str = Header(None)):
    """포인트 조회"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    
    token = authorization.replace("Bearer ", "")
    user_id = verify_token(token)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    
    points = get_user_points(user_id)
    return {"points": points}

@app.get("/api/items")
async def list_items(item_type: str = "macro"):
    """아이템 목록 조회"""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, item_type, name, author, description, price, download_count, created_at
        FROM items 
        WHERE item_type = ?
        ORDER BY created_at DESC
    """, (item_type,))
    
    items = []
    for row in c.fetchall():
        items.append({
            "id": row[0],
            "type": row[1],
            "name": row[2],
            "author": row[3],
            "description": row[4],
            "price": row[5],
            "download_count": row[6],
            "created_at": row[7]
        })
    
    conn.close()
    return {"items": items}

@app.post("/api/upload")
async def upload_item(request: UploadRequest, authorization: str = Header(None)):
    """아이템 업로드 (판매하기)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    
    token = authorization.replace("Bearer ", "")
    user_id = verify_token(token)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    
    # ZIP 데이터 디코딩
    try:
        zip_data = base64.b64decode(request.zip_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ZIP 데이터 디코딩 실패: {e}")
    
    # 데이터베이스에 저장
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO items (item_type, name, author, description, price, zip_data, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        request.type,
        request.name,
        user_id,
        request.metadata.get("description", ""),
        request.metadata.get("price", 0),
        zip_data,
        json.dumps(request.metadata, ensure_ascii=False)
    ))
    
    # 판매자에게 포인트 지급 (판매 가격의 10% 보너스)
    bonus = int(request.metadata.get("price", 0) * 0.1)
    if bonus > 0:
        current_points = get_user_points(user_id)
        update_user_points(user_id, current_points + bonus)
    
    conn.commit()
    item_id = c.lastrowid
    conn.close()
    
    return {
        "success": True,
        "item_id": item_id,
        "points": get_user_points(user_id),
        "message": "업로드 성공"
    }

@app.post("/api/download")
async def download_item(request: DownloadRequest, authorization: str = Header(None)):
    """아이템 다운로드 (구매하기)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    
    token = authorization.replace("Bearer ", "")
    user_id = verify_token(token)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    
    conn = get_db()
    c = conn.cursor()
    
    # 아이템 조회
    c.execute("SELECT price, zip_data, author FROM items WHERE id = ?", (request.item_id,))
    item = c.fetchone()
    
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="아이템을 찾을 수 없습니다.")
    
    price = item[0]
    zip_data = item[1]
    author = item[2]
    
    # 본인이 올린 아이템은 무료
    if author == user_id:
        price = 0
    
    # 포인트 확인
    current_points = get_user_points(user_id)
    if current_points < price:
        conn.close()
        raise HTTPException(status_code=400, detail=f"포인트가 부족합니다. (필요: {price}P, 보유: {current_points}P)")
    
    # 포인트 차감
    if price > 0:
        update_user_points(user_id, current_points - price)
        
        # 판매자에게 포인트 지급
        seller_points = get_user_points(author)
        update_user_points(author, seller_points + price)
        
        # 거래 기록
        c.execute("INSERT INTO transactions (buyer_id, item_id, price) VALUES (?, ?, ?)",
                  (user_id, request.item_id, price))
    
    # 다운로드 횟수 증가
    c.execute("UPDATE items SET download_count = download_count + 1 WHERE id = ?", (request.item_id,))
    
    conn.commit()
    conn.close()
    
    # ZIP 데이터 base64 인코딩
    zip_base64 = base64.b64encode(zip_data).decode("utf-8")
    
    return {
        "zip_data": zip_base64,
        "points": get_user_points(user_id),
        "message": "다운로드 성공"
    }

# ==========================================
# Streamlit 관리 UI
# ==========================================

def streamlit_app():
    """Streamlit 관리 인터페이스"""
    st.set_page_config(
        page_title="마켓플레이스 관리",
        page_icon="🛒",
        layout="wide"
    )
    
    # 세션 상태 초기화
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "user_token" not in st.session_state:
        st.session_state.user_token = None
    
    # 로그인 페이지
    if not st.session_state.logged_in:
        st.title("🛒 마켓플레이스 로그인")
        
        tab_login, tab_register = st.tabs(["🔐 로그인", "📝 회원가입"])
        
        with tab_login:
            st.header("로그인")
            login_user_id = st.text_input("사용자 ID", key="login_id")
            login_password = st.text_input("비밀번호", type="password", key="login_pw")
            
            if st.button("로그인", type="primary"):
                if login_user_id and login_password:
                    try:
                        import requests
                        response = requests.post(
                            "http://localhost:8000/api/login",
                            json={"user_id": login_user_id, "password": login_password},
                            timeout=5
                        )
                        if response.status_code == 200:
                            data = response.json()
                            st.session_state.logged_in = True
                            st.session_state.user_id = data["user_id"]
                            st.session_state.user_token = data["token"]
                            st.success(f"로그인 성공! 포인트: {data['points']}P")
                            st.rerun()
                        else:
                            st.error(response.json().get("detail", "로그인 실패"))
                    except Exception as e:
                        st.error(f"서버 연결 실패: {e}")
                else:
                    st.warning("ID와 비밀번호를 입력하세요.")
        
        with tab_register:
            st.header("회원가입")
            reg_user_id = st.text_input("사용자 ID", key="reg_id")
            reg_password = st.text_input("비밀번호", type="password", key="reg_pw")
            reg_password_confirm = st.text_input("비밀번호 확인", type="password", key="reg_pw_confirm")
            
            if st.button("회원가입", type="primary"):
                if reg_user_id and reg_password:
                    if reg_password != reg_password_confirm:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        try:
                            import requests
                            response = requests.post(
                                "http://localhost:8000/api/register",
                                json={"user_id": reg_user_id, "password": reg_password},
                                timeout=5
                            )
                            if response.status_code == 200:
                                st.success("회원가입 성공! 로그인 탭에서 로그인하세요.")
                            else:
                                st.error(response.json().get("detail", "회원가입 실패"))
                        except Exception as e:
                            st.error(f"서버 연결 실패: {e}")
                else:
                    st.warning("ID와 비밀번호를 입력하세요.")
        
        # 테스트용 사용자 생성 버튼
        with st.sidebar:
            st.header("테스트")
            if st.button("🧪 테스트 사용자 생성"):
                try:
                    import requests
                    test_id = "test_user"
                    test_pw = "test123"
                    response = requests.post(
                        "http://localhost:8000/api/register",
                        json={"user_id": test_id, "password": test_pw},
                        timeout=5
                    )
                    if response.status_code == 200:
                        st.success(f"테스트 사용자 생성 완료!\nID: {test_id}\nPW: {test_pw}")
                    else:
                        st.info("이미 존재하는 사용자입니다.")
                except Exception as e:
                    st.error(f"오류: {e}")
        
        return
    
    # 로그인 후 메인 페이지
    st.title("🛒 마켓플레이스 관리 시스템")
    
    # 사이드바
    with st.sidebar:
        st.header("사용자 정보")
        st.success(f"✅ {st.session_state.user_id}님")
        
        # 포인트 조회
        try:
            import requests
            response = requests.get(
                "http://localhost:8000/api/points",
                headers={"Authorization": f"Bearer {st.session_state.user_token}"},
                timeout=5
            )
            if response.status_code == 200:
                points = response.json().get("points", 0)
                st.metric("포인트", f"{points}P")
        except:
            pass
        
        if st.button("🚪 로그아웃"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.user_token = None
            st.rerun()
        
        st.divider()
        st.header("서버 상태")
        st.success("✅ 서버 실행 중")
        st.info(f"포트: 8000")
        
        if st.button("🔄 데이터베이스 초기화"):
            init_db()
            st.success("데이터베이스 초기화 완료")
    
    # 탭
    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "👥 사용자 관리", "📦 아이템 관리", "💰 거래 내역"])
    
    with tab1:
        st.header("📊 대시보드")
        
        conn = get_db()
        c = conn.cursor()
        
        # 통계
        col1, col2, col3, col4 = st.columns(4)
        
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        col1.metric("총 사용자", user_count)
        
        c.execute("SELECT COUNT(*) FROM items")
        item_count = c.fetchone()[0]
        col2.metric("총 아이템", item_count)
        
        c.execute("SELECT SUM(price) FROM transactions")
        total_revenue = c.fetchone()[0] or 0
        col3.metric("총 거래액", f"{total_revenue}P")
        
        c.execute("SELECT COUNT(*) FROM transactions")
        transaction_count = c.fetchone()[0]
        col4.metric("총 거래 수", transaction_count)
        
        # 최근 아이템
        st.subheader("최근 등록된 아이템")
        c.execute("""
            SELECT id, item_type, name, author, price, download_count, created_at
            FROM items
            ORDER BY created_at DESC
            LIMIT 10
        """)
        
        items = c.fetchall()
        if items:
            for item in items:
                with st.expander(f"[{item[1]}] {item[2]} - {item[3]} ({item[4]}P)"):
                    st.write(f"**ID:** {item[0]}")
                    st.write(f"**다운로드 수:** {item[5]}")
                    st.write(f"**등록일:** {item[6]}")
        else:
            st.info("등록된 아이템이 없습니다.")
        
        conn.close()
    
    with tab2:
        st.header("👥 사용자 관리")
        
        conn = get_db()
        c = conn.cursor()
        
        # 사용자 목록
        c.execute("SELECT user_id, points, created_at FROM users ORDER BY created_at DESC")
        users = c.fetchall()
        
        if users:
            st.dataframe(
                [[u[0], u[1], u[2]] for u in users],
                columns=["사용자 ID", "포인트", "가입일"],
                use_container_width=True
            )
        else:
            st.info("등록된 사용자가 없습니다.")
        
        # 포인트 수동 조정
        st.subheader("포인트 수동 조정")
        user_id = st.text_input("사용자 ID")
        points = st.number_input("포인트", value=0, step=10)
        
        if st.button("포인트 조정"):
            if user_id:
                current = get_user_points(user_id)
                update_user_points(user_id, points)
                st.success(f"{user_id}의 포인트를 {current}에서 {points}로 변경했습니다.")
            else:
                st.error("사용자 ID를 입력하세요.")
        
        conn.close()
    
    with tab3:
        st.header("📦 아이템 관리")
        
        conn = get_db()
        c = conn.cursor()
        
        # 아이템 목록
        c.execute("""
            SELECT id, item_type, name, author, price, download_count, created_at
            FROM items
            ORDER BY created_at DESC
        """)
        items = c.fetchall()
        
        if items:
            for item in items:
                with st.expander(f"[{item[1]}] {item[2]} - {item[3]} ({item[4]}P, 다운로드: {item[5]})"):
                    col1, col2 = st.columns(2)
                    col1.write(f"**ID:** {item[0]}")
                    col1.write(f"**타입:** {item[1]}")
                    col1.write(f"**작성자:** {item[3]}")
                    col2.write(f"**가격:** {item[4]}P")
                    col2.write(f"**다운로드 수:** {item[5]}")
                    col2.write(f"**등록일:** {item[6]}")
                    
                    if st.button(f"삭제", key=f"delete_{item[0]}"):
                        c.execute("DELETE FROM items WHERE id = ?", (item[0],))
                        conn.commit()
                        st.success("삭제되었습니다.")
                        st.rerun()
        else:
            st.info("등록된 아이템이 없습니다.")
        
        conn.close()
    
    with tab4:
        st.header("💰 거래 내역")
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute("""
            SELECT t.id, t.buyer_id, i.name, t.price, t.created_at
            FROM transactions t
            JOIN items i ON t.item_id = i.id
            ORDER BY t.created_at DESC
            LIMIT 50
        """)
        
        transactions = c.fetchall()
        
        if transactions:
            st.dataframe(
                [[t[0], t[1], t[2], t[3], t[4]] for t in transactions],
                columns=["ID", "구매자", "아이템", "가격", "거래일"],
                use_container_width=True
            )
        else:
            st.info("거래 내역이 없습니다.")
        
        conn.close()

# ==========================================
# 서버 실행
# ==========================================

def run_fastapi():
    """FastAPI 서버 실행"""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

# 데이터베이스 초기화 (모듈 로드 시)
init_db()

# Streamlit 실행 시 FastAPI 서버 자동 시작
import threading
import time

def start_api_server():
    """FastAPI 서버를 백그라운드에서 시작"""
    time.sleep(1)  # Streamlit 시작 대기
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    except Exception as e:
        pass  # 이미 실행 중일 수 있음

# 백그라운드 스레드에서 API 서버 시작
api_thread = threading.Thread(target=start_api_server, daemon=True)
api_thread.start()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        # API 서버만 실행
        print("🚀 FastAPI 서버 시작: http://localhost:8000")
        print("📚 API 문서: http://localhost:8000/docs")
        run_fastapi()
    else:
        # Streamlit UI 실행
        print("🛒 Streamlit UI 시작 중...")
        print("🚀 FastAPI 서버도 자동으로 시작됩니다: http://localhost:8000")
        streamlit_app()

