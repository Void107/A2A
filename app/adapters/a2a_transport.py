"""Pinned official A2A SDK 0.3.0 JSON-RPC adapter; synchronous JSON subset only."""
import uuid
from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentExtension, Message, Part, DataPart, InvalidParamsError, UnsupportedOperationError
from a2a.utils.errors import ServerError

EXTENSION = 'urn:uuid:061c06b4-2078-4a1a-95e0-fbd397e27d78'


class ContractExecutor(AgentExecutor):
    def __init__(self, deliver):
        self.deliver = deliver

    async def execute(self, context, event_queue):
        if EXTENSION not in context.requested_extensions:
            raise ServerError(InvalidParamsError(message='REQUIRED_CONTRACT_EXTENSION'))
        parts = context.message.parts
        if len(parts) != 1 or not isinstance(parts[0].root, DataPart):
            raise ServerError(InvalidParamsError(message='JSON_DATA_PART_REQUIRED'))
        context.add_activated_extension(EXTENSION)
        headers = context.call_context.state.get('headers', {}) if context.call_context else {}
        result = await self.deliver(parts[0].root.data, headers)
        await event_queue.enqueue_event(Message(message_id=uuid.uuid4().hex, role='agent',
            parts=[Part(root=DataPart(data=result))], extensions=[EXTENSION]))

    async def cancel(self, context, event_queue):
        raise ServerError(UnsupportedOperationError(message='CANCELLATION_NOT_SUPPORTED'))


def build_app(deliver, url):
    card = AgentCard(name='Data Contract Hub', description='Synchronous JSON data contracts; no streaming or push',
        url=url, version='0.3.0-alpha', protocol_version='0.3.0',
        default_input_modes=['application/json'], default_output_modes=['application/json'], skills=[],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False,
            extensions=[AgentExtension(uri=EXTENSION, required=True, description='Fixed contract/version/view/query envelope')]))
    handler = DefaultRequestHandler(ContractExecutor(deliver), InMemoryTaskStore())
    return A2AStarletteApplication(card, handler).build()


def mount_hub(app, url):
    from pydantic import ValidationError
    from a2a.types import JSONRPCError
    from app.api.auth import require_auth
    from app.database import AsyncSessionLocal
    from app.services.delivery import DeliveryRequest, deliver

    async def dispatch(data, headers):
        try:
            body = DeliveryRequest.model_validate(data)
        except ValidationError:
            raise ServerError(InvalidParamsError(message='REQUEST_INVALID')) from None
        try:
            async with AsyncSessionLocal() as db:
                identity = await require_auth(headers.get('authorization'), db)
                return await deliver(body, identity, db, app.state)
        except Exception as error:
            code = getattr(error, 'code', None)
            detail = getattr(error, 'detail', None)
            if code is None and isinstance(detail, dict): code = detail.get('code')
            from app.services.receipts import record_failure
            request_id = getattr(error, 'request_id', None) or uuid.uuid4().hex
            code = code or 'PROCESSING_UNAVAILABLE'
            actor = locals().get('identity', {}).get('sub')
            recorded = await record_failure(request_id, actor, code, getattr(error, 'diagnostics', None)) if actor else False
            raise ServerError(JSONRPCError(code=-32000, message=code,
                data={'request_id': request_id, 'diagnostic_recorded': recorded})) from None

    app.mount('/a2a', build_app(dispatch, url))
