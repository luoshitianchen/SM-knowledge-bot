from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SM Knowledge Bot", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Document:
    id: str
    title: str
    content: str
    department: str
    min_role: str


ROLE_LEVEL = {"employee": 1, "manager": 2, "admin": 3}
documents: list[Document] = []
conversations: dict[str, list[dict[str, str]]] = defaultdict(list)


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    department: str = "all"
    min_role: Literal["employee", "manager", "admin"] = "employee"


class ChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    user_id: str = Field(min_length=1)
    role: Literal["employee", "manager", "admin"] = "employee"
    department: str = "all"
    conversation_id: str | None = None


def allowed(document: Document, role: str, department: str) -> bool:
    return ROLE_LEVEL[role] >= ROLE_LEVEL[document.min_role] and (
        document.department == "all" or document.department == department
    )


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def retrieve(question: str, role: str, department: str, limit: int = 3) -> list[Document]:
    query = tokens(question)
    ranked = []
    for document in documents:
        if not allowed(document, role, department):
            continue
        score = len(query & tokens(document.title + " " + document.content))
        if score:
            ranked.append((score, document))
    return [document for _, document in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents")
def create_document(payload: DocumentInput) -> dict[str, str]:
    document = Document(id=str(uuid4()), **payload.model_dump())
    documents.append(document)
    return {"id": document.id, "message": "文档已写入知识库"}


@app.post("/chat")
def chat(payload: ChatInput) -> dict[str, object]:
    conversation_id = payload.conversation_id or str(uuid4())
    history = conversations[conversation_id]
    sources = retrieve(payload.question, payload.role, payload.department)
    if sources:
        excerpts = [f"《{item.title}》：{item.content[:240]}" for item in sources]
        answer = "根据已授权的知识库内容：\n" + "\n".join(excerpts)
    else:
        answer = "在你当前权限可访问的知识库中，未检索到相关内容。"
    history.extend([
        {"role": "user", "content": payload.question},
        {"role": "assistant", "content": answer},
    ])
    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "sources": [{"id": item.id, "title": item.title} for item in sources],
        "history_length": len(history),
    }
