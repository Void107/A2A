"""Loopback test proxy: successful responses always come from the real dependency."""
import asyncio
import httpx

class FaultProxy:
    def __init__(self, destination):
        self.destination = destination
        self.mode = 'normal'
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.tasks = set()
    async def start(self):
        self.client = httpx.AsyncClient(trust_env=False, timeout=8)
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
        self.url = 'http://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1])
        return self
    async def handle(self, reader, writer):
        task=asyncio.current_task(); self.tasks.add(task)
        try:
            lines=(await reader.readuntil(b'\r\n\r\n')).decode().split('\r\n')
            method,path,_=lines[0].split(); headers=dict(line.lower().split(': ',1) for line in lines[1:] if ': ' in line)
            body=await reader.readexactly(int(headers.get('content-length',0)))
            self.calls+=1; mode=self.mode; self.entered.set()
            if mode=='delay': await asyncio.sleep(4)
            if mode=='barrier': await self.release.wait()
            if mode=='error': status,data=503,b'{}'
            elif mode=='invalid': status,data=200,b'not-json'
            else:
                try:
                    response=await self.client.request(method,self.destination+path,content=body,headers={'Content-Type':'application/json'})
                    status,data=response.status_code,response.content
                except httpx.HTTPError: status,data=503,b'{}'
            writer.write(('HTTP/1.1 %d Test\r\nConnection: close\r\nContent-Length: %d\r\n\r\n'%(status,len(data))).encode()+data)
            await writer.drain()
        except (ConnectionError,asyncio.IncompleteReadError): pass
        finally:
            writer.close(); self.tasks.discard(task)
    async def close(self):
        self.server.close(); await self.server.wait_closed()
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*list(self.tasks),return_exceptions=True)
        await self.client.aclose()
