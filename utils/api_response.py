from flask import jsonify
from typing import Any, Optional, Union, List, Dict

class ApiResponse:
    @staticmethod
    def success(data: Any = None, message: str = "Success", status_code: int = 200):
        """
        Standard success response.
        Structure:
        {
            "success": True,
            "message": "...",
            "data": ...
        }
        """
        response = {
            "success": True,
            "message": message,
            "data": data
        }
        return jsonify(response), status_code

    @staticmethod
    def error(message: str, status_code: int = 400, errors: Optional[Any] = None):
        """
        Standard error response.
        Structure:
        {
            "success": False,
            "message": "...",
            "errors": ... (optional validation details)
        }
        """
        response = {
            "success": False,
            "message": message
        }
        if errors:
            response["errors"] = errors
            
        return jsonify(response), status_code
