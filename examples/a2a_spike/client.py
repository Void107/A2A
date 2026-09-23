import asyncio
import uuid
import httpx
from a2a.client import A2AClient, A2ACardResolver
from a2a.types import SendMessageRequest, MessageSendParams, Message, Part, DataPart
from app.adapters.a2a_transport import EXTENSION


async def main():
    async with httpx.AsyncClient(headers={'X-A2A-Extensions': EXTENSION}) as http:
        card = await A2ACardResolver(http, 'http://127.0.0.1:58184').get_agent_card()
        assert card.protocol_version == '0.3.0'
        assert card.capabilities.extensions[0].required
        client = A2AClient(http, agent_card=card)
        request = SendMessageRequest(id=uuid.uuid4().hex, params=MessageSendParams(message=Message(
            message_id=uuid.uuid4().hex, role='user', parts=[Part(root=DataPart(data={
                'contract_id': 'meeting-actions', 'contract_version': '1.0.0', 'view_id': 'internal-project'}))])))
        response = await client.send_message(request)
        assert response.root.result.parts[0].root.data == {'status': 'shape_verified', 'business_delivery': False}
        http.headers.pop('X-A2A-Extensions')
        response = await client.send_message(request)
        assert response.root.error.code == -32602
        print('PASS: official card discovery, required extension, Message/DataPart response and missing-extension error')


if __name__ == '__main__': asyncio.run(main())
