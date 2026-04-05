from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import users, documents, plagiarism, auth

app = FastAPI(
    title="Plagiarism Detection API",
    description="Backend API for document management and plagiarism checking",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # Update this to match your frontend's URL!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Register the Routers
# This links the route paths we defined in the other files to this main app
app.include_router(users.router, prefix='/api')
app.include_router(documents.router, prefix='/api')
app.include_router(plagiarism.router, prefix='/api')
app.include_router(auth.router, prefix='/api')

# 5. Add a simple root endpoint (Health Check)
@app.get("/", tags=["Health"])
def read_root():
    return {
        "status": "online", 
        "message": "Welcome to the Plagiarism Detection API"
    }