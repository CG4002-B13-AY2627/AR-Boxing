"""Menu/pickup/recovery acceptance against the actual CPU authority."""
import asyncio
import json
import unittest
from unittest.mock import patch
import websockets
from game_engine import GameEngine, BASE_DAMAGE
from visualizer_protocol import PhoneHub, encode, decode_hello, decode_observation
from contract_validation import validator, decode


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class Socket:
    def __init__(self): self.messages = []; self.closed = False
    async def send(self, raw): self.messages.append(json.loads(raw))
    async def close(self, **kwargs): self.closed = True


def command(hub, player, action, identifier=None):
    return dict(type="PlayerCommand", protocol_version=2, match_id=hub.match_id,
        stream_id=hub.stream_id, player_id=player, command_id=identifier or action+str(player),
        command=action, timestamp=0)


def pickup_reply(check, distance=.5, observation="AVAILABLE"):
    value = {key: check[key] for key in ("match_id", "stream_id", "request_id", "item_id", "player_id")}
    value.update(type="PickupObservation", protocol_version=2, client_timestamp=0, observation=observation)
    if observation == "AVAILABLE": value.update(observed_distance_m=distance, hand="LEFT")
    return value


async def receive(socket, kind, predicate=lambda value: True):
    while True:
        value = json.loads(await asyncio.wait_for(socket.recv(), 3))
        if value["type"] == kind and predicate(value): return value


class MatchRules(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.engine = GameEngine(clock=self.clock, seed=4002)
        for player in (1, 2): self.engine.set_connected(player, True)

    def fight(self):
        for action in ("READY", "CALIBRATED"):
            for player in (1, 2): self.engine.command(player, action)
        self.assertEqual(self.engine.phase, "COUNTDOWN")
        self.clock.advance(3); self.engine.advance()

    def test_join_never_starts_and_commands_need_both_players(self):
        self.assertEqual(self.engine.phase, "LOBBY")
        self.assertFalse(self.engine.command(1, "CALIBRATED"))
        self.engine.command(1, "READY")
        self.assertEqual(self.engine.phase, "LOBBY")
        self.engine.command(1, "UNREADY")
        self.assertFalse(self.engine.players[1].ready)
        self.fight()
        self.assertEqual(self.engine.phase, "FIGHTING")
        self.assertFalse(any(p.ready for p in self.engine.players.values()))

    def test_pause_freezes_every_game_clock_and_resume_needs_both(self):
        self.fight(); self.clock.advance(30); self.engine.advance()
        state = self.engine.snapshot(); self.engine.command(1, "PAUSE")
        self.clock.advance(100); self.engine.advance()
        frozen = self.engine.snapshot()
        self.assertEqual(frozen["active_items"], state["active_items"])
        self.assertEqual(frozen["round_time"], state["round_time"])
        self.engine.command(1, "RESUME"); self.assertEqual(self.engine.phase, "PAUSED")
        self.engine.command(2, "RESUME"); self.assertEqual(self.engine.phase, "COUNTDOWN")
        self.clock.advance(3); self.engine.advance()
        self.assertEqual(self.engine.snapshot()["round_time"], 60)

    def test_expire_before_boundary_respawn_and_no_catchup_burst(self):
        self.fight(); self.clock.advance(29.99); self.engine.advance(); self.assertFalse(self.engine.items)
        self.clock.advance(.01); self.engine.advance()
        old = {p: i[0]["id"] for p, i in self.engine.items.items()}
        self.clock.advance(30); self.engine.advance()
        self.assertEqual(len(self.engine.items), 2)
        self.assertTrue(all(self.engine.items[p][0]["id"] != old[p] for p in old))
        self.clock.advance(25); self.engine.advance(); self.assertEqual(len(self.engine.items), 2)
        self.assertEqual(self.engine.next_spawn, 90)

    def test_existing_pack_is_not_replaced_when_schedule_is_shorter(self):
        self.engine.spawn_seconds = 10; self.engine.next_spawn = 10
        self.fight(); self.clock.advance(10); self.engine.advance()
        old = self.engine.items[1][0]["id"]
        self.clock.advance(10); self.engine.advance()
        self.assertEqual(self.engine.items[1][0]["id"], old)

    def test_disconnect_calibration_and_countdown_and_result(self):
        self.engine.command(1, "READY"); self.engine.set_connected(1, False)
        self.assertFalse(self.engine.players[1].ready)
        self.engine.set_connected(1, True); self.fight()
        self.engine.command(1, "PAUSE")
        self.engine.command(1, "RESUME"); self.engine.command(2, "RESUME")
        self.engine.set_connected(2, False)
        self.assertEqual(self.engine.phase, "PAUSED")
        self.engine.set_connected(2, True); self.assertEqual(self.engine.phase, "PAUSED")
        self.engine.command(1, "RESUME"); self.engine.command(2, "RESUME")
        self.clock.advance(3); self.engine.advance()
        self.engine.players[2].health = 1
        self.engine.resolve_punch(1, "JAB", 1, True)
        self.assertEqual(self.engine.snapshot()["match_result"], "PENDING")
        self.clock.advance(2); self.engine.advance()
        self.assertEqual(self.engine.snapshot()["match_result"], "P1_WIN")
        self.assertFalse(self.engine.command(1, "READY"))
        self.assertFalse(self.engine.items)

    def test_draw_and_large_tick_ends_without_spawning(self):
        self.fight(); self.clock.advance(92); self.engine.advance()
        self.assertEqual(self.engine.snapshot()["match_result"], "DRAW")
        self.assertFalse(self.engine.items)


class AuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock(); self.hub = PhoneHub(engine=GameEngine(clock=self.clock))
        self.one, self.two = Socket(), Socket()
        self.hub.ready = {1: self.one, 2: self.two}
        self.hub.active = dict(self.hub.ready)
        for player in (1, 2): self.hub.engine.set_connected(player, True)
        for action in ("READY", "CALIBRATED"):
            for player in (1, 2): await self.hub.player_command(player, command(self.hub, player, action))
        self.clock.advance(3); await self.hub.broadcast_state()
        self.one.messages.clear(); self.two.messages.clear()

    async def asyncTearDown(self): await self.hub.close()

    async def check(self, player=1, identifier="action", health=60):
        self.hub.engine.players[player].health = health
        await self.hub.spawn_health(player)
        return await self.hub.request_pickup(player, identifier)

    async def test_pickup_private_result_identical_broadcast_and_immutable_retry(self):
        check = await self.check()
        self.assertEqual(check, self.one.messages[-1]); self.assertNotEqual(check, self.two.messages[-1])
        reply = pickup_reply(check)
        await self.hub.pickup_observation(1, reply, self.one)
        self.assertEqual(self.hub.health[1], 85)
        result = self.one.messages[-3]; event = self.one.messages[-2]
        self.assertEqual(result["type"], "PickupResult"); self.assertTrue(result["accepted"])
        self.assertEqual(event["magnitude"], 25)
        self.assertEqual(self.one.messages[-2:], self.two.messages[-2:])
        self.assertFalse(any(m["type"] == "PickupResult" for m in self.two.messages))
        seq = self.hub.event_seq
        await self.hub.pickup_observation(1, reply, self.one)
        await self.hub.request_pickup(1, "action")
        self.assertEqual(self.hub.event_seq, seq); self.assertEqual(self.hub.health[1], 85)
        count = len(self.one.messages)
        await self.hub.pickup_observation(1, dict(reply, observed_distance_m=.1), self.one)
        self.assertEqual(len(self.one.messages), count)
        names = {"GameEvent":"game-event", "MatchState":"match-state", "PickupResult":"pickup-result", "PickupCheck":"pickup-check"}
        for message in self.one.messages: validator(names[message["type"]]).validate(message)

    async def test_distance_boundary_and_clamped_full_health(self):
        for player, distance, reason in ((1, .50001, "OUT_OF_RANGE"), (2, .5, "ACCEPTED")):
            check = await self.check(player, health=100)
            socket = self.hub.ready[player]
            await self.hub.pickup_observation(player, pickup_reply(check, distance), socket)
            self.assertEqual(self.hub.pickups[check["request_id"]]["result"]["reason"], reason)
            self.assertEqual(self.hub.health[player], 100)
        self.assertNotIn(2, self.hub.engine.items)
        self.assertEqual(self.two.messages[-2]["magnitude"], 0)

    async def test_wrong_owner_stream_item_and_unavailable_never_heal(self):
        check = await self.check()
        reply = pickup_reply(check)
        for message, player, socket in ((reply,2,self.two),(dict(reply,stream_id="old"),1,self.one),
                (dict(reply,item_id="other"),1,self.one),(dict(reply,player_id=2),1,self.one)):
            await self.hub.pickup_observation(player, message, socket)
        self.assertIn(1,self.hub.pending_pickups)
        await self.hub.pickup_observation(1,pickup_reply(check,observation="TRACKING_UNAVAILABLE"),self.one)
        self.assertEqual(self.hub.health[1],60); self.assertIn(1,self.hub.engine.items)

    async def test_pending_timeout_pause_and_disconnect(self):
        check = await self.check()
        self.hub.pickups[check["request_id"]]["deadline"] = 0
        await self.hub.broadcast_state()
        self.assertEqual(self.hub.pickups[check["request_id"]]["result"]["reason"],"OBSERVATION_TIMEOUT")
        await self.hub.pickup_observation(1,pickup_reply(check),self.one)
        self.assertEqual(self.hub.health[1],60)
        check = await self.hub.request_pickup(1,"pause")
        await self.hub.player_command(2,command(self.hub,2,"PAUSE"))
        self.assertEqual(self.hub.pickups[check["request_id"]]["result"]["reason"],"MATCH_NOT_ACTIVE")
        self.assertIn(1,self.hub.engine.items)

    async def test_interrupted_punch_cannot_damage_after_resume(self):
        task=asyncio.create_task(self.hub.request_punch(1,"JAB",1,1,attack_id="pending"))
        while not any(m["type"]=="PunchAttempt" for m in self.one.messages): await asyncio.sleep(0)
        await self.hub.operator_pause()
        self.hub.engine.resume()
        event=await task
        self.assertEqual(event["outcome"],"MISS"); self.assertEqual(self.hub.health[2],100)
        self.assertEqual(await self.hub.request_punch(1,"JAB",1,1,attack_id="pending"),event)

    async def test_commands_are_bound_deduplicated_and_bounded(self):
        before=self.hub.state_seq
        await self.hub.player_command(1,command(self.hub,2,"PAUSE"))
        await self.hub.player_command(1,dict(command(self.hub,1,"PAUSE"),stream_id="old"))
        await self.hub.player_command(1,command(self.hub,1,"UNKNOWN"))
        self.assertEqual(self.hub.state_seq,before)
        msg=command(self.hub,1,"PAUSE")
        self.assertTrue(await self.hub.player_command(1,msg))
        self.assertFalse(await self.hub.player_command(1,msg))
        with patch("visualizer_protocol.MAX_ATTACK_RECORDS",len(self.hub.commands)):
            self.assertFalse(await self.hub.player_command(1,command(self.hub,1,"RESUME")))
        self.assertEqual(self.hub.engine.phase,"PAUSED")

    async def test_rejected_pickup_action_stays_rejected_and_capacity_refuses(self):
        self.assertIsNone(await self.hub.request_pickup(1,"no-item"))
        await self.hub.spawn_health(1)
        self.assertIsNone(await self.hub.request_pickup(1,"no-item"))
        with patch("visualizer_protocol.MAX_ATTACK_RECORDS",1):
            self.assertIsNone(await self.hub.request_pickup(1,"new"))

    async def test_send_deadline_does_not_hold_other_phone_and_disconnects(self):
        async def stalled(raw): await asyncio.Future()
        self.one.send=stalled
        with patch("visualizer_protocol.SEND_TIMEOUT_SECONDS",.02):
            await asyncio.wait_for(self.hub.broadcast_state(),.5)
        await asyncio.sleep(.05)
        self.assertTrue(self.one.closed)
        self.assertFalse(self.hub.engine.players[1].connected)
        self.assertEqual(self.hub.engine.phase,"PAUSED")


class RealSockets(unittest.IsolatedAsyncioTestCase):
    async def test_two_clients_menu_attack_pickup_disconnect_reconnect(self):
        clock=Clock(); hub=PhoneHub(engine=GameEngine(clock=clock))
        async with websockets.serve(hub.handle,"127.0.0.1",0,max_size=65536) as server:
            url="ws://127.0.0.1:"+str(server.sockets[0].getsockname()[1])
            async def join(player):
                ws=await websockets.connect(url)
                await ws.send(encode(dict(type="ClientHello",protocol_version=2,client_id="socket-"+str(player),player_id=player)))
                welcome=await receive(ws,"ServerWelcome"); self.assertTrue(welcome["supports_player_commands"])
                await receive(ws,"MatchState")
                return ws
            one=await join(1); two=await join(2)
            try:
                self.assertEqual(hub.engine.phase,"LOBBY")
                for action, phase in (("READY","CALIBRATING"),("CALIBRATED","COUNTDOWN")):
                    await one.send(encode(command(hub,1,action))); await two.send(encode(command(hub,2,action)))
                    a=await receive(one,"MatchState",lambda s:s["state"]==phase)
                    self.assertEqual(a,await receive(two,"MatchState",lambda s:s["state"]==phase))
                clock.advance(3); await hub.broadcast_state()
                await receive(one,"MatchState",lambda s:s["state"]=="FIGHTING")
                await receive(two,"MatchState",lambda s:s["state"]=="FIGHTING")
                task=asyncio.create_task(hub.request_punch(1,"JAB",1,1,attack_id="socket-attack"))
                attempt=await receive(one,"PunchAttempt")
                observation=dict(type="PunchObservation",protocol_version=2,match_id=hub.match_id,stream_id=hub.stream_id,
                    attack_id=attempt["attack_id"],observer_player=1,observation="TARGET_TRACKED",target_age_ms=10,client_timestamp=0)
                await two.send(encode(observation)); await one.send(encode(observation))
                final=await task
                self.assertEqual(final["outcome"],"HIT")
                self.assertEqual(final,await receive(one,"GameEvent",lambda e:e.get("attack_id")=="socket-attack"))
                self.assertEqual(final,await receive(two,"GameEvent",lambda e:e.get("attack_id")=="socket-attack"))
                await hub.spawn_health(1); check=await hub.request_pickup(1,"socket-pickup")
                await receive(one,"PickupCheck"); await one.send(encode(pickup_reply(check)))
                self.assertTrue((await receive(one,"PickupResult"))["accepted"])
                await receive(one,"GameEvent",lambda e:e["event"]=="ITEM_PICKUP")
                await receive(two,"GameEvent",lambda e:e["event"]=="ITEM_PICKUP")
                await two.close()
                await receive(one,"MatchState",lambda s:s["state"]=="PAUSED")
                two=await join(2); self.assertEqual(hub.engine.phase,"PAUSED")
                for player,ws in ((1,one),(2,two)): await ws.send(encode(command(hub,player,"RESUME")))
                await receive(one,"MatchState",lambda s:s["state"]=="COUNTDOWN")
                clock.advance(3); await hub.broadcast_state()
                clock.advance(90); await hub.broadcast_state(); clock.advance(2); await hub.broadcast_state()
                state=await receive(one,"MatchState",lambda s:s["state"]=="MATCH_END")
                self.assertEqual(state["match_result"],"P1_WIN")
            finally:
                await one.close(); await two.close(); await hub.close()

    def test_strict_json_rejects_duplicate_nonfinite_and_oversized(self):
        self.assertIsNone(decode('{"type":"A","type":"B"}'))
        self.assertIsNone(decode('{"x":NaN}'))
        self.assertIsNone(decode(" "*65537))
        self.assertIsNone(decode_hello('{"type":"ClientHello","protocol_version":true,"client_id":"x","player_id":1}'))


if __name__=="__main__": unittest.main()
