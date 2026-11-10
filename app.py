import os
import random
import datetime
import time
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import jwt
from pymongo import MongoClient

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.environ.get("MONGO_URI")
SECRET_KEY = os.environ.get("JWT_SECRET", "FALLBACK_SECURE_KEY_12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

ADMIN_USERNAME = "admin"
ADMIN_PLAIN_PASSWORD = "SecretAdminPassword123" 

header_scheme = APIKeyHeader(name="Authorization", auto_error=False)

class BlogCreate(BaseModel):
    title: str
    content: str

class LoginRequest(BaseModel):
    username: str
    password: str

def get_db_collection():
    if not MONGO_URI:
        raise HTTPException(status_code=500, detail="Database URL (MONGO_URI) missing.")
    client = MongoClient(MONGO_URI)
    db = client["blog_db"]
    return db["blogs"]

def verify_token(request: Request, header_value: str = Depends(header_scheme)):
    if request.method == "OPTIONS":
        return None
    if not header_value or not header_value.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing or malformed")
    
    token = header_value.split(" ")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username != ADMIN_USERNAME:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate signature")

@app.post("/api/admin/login/")
def login(data: LoginRequest):
    if not data.password or data.password.strip() == "":
        raise HTTPException(status_code=400, detail="Password field cannot be empty.")
    if data.username != ADMIN_USERNAME or data.password != ADMIN_PLAIN_PASSWORD:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {"sub": data.username, "exp": expire}
    encoded_jwt = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@app.post("/api/admin/blogs/")
def create_blog(blog: BlogCreate, username: str = Depends(verify_token)):
    try:
        collection = get_db_collection()
        blog_document = {
            "title": blog.title,
            "content": blog.content,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
        collection.insert_one(blog_document)
        return {"status": "Success", "message": "Blog permanently logged in MongoDB."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Write error: {str(e)}")

# --- STABILIZED TIME-LOCKED READ-ONLY ROUTE ---
@app.get("/api/blogs/shuffled/")
def get_shuffled_blogs():
    try:
        collection = get_db_collection()
        
        # 1. Fetch the raw repository stack (limiting to newest 50 entries)
        cursor = collection.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
        blogs = list(cursor)
        
        if not blogs:
            return []

        # 2. Build the exact 2-hour structural alignment key seed
        # 7200 seconds = exactly 2 hours. This changes integer value precisely every 2 hours.
        current_epoch_time = time.time()
        two_hour_window_block = int(current_epoch_time // 7200)
        
        # 3. Freeze random execution pattern state to this window block index
        # This keeps the layout identical for everyone and across restarts for the full 2 hours
        rng = random.Random(two_hour_window_block)
        rng.shuffle(blogs)
        
        return blogs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database read failure: {str(e)}")
