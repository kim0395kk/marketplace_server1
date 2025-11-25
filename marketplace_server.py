"""
웹 게시판 마켓플레이스 서버 (Streamlit)
Streamlit Cloud 호환 버전
"""

import streamlit as st
import sqlite3
import json
import os
import hashlib
import secrets
import base64
from datetime import datetime

# Streamlit Cloud 체크 (여러 방법으로 확인)
IS_STREAMLIT_CLOUD = (
    os.environ.get("STREAMLIT_SERVER_PORT") is not None or
    os.environ.get("STREAMLIT_CLOUD") is not None or
    "streamlit.app" in os.environ.get("_", "")
)

# FastAPI는 로컬에서만 사용
if not IS_STREAMLIT_CLOUD:
    try:
        from fastapi import FastAPI, HTTPException, Depends, Header
        from fastapi.responses import JSONResponse
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
        import uvicorn
        FASTAPI_AVAILABLE = True
    except ImportError:
        FASTAPI_AVAILABLE = False
else:
    FASTAPI_AVAILABLE = False

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
# FastAPI 서버 (로컬에서만)
# ==========================================

if FASTAPI_AVAILABLE:
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
else:
    app = None

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

# API 엔드포인트 (FastAPI가 사용 가능할 때만)
if FASTAPI_AVAILABLE and app:
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
    """Streamlit 마켓플레이스 (인스타그램 + 깃허브 스타일)"""
    st.set_page_config(
        page_title="마켓플레이스",
        page_icon="🛒",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # 인스타그램 스타일 CSS (반응형 그리드)
    st.markdown("""
    <style>
    .main {
        padding-top: 1rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
    }
    
    /* 반응형 그리드 컨테이너 - 유동적 배치 */
    .items-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 16px;
        padding: 16px 0;
    }
    
    /* 최대 5개까지 표시 */
    @media (min-width: 1200px) {
        .items-grid {
            grid-template-columns: repeat(5, 1fr);
        }
    }
    
    /* 중간 크기: 4개 */
    @media (min-width: 960px) and (max-width: 1199px) {
        .items-grid {
            grid-template-columns: repeat(4, 1fr);
        }
    }
    
    /* 작은 화면: 3개 */
    @media (min-width: 720px) and (max-width: 959px) {
        .items-grid {
            grid-template-columns: repeat(3, 1fr);
        }
    }
    
    /* 더 작은 화면: 2개 */
    @media (min-width: 480px) and (max-width: 719px) {
        .items-grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }
    
    /* 모바일: 1개 */
    @media (max-width: 479px) {
        .items-grid {
            grid-template-columns: 1fr;
        }
    }
    
    /* 인스타그램 스타일 카드 */
    .instagram-card {
        background: white;
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .instagram-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 30px rgba(0,0,0,0.2);
    }
    
    .card-image {
        width: 100%;
        height: 200px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 60px;
        position: relative;
        overflow: hidden;
        flex-shrink: 0;
    }
    
    .card-image::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: linear-gradient(45deg, transparent, rgba(255,255,255,0.1), transparent);
        animation: shine 3s infinite;
    }
    
    @keyframes shine {
        0% { transform: translateX(-100%) translateY(-100%) rotate(45deg); }
        100% { transform: translateX(100%) translateY(100%) rotate(45deg); }
    }
    
    .card-content {
        padding: 16px;
        flex: 1;
        display: flex;
        flex-direction: column;
    }
    
    .card-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1a1a1a;
        margin: 0 0 6px 0;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    
    .card-meta {
        color: #8e8e8e;
        font-size: 0.8rem;
        margin-bottom: 8px;
    }
    
    .card-price {
        font-size: 1.5rem;
        font-weight: 800;
        color: #FF6F0F;
        margin: 8px 0;
    }
    
    .card-desc {
        color: #262626;
        line-height: 1.5;
        margin: 8px 0;
        padding: 10px;
        background: #fafafa;
        border-radius: 8px;
        font-size: 0.85rem;
        flex: 1;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border: none;
        font-size: 0.9rem;
    }
    
    .stButton>button:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 세션 상태 초기화
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "user_token" not in st.session_state:
        st.session_state.user_token = None
    if "current_tab" not in st.session_state:
        st.session_state.current_tab = "마켓플레이스"
    
    # 사이드바 (로그인/회원가입)
    with st.sidebar:
        st.markdown("### 🦦 충주씨 마켓플레이스")
        
        if st.session_state.logged_in:
            st.success(f"✅ {st.session_state.user_id}님")
            try:
                if IS_STREAMLIT_CLOUD or not FASTAPI_AVAILABLE:
                    points = get_user_points(st.session_state.user_id)
                else:
                    import requests
                    response = requests.get(
                        "http://localhost:8000/api/points",
                        headers={"Authorization": f"Bearer {st.session_state.user_token}"},
                        timeout=5
                    )
                    points = response.json().get("points", 0) if response.status_code == 200 else 0
                st.metric("포인트", f"{points}P")
            except:
                pass
            
            if st.button("🚪 로그아웃", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.user_id = None
                st.session_state.user_token = None
                st.rerun()
        else:
            st.header("🔐 로그인")
            login_user_id = st.text_input("사용자 ID", key="login_id")
            login_password = st.text_input("비밀번호", type="password", key="login_pw")
            
            if st.button("로그인", type="primary", use_container_width=True):
                if login_user_id and login_password:
                    try:
                        if IS_STREAMLIT_CLOUD or not FASTAPI_AVAILABLE:
                            conn = get_db()
                            c = conn.cursor()
                            password_hash = hash_password(login_password)
                            c.execute("SELECT user_id, points FROM users WHERE user_id = ? AND password_hash = ?", 
                                      (login_user_id, password_hash))
                            user = c.fetchone()
                            
                            if user:
                                token = secrets.token_urlsafe(32)
                                expires_at = datetime.now().replace(hour=23, minute=59, second=59).isoformat()
                                c.execute("DELETE FROM tokens WHERE user_id = ?", (login_user_id,))
                                c.execute("INSERT INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                                          (token, login_user_id, expires_at))
                                conn.commit()
                                conn.close()
                                
                                st.session_state.logged_in = True
                                st.session_state.user_id = login_user_id
                                st.session_state.user_token = token
                                st.success("로그인 성공!")
                                st.rerun()
                            else:
                                conn.close()
                                st.error("아이디 또는 비밀번호가 잘못되었습니다.")
                        else:
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
                                st.success("로그인 성공!")
                                st.rerun()
                            else:
                                st.error("로그인 실패")
                    except Exception as e:
                        st.error(f"로그인 실패: {e}")
            
            st.divider()
            st.header("📝 회원가입")
            reg_user_id = st.text_input("사용자 ID", key="reg_id")
            reg_password = st.text_input("비밀번호", type="password", key="reg_pw")
            reg_password_confirm = st.text_input("비밀번호 확인", type="password", key="reg_pw_confirm")
            
            if st.button("회원가입", use_container_width=True):
                if reg_user_id and reg_password:
                    if reg_password != reg_password_confirm:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        try:
                            if IS_STREAMLIT_CLOUD or not FASTAPI_AVAILABLE:
                                conn = get_db()
                                c = conn.cursor()
                                c.execute("SELECT user_id FROM users WHERE user_id = ?", (reg_user_id,))
                                if c.fetchone():
                                    conn.close()
                                    st.error("이미 존재하는 사용자 ID입니다.")
                                else:
                                    password_hash = hash_password(reg_password)
                                    c.execute("INSERT INTO users (user_id, password_hash, points) VALUES (?, ?, ?)",
                                              (reg_user_id, password_hash, 100))
                                    conn.commit()
                                    conn.close()
                                    st.success("회원가입 성공! 100포인트 지급")
                            else:
                                import requests
                                response = requests.post(
                                    "http://localhost:8000/api/register",
                                    json={"user_id": reg_user_id, "password": reg_password},
                                    timeout=5
                                )
                                if response.status_code == 200:
                                    st.success("회원가입 성공!")
                                else:
                                    st.error("회원가입 실패")
                        except Exception as e:
                            st.error(f"회원가입 실패: {e}")
    
    # 메인 페이지 - 마켓플레이스
    st.markdown("## 🦦 충주씨 자동화 부품 마켓플레이스")
    
    # 탭: 마켓플레이스, 판매하기, 내 상점
    tab_market, tab_sell, tab_my_shop = st.tabs(["🏪 마켓플레이스", "📤 판매하기", "🛍️ 내 상점"])
    
    # 아이템 목록 조회 함수
    def get_all_items():
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT id, item_type, name, author, description, price, download_count, created_at
            FROM items
            ORDER BY created_at DESC
        """)
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
        return items
    
    # 인스타그램 스타일 아이콘 생성
    def get_item_icon(item_id, item_name):
        """아이템에 맞는 이모지/아이콘 반환"""
        icons = ["🏛️", "🔐", "📊", "⚙️", "🤖", "💼", "🎯", "🚀", "✨", "🎨"]
        # 이름에 따라 아이콘 선택
        name_lower = item_name.lower()
        if "로그인" in item_name or "login" in name_lower:
            return "🔐"
        elif "엑셀" in item_name or "excel" in name_lower or "복사" in name_lower:
            return "📊"
        elif "민원" in item_name or "공무원" in item_name:
            return "🏛️"
        else:
            return icons[item_id % len(icons)]
    
    # 구매 처리 함수
    def _handle_purchase(item):
        try:
            if IS_STREAMLIT_CLOUD or not FASTAPI_AVAILABLE:
                user_id = st.session_state.user_id
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT price, zip_data, author FROM items WHERE id = ?", (item['id'],))
                item_data = c.fetchone()
                if item_data:
                    price = item_data[0] if item_data[2] != user_id else 0
                    zip_data = item_data[1]
                    current_points = get_user_points(user_id)
                    if current_points < price:
                        st.error(f"포인트가 부족합니다. (필요: {price}P, 보유: {current_points}P)")
                    else:
                        if price > 0:
                            update_user_points(user_id, current_points - price)
                            seller_points = get_user_points(item_data[2])
                            update_user_points(item_data[2], seller_points + price)
                            c.execute("INSERT INTO transactions (buyer_id, item_id, price) VALUES (?, ?, ?)",
                                      (user_id, item['id'], price))
                        c.execute("UPDATE items SET download_count = download_count + 1 WHERE id = ?", (item['id'],))
                        st.download_button(
                            label="📥 다운로드",
                            data=zip_data,
                            file_name=f"{item['name']}.zip",
                            mime="application/zip",
                            key=f"dl_{item['id']}"
                        )
                        st.success("✅ 구매 완료!")
                        conn.commit()
                        conn.close()
                        st.rerun()
        except Exception as e:
            st.error(f"구매 실패: {e}")
    
    # 인스타그램 스타일 카드 (그리드용)
    def show_item_card(item, show_download=True):
        is_sample = item.get('id', 0) >= 900
        icon = get_item_icon(item.get('id', 0), item['name'])
        
        desc = item.get('description', '')
        if not desc:
            name = item['name']
            if "로그인" in name or "login" in name.lower():
                desc = "🔐 자동 로그인 자동화"
            elif "엑셀" in name or "excel" in name.lower() or "복사" in name:
                desc = "📊 웹페이지에서 엑셀로 복사하기 자동화"
            elif "민원" in name or "공무원" in name:
                desc = "🏛️ 민원/공무원 프로그램 자동화"
            else:
                desc = f"⚙️ {item['type']} 자동화 부품"
        
        price_text = f"{item['price']:,}P" if item['price'] > 0 else "🆓 무료"
        
        # 그라데이션 색상 (아이템별로 다르게)
        gradients = [
            "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
            "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
            "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
            "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
        ]
        gradient = gradients[item.get('id', 0) % len(gradients)]
        
        # 인스타그램 스타일 카드 HTML
        card_html = f"""
        <div class="instagram-card">
            <div class="card-image" style="background: {gradient};">
                <div style="font-size: 60px; filter: drop-shadow(0 4px 8px rgba(0,0,0,0.2));">
                    {icon}
                </div>
            </div>
            <div class="card-content">
                <div class="card-title">{item['name']}</div>
                <div class="card-meta">
                    👤 {item['author']} • ⬇️ {item['download_count']}명
                </div>
                <div class="card-price">{price_text}</div>
                <div class="card-desc">
                    {desc.replace(chr(10), '<br>')}
                </div>
            </div>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)
        
        # 구매 버튼
        if show_download and not is_sample:
            if st.session_state.logged_in:
                if st.button("💬 구매", key=f"buy_{item['id']}", use_container_width=True, type="primary"):
                    _handle_purchase(item)
            else:
                st.caption("💡 로그인 필요")
        elif is_sample:
            st.caption("📝 샘플")
    
    # 마켓플레이스 탭
    with tab_market:
        st.header("🛍️ 부품 & 조립품 마켓")
        
        # 필터
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            filter_type = st.selectbox("타입", ["전체", "부품 (macro)", "조립품 (job)"], key="filter_type")
        with col_filter2:
            sort_by = st.selectbox("정렬", ["최신순", "인기순", "가격순"], key="sort_by")
        
        # 아이템 목록
        items = get_all_items()
        
        # 필터링
        if filter_type != "전체":
            type_filter = "macro" if "부품" in filter_type else "job"
            items = [i for i in items if i['type'] == type_filter]
        
        # 정렬
        if sort_by == "인기순":
            items.sort(key=lambda x: x['download_count'], reverse=True)
        elif sort_by == "가격순":
            items.sort(key=lambda x: x['price'])
        
        # 샘플 데이터 (16개)
        sample_items = [
            {
                "id": 999,
                "type": "macro",
                "name": "새올로그인 자동화",
                "author": "샘플",
                "description": "🔐 자동 로그인 자동화\n\n새올 시스템에 자동으로 로그인하는 부품입니다.",
                "price": 50,
                "download_count": 123,
                "created_at": "2024-01-15 10:30:00"
            },
            {
                "id": 998,
                "type": "macro",
                "name": "웹페이지에서 엑셀로 복사하기 자동화",
                "author": "샘플",
                "description": "📊 웹페이지에서 엑셀로 복사하기 자동화\n\n웹페이지의 데이터를 자동으로 복사하여 엑셀 파일로 저장합니다.",
                "price": 80,
                "download_count": 89,
                "created_at": "2024-01-14 15:20:00"
            },
            {
                "id": 997,
                "type": "macro",
                "name": "민원프로그램 모두 로그인 자동화",
                "author": "샘플",
                "description": "🏛️ 민원/공무원 프로그램 자동화\n\n민원 처리나 공무원 업무 프로그램을 자동으로 실행합니다.",
                "price": 100,
                "download_count": 156,
                "created_at": "2024-01-13 09:15:00"
            },
            {
                "id": 996,
                "type": "macro",
                "name": "엑셀 데이터 자동 입력",
                "author": "샘플",
                "description": "📝 엑셀 데이터 자동 입력\n\n엑셀 파일의 데이터를 자동으로 입력하는 부품입니다.",
                "price": 60,
                "download_count": 78,
                "created_at": "2024-01-12 14:00:00"
            },
            {
                "id": 995,
                "type": "macro",
                "name": "웹 폼 자동 작성",
                "author": "샘플",
                "description": "📋 웹 폼 자동 작성\n\n웹 폼에 자동으로 데이터를 입력하는 부품입니다.",
                "price": 70,
                "download_count": 92,
                "created_at": "2024-01-11 11:30:00"
            },
            {
                "id": 994,
                "type": "macro",
                "name": "이미지 자동 캡처",
                "author": "샘플",
                "description": "📸 이미지 자동 캡처\n\n화면의 특정 영역을 자동으로 캡처하는 부품입니다.",
                "price": 55,
                "download_count": 67,
                "created_at": "2024-01-10 09:20:00"
            },
            {
                "id": 993,
                "type": "macro",
                "name": "파일 자동 다운로드",
                "author": "샘플",
                "description": "💾 파일 자동 다운로드\n\n웹에서 파일을 자동으로 다운로드하는 부품입니다.",
                "price": 65,
                "download_count": 84,
                "created_at": "2024-01-09 16:45:00"
            },
            {
                "id": 992,
                "type": "macro",
                "name": "텍스트 자동 추출",
                "author": "샘플",
                "description": "📄 텍스트 자동 추출\n\n화면에서 텍스트를 자동으로 추출하는 부품입니다.",
                "price": 45,
                "download_count": 56,
                "created_at": "2024-01-08 13:15:00"
            },
            {
                "id": 991,
                "type": "macro",
                "name": "버튼 자동 클릭",
                "author": "샘플",
                "description": "🖱️ 버튼 자동 클릭\n\n특정 버튼을 자동으로 클릭하는 부품입니다.",
                "price": 40,
                "download_count": 112,
                "created_at": "2024-01-07 10:00:00"
            },
            {
                "id": 990,
                "type": "macro",
                "name": "데이터베이스 자동 조회",
                "author": "샘플",
                "description": "🗄️ 데이터베이스 자동 조회\n\n데이터베이스에서 정보를 자동으로 조회하는 부품입니다.",
                "price": 90,
                "download_count": 45,
                "created_at": "2024-01-06 15:30:00"
            },
            {
                "id": 989,
                "type": "macro",
                "name": "이메일 자동 발송",
                "author": "샘플",
                "description": "📧 이메일 자동 발송\n\n이메일을 자동으로 작성하고 발송하는 부품입니다.",
                "price": 75,
                "download_count": 38,
                "created_at": "2024-01-05 12:20:00"
            },
            {
                "id": 988,
                "type": "macro",
                "name": "PDF 자동 생성",
                "author": "샘플",
                "description": "📑 PDF 자동 생성\n\n데이터를 PDF 파일로 자동 변환하는 부품입니다.",
                "price": 85,
                "download_count": 52,
                "created_at": "2024-01-04 14:10:00"
            },
            {
                "id": 987,
                "type": "job",
                "name": "민원 처리 전체 자동화",
                "author": "샘플",
                "description": "🏭 민원 처리 전체 자동화\n\n민원 처리 전체 프로세스를 자동화하는 조립품입니다.",
                "price": 200,
                "download_count": 34,
                "created_at": "2024-01-03 11:00:00"
            },
            {
                "id": 986,
                "type": "job",
                "name": "보고서 작성 자동화",
                "author": "샘플",
                "description": "📊 보고서 작성 자동화\n\n데이터를 수집하여 보고서를 자동으로 작성하는 조립품입니다.",
                "price": 150,
                "download_count": 28,
                "created_at": "2024-01-02 09:30:00"
            },
            {
                "id": 985,
                "type": "job",
                "name": "데이터 수집 및 분석",
                "author": "샘플",
                "description": "📈 데이터 수집 및 분석\n\n여러 소스에서 데이터를 수집하고 분석하는 조립품입니다.",
                "price": 180,
                "download_count": 41,
                "created_at": "2024-01-01 16:00:00"
            },
            {
                "id": 984,
                "type": "job",
                "name": "문서 처리 자동화",
                "author": "샘플",
                "description": "📚 문서 처리 자동화\n\n문서를 자동으로 처리하고 분류하는 조립품입니다.",
                "price": 120,
                "download_count": 63,
                "created_at": "2023-12-31 10:15:00"
            }
        ]
        
        if not items:
            items = sample_items
            st.info("💡 현재 등록된 아이템이 없습니다. 아래는 샘플 아이템입니다.")
        
        # Streamlit 네이티브 방식으로 카드 표시 (반응형 그리드)
        # 5개씩 그룹으로 나누어 표시
        for i in range(0, len(items), 5):
            cols = st.columns(5)
            for j, col in enumerate(cols):
                if i + j < len(items):
                    item = items[i + j]
                    is_sample = item.get('id', 0) >= 900
                    icon = get_item_icon(item.get('id', 0), item['name'])
                    
                    desc = item.get('description', '')
                    if not desc:
                        name = item['name']
                        if "로그인" in name or "login" in name.lower():
                            desc = "🔐 자동 로그인 자동화"
                        elif "엑셀" in name or "excel" in name.lower() or "복사" in name:
                            desc = "📊 웹페이지에서 엑셀로 복사하기 자동화"
                        elif "민원" in name or "공무원" in name:
                            desc = "🏛️ 민원/공무원 프로그램 자동화"
                        else:
                            desc = f"⚙️ {item['type']} 자동화 부품"
                    
                    price_text = f"{item['price']:,}P" if item['price'] > 0 else "🆓 무료"
                    gradients = [
                        "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                        "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
                        "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
                        "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
                        "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
                    ]
                    gradient = gradients[item.get('id', 0) % len(gradients)]
                    
                    with col:
                        # 카드 컨테이너
                        with st.container():
                            # 카드 이미지 영역 (그라데이션 배경)
                            st.markdown(
                                f"""
                                <div style="
                                    background: {gradient};
                                    height: 200px;
                                    border-radius: 16px 16px 0 0;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    font-size: 60px;
                                    margin-bottom: 0;
                                ">
                                    {icon}
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                            
                            # 카드 내용 영역
                            st.markdown(
                                f"""
                                <div style="
                                    background: white;
                                    padding: 16px;
                                    border-radius: 0 0 16px 16px;
                                    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
                                    margin-bottom: 16px;
                                ">
                                    <div style="font-size: 1.1rem; font-weight: 700; color: #1a1a1a; margin-bottom: 8px;">
                                        {item['name']}
                                    </div>
                                    <div style="color: #8e8e8e; font-size: 0.85rem; margin-bottom: 8px;">
                                        👤 {item['author']} • ⬇️ {item['download_count']}명
                                    </div>
                                    <div style="font-size: 1.5rem; font-weight: 800; color: #FF6F0F; margin: 8px 0;">
                                        {price_text}
                                    </div>
                                    <div style="color: #262626; line-height: 1.5; font-size: 0.85rem; padding: 10px; background: #fafafa; border-radius: 8px;">
                                        {desc.replace(chr(10), '<br>')}
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                            
                            # 구매 버튼
                            if not is_sample:
                                if st.session_state.logged_in:
                                    if st.button("💬 구매", key=f"buy_{item['id']}", use_container_width=True, type="primary"):
                                        _handle_purchase(item)
                                else:
                                    st.caption("💡 로그인 필요")
                            else:
                                st.caption("📝 샘플")
    
    # 판매하기 탭
    with tab_sell:
        if not st.session_state.logged_in:
            st.info("💡 판매하려면 사이드바에서 로그인하세요.")
        else:
            st.header("📤 새 아이템 판매하기")
            
            with st.form("sell_form"):
                item_type = st.selectbox("타입", ["부품 (macro)", "조립품 (job)"])
                item_name = st.text_input("이름 *", placeholder="예: 자동 로그인 부품")
                item_description = st.text_area("설명", placeholder="이 부품의 기능과 사용법을 설명하세요...", height=100)
                item_price = st.number_input("가격 (포인트)", min_value=0, value=0, step=10)
                uploaded_file = st.file_uploader("ZIP 파일 업로드 *", type=['zip'])
                
                submitted = st.form_submit_button("🚀 판매 등록", type="primary", use_container_width=True)
                
                if submitted:
                    if not item_name or not uploaded_file:
                        st.error("이름과 ZIP 파일은 필수입니다.")
                    else:
                        try:
                            zip_data = uploaded_file.read()
                            conn = get_db()
                            c = conn.cursor()
                            
                            type_val = "macro" if "부품" in item_type else "job"
                            c.execute("""
                                INSERT INTO items (item_type, name, author, description, price, zip_data, metadata)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                type_val,
                                item_name,
                                st.session_state.user_id,
                                item_description,
                                item_price,
                                zip_data,
                                json.dumps({"description": item_description, "price": item_price}, ensure_ascii=False)
                            ))
                            
                            # 판매자에게 보너스 포인트
                            bonus = int(item_price * 0.1)
                            if bonus > 0:
                                current_points = get_user_points(st.session_state.user_id)
                                update_user_points(st.session_state.user_id, current_points + bonus)
                            
                            conn.commit()
                            conn.close()
                            st.success(f"✅ 판매 등록 완료! {'보너스 ' + str(bonus) + 'P 지급' if bonus > 0 else ''}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"등록 실패: {e}")
    
    # 내 상점 탭
    with tab_my_shop:
        if not st.session_state.logged_in:
            st.info("💡 내 상점을 보려면 사이드바에서 로그인하세요.")
        else:
            st.header("🛍️ 내 상점")
            
            # 내 아이템 목록
            my_items = [i for i in get_all_items() if i['author'] == st.session_state.user_id]
            
            if my_items:
                st.subheader(f"내가 판매한 아이템 ({len(my_items)}개)")
                for item in my_items:
                    with st.expander(f"{item['name']} - {item['price']}P"):
                        show_item_card(item, show_download=False)
                        if st.button(f"🗑️ 삭제", key=f"del_{item['id']}"):
                            conn = get_db()
                            c = conn.cursor()
                            c.execute("DELETE FROM items WHERE id = ?", (item['id'],))
                            conn.commit()
                            conn.close()
                            st.success("삭제되었습니다.")
                            st.rerun()
            else:
                st.info("판매한 아이템이 없습니다.")
    

# ==========================================
# 서버 실행
# ==========================================

# 데이터베이스 초기화 (모듈 로드 시)
init_db()

# Streamlit Cloud가 아닐 때만 FastAPI 서버 시작
if FASTAPI_AVAILABLE and app:
    def run_fastapi():
        """FastAPI 서버 실행"""
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    
    # Streamlit 실행 시 FastAPI 서버 자동 시작 (로컬에서만)
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
    if FASTAPI_AVAILABLE and app and len(sys.argv) > 1 and sys.argv[1] == "api":
        # API 서버만 실행 (로컬에서만)
        print("🚀 FastAPI 서버 시작: http://localhost:8000")
        print("📚 API 문서: http://localhost:8000/docs")
        run_fastapi()
    else:
        # Streamlit UI 실행
        if IS_STREAMLIT_CLOUD:
            print("☁️ Streamlit Cloud 모드로 실행 중...")
            print("⚠️ FastAPI 서버는 로컬에서만 사용 가능합니다.")
        else:
            print("🛒 Streamlit UI 시작 중...")
            if FASTAPI_AVAILABLE and app:
                print("🚀 FastAPI 서버도 자동으로 시작됩니다: http://localhost:8000")
        streamlit_app()


