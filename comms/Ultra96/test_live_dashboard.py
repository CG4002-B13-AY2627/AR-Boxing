"""Hardware-free dashboard/protocol checks; selected-model preprocessing stays intact."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import websockets
from classified_actions import FakeAiEvent
from esp_ai_live_dashboard import Dashboard, Pipeline
from game_engine import GameEngine
from server_runtime import serve_phones
from visualizer_protocol import PhoneHub
from test_multiplayer import Clock, Socket, command, receive


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.hub = PhoneHub(engine=GameEngine(clock=self.clock))
        self.args = SimpleNamespace(wait_players=2, mode='inspect', ai_dir=Path('/selected/build'),
            demo_intensity=.6, host='127.0.0.1', port=0, insecure_ws=True)
        self.pipeline = Pipeline(self.args, self.hub, asyncio.get_running_loop())
        self.gateways = SimpleNamespace(players=set(), aligners={})
        self.monitor = Dashboard(self.pipeline, self.gateways, self.hub, self.args, self.clock)

    async def asyncTearDown(self):
        await self.hub.close()

    async def test_snapshot_is_read_only_and_reports_readiness_items_and_results(self):
        self.hub.engine.set_connected(1, True)
        self.hub.ready[1] = Socket()
        await self.hub.player_command(1, command(self.hub,1,'READY'))
        initial_seq = self.hub.state_seq
        for _ in range(3):
            state = self.monitor.snapshot()
            json.dumps(state,allow_nan=False)
            self.assertEqual(state['game'],'LOBBY')
            self.assertTrue(state['players'][0]['ready'])
            self.assertIn('waiting for opponent',state['players'][0]['phone_detail'])
        self.assertEqual(self.hub.state_seq,initial_seq)
        self.hub.engine.start()
        self.clock.advance(30)
        self.monitor.snapshot()  # the HTTP endpoint must not advance authority clocks
        self.assertEqual(self.hub.engine.fight_time,0)
        await self.hub.broadcast_state()
        state=self.monitor.snapshot()
        self.assertEqual(len(state['active_items']),2)
        self.assertIsNotNone(state['players'][0]['active_item'])
        self.assertEqual(state['match_result'],'PENDING')

    async def test_publish_uses_shared_pickup_adapter_only_while_fighting(self):
        event=FakeAiEvent('pickup',0,.95)
        self.pipeline.publish(1,event)
        self.assertFalse(self.pipeline.pending)
        self.hub.engine.start()
        self.hub.ready[1]=Socket()
        self.hub.engine.spawn_health(1)
        self.pipeline.publish(1,event)
        await asyncio.gather(*tuple(self.pipeline.pending))
        self.assertIn(1,self.hub.pending_pickups)
        self.assertEqual(self.hub.ready[1].messages[-1]['type'],'PickupCheck')
        self.assertTrue(self.monitor.snapshot()['players'][0]['pickup_pending'])

    async def test_http_get_is_read_only_and_mutating_requests_are_rejected(self):
        async with await asyncio.start_server(self.monitor.handle,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async def request(method):
                reader,writer=await asyncio.open_connection('127.0.0.1',port)
                writer.write(f'{method} /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
                await writer.drain()
                raw=await reader.read()
                writer.close();await writer.wait_closed()
                return raw.split(b'\r\n\r\n',1)
            header,body=await request('GET')
            self.assertIn(b'200 OK',header)
            self.assertEqual(json.loads(body)['game'],'LOBBY')
            header,_=await request('POST')
            self.assertIn(b'405 Method Not Allowed',header)
            self.assertEqual(self.hub.state_seq,0)

    async def test_listener_hook_preserves_handshake_and_menu_dispatch(self):
        async with serve_phones(self.hub,self.args,handler=self.monitor.phone_handle) as server:
            url='ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])
            async with websockets.connect(url) as one, websockets.connect(url) as two:
                for player,ws in ((1,one),(2,two)):
                    await ws.send(json.dumps(dict(type='ClientHello',protocol_version=2,
                        client_id='dashboard-'+str(player),player_id=player)))
                    self.assertTrue((await receive(ws,'ServerWelcome'))['supports_player_commands'])
                    await receive(ws,'MatchState')
                self.assertEqual(self.monitor.phone_sockets,2)
                self.assertEqual(self.hub.engine.phase,'LOBBY')
                for player,ws in ((1,one),(2,two)):
                    await ws.send(json.dumps(command(self.hub,player,'READY')))
                await receive(one,'MatchState',lambda state:state['state']=='CALIBRATING')
                self.assertEqual(self.monitor.snapshot()['game'],'CALIBRATING')


if __name__=='__main__': unittest.main()
