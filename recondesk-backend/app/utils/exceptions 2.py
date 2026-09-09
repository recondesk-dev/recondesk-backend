from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class ReconDeskException(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def recondesk_exception_handler(request: Request, exc: ReconDeskException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


class FileTooLargeError(ReconDeskException):
    def __init__(self) -> None:
        super().__init__("File exceeds maximum allowed size", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)


class UnsupportedFileTypeError(ReconDeskException):
    def __init__(self, content_type: str) -> None:
        super().__init__(f"Unsupported file type: {content_type}", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)


class PlanLimitExceededError(ReconDeskException):
    def __init__(self) -> None:
        super().__init__(
            "Row limit exceeded for your current plan. Please upgrade to continue.",
            status.HTTP_402_PAYMENT_REQUIRED,
        )
