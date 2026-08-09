from fastapi import APIRouter

from jat_api.api.v1.health import router as health_router
from jat_api.auth.routes import router as auth_router
from jat_api.chat import router as chat_router
from jat_api.conversations import router as conversations_router
from jat_api.knowledge_bases import router as knowledge_bases_router
from jat_api.settings.routes import router as settings_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(chat_router)
api_router.include_router(knowledge_bases_router)
api_router.include_router(settings_router)
