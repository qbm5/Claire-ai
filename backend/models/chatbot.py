from pydantic import BaseModel


class ChatBot(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    tag: str = ""
    is_enabled: bool = True
    is_deleted: bool = False
    source_type: str = "filesystem"  # 'filesystem' | 'text' | 'upload' | 'github'
    source_folder: str = ""
    source_texts: list[str] = []
    github_owner: str = ""
    github_repo: str = ""
    github_branch: str = "main"
    github_folder: str = ""
    model: str = ""
    created_at: str = ""
    updated_at: str = ""


class ChatMessage(BaseModel):
    id: str = ""
    role: str = "user"  # 'user' | 'assistant'
    content: str = ""
    sources: list[str] = []
    timestamp: str = ""


class ChatHistory(BaseModel):
    id: str = ""
    chatbot_id: str = ""
    user_id: str = "default"
    title: str = ""
    messages: list[ChatMessage] = []
    created_at: str = ""
    updated_at: str = ""
