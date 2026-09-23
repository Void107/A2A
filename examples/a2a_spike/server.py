"""Protocol shape spike only; this server never returns meeting/business data."""
from app.adapters.a2a_transport import build_app


async def acknowledge(data, headers):
    return {'status': 'shape_verified', 'business_delivery': False}


app = build_app(acknowledge, 'http://127.0.0.1:58184/')
