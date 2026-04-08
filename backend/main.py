from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import users, documents, plagiarism, auth

app = FastAPI(
    title="Plagiarism Detection API",
    description="Backend API for document management and plagiarism checking",
    version="1.0.0",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router,      prefix="/api")
app.include_router(documents.router,  prefix="/api")
app.include_router(plagiarism.router, prefix="/api")
app.include_router(auth.router,       prefix="/api")


@app.get("/", tags=["Health"])
def read_root():
    return {
        "status": "online",
        "message": "Welcome to the Plagiarism Detection API",
    }