from pydantic import BaseModel, Field


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


class ExecRequest(BaseModel):
    command: str
    timeout: int = Field(default=30, ge=1, le=300)

class ExecResponse(BaseModel):
    sandbox_id: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
