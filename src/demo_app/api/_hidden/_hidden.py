from fastapi import APIRouter

router = APIRouter(include_in_schema=False)


@router.get("/healthcheck")
async def healthcheck() -> str:
    """A healthcheck API used by tests to determine the app is ready or not"""
    return "ok"
