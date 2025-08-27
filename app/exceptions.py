from app.schema.api_schema import ErrorDetail

class ProjectCreationError(Exception):
    def __init__(self, message: str, error_detail: ErrorDetail):
        super().__init__(message)
        self.error_detail = error_detail

class ProjectDeletionError(Exception):
    def __init__(self, message: str, error_detail: ErrorDetail):
        super().__init__(message)
        self.error_detail = error_detail