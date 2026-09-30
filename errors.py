class TransientToolError(Exception):
    """Error temporal: reintentar tiene sentido (timeout, servicio caído momentáneamente)."""


class PermanentToolError(Exception):
    """Error definitivo: reintentar NO cambia el resultado (input inválido, no autorizado)."""

class ToolValidationError(PermanentToolError):
    """Error definitivo: No vale la pena reintentar (entrada no valida)."""