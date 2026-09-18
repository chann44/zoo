from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    password: str


class Agent:
    id: int
    computerId: int
    userId: int
    name: str


class Computer(BaseModel):
    id: int
    userId: str
    name: str


class ComputerSessions(BaseModel):
    id: int
    computerId: int


class Files(BaseModel):
    id: int
    computerId: int


class NetworkSettings:
    id: int
    computerId: int

class ClickRequestSchema(BaseModel):
    x: int
    y: int
    button: str
    
