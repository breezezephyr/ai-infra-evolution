import asyncio
import json
import tempfile
import unittest
try:
    from server import create_app
except ImportError:
    create_app=None
from protocol import pack_audio, unpack_audio
from test_pipeline import ToyModels


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_websocket_pcm_and_terminal(self):
        self.assertIsNotNone(create_app,'server not implemented')
        from aiohttp import web,ClientSession,WSMsgType
        class M(ToyModels):
            metadata={'kind':'controlled_test'}
            class vad:
                @staticmethod
                def reset_states(): pass
            def speech_probability(self,window):
                return .9 if window[:2]==b'\x01\x00' else 0.
        with tempfile.TemporaryDirectory() as out:
            app=create_app(M(),out);runner=web.AppRunner(app)
            await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            port=site._server.sockets[0].getsockname()[1]
            try:
                async with ClientSession() as client:
                    async with client.ws_connect(f'http://127.0.0.1:{port}/ws') as ws:
                        await ws.send_json({'type':'start','session_id':'test','turn_id':1,'generation_id':1,'mode':'C','playback':'capture_only'})
                        await ws.receive_json()
                        pcm=b'\x01\x00'*512+b'\x00\x00'*4096
                        for seq,offset in enumerate(range(0,len(pcm)//2,320)):
                            await ws.send_bytes(pack_audio(1,1,seq,offset,pcm[offset*2:(offset+320)*2]))
                        await ws.send_json({'type':'input_end'})
                        frames=[];terminal=None
                        async with asyncio.timeout(3):
                            async for msg in ws:
                                if msg.type==WSMsgType.BINARY:
                                    f=unpack_audio(msg.data);frames.append(f)
                                    await ws.send_json({'type':'ack','samples':f.sample_offset+len(f.pcm)//2})
                                elif msg.type==WSMsgType.TEXT:
                                    data=json.loads(msg.data)
                                    if data['type']=='terminal':terminal=data;break
                        self.assertEqual(sum(len(f.pcm)//2 for f in frames),960)
                        self.assertEqual(terminal['finish_reason'],'stop')
                        self.assertTrue(terminal['state']['tts_thread_stopped'])
                        self.assertTrue(terminal['input_complete'])
            finally:
                await runner.cleanup()


if __name__=='__main__':unittest.main()
