from fastapi import APIRouter

from . import _core, _elements, _export

router = APIRouter()
for _mod in [_core, _elements, _export]:
    router.include_router(_mod.router)
