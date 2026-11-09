"""Health pickups: engine rules and the private PickupCheck -> Observation -> Result flow."""

import asyncio
import json
import unittest

import websockets

import visualizer_protocol
from game_engine import GameEngine
from test_match_flow import FakeClock, contract_validators
from visualizer_protocol import PhoneHub, decode_pickup_observation


def fighting(clock=None):
    engine = GameEngine(clock=clock or FakeClock())
    engine.start()
    return engine


class EnginePickupTests(unittest.TestCase):
    def test_spawn_only_while_fighting_and_one_per_player(self):
        engine = GameEngine(clock=FakeClock())
        self.assertIsNone(engine.spawn_health(1), "not in LOBBY")
        engine.start()
        item = engine.spawn_health(1)
        self.assertEqual(item.owner, 1)
        self.assertTrue(-65 <= item.bearing_degrees <= 65)
        self.assertIsNone(engine.spawn_health(1), "one at a time")
        self.assertIsNotNone(engine.spawn_health(2))
        self.assertEqual(len(engine.snapshot()["active_items"]), 2)

    def test_items_match_the_contract(self):
        validators = contract_validators()
        if "match-state" not in validators:
            self.skipTest("jsonschema or CG4002-Viz contracts unavailable")
        hub = PhoneHub(engine=fighting())
        hub.engine.spawn_health(1)
        state = hub.state()
        validators["match-state"].validate(state)
        self.assertEqual(state["active_items"][0]["remaining_ms"], 30000)

    def test_lifetime_counts_fight_time_only(self):
        engine = fighting()
        engine.spawn_health(1)
        engine.clock.advance(10)
        engine.pause()
        engine.clock.advance(100)          # paused: the item's timer is frozen
        engine.resume()
        engine.advance()
        self.assertEqual(engine.snapshot()["active_items"][0]["remaining_ms"], 20000)
        engine.clock.advance(20)
        engine.advance()
        self.assertEqual(engine.snapshot()["active_items"], [])

    def test_collect_in_reach_heals_up_to_full_and_removes_the_item(self):
        engine = fighting()
        engine.players[1].health = 90.0
        item = engine.spawn_health(1)
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.5),
                         ("ACCEPTED", 10.0))
        self.assertEqual(engine.players[1].health, 100.0)
        self.assertEqual(engine.snapshot()["active_items"], [])

    def test_rejections_keep_the_item(self):
        engine = fighting()
        item = engine.spawn_health(1)
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.51)[0], "OUT_OF_RANGE")
        self.assertEqual(engine.collect_health(1, "health-other", "AVAILABLE", 0.1)[0], "ITEM_NOT_FOUND")
        self.assertEqual(engine.collect_health(2, item.item_id, "AVAILABLE", 0.1)[0], "ITEM_NOT_FOUND")
        self.assertEqual(engine.collect_health(1, item.item_id, "TRACKING_UNAVAILABLE", 0.0)[0],
                         "TRACKING_UNAVAILABLE")
        engine.pause()
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.1)[0], "MATCH_NOT_ACTIVE")
        self.assertEqual(len(engine.items), 1)

    def test_round_end_clears_items(self):
        engine = fighting()
        engine.spawn_health(1)
        engine.clock.advance(90)
        engine.advance()
        self.assertEqual(engine.phase, "ROUND_END")
        self.assertEqual(engine.snapshot()["active_items"], [])


class ObservationDecodeTests(unittest.TestCase):
    def observation(self, **changes):
        value = {
            "type": "PickupObservation", "protocol_version": 2,
            "match_id": "match-demo-001", "stream_id": "ultra96-abc",
            "request_id": "p1:act-1", "item_id": "health-p1-0001", "player_id": 1,
            "observation": "AVAILABLE", "client_timestamp": 5,
            "observed_distance_m": 0.3, "hand": "LEFT",
        }
        value.update(changes)
        return {key: item for key, item in value.items() if item is not None}

    def test_canonical_observations_decode_and_match_the_contract(self):
        validators = contract_validators()
        for value in (self.observation(),
                      self.observation(observation="ITEM_UNAVAILABLE",
                                       observed_distance_m=None, hand=None)):
            self.assertIsNotNone(decode_pickup_observation(json.dumps(value)))
            if "pickup-observation" in validators:
                validators["pickup-observation"].validate(value)

    def test_noncanonical_observations_are_rejected(self):
        for value in (
            self.observation(observed_distance_m=None),               # AVAILABLE needs it
            self.observation(hand="BOTH"),
            self.observation(observed_distance_m=-0.1),
            self.observation(observation="ITEM_UNAVAILABLE"),         # must omit both
            self.observation(extra=1),
            self.observation(request_id="bad id"),
        ):
            self.assertIsNone(decode_pickup_observation(json.dumps(value)), value)
        self.assertIsNone(decode_pickup_observation("NaN"))


class SocketPickupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.validators = contract_validators()
        self.hub = PhoneHub(engine=fighting(), auto_start=True)
        self.hub.engine.players[1].health = 60.0
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        self.one = await self.join(url, 1)
        self.two = await self.join(url, 2)
        self.item = await self.hub.spawn_health(1)

    async def asyncTearDown(self):
        await self.one.close()
        await self.two.close()
        self.server.close()
        await self.server.wait_closed()

    async def join(self, url, player):
        socket = await websockets.connect(url)
        await socket.send(json.dumps({"type": "ClientHello", "protocol_version": 2,
                                      "client_id": f"phone-{player}", "player_id": player}))
        await asyncio.wait_for(socket.recv(), 3)
        return socket

    async def next_of(self, socket, kind, seconds=3):
        async def read():
            while True:
                message = json.loads(await socket.recv())
                if message["type"] == kind:
                    return message
        return await asyncio.wait_for(read(), seconds)

    def validate(self, name, message):
        if name in self.validators:
            self.validators[name].validate(message)

    def answer(self, check, **evidence):
        body = {
            "type": "PickupObservation", "protocol_version": 2,
            "match_id": check["match_id"], "stream_id": check["stream_id"],
            "request_id": check["request_id"], "item_id": check["item_id"],
            "player_id": check["player_id"], "observation": "AVAILABLE",
            "client_timestamp": 1, "observed_distance_m": 0.3, "hand": "LEFT",
        }
        body.update(evidence)
        return json.dumps({key: value for key, value in body.items() if value is not None})

    async def test_a_pickup_in_reach_heals_and_both_phones_see_it(self):
        await self.hub.request_pickup(1, "act-1")
        check = await self.next_of(self.one, "PickupCheck")
        self.validate("pickup-check", check)
        self.assertEqual(check["item_id"], self.item.item_id)
        await self.one.send(self.answer(check))
        result = await self.next_of(self.one, "PickupResult")
        self.validate("pickup-result", result)
        self.assertEqual((result["accepted"], result["reason"]), (True, "ACCEPTED"))
        for phone in (self.one, self.two):
            event = await self.next_of(phone, "GameEvent")
            self.validate("game-event", event)
            self.assertEqual((event["event"], event["magnitude"], event["hand"]),
                             ("ITEM_PICKUP", 25.0, "LEFT"))
            state = await self.next_of(phone, "MatchState")
            self.assertEqual(state["player_1"]["health"], 85.0)
            self.assertEqual(state["active_items"], [])

    async def test_each_phone_only_receives_its_own_active_item(self):
        second = await self.hub.spawn_item(2, "ATTACK_MULTIPLIER")
        seq = self.hub.state_seq
        for phone, own in ((self.one, self.item), (self.two, second)):
            state = await self.next_of(phone, "MatchState")
            while state["seq"] < seq:
                state = await self.next_of(phone, "MatchState")
            self.assertEqual([item["id"] for item in state["active_items"]], [own.item_id])
            self.assertEqual(state["seq"], seq)
            self.validate("match-state", state)

        await self.hub.request_pickup(1, "private-replay")
        check = await self.next_of(self.one, "PickupCheck")
        await self.one.send(self.answer(check))
        await self.next_of(self.one, "PickupResult")
        await self.next_of(self.one, "GameEvent")
        await self.next_of(self.one, "MatchState")
        await self.hub.request_pickup(1, "private-replay")
        await self.next_of(self.one, "PickupResult")
        replay = await self.next_of(self.one, "MatchState")
        self.assertEqual(replay["active_items"], [])
        self.assertEqual(self.hub.engine.items[2].item_id, second.item_id)

    async def test_retrying_an_action_replays_without_a_second_effect(self):
        await self.hub.request_pickup(1, "act-1")
        check = await self.next_of(self.one, "PickupCheck")
        await self.one.send(self.answer(check))
        first = await self.next_of(self.one, "PickupResult")
        await self.next_of(self.two, "GameEvent")
        seq = self.hub.event_seq
        cached = await self.hub.request_pickup(1, "act-1")
        self.assertEqual(cached, first)
        await self.one.send(self.answer(check))          # same evidence again
        await asyncio.sleep(0.1)
        self.assertEqual(self.hub.event_seq, seq, "no second ITEM_PICKUP")
        self.assertEqual(self.hub.engine.players[1].health, 85.0)

    async def test_out_of_reach_is_rejected_and_the_item_stays(self):
        await self.hub.request_pickup(1, "act-1")
        check = await self.next_of(self.one, "PickupCheck")
        await self.one.send(self.answer(check, observed_distance_m=0.9))
        result = await self.next_of(self.one, "PickupResult")
        self.assertEqual((result["accepted"], result["reason"]), (False, "OUT_OF_RANGE"))
        self.assertEqual(len(self.hub.engine.items), 1)

    async def test_no_answer_times_out_without_consuming_the_item(self):
        saved = visualizer_protocol.PICKUP_TIMEOUT_MS
        visualizer_protocol.PICKUP_TIMEOUT_MS = 100
        try:
            await self.hub.request_pickup(1, "act-1")
            await self.next_of(self.one, "PickupCheck")
            result = await self.next_of(self.one, "PickupResult", seconds=2)
        finally:
            visualizer_protocol.PICKUP_TIMEOUT_MS = saved
        self.assertEqual(result["reason"], "OBSERVATION_TIMEOUT")
        self.assertEqual(len(self.hub.engine.items), 1)
        self.assertNotIn(1, self.hub.pending_pickups, "a new pickup can be tried")

    async def test_bad_evidence_is_ignored_and_a_good_answer_still_counts(self):
        await self.hub.request_pickup(1, "act-1")
        check = await self.next_of(self.one, "PickupCheck")
        await self.one.send(self.answer(check, observed_distance_m=None))  # missing distance
        await self.one.send(self.answer(check, player_id=2))               # not this phone's
        await self.one.send(self.answer(check))
        result = await self.next_of(self.one, "PickupResult")
        self.assertEqual(result["reason"], "ACCEPTED")

    async def test_the_ai_pickup_label_sends_a_check(self):
        from ai_to_visualizer_demo import FakeAiEvent, send_ai_demo
        sent = await send_ai_demo(self.hub, 0, FakeAiEvent("pickup", 0.0, 0.9), {}, 0.6,
                                  attack_id="ai-run-p1-7")
        self.assertEqual(sent["type"], "PickupCheck")
        self.assertEqual(sent["request_id"], "p1:ai-run-p1-7")
        await self.next_of(self.one, "PickupCheck")

    async def test_only_the_owner_is_asked_and_one_check_at_a_time(self):
        self.assertIsNone(await self.hub.request_pickup(2, "act-x"), "P2 has no item")
        await self.hub.request_pickup(1, "act-1")
        self.assertIsNone(await self.hub.request_pickup(1, "act-2"), "check still pending")
        await self.next_of(self.one, "PickupCheck")
        with self.assertRaises(asyncio.TimeoutError):
            await self.next_of(self.two, "PickupCheck", seconds=0.2)


if __name__ == "__main__":
    unittest.main()
