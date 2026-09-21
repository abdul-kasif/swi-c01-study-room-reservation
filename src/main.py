from fastapi import FastAPI
from sqlalchemy import create_engine

# Initialize empty SQLite database configuration
SQLALCHEMY_DATABASE_URL = "sqlite:///./reservation.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

app = FastAPI(title="Study Room Reservation API")


@app.get("/")
def read_root():
    return {"status": "API is running and database configured"}
