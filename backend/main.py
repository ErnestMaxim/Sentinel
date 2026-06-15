from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routes import auth, documents, plagiarism, users

settings = get_settings()

app = FastAPI(
    title="Sentinel API",
    description="Backend API for document management and plagiarism detection",
    version="3.0",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/api")
app.include_router(users.router,     prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(plagiarism.router, prefix="/api")


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "online"}