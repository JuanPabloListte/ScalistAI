from fastapi import APIRouter

from . import _core, _detection, _elements, _export, _render, _scale, _training

router = APIRouter()
for _mod in [_training, _detection, _core, _scale, _render, _elements, _export]:
    router.include_router(_mod.router)
