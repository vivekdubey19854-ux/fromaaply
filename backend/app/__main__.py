from app.database import Base, engine
from app import db_models  # noqa: F401
from app.main import app
from app.routes import router

Base.metadata.create_all(bind=engine)
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
