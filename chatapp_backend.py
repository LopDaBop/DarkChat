# backend.py
# FastAPI app with user, chat, friend, and group management
# Serves static files and HTML templates from the same directory

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import List, Optional, Dict
import sqlite3
import time
import os

SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

app = FastAPI()

# Set up CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    conn = sqlite3.connect("chatapp.db")
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        display_name TEXT,
        bio TEXT,
        avatar TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        friend_id INTEGER,
        status TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        sender_id INTEGER,
        content TEXT,
        timestamp INTEGER,
        deleted INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        owner_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
        group_id INTEGER,
        user_id INTEGER
    )''')
    conn.commit()
    conn.close()

create_tables()

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[int] = None):
    to_encode = data.copy()
    expire = int(time.time()) + (expires_delta if expires_delta else ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    if user is None:
        raise credentials_exception
    return user

@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)",
                    (username, get_password_hash(password), username))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username already registered")
    conn.close()
    return {"msg": "User registered successfully"}

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (form_data.username,))
    user = cur.fetchone()
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": user["username"]})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
async def get_me(user=Depends(get_current_user)):
    return {"username": user["username"], "display_name": user["display_name"], "bio": user["bio"], "avatar": user["avatar"]}

@app.post("/profile/update")
async def update_profile(display_name: str = Form(...), bio: str = Form(''), avatar: str = Form(''), user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET display_name=?, bio=?, avatar=? WHERE id=?", (display_name, bio, avatar, user["id"]))
    conn.commit()
    conn.close()
    return {"msg": "Profile updated"}

@app.get("/users/search")
async def search_users(q: str, user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, avatar FROM users WHERE username LIKE ? AND id != ? LIMIT 10", (f"%{q}%", user["id"]))
    results = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "avatar": r["avatar"]} for r in results]

@app.post("/friends/add")
async def add_friend(friend_id: int, user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM friends WHERE user_id=? AND friend_id=?", (user["id"], friend_id))
    if cur.fetchone() is not None:
        conn.close()
        raise HTTPException(status_code=400, detail="Already friends or request pending")
    cur.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (?, ?, 'pending')", (user["id"], friend_id))
    conn.commit()
    conn.close()
    return {"msg": "Friend request sent"}

@app.post("/friends/accept")
async def accept_friend(friend_id: int, user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (friend_id, user["id"]))
    conn.commit()
    conn.close()
    return {"msg": "Friend request accepted"}

@app.get("/friends/list")
async def friends_list(user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT u.id, u.username, u.display_name, u.avatar FROM users u JOIN friends f ON u.id = f.friend_id WHERE f.user_id=? AND f.status='accepted'", (user["id"],))
    results = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "avatar": r["avatar"]} for r in results]

@app.get("/chats/list")
async def chats_list(user=Depends(get_current_user)):
    # Returns general chat, private chats, and group chats
    conn = get_db()
    cur = conn.cursor()
    # General chat
    chats = [{"chat_id": "general", "name": "General Chat", "type": "general"}]
    # Private chats
    cur.execute("SELECT u.id, u.username, u.display_name FROM users u JOIN friends f ON u.id=f.friend_id WHERE f.user_id=? AND f.status='accepted'", (user["id"],))
    for r in cur.fetchall():
        chats.append({"chat_id": f"private_{min(user['id'], r['id'])}_{max(user['id'], r['id'])}", "name": r["display_name"], "type": "private", "user_id": r["id"]})
    # Group chats
    cur.execute("SELECT g.id, g.name FROM groups g JOIN group_members gm ON g.id=gm.group_id WHERE gm.user_id=?", (user["id"],))
    for r in cur.fetchall():
        chats.append({"chat_id": f"group_{r['id']}", "name": r["name"], "type": "group", "group_id": r["id"]})
    conn.close()
    return chats

@app.post("/groups/create")
async def create_group(name: str = Form(...), user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO groups (name, owner_id) VALUES (?, ?)", (name, user["id"]))
    group_id = cur.lastrowid
    cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user["id"]))
    conn.commit()
    conn.close()
    return {"group_id": group_id, "name": name}

@app.post("/groups/add_member")
async def add_member(group_id: int, member_id: int, user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM groups WHERE id=? AND owner_id=?", (group_id, user["id"]))
    if cur.fetchone() is None:
        conn.close()
        raise HTTPException(status_code=403, detail="Only group owner can add members")
    cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, member_id))
    conn.commit()
    conn.close()
    return {"msg": "Member added"}

@app.get("/messages/{chat_id}")
async def get_messages(chat_id: str, user=Depends(get_current_user)):
    # Check if user is allowed
    if chat_id == "general":
        allowed = True
    elif chat_id.startswith("private_"):
        ids = chat_id.replace("private_", "").split("_")
        allowed = str(user["id"]) in ids
    elif chat_id.startswith("group_"):
        group_id = int(chat_id.replace("group_", ""))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM group_members WHERE group_id=? AND user_id=?", (group_id, user["id"]))
        allowed = cur.fetchone() is not None
        conn.close()
    else:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT m.id, m.sender_id, u.display_name, m.content, m.timestamp, m.deleted FROM messages m JOIN users u ON m.sender_id=u.id WHERE m.chat_id=? ORDER BY m.timestamp ASC", (chat_id,))
    messages = cur.fetchall()
    conn.close()
    return [{
        "id": m["id"],
        "sender_id": m["sender_id"],
        "sender": m["display_name"],
        "content": m["content"],
        "timestamp": m["timestamp"],
        "deleted": bool(m["deleted"])
    } for m in messages]

@app.post("/messages/delete")
async def delete_message(message_id: int, user=Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM messages WHERE id=?", (message_id,))
    msg = cur.fetchone()
    if not msg or msg["sender_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not allowed")
    cur.execute("UPDATE messages SET deleted=1 WHERE id=?", (message_id,))
    conn.commit()
    conn.close()
    return {"msg": "Message deleted"}

# WebSocket chat manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, chat_id: str, websocket: WebSocket):
        await websocket.accept()
        if chat_id not in self.active_connections:
            self.active_connections[chat_id] = []
        self.active_connections[chat_id].append(websocket)

    def disconnect(self, chat_id: str, websocket: WebSocket):
        if chat_id in self.active_connections:
            self.active_connections[chat_id].remove(websocket)
            if not self.active_connections[chat_id]:
                del self.active_connections[chat_id]

    async def broadcast(self, chat_id: str, message: dict):
        if chat_id in self.active_connections:
            for connection in self.active_connections[chat_id]:
                await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str, token: str = ""):
    # Authenticate
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close()
            return
    except JWTError:
        await websocket.close()
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()
    if not user:
        await websocket.close()
        return
    await manager.connect(chat_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                msg_content = data.get("content", "")
                ts = int(time.time())
                # Save message
                conn = get_db()
                cur = conn.cursor()
                cur.execute("INSERT INTO messages (chat_id, sender_id, content, timestamp) VALUES (?, ?, ?, ?)",
                            (chat_id, user["id"], msg_content, ts))
                conn.commit()
                msg_id = cur.lastrowid
                conn.close()
                msg = {
                    "id": msg_id,
                    "sender_id": user["id"],
                    "sender": user["display_name"],
                    "content": msg_content,
                    "timestamp": ts,
                    "deleted": False
                }
                await manager.broadcast(chat_id, {"type": "message", "message": msg})
            elif data.get("type") == "delete":
                msg_id = data.get("id")
                # Only sender can delete
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT * FROM messages WHERE id=?", (msg_id,))
                msg = cur.fetchone()
                if msg and msg["sender_id"] == user["id"]:
                    cur.execute("UPDATE messages SET deleted=1 WHERE id=?", (msg_id,))
                    conn.commit()
                    await manager.broadcast(chat_id, {"type": "delete", "id": msg_id})
                conn.close()
    except WebSocketDisconnect:
        manager.disconnect(chat_id, websocket)

# Serve static files and HTML
@app.get("/styles.css")
async def styles():
    return FileResponse("styles.css")

@app.get("/main.js")
async def js():
    return FileResponse("main.js")

@app.get("/")
async def index():
    return FileResponse("index.html")

@app.get("/profile")
async def profile():
    return FileResponse("profile.html")

@app.get("/chat")
async def chat():
    return FileResponse("chat.html")

@app.get("/login")
async def login_page():
    return FileResponse("login.html")

@app.get("/register")
async def register_page():
    return FileResponse("register.html")

if __name__ == "__main__":
    uvicorn.run("chatapp_backend:app", host="0.0.0.0", port=8000, reload=True)
