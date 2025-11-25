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
    
    # CSS 스타일 (인스타그램 + 깃허브 느낌)
    st.markdown("""
    <style>
    .main {
        padding-top: 2rem;
    }
    .item-card {
        border: 1px solid #e1e4e8;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        background: white;
        transition: box-shadow 0.2s;
    }
    .item-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .item-header {
        display: flex;
        align-items: center;
        margin-bottom: 0.5rem;
    }
    .item-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #24292f;
        margin: 0;
    }
    .item-author {
        color: #656d76;
        font-size: 0.9rem;
        margin-left: 0.5rem;
    }
    .item-price {
        font-size: 1.1rem;
        font-weight: 600;
        color: #0969da;
    }
    .item-description {
        color: #656d76;
        margin: 0.5rem 0;
        font-size: 0.9rem;
    }
    .item-stats {
        display: flex;
        gap: 1rem;
        color: #656d76;
        font-size: 0.85rem;
        margin-top: 0.5rem;
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
        st.title("🛒 마켓플레이스")
        
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
    
    # 메인 페이지 - 마켓플레이스 (인스타그램 + 깃허브 스타일)
    st.title("🛒 마켓플레이스")
    
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
    
    # 아이템 카드 표시 함수
    def show_item_card(item, show_download=True):
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {item['name']}")
                st.caption(f"👤 {item['author']} • 📅 {item['created_at'][:10]}")
            with col2:
                if item['price'] > 0:
                    st.markdown(f"### {item['price']}P")
                else:
                    st.markdown("### 🆓 무료")
            
            if item['description']:
                st.write(item['description'])
            
            col_info, col_action = st.columns([2, 1])
            with col_info:
                st.caption(f"📦 {item['type']} • ⬇️ {item['download_count']}회 다운로드")
            with col_action:
                if show_download:
                    if st.session_state.logged_in:
                        if st.button("🛒 구매하기", key=f"buy_{item['id']}", use_container_width=True):
                            # 구매 로직
                            try:
                                if IS_STREAMLIT_CLOUD or not FASTAPI_AVAILABLE:
                                    user_id = st.session_state.user_id
                                    conn = get_db()
                                    c = conn.cursor()
                                    
                                    # 아이템 조회
                                    c.execute("SELECT price, zip_data, author FROM items WHERE id = ?", (item['id'],))
                                    item_data = c.fetchone()
                                    
                                    if item_data:
                                        price = item_data[0] if item_data[2] != user_id else 0
                                        zip_data = item_data[1]
                                        
                                        # 포인트 확인
                                        current_points = get_user_points(user_id)
                                        if current_points < price:
                                            st.error(f"포인트가 부족합니다. (필요: {price}P, 보유: {current_points}P)")
                                        else:
                                            # 포인트 차감
                                            if price > 0:
                                                update_user_points(user_id, current_points - price)
                                                seller_points = get_user_points(item_data[2])
                                                update_user_points(item_data[2], seller_points + price)
                                                c.execute("INSERT INTO transactions (buyer_id, item_id, price) VALUES (?, ?, ?)",
                                                          (user_id, item['id'], price))
                                            
                                            # 다운로드 횟수 증가
                                            c.execute("UPDATE items SET download_count = download_count + 1 WHERE id = ?", (item['id'],))
                                            
                                            # ZIP 파일 다운로드
                                            import tempfile
                                            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                                                tmp.write(zip_data)
                                                tmp_path = tmp.name
                                            
                                            st.download_button(
                                                label="📥 다운로드",
                                                data=zip_data,
                                                file_name=f"{item['name']}.zip",
                                                mime="application/zip",
                                                key=f"dl_{item['id']}"
                                            )
                                            st.success("구매 완료!")
                                            
                                            conn.commit()
                                            conn.close()
                                            st.rerun()
                                    else:
                                        st.error("아이템을 찾을 수 없습니다.")
                                else:
                                    st.info("로컬 API 서버가 필요합니다.")
                            except Exception as e:
                                st.error(f"구매 실패: {e}")
                    else:
                        st.info("로그인 필요")
            st.divider()
    
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
        
        if items:
            for item in items:
                show_item_card(item)
        else:
            st.info("등록된 아이템이 없습니다.")
    
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

