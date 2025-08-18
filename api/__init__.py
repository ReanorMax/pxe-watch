from flask import Blueprint

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Import route modules to register their endpoints
from . import ansible  # noqa: F401
from . import ipxe  # noqa: F401
from . import hosts  # noqa: F401
from . import system  # noqa: F401
