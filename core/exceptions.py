import logging
from django.http import Http404
from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('apps')


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns standardized JSON error responses
    for all exceptions including 404, 403, 500, and DRF validation errors.
    """
    # Call DRF's default exception handler first to get the standard error response
    response = exception_handler(exc, context)

    if response is not None:
        # DRF handled the exception
        error_data = {
            'success': False,
            'message': _get_error_message(exc),
            'errors': _format_errors(response.data),
        }
        response.data = error_data
        return response

    # Handle Django-specific exceptions not caught by DRF
    if isinstance(exc, Http404):
        return Response(
            {
                'success': False,
                'message': 'La ressource demandée est introuvable.',
                'errors': None,
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {
                'success': False,
                'message': "Vous n'avez pas la permission d'effectuer cette action.",
                'errors': None,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Unhandled exception — log it and return 500
    logger.exception('Unhandled exception: %s', exc)
    return Response(
        {
            'success': False,
            'message': 'Une erreur interne du serveur est survenue.',
            'errors': None,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _get_error_message(exc):
    """Extract a human-readable message from the exception."""
    if isinstance(exc, ValidationError):
        return 'Les données fournies sont invalides.'
    if isinstance(exc, NotAuthenticated):
        return 'Authentification requise.'
    if isinstance(exc, AuthenticationFailed):
        return 'Identifiants invalides.'
    if hasattr(exc, 'detail'):
        detail = exc.detail
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            return str(first) if not hasattr(first, 'get') else 'Erreur de validation.'
    return str(exc) if str(exc) else 'Une erreur est survenue.'


def _format_errors(data):
    """Format error data into a consistent structure."""
    if data is None:
        return None
    if isinstance(data, list):
        return [str(item) for item in data]
    if isinstance(data, dict):
        formatted = {}
        for key, value in data.items():
            if key in ('success', 'message', 'errors'):
                continue
            if isinstance(value, list):
                formatted[key] = [str(v) for v in value]
            else:
                formatted[key] = str(value)
        return formatted if formatted else None
    return str(data)


class ServiceException(APIException):
    """Base exception for service layer errors."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Une erreur de service est survenue.'
    default_code = 'service_error'


class StockException(ServiceException):
    """Raised when a product is out of stock."""
    default_detail = 'Stock insuffisant pour ce produit.'
    default_code = 'insufficient_stock'


class OrderException(ServiceException):
    """Raised for order-related errors."""
    default_detail = "Erreur lors du traitement de la commande."
    default_code = 'order_error'


class PaymentException(ServiceException):
    """Raised for payment-related errors."""
    default_detail = 'Erreur lors du traitement du paiement.'
    default_code = 'payment_error'
