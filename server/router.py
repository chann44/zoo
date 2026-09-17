from fastapi import APIRouter
from server.handler import Handlers

router = APIRouter(tags=["routes"]) 

@router.get("/", status_code=200)
def home():
    return Handlers.home() 

