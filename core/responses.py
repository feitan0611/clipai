from rest_framework.response import Response
from rest_framework import status


def success_response(data=None, message="", status_code=status.HTTP_200_OK):
    """Return a standardized success JSON response."""
    return Response(
        {
            "success": True,
            "message": message,
            "data": data,
        },
        status=status_code,
    )


def error_response(message="", errors=None, status_code=status.HTTP_400_BAD_REQUEST):
    """Return a standardized error JSON response."""
    return Response(
        {
            "success": False,
            "message": message,
            "errors": errors,
        },
        status=status_code,
    )


def created_response(data=None, message="Ressource créée avec succès."):
    """Return a 201 Created standardized response."""
    return success_response(data=data, message=message, status_code=status.HTTP_201_CREATED)


def no_content_response(message="Opération effectuée avec succès."):
    """Return a 204 No Content response with a message body."""
    return success_response(data=None, message=message, status_code=status.HTTP_200_OK)
